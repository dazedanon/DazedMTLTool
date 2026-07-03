//! The Translation section's data model and the headless logic behind it.
//!
//! A translator opens a game's unpacked `Data/`, gets an editable source<->translation grid, edits
//! the translations, then injects them back into byte-exact game files. This module owns everything
//! *except* the egui rendering (which lives in `app.rs`), so the whole workflow can be exercised in
//! tests without a window:
//!
//!   * [`extract_model`] walks a data dir, calls the **same** `wolf_decompiler` extract functions the
//!     CLI uses, and parses the per-file JSON they emit into a [`TranslationModel`] of editable
//!     [`Row`]s. Each file keeps its *original parsed JSON* (`doc`) so injection is byte-for-byte
//!     lossless: a row edit only rewrites a single `text` leaf inside that `Value`, never rebuilds
//!     the shape (exactly how the library's own merge does it).
//!   * [`inject_model`] serializes each file's (edited) JSON back and calls the matching
//!     `inject_*` / `inject_names` library path with [`InjectOptions`] from the UI checkboxes.
//!   * [`merge_into_model`] / [`check_conflicts`] / save+load round out the workflow.
//!
//! The DB `.project` is the canonical handle for a database. Injection writes the `.project`+`.dat`
//! pair together, mirroring the CLI's `strings_inject_db` / `names-inject`.

use std::path::{Path, PathBuf};

use serde_json::Value;
use wolf_decompiler::{
    apply_memory, build_memory, check_name_conflicts, db_strings_to_json, extract_common_events,
    extract_db_strings, extract_game_dat, extract_map, extract_names, extract_txt_events,
    inject_common_events, inject_db_strings, inject_game_dat, inject_map, inject_names,
    inject_txt_events, scenes_to_json, InjectOptions,
};

// Re-export the library's conflict type so the section UI can name it without reaching past this
// module (it owns the translation surface).
pub use wolf_decompiler::Conflict;
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::database::Database;
use wolf_formats::game_dat::GameDat;
use wolf_formats::map::Map;

/// What kind of file a [`FileEntry`] came from. Decides which extract/inject library path applies
/// and (for the DB) that the `.project`+`.dat` pair must be written together.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum FileKind {
    /// A `.mps` map (`scenes` JSON).
    Map,
    /// `CommonEvent.dat` (`scenes` JSON).
    CommonEvent,
    /// A database `.project` (+ sibling `.dat`); `db` JSON.
    Database,
    /// `Game.dat` (`gamedat` JSON).
    GameDat,
    /// An external event-text `.txt` scene file (`txt` JSON). Some GamePro games keep their
    /// dialogue in Shift-JIS `.txt` files (the unpacked `Evtext*.wolf`), one scene per file.
    TxtEvent,
}

impl FileKind {
    /// A short label for the file list.
    pub fn tag(self) -> &'static str {
        match self {
            FileKind::Map => "map",
            FileKind::CommonEvent => "common",
            FileKind::Database => "db",
            FileKind::GameDat => "gamedat",
            FileKind::TxtEvent => "txt",
        }
    }
}

/// One editable translation row: the read-only `source`, the editable `translation`, plus a
/// human-readable `location`/`note` and the JSON-pointer (`ptr`) of this row's `text` leaf inside
/// its owning [`FileEntry::doc`]. The pointer is what makes injection lossless: an edit rewrites
/// exactly that one leaf, leaving every other byte of the document untouched.
#[derive(Clone)]
pub struct Row {
    pub source: String,
    pub translation: String,
    /// Where this string lives (e.g. `ev42/p0 · ▼Speaker`, `Type 3 row 7 · Name`).
    pub location: String,
    /// A small dim note (occurrence count for names, field hint for DB, etc.).
    pub note: String,
    /// JSON Pointer (RFC 6901) to the `text` value inside the owning document.
    ptr: String,
}

impl Row {
    /// True when the translator has actually changed the text from the source.
    pub fn is_translated(&self) -> bool {
        self.translation != self.source && !self.translation.is_empty()
    }
}

/// One translatable file's rows plus the parsed JSON document they index into. `path` is the
/// on-disk file the inject writes back to (the `.project` for a database).
pub struct FileEntry {
    pub path: PathBuf,
    pub kind: FileKind,
    pub rows: Vec<Row>,
    /// The original extract JSON, parsed. Rows mutate `text` leaves here. Inject serializes it back.
    doc: Value,
}

impl FileEntry {
    /// A short display name for the file list (the file name, or a DB-friendly stem).
    pub fn display_name(&self) -> String {
        self.path
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("?")
            .to_string()
    }

    /// Translated-row count, for the per-file and overall counters.
    pub fn translated_count(&self) -> usize {
        self.rows.iter().filter(|r| r.is_translated()).count()
    }
}

/// The whole editable project: every translatable file plus the project-level name glossary.
#[derive(Default)]
pub struct TranslationModel {
    /// The data dir this was extracted from (so inject/merge default sensibly).
    pub data_dir: PathBuf,
    pub files: Vec<FileEntry>,
    /// The glossary rows (the "Names" entry), kept beside its own parsed `names.json` document.
    pub names: Vec<Row>,
    names_doc: Value,
}

impl TranslationModel {
    /// Total source lines across files + names.
    pub fn total_rows(&self) -> usize {
        self.files.iter().map(|f| f.rows.len()).sum::<usize>() + self.names.len()
    }

    /// Total translated lines across files + names.
    pub fn translated_rows(&self) -> usize {
        self.files.iter().map(FileEntry::translated_count).sum::<usize>()
            + self.names.iter().filter(|r| r.is_translated()).count()
    }

    /// Push the editable `translation` values back into the parsed documents, so the documents are
    /// current before serialization (inject/save). Called by [`inject_model`] and `save_to_path`.
    fn sync_docs(&mut self) {
        for f in &mut self.files {
            apply_rows_to_doc(&mut f.doc, &f.rows);
        }
        apply_rows_to_doc(&mut self.names_doc, &self.names);
    }
}

/// Write each row's `translation` into the `text` leaf its pointer addresses. An untranslated row
/// (empty `translation`) writes its `source` back, so the doc's text equals the source (the inject
/// then treats it as a no-op) and clearing a translation correctly resets the cell to its source.
fn apply_rows_to_doc(doc: &mut Value, rows: &[Row]) {
    for r in rows {
        if let Some(slot) = doc.pointer_mut(&r.ptr) {
            let text = if r.is_translated() { &r.translation } else { &r.source };
            *slot = Value::String(text.clone());
        }
    }
}

// ----------------------------------------------------------------------------
// Extraction: walk the data dir, call the library extract fns, parse to rows
// ----------------------------------------------------------------------------

/// Resolve which of `dir` / `dir/BasicData` holds `CommonEvent.dat` + the DB pairs (mirrors the
/// CLI's `basic_data_dir`).
fn basic_data_dir(dir: &Path) -> PathBuf {
    if dir.join("CommonEvent.dat").exists() || dir.join("DataBase.project").exists() {
        dir.to_path_buf()
    } else if dir.join("BasicData").join("CommonEvent.dat").exists()
        || dir.join("BasicData").join("DataBase.project").exists()
    {
        dir.join("BasicData")
    } else {
        dir.to_path_buf()
    }
}

/// Every translatable file under a data dir, in a stable order: maps, then `CommonEvent.dat`, the
/// three DB pairs, and `Game.dat` (mirrors how the CLI's `discover_data_dir` + `cmd_*` locate them).
fn discover_files(dir: &Path) -> (Vec<PathBuf>, Vec<(FileKind, PathBuf)>) {
    let basic = basic_data_dir(dir);

    // Maps live in MapData (or directly under dir for a flattened layout).
    let mut maps: Vec<PathBuf> = Vec::new();
    for sub in [dir.to_path_buf(), dir.join("MapData")] {
        let Ok(rd) = std::fs::read_dir(&sub) else {
            continue;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.extension().and_then(|s| s.to_str()) == Some("mps") {
                maps.push(p);
            }
        }
    }
    maps.sort();
    maps.dedup();

    let mut others: Vec<(FileKind, PathBuf)> = Vec::new();
    let ce = basic.join("CommonEvent.dat");
    if ce.exists() {
        others.push((FileKind::CommonEvent, ce));
    }
    for stem in ["DataBase", "CDataBase", "SysDatabase"] {
        let proj = basic.join(format!("{stem}.project"));
        if proj.exists() && proj.with_extension("dat").exists() {
            others.push((FileKind::Database, proj));
        }
    }
    let game_dat = basic.join("Game.dat");
    if game_dat.exists() {
        others.push((FileKind::GameDat, game_dat));
    }
    (maps, others)
}

/// Every external event-text `.txt` file anywhere under `dir`, sorted by path. These are the
/// unpacked `Evtext*.wolf` scene files. The walk is bounded by a depth limit so a deep tree cannot
/// run away, and it only collects `.txt` (the sole `.txt` use in a Wolf game), so it skips the
/// image/audio archives cheaply.
fn discover_txt_files(dir: &Path) -> Vec<PathBuf> {
    fn walk(dir: &Path, depth: usize, out: &mut Vec<PathBuf>) {
        if depth > 8 {
            return;
        }
        let Ok(rd) = std::fs::read_dir(dir) else {
            return;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                walk(&p, depth + 1, out);
            } else if p.extension().and_then(|s| s.to_str()).map(|x| x.eq_ignore_ascii_case("txt")) == Some(true) {
                out.push(p);
            }
        }
    }
    let mut out = Vec::new();
    walk(dir, 0, &mut out);
    out.sort();
    out
}

/// Extract the whole data dir into a [`TranslationModel`]. `report` receives progress callbacks
/// (`fraction`, `message`) so a background job can drive the progress bar. Pass a no-op closure in
/// tests. Errors only on a truly empty dir. An unreadable single file is logged-and-skipped via the
/// returned `warnings` list.
pub struct ExtractOutcome {
    pub model: TranslationModel,
    pub warnings: Vec<String>,
}

pub fn extract_model(
    dir: &Path,
    mut report: impl FnMut(f32, String),
) -> Result<ExtractOutcome, String> {
    let (maps, others) = discover_files(dir);
    // External event-text .txt files (unpacked Evtext*). Found anywhere under the dir, so a game
    // that keeps its dialogue in .txt (some GamePro titles) gets that text too, not just the
    // command stream. Most games have none, so this adds nothing for them.
    let txts = discover_txt_files(dir);
    let total = maps.len() + others.len() + txts.len() + 1; // +1 for the names glossary pass
    if total <= 1 {
        return Err(format!(
            "no translatable files found under {} (looked for *.mps, CommonEvent.dat, the DB pairs, Game.dat, event .txt)",
            dir.display()
        ));
    }
    let mut done = 0usize;
    let mut warnings = Vec::new();
    let mut files: Vec<FileEntry> = Vec::new();

    let step = |report: &mut dyn FnMut(f32, String), done: &mut usize, msg: String| {
        *done += 1;
        report(*done as f32 / total as f32, msg);
    };

    // Maps.
    for p in &maps {
        let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("?").to_string();
        step(&mut report, &mut done, format!("map {name}"));
        match extract_map_file(p) {
            Ok(entry) => files.push(entry),
            Err(e) => warnings.push(format!("skip {name}: {e}")),
        }
    }
    // CommonEvent / DB / Game.dat.
    for (kind, p) in &others {
        let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("?").to_string();
        step(&mut report, &mut done, format!("{} {name}", kind.tag()));
        let r = match kind {
            FileKind::CommonEvent => extract_common_file(p),
            FileKind::Database => extract_db_file(p),
            FileKind::GameDat => extract_gamedat_file(p),
            FileKind::Map => unreachable!("maps handled above"),
            FileKind::TxtEvent => unreachable!("txt handled in its own loop"),
        };
        match r {
            Ok(entry) => files.push(entry),
            Err(e) => warnings.push(format!("skip {name}: {e}")),
        }
    }
    // External event-text .txt scene files, one entry each (so the per-file grid stays responsive
    // even when a game ships thousands of them).
    for p in &txts {
        let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("?").to_string();
        step(&mut report, &mut done, format!("txt {name}"));
        match extract_txt_file(p) {
            Ok(entry) => files.push(entry),
            Err(e) => warnings.push(format!("skip {name}: {e}")),
        }
    }

    // Names glossary (whole-dir).
    step(&mut report, &mut done, "names glossary".to_string());
    let (names, names_doc) = match extract_names_doc(dir) {
        Ok(v) => v,
        Err(e) => {
            warnings.push(format!("names glossary: {e}"));
            (Vec::new(), Value::Null)
        }
    };

    Ok(ExtractOutcome {
        model: TranslationModel {
            data_dir: dir.to_path_buf(),
            files,
            names,
            names_doc,
        },
        warnings,
    })
}

fn extract_map_file(path: &Path) -> Result<FileEntry, String> {
    let bytes = std::fs::read(path).map_err(|e| e.to_string())?;
    let map = Map::read(&bytes).map_err(|e| e.to_string())?;
    let fname = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
    let json = scenes_to_json(fname, "map", &extract_map(&map));
    let doc: Value = serde_json::from_str(&json).map_err(|e| e.to_string())?;
    let rows = rows_from_scenes(&doc);
    Ok(FileEntry { path: path.to_path_buf(), kind: FileKind::Map, rows, doc })
}

fn extract_common_file(path: &Path) -> Result<FileEntry, String> {
    let bytes = std::fs::read(path).map_err(|e| e.to_string())?;
    let ce = CommonEventsFile::read(&bytes).map_err(|e| e.to_string())?;
    let fname = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
    let json = scenes_to_json(fname, "common", &extract_common_events(&ce));
    let doc: Value = serde_json::from_str(&json).map_err(|e| e.to_string())?;
    let rows = rows_from_scenes(&doc);
    Ok(FileEntry { path: path.to_path_buf(), kind: FileKind::CommonEvent, rows, doc })
}

fn extract_db_file(proj: &Path) -> Result<FileEntry, String> {
    let dat = proj.with_extension("dat");
    let (p, d) = (
        std::fs::read(proj).map_err(|e| e.to_string())?,
        std::fs::read(&dat).map_err(|e| e.to_string())?,
    );
    let db = Database::read(&p, &d).map_err(|e| e.to_string())?;
    let fname = proj.file_name().and_then(|s| s.to_str()).unwrap_or("");
    let glossary = wolf_decompiler::symbols::load_embedded_engine_glossary();
    let json = db_strings_to_json(fname, &extract_db_strings(&db, &glossary));
    let doc: Value = serde_json::from_str(&json).map_err(|e| e.to_string())?;
    let rows = rows_from_db(&doc);
    Ok(FileEntry { path: proj.to_path_buf(), kind: FileKind::Database, rows, doc })
}

fn extract_gamedat_file(path: &Path) -> Result<FileEntry, String> {
    let bytes = std::fs::read(path).map_err(|e| e.to_string())?;
    let gd = GameDat::read(&bytes).map_err(|e| e.to_string())?;
    let json = extract_game_dat(&gd);
    let doc: Value = serde_json::from_str(&json).map_err(|e| e.to_string())?;
    let rows = rows_from_gamedat(&doc);
    Ok(FileEntry { path: path.to_path_buf(), kind: FileKind::GameDat, rows, doc })
}

fn extract_txt_file(path: &Path) -> Result<FileEntry, String> {
    let bytes = std::fs::read(path).map_err(|e| e.to_string())?;
    let json = extract_txt_events(&bytes);
    let doc: Value = serde_json::from_str(&json).map_err(|e| e.to_string())?;
    let rows = rows_from_txt(&doc);
    Ok(FileEntry { path: path.to_path_buf(), kind: FileKind::TxtEvent, rows, doc })
}

/// Extract the project-level name glossary, returning its rows + parsed `names.json`.
fn extract_names_doc(dir: &Path) -> Result<(Vec<Row>, Value), String> {
    let basic = basic_data_dir(dir);
    let mut dbs = Vec::new();
    for stem in ["DataBase", "CDataBase", "SysDatabase"] {
        let proj = basic.join(format!("{stem}.project"));
        let dat = basic.join(format!("{stem}.dat"));
        if let (Ok(p), Ok(d)) = (std::fs::read(&proj), std::fs::read(&dat)) {
            if let Ok(db) = Database::read(&p, &d) {
                dbs.push(db);
            }
        }
    }
    if dbs.is_empty() {
        return Err("no databases found for the name glossary".into());
    }
    let ce = std::fs::read(basic.join("CommonEvent.dat"))
        .ok()
        .and_then(|b| CommonEventsFile::read(&b).ok());
    let mut maps = Vec::new();
    for sub in [dir.to_path_buf(), dir.join("MapData")] {
        let Ok(rd) = std::fs::read_dir(&sub) else {
            continue;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.extension().and_then(|s| s.to_str()) == Some("mps") {
                if let Ok(b) = std::fs::read(&p) {
                    if let Ok(m) = Map::read(&b) {
                        maps.push(m);
                    }
                }
            }
        }
    }
    let ce_refs: Vec<&CommonEventsFile> = ce.iter().collect();
    let glossary = wolf_decompiler::symbols::load_embedded_engine_glossary();
    let json = extract_names(&dbs, &ce_refs, &maps, &glossary);
    let doc: Value = serde_json::from_str(&json).map_err(|e| e.to_string())?;
    let rows = rows_from_names(&doc);
    Ok((rows, doc))
}

// --- JSON document -> editable rows (each row carries the pointer to its `text`) --------------

fn rows_from_scenes(doc: &Value) -> Vec<Row> {
    let mut rows = Vec::new();
    let Some(scenes) = doc.get("scenes").and_then(Value::as_array) else {
        return rows;
    };
    for (si, sc) in scenes.iter().enumerate() {
        let event = sc.get("event").and_then(Value::as_i64).unwrap_or(0);
        let page = sc.get("page").and_then(Value::as_i64);
        let name = sc.get("name").and_then(Value::as_str).unwrap_or("");
        let loc_prefix = match page {
            Some(p) => format!("ev{event}/p{p}"),
            None => format!("ev{event}"),
        };
        let Some(lines) = sc.get("lines").and_then(Value::as_array) else {
            continue;
        };
        for (li, ln) in lines.iter().enumerate() {
            let source = ln.get("source").and_then(Value::as_str).unwrap_or("").to_string();
            let t = ln.get("text").and_then(Value::as_str).unwrap_or(&source).to_string();
            // Untranslated rows hold an empty translation (no copy of the source), which both saves
            // memory on big files and gives translators a clean target box. is_translated/apply treat
            // empty as "same as source".
            let text = if t == source { String::new() } else { t };
            let speaker = ln.get("speaker").and_then(Value::as_str).unwrap_or("");
            let mut note = String::new();
            if !speaker.is_empty() {
                note = speaker.to_string();
            } else if !name.is_empty() {
                note = name.to_string();
            }
            rows.push(Row {
                source,
                translation: text,
                location: loc_prefix.clone(),
                note,
                ptr: format!("/scenes/{si}/lines/{li}/text"),
            });
        }
    }
    rows
}

fn rows_from_db(doc: &Value) -> Vec<Row> {
    let mut rows = Vec::new();
    let Some(groups) = doc.get("groups").and_then(Value::as_array) else {
        return rows;
    };
    for (gi, g) in groups.iter().enumerate() {
        let type_name = g.get("typeName").and_then(Value::as_str).unwrap_or("");
        let Some(lines) = g.get("lines").and_then(Value::as_array) else {
            continue;
        };
        for (li, ln) in lines.iter().enumerate() {
            let source = ln.get("source").and_then(Value::as_str).unwrap_or("").to_string();
            let t = ln.get("text").and_then(Value::as_str).unwrap_or(&source).to_string();
            // Untranslated rows hold an empty translation (no copy of the source), which both saves
            // memory on big files and gives translators a clean target box. is_translated/apply treat
            // empty as "same as source".
            let text = if t == source { String::new() } else { t };
            let row_name = ln.get("rowName").and_then(Value::as_str).unwrap_or("");
            let field = ln.get("fieldName").and_then(Value::as_str).unwrap_or("");
            rows.push(Row {
                source,
                translation: text,
                location: format!("{type_name} · {row_name}"),
                note: field.to_string(),
                ptr: format!("/groups/{gi}/lines/{li}/text"),
            });
        }
    }
    rows
}

fn rows_from_gamedat(doc: &Value) -> Vec<Row> {
    let mut rows = Vec::new();
    let Some(lines) = doc.get("lines").and_then(Value::as_array) else {
        return rows;
    };
    for (li, ln) in lines.iter().enumerate() {
        let source = ln.get("source").and_then(Value::as_str).unwrap_or("").to_string();
        let t = ln.get("text").and_then(Value::as_str).unwrap_or(&source).to_string();
        let text = if t == source { String::new() } else { t };
        let key = ln.get("key").and_then(Value::as_str).unwrap_or("");
        rows.push(Row {
            source,
            translation: text,
            location: key.to_string(),
            note: String::new(),
            ptr: format!("/lines/{li}/text"),
        });
    }
    rows
}

/// Rows for an event-text `.txt` document (`{ lines: [ {i, source, text} ] }`). Each translatable
/// line becomes a row pointing at its `text` leaf. The `i` (the physical line index in the file)
/// is shown as the location so a translator can find it in the original.
fn rows_from_txt(doc: &Value) -> Vec<Row> {
    let mut rows = Vec::new();
    let Some(lines) = doc.get("lines").and_then(Value::as_array) else {
        return rows;
    };
    for (li, ln) in lines.iter().enumerate() {
        let source = ln.get("source").and_then(Value::as_str).unwrap_or("").to_string();
        let t = ln.get("text").and_then(Value::as_str).unwrap_or(&source).to_string();
        let text = if t == source { String::new() } else { t };
        let i = ln.get("i").and_then(Value::as_i64).unwrap_or(li as i64);
        rows.push(Row {
            source,
            translation: text,
            location: format!("line {i}"),
            note: String::new(),
            ptr: format!("/lines/{li}/text"),
        });
    }
    rows
}

fn rows_from_names(doc: &Value) -> Vec<Row> {
    let mut rows = Vec::new();
    let Some(names) = doc.get("names").and_then(Value::as_array) else {
        return rows;
    };
    for (i, e) in names.iter().enumerate() {
        let source = e.get("source").and_then(Value::as_str).unwrap_or("").to_string();
        let t = e.get("text").and_then(Value::as_str).unwrap_or(&source).to_string();
        let text = if t == source { String::new() } else { t };
        let occ = e.get("occurrences").and_then(Value::as_i64).unwrap_or(0);
        let glossary_note = e.get("note").and_then(Value::as_str).unwrap_or("");
        let note = if glossary_note.is_empty() {
            format!("×{occ}")
        } else {
            format!("×{occ} · {glossary_note}")
        };
        rows.push(Row {
            source,
            translation: text,
            location: "name".to_string(),
            note,
            ptr: format!("/names/{i}/text"),
        });
    }
    rows
}

// ----------------------------------------------------------------------------
// Injection: serialize the edited docs back, call the library inject paths
// ----------------------------------------------------------------------------

/// Where an inject writes. `InPlace` overwrites the source files. `OutDir` mirrors the data dir's
/// relative layout under a chosen output directory (like the CLI's `-o`).
#[derive(Clone)]
pub enum InjectTarget {
    InPlace,
    OutDir(PathBuf),
}

/// Per-file inject result line for the log.
pub struct InjectReport {
    pub file: String,
    pub applied: usize,
    pub skipped: usize,
    pub drifted: usize,
}

/// Inject the whole (edited) model back into byte-exact game files. Calls the same `inject_*` /
/// `inject_names` library paths the CLI uses, with `opts` from the UI checkboxes. `report` drives
/// progress. The returned per-file [`InjectReport`]s are logged by the caller.
pub fn inject_model(
    model: &mut TranslationModel,
    opts: &InjectOptions,
    target: &InjectTarget,
    mut report: impl FnMut(f32, String),
) -> Result<Vec<InjectReport>, String> {
    model.sync_docs();
    let total = model.files.len() + 1; // +1 names
    let mut done = 0usize;
    let mut out = Vec::new();

    let out_path = |orig: &Path| -> PathBuf {
        match target {
            InjectTarget::InPlace => orig.to_path_buf(),
            InjectTarget::OutDir(od) => od.join(rel(&model.data_dir, orig)),
        }
    };

    for f in &model.files {
        done += 1;
        let name = f.display_name();
        report(done as f32 / total as f32, format!("inject {name}"));
        let json = serde_json::to_string(&f.doc).map_err(|e| e.to_string())?;
        let dest = out_path(&f.path);
        let rep = inject_one_file(f.kind, &f.path, &dest, &json, opts)
            .map_err(|e| format!("{name}: {e}"))?;
        out.push(rep);
    }

    // Names glossary: applied consistently across the WHOLE dir (DBs + CE + maps), like names-inject.
    done += 1;
    report(done as f32 / total as f32, "inject names".to_string());
    let names_json = serde_json::to_string(&model.names_doc).map_err(|e| e.to_string())?;
    if let Some(rep) = inject_names_all(&model.data_dir, &names_json, opts, target)? {
        out.push(rep);
    }

    Ok(out)
}

/// Apply one file's translation JSON to its base, writing byte-exact output. Databases write the
/// `.project`+`.dat` pair (mirrors the CLI's `strings_inject_db`). Every written file is re-parsed
/// to never ship a structurally-corrupt file.
fn inject_one_file(
    kind: FileKind,
    base: &Path,
    dest: &Path,
    json: &str,
    opts: &InjectOptions,
) -> Result<InjectReport, String> {
    let name = base.file_name().and_then(|s| s.to_str()).unwrap_or("?").to_string();
    if let Some(parent) = dest.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    // External event-text .txt: `inject_txt_events` rebuilds the file byte-exact from the base, so
    // there is no structured stats struct. Count the intended edits (lines whose text differs from
    // source) for the report, then return early.
    if kind == FileKind::TxtEvent {
        let base_bytes = std::fs::read(base).map_err(|e| e.to_string())?;
        let out = inject_txt_events(json, &base_bytes)?;
        std::fs::write(dest, &out).map_err(|e| e.to_string())?;
        let applied = serde_json::from_str::<Value>(json)
            .ok()
            .and_then(|v| {
                v.get("lines").and_then(|l| l.as_array()).map(|ls| {
                    ls.iter()
                        .filter(|l| {
                            l.get("text").and_then(Value::as_str)
                                != l.get("source").and_then(Value::as_str)
                        })
                        .count()
                })
            })
            .unwrap_or(0);
        return Ok(InjectReport { file: name, applied, skipped: 0, drifted: 0 });
    }
    let stats = match kind {
        FileKind::CommonEvent => {
            let base_bytes = std::fs::read(base).map_err(|e| e.to_string())?;
            let mut ce = CommonEventsFile::read(&base_bytes).map_err(|e| e.to_string())?;
            let st = inject_common_events(json, &mut ce, opts)?;
            let out = ce.write();
            CommonEventsFile::read(&out).map_err(|e| format!("re-parse failed: {e}"))?;
            std::fs::write(dest, &out).map_err(|e| e.to_string())?;
            st
        }
        FileKind::Map => {
            let base_bytes = std::fs::read(base).map_err(|e| e.to_string())?;
            let mut m = Map::read(&base_bytes).map_err(|e| e.to_string())?;
            let st = inject_map(json, &mut m, opts)?;
            let out = m.write();
            Map::read(&out).map_err(|e| format!("re-parse failed: {e}"))?;
            std::fs::write(dest, &out).map_err(|e| e.to_string())?;
            st
        }
        FileKind::GameDat => {
            let base_bytes = std::fs::read(base).map_err(|e| e.to_string())?;
            let mut gd = GameDat::read(&base_bytes).map_err(|e| e.to_string())?;
            let st = inject_game_dat(json, &mut gd, opts)?;
            let out = gd.write();
            GameDat::read(&out).map_err(|e| format!("re-parse failed: {e}"))?;
            std::fs::write(dest, &out).map_err(|e| e.to_string())?;
            st
        }
        FileKind::Database => {
            // The `.project`+`.dat` pair, written together byte-exact.
            let proj = base.to_path_buf();
            let base_dat = proj.with_extension("dat");
            let out_dat = dest.with_extension("dat");
            let (p, d) = (
                std::fs::read(&proj).map_err(|e| e.to_string())?,
                std::fs::read(&base_dat).map_err(|e| e.to_string())?,
            );
            let mut db = Database::read(&p, &d).map_err(|e| e.to_string())?;
            let st = inject_db_strings(json, &mut db, opts)?;
            let (op, od) = db.write();
            Database::read(&op, &od).map_err(|e| format!("re-parse failed: {e}"))?;
            std::fs::write(dest, &op).map_err(|e| e.to_string())?;
            std::fs::write(&out_dat, &od).map_err(|e| e.to_string())?;
            st
        }
        FileKind::TxtEvent => unreachable!("txt handled before the match"),
    };
    Ok(InjectReport {
        file: name,
        applied: stats.applied,
        skipped: stats.untranslated + stats.code_mismatch + stats.unrepresentable,
        drifted: stats.drifted,
    })
}

/// Apply the name glossary across the whole data dir (DB pairs + CommonEvent + maps), consistently,
/// exactly as the CLI's `names-inject` does. Returns `None` if the glossary is empty/absent.
fn inject_names_all(
    dir: &Path,
    names_json: &str,
    opts: &InjectOptions,
    target: &InjectTarget,
) -> Result<Option<InjectReport>, String> {
    // Parse everything up front so a partial write can't desync the name mirrors.
    let basic = basic_data_dir(dir);

    // The names pass must LAYER on top of the per-file string injects: when writing to an output
    // dir, the string pass has already written its edits to `<out>/<rel>`. So we read each base file
    // from its output destination if that exists (string-inject touched it), else from the original.
    // This stops the names pass from clobbering a string-edited file with a fresh original copy.
    // In place, the destination IS the original, so it reads the just-string-injected file directly.
    let remap = |orig: &Path| -> PathBuf {
        match target {
            InjectTarget::InPlace => orig.to_path_buf(),
            InjectTarget::OutDir(od) => od.join(rel(dir, orig)),
        }
    };
    let base_of = |orig: &Path| -> PathBuf {
        let dest = remap(orig);
        if dest.exists() {
            dest
        } else {
            orig.to_path_buf()
        }
    };

    let mut db_paths: Vec<(PathBuf, PathBuf)> = Vec::new();
    for stem in ["DataBase", "CDataBase", "SysDatabase"] {
        let proj = basic.join(format!("{stem}.project"));
        let dat = basic.join(format!("{stem}.dat"));
        if proj.exists() && dat.exists() {
            db_paths.push((proj, dat));
        }
    }
    if db_paths.is_empty() {
        return Ok(None);
    }
    let mut db_loaded: Vec<(PathBuf, PathBuf, Database)> = Vec::new();
    for (proj, dat) in &db_paths {
        let (p, d) = (
            std::fs::read(base_of(proj)).map_err(|e| e.to_string())?,
            std::fs::read(base_of(dat)).map_err(|e| e.to_string())?,
        );
        let db = Database::read(&p, &d).map_err(|e| e.to_string())?;
        db_loaded.push((proj.clone(), dat.clone(), db));
    }
    let ce_path = basic.join("CommonEvent.dat");
    let mut ce_loaded: Option<(PathBuf, CommonEventsFile)> = None;
    if ce_path.exists() {
        let b = std::fs::read(base_of(&ce_path)).map_err(|e| e.to_string())?;
        let ce = CommonEventsFile::read(&b).map_err(|e| e.to_string())?;
        ce_loaded = Some((ce_path.clone(), ce));
    }
    let mut map_paths: Vec<PathBuf> = Vec::new();
    for sub in [dir.to_path_buf(), dir.join("MapData")] {
        let Ok(rd) = std::fs::read_dir(&sub) else {
            continue;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.extension().and_then(|s| s.to_str()) == Some("mps") {
                map_paths.push(p);
            }
        }
    }
    map_paths.sort();
    map_paths.dedup();
    let mut map_loaded: Vec<(PathBuf, Map)> = Vec::new();
    for p in &map_paths {
        let b = std::fs::read(base_of(p)).map_err(|e| e.to_string())?;
        let m = Map::read(&b).map_err(|e| e.to_string())?;
        map_loaded.push((p.clone(), m));
    }

    let glossary = wolf_decompiler::symbols::load_embedded_engine_glossary();
    let mut dbs: Vec<Database> = db_loaded.iter().map(|(_, _, db)| db.clone()).collect();
    let mut ce_vec: Vec<&mut CommonEventsFile> =
        ce_loaded.as_mut().map(|(_, c)| c).into_iter().collect();
    let mut maps: Vec<Map> = map_loaded.iter().map(|(_, m)| m.clone()).collect();
    let stats = inject_names(names_json, &mut dbs, &mut ce_vec, &mut maps, opts, &glossary)?;
    // Move the mutated copies back.
    for ((_, _, db), new) in db_loaded.iter_mut().zip(dbs) {
        *db = new;
    }
    for ((_, m), new) in map_loaded.iter_mut().zip(maps) {
        *m = new;
    }

    let ensure_parent = |p: &Path| {
        if let Some(parent) = p.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
    };

    // Write everything (re-parsing each) only after the whole apply succeeded.
    for (proj, dat, db) in &db_loaded {
        let (op, od) = db.write();
        Database::read(&op, &od).map_err(|e| format!("names: DB re-parse failed: {e}"))?;
        let (out_proj, out_dat) = (remap(proj), remap(dat));
        ensure_parent(&out_proj);
        std::fs::write(&out_proj, &op).map_err(|e| e.to_string())?;
        std::fs::write(&out_dat, &od).map_err(|e| e.to_string())?;
    }
    if let Some((p, c)) = &ce_loaded {
        let out = c.write();
        CommonEventsFile::read(&out).map_err(|e| format!("names: CE re-parse failed: {e}"))?;
        let dest = remap(p);
        ensure_parent(&dest);
        std::fs::write(&dest, &out).map_err(|e| e.to_string())?;
    }
    for (p, m) in &map_loaded {
        let out = m.write();
        Map::read(&out).map_err(|e| format!("names: map re-parse failed: {e}"))?;
        let dest = remap(p);
        ensure_parent(&dest);
        std::fs::write(&dest, &out).map_err(|e| e.to_string())?;
    }

    Ok(Some(InjectReport {
        file: "Names (glossary)".to_string(),
        applied: stats.applied,
        skipped: stats.untranslated + stats.code_mismatch + stats.unrepresentable,
        drifted: stats.drifted,
    }))
}

// ----------------------------------------------------------------------------
// Merge (translation memory), name-conflict check, save/load
// ----------------------------------------------------------------------------

/// Outcome of a merge: how many rows got a translation carried in, and how many are still untouched.
pub struct MergeOutcome {
    pub carried: usize,
    pub still_new: usize,
}

/// Carry existing translations from old translation JSON file(s)/dir into the current model, matched
/// by exact source string. Reuses the library's `build_memory` + `apply_memory`: a memory is built
/// from every old `*.json`, then applied to each file's parsed document. The carried `text` values
/// are read back into the rows. Untouched (already-translated) rows are kept.
pub fn merge_into_model(model: &mut TranslationModel, old_paths: &[PathBuf]) -> Result<MergeOutcome, String> {
    // Build one global memory from every old JSON (files + every *.json under old dirs).
    let mut old_files: Vec<PathBuf> = Vec::new();
    for p in old_paths {
        collect_json_files(p, &mut old_files);
    }
    old_files.sort();
    old_files.dedup();
    if old_files.is_empty() {
        return Err("no *.json found under the chosen old translation path(s)".into());
    }
    let mut texts: Vec<String> = Vec::with_capacity(old_files.len());
    for p in &old_files {
        texts.push(std::fs::read_to_string(p).map_err(|e| format!("{}: {e}", p.display()))?);
    }
    let refs: Vec<&str> = texts.iter().map(String::as_str).collect();
    let (memory, _conflicts) = build_memory(&refs);

    // Sync current edits into the docs first so we don't clobber existing in-session translations.
    model.sync_docs();

    let mut carried = 0usize;
    let mut still_new = 0usize;
    for f in &mut model.files {
        let json = serde_json::to_string(&f.doc).map_err(|e| e.to_string())?;
        let (merged, stats) = apply_memory(&json, &memory)?;
        f.doc = serde_json::from_str(&merged).map_err(|e| e.to_string())?;
        read_docs_into_rows(&f.doc, &mut f.rows);
        carried += stats.carried;
        still_new += stats.still_new;
    }
    if !model.names_doc.is_null() {
        let json = serde_json::to_string(&model.names_doc).map_err(|e| e.to_string())?;
        let (merged, stats) = apply_memory(&json, &memory)?;
        model.names_doc = serde_json::from_str(&merged).map_err(|e| e.to_string())?;
        read_docs_into_rows(&model.names_doc, &mut model.names);
        carried += stats.carried;
        still_new += stats.still_new;
    }
    Ok(MergeOutcome { carried, still_new })
}

/// Read the `text` leaf each row points at back into the row's `translation` (the inverse of
/// [`apply_rows_to_doc`]). Used after a merge rewrote the documents.
fn read_docs_into_rows(doc: &Value, rows: &mut [Row]) {
    for r in rows {
        if let Some(Value::String(s)) = doc.pointer(&r.ptr) {
            // Keep the empty-when-untranslated invariant so the memory + UX stay consistent.
            r.translation = if *s == r.source { String::new() } else { s.clone() };
        }
    }
}

/// Run the name-conflict check over the current model's name glossary + every file's current JSON
/// (so a name translated inconsistently between the glossary and a DB/scene is caught). Returns the
/// conflicts the library found.
pub fn check_conflicts(model: &mut TranslationModel) -> Vec<Conflict> {
    model.sync_docs();
    let mut docs: Vec<(String, String)> = Vec::new();
    docs.push(("Names".to_string(), model.names_doc.to_string()));
    for f in &model.files {
        docs.push((f.display_name(), f.doc.to_string()));
    }
    let refs: Vec<(String, &str)> = docs.iter().map(|(n, j)| (n.clone(), j.as_str())).collect();
    check_name_conflicts(&refs)
}

/// Serialize the whole model to a single self-describing JSON for the project file. Stores each
/// file's path/kind + its (synced) document, plus the names document, enough to fully restore.
pub fn save_to_path(model: &mut TranslationModel, path: &Path) -> Result<(), String> {
    model.sync_docs();
    let files: Vec<Value> = model
        .files
        .iter()
        .map(|f| {
            serde_json::json!({
                "path": f.path.to_string_lossy(),
                "kind": f.kind.tag(),
                "doc": f.doc,
            })
        })
        .collect();
    let root = serde_json::json!({
        "wolfdawn_translation": 1,
        "data_dir": model.data_dir.to_string_lossy(),
        "files": files,
        "names": model.names_doc,
    });
    let text = serde_json::to_string_pretty(&root).map_err(|e| e.to_string())?;
    std::fs::write(path, text).map_err(|e| e.to_string())
}

/// Restore a model previously written by [`save_to_path`].
pub fn load_from_path(path: &Path) -> Result<TranslationModel, String> {
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let root: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    if root.get("wolfdawn_translation").is_none() {
        return Err("not a WolfDawn translation project file".into());
    }
    let data_dir = PathBuf::from(root.get("data_dir").and_then(Value::as_str).unwrap_or(""));
    let mut files = Vec::new();
    if let Some(arr) = root.get("files").and_then(Value::as_array) {
        for f in arr {
            let path = PathBuf::from(f.get("path").and_then(Value::as_str).unwrap_or(""));
            let kind = match f.get("kind").and_then(Value::as_str).unwrap_or("") {
                "map" => FileKind::Map,
                "common" => FileKind::CommonEvent,
                "db" => FileKind::Database,
                "gamedat" => FileKind::GameDat,
                "txt" => FileKind::TxtEvent,
                other => return Err(format!("unknown file kind {other:?} in project file")),
            };
            let doc = f.get("doc").cloned().unwrap_or(Value::Null);
            let rows = match kind {
                FileKind::Map | FileKind::CommonEvent => rows_from_scenes(&doc),
                FileKind::Database => rows_from_db(&doc),
                FileKind::GameDat => rows_from_gamedat(&doc),
                FileKind::TxtEvent => rows_from_txt(&doc),
            };
            files.push(FileEntry { path, kind, rows, doc });
        }
    }
    let names_doc = root.get("names").cloned().unwrap_or(Value::Null);
    let names = rows_from_names(&names_doc);
    Ok(TranslationModel { data_dir, files, names, names_doc })
}

// --- small helpers (mirror the CLI's) ---------------------------------------------------------

/// Relative path of `path` under `base`, as a `PathBuf` for re-joining under an output dir.
fn rel(base: &Path, path: &Path) -> PathBuf {
    path.strip_prefix(base).unwrap_or(path).to_path_buf()
}

/// Collect every `*.json` under `path` (recursively for a dir, the file itself if it is a `.json`).
fn collect_json_files(path: &Path, out: &mut Vec<PathBuf>) {
    if path.is_dir() {
        let Ok(rd) = std::fs::read_dir(path) else {
            return;
        };
        for e in rd.flatten() {
            collect_json_files(&e.path(), out);
        }
    } else if path.extension().and_then(|s| s.to_str()) == Some("json") {
        out.push(path.to_path_buf());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Resolve a fixture by its clean relative path under `WOLFDAWN_TEST_DATA`. Returns `None` when
    /// the var is unset or the file/dir is missing, so the data-dependent tests skip gracefully.
    fn test_data(rel: &str) -> Option<PathBuf> {
        let base = std::env::var_os("WOLFDAWN_TEST_DATA")?;
        let p = std::path::Path::new(&base).join(rel);
        p.exists().then_some(p)
    }

    /// The shared Data-dir fixture. Tests skip gracefully when it is absent (CI without the corpus).
    fn fixture_dir() -> Option<PathBuf> {
        test_data("chamber/Data")
            .filter(|d| d.join("BasicData").join("CommonEvent.dat").exists())
    }

    fn tmp_out(tag: &str) -> PathBuf {
        let p = std::env::temp_dir().join(format!(
            "wolfdawn_tr_{tag}_{}_{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        ));
        let _ = std::fs::create_dir_all(&p);
        p
    }

    /// A self-contained data dir with one event-text `.txt` (no external fixture needed) round-trips
    /// through the model: extract picks it up as a TxtEvent entry with the dialogue (not the `/`
    /// command lines), and an edit injects back into the file byte-aware while the commands survive.
    #[test]
    fn txt_event_round_trip_through_model() {
        let dir = tmp_out("txt");
        let evt = dir.join("Evtext");
        std::fs::create_dir_all(&evt).unwrap();
        let txt_path = evt.join("scene.txt");
        // UTF-8 so the test needs no encoding crate; the extractor detects UTF-8 vs Shift-JIS.
        let original = "/evcg,a0\r\nアイリス：\r\n元のセリフ\r\n/b\r\n";
        std::fs::write(&txt_path, original.as_bytes()).unwrap();

        let mut outcome = extract_model(&dir, |_, _| {}).expect("extract");
        let entry = outcome
            .model
            .files
            .iter_mut()
            .find(|f| f.kind == FileKind::TxtEvent)
            .expect("a TxtEvent entry from the .txt");
        assert!(
            entry.rows.iter().any(|r| r.source == "元のセリフ"),
            "the dialogue line should be extracted"
        );
        assert!(
            entry.rows.iter().all(|r| !r.source.starts_with('/')),
            "no /command or //comment line should be extracted"
        );

        // Edit the dialogue line, inject in place.
        let row = entry.rows.iter_mut().find(|r| r.source == "元のセリフ").unwrap();
        row.translation = "新しいセリフ".to_string();
        let reports = inject_model(
            &mut outcome.model,
            &InjectOptions::default(),
            &InjectTarget::InPlace,
            |_, _| {},
        )
        .expect("inject");
        assert!(reports.iter().any(|r| r.applied >= 1), "the txt edit should apply");

        // The file now holds the new text, the old text is gone, and the commands are intact.
        let after = std::fs::read_to_string(&txt_path).unwrap();
        assert!(after.contains("新しいセリフ"), "edited text present");
        assert!(!after.contains("元のセリフ"), "old text gone");
        assert!(after.contains("/evcg,a0") && after.contains("/b"), "command lines intact");
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Extract -> edit one row -> inject to a temp out dir -> re-extract -> the edit is present.
    /// Proves extract->edit->inject works through the GUI's own code paths.
    #[test]
    fn round_trip_extract_edit_inject() {
        let Some(dir) = fixture_dir() else {
            eprintln!("skip round_trip_extract_edit_inject: fixture not present");
            return;
        };
        let mut outcome = extract_model(&dir, |_, _| {}).expect("extract");
        let model = &mut outcome.model;
        assert!(!model.files.is_empty(), "should have extracted at least one file");
        assert!(model.total_rows() > 0, "model should have non-empty rows");

        // Find the first file with at least one row and edit its first row.
        let (fi, edited_source, edited_text) = {
            let f = model
                .files
                .iter_mut()
                .find(|f| !f.rows.is_empty())
                .expect("a file with rows");
            let row = &mut f.rows[0];
            let src = row.source.clone();
            let new = format!("{src} [EDITED-BY-TEST]");
            row.translation = new.clone();
            (f.path.clone(), src, new)
        };

        let out = tmp_out("rt");
        let reports = inject_model(
            model,
            &InjectOptions::default(),
            &InjectTarget::OutDir(out.clone()),
            |_, _| {},
        )
        .expect("inject");
        assert!(reports.iter().any(|r| r.applied >= 1), "at least one translation applied");

        // Re-extract from the output dir and confirm the edit survived the byte-exact round-trip.
        let re = extract_model(&out, |_, _| {}).expect("re-extract");
        let same_file = re
            .model
            .files
            .iter()
            .find(|f| f.path.file_name() == fi.file_name())
            .expect("the edited file re-extracted");
        let found = same_file
            .rows
            .iter()
            .any(|r| r.source == edited_text || r.translation == edited_text);
        assert!(found, "the injected edit {edited_text:?} should re-extract (source was {edited_source:?})");

        let _ = std::fs::remove_dir_all(&out);
    }

    /// en-punct: a translation containing 「」, injected with normalize_punct=true, re-extracts as
    /// ASCII quotes.
    #[test]
    fn en_punct_normalizes_brackets() {
        let Some(dir) = fixture_dir() else {
            eprintln!("skip en_punct_normalizes_brackets: fixture not present");
            return;
        };
        let mut outcome = extract_model(&dir, |_, _| {}).expect("extract");
        let model = &mut outcome.model;

        // Pick a CLEAN source row (no inline `\code`, `@window` prefix, or `<R>/<C>` tag, and no
        // newlines) so replacing it wholesale with a bracketed translation can never trip the
        // control-code guard, and the assertion is unambiguous. Set it to a fixed `「Hello」`.
        let marker = "「Hello」";
        let edited_loc = {
            let mut chosen: Option<(usize, usize)> = None;
            'outer: for (fi, f) in model.files.iter().enumerate() {
                for (ri, r) in f.rows.iter().enumerate() {
                    if !r.source.contains(['\\', '@', '<', '>', '\n']) && !r.source.is_empty() {
                        chosen = Some((fi, ri));
                        break 'outer;
                    }
                }
            }
            let (fi, ri) = chosen.expect("a clean source row");
            model.files[fi].rows[ri].translation = marker.to_string();
            (fi, ri)
        };

        let out = tmp_out("punct");
        let opts = InjectOptions {
            normalize_punct: true,
            ..Default::default()
        };
        let reports =
            inject_model(model, &opts, &InjectTarget::OutDir(out.clone()), |_, _| {}).expect("inject");
        assert!(reports.iter().any(|r| r.applied >= 1), "the en-punct edit should apply");

        // Re-extract from the output dir: the brackets must have become ASCII double quotes.
        let re = extract_model(&out, |_, _| {}).expect("re-extract");
        let edited_file = &model.files[edited_loc.0];
        let same = re
            .model
            .files
            .iter()
            .find(|f| f.path.file_name() == edited_file.path.file_name())
            .expect("edited file re-extracted");
        let found = same.rows.iter().any(|r| r.source == "\"Hello\"");
        assert!(
            found,
            "en-punct should have produced ASCII quotes (\"Hello\"); re-extracted sources did not contain it"
        );

        let _ = std::fs::remove_dir_all(&out);
    }

    /// Save then load restores the model's rows and edits.
    #[test]
    fn save_load_round_trip() {
        let Some(dir) = fixture_dir() else {
            eprintln!("skip save_load_round_trip: fixture not present");
            return;
        };
        let mut outcome = extract_model(&dir, |_, _| {}).expect("extract");
        let model = &mut outcome.model;
        let total = model.total_rows();
        // Edit a row so we can assert the translation survives save/load.
        let edited = {
            let f = model.files.iter_mut().find(|f| !f.rows.is_empty()).expect("rows");
            f.rows[0].translation = format!("{} [SAVED]", f.rows[0].source);
            f.rows[0].translation.clone()
        };

        let out = tmp_out("save");
        let proj_file = out.join("project.wdtr.json");
        save_to_path(model, &proj_file).expect("save");
        let restored = load_from_path(&proj_file).expect("load");
        assert_eq!(restored.total_rows(), total, "row count should survive save/load");
        let found = restored
            .files
            .iter()
            .flat_map(|f| f.rows.iter())
            .any(|r| r.translation == edited);
        assert!(found, "the edited translation should survive save/load");

        let _ = std::fs::remove_dir_all(&out);
    }
}
