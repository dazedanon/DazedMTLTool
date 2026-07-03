//! The Database section's data model and the headless logic behind it.
//!
//! A spreadsheet-like editor over a Wolf database (`*.project` + sibling `*.dat`) so a non-coder can
//! change values like item prices, skill power, or enemy HP without touching JSON. This module owns
//! everything *except* the egui rendering (which lives in `app.rs`), so the whole load/edit/save
//! flow can be exercised headlessly in tests.
//!
//! It mirrors the CLI's `db-json` (`database_to_json`) + `db-apply` (`apply_database_edit`) pair,
//! calling the **same** `wolf_decompiler` library functions directly (no shelling out), so the GUI
//! and CLI agree on the JSON shape and the byte-exact apply:
//!
//!   * [`load`] reads the `.project`+`.dat` pair with [`Database::read`], renders it to JSON with
//!     [`database_to_json`] (exactly what `cmd_db_json` does, via the same per-stem `kind` label),
//!     parses it into a [`DbModel`] of [`DbType`]s -> [`DbRow`]s -> [`Cell`]s, and **keeps the parsed
//!     `doc`** so a save can rewrite just the edited leaves. Each editable cell carries a JSON
//!     Pointer (RFC 6901) to its leaf in `doc`, exactly like `translation.rs`, so an edit touches
//!     one leaf and every other byte stays identical.
//!   * [`save`] writes each row's edited value into the leaf its pointer addresses, serializes the
//!     patched `doc`, and applies it with [`apply_database_edit`] onto a freshly-read base (the
//!     `db-apply` path), re-parses the [`Database::write`] output to verify it round-trips, and
//!     writes the `.project`+`.dat` pair together byte-exact, optionally backing up the originals
//!     first. Untouched data re-serializes verbatim, so a no-change save reproduces both halves
//!     byte-for-byte.
//!
//! The DB `.project` is the canonical handle. The sibling `.dat` is paired by extension, mirroring
//! the CLI's `cmd_db_apply` (`base.with_extension("dat")`).

use std::path::{Path, PathBuf};

use serde_json::Value;
use wolf_decompiler::{apply_database_edit, database_to_json};
use wolf_formats::database::Database;

/// One editable cell of a data row: which field column it belongs to, the editable value (as text -
/// ints are edited as their decimal string and validated on apply), whether it is a string or int
/// field (so the grid can hint and the apply path can re-type it), and the JSON Pointer to this
/// cell's leaf inside the owning [`DbModel::doc`]. The pointer is what makes a save lossless: an edit
/// rewrites exactly that one leaf, leaving every other byte of the document untouched.
#[derive(Clone)]
pub struct Cell {
    /// The owning field's display key (the same key the JSON `values` object uses).
    pub field: String,
    /// The editable value, as text (string cells verbatim, int cells as their decimal form).
    pub value: String,
    /// The value as loaded (read-only, for change detection).
    pub original: String,
    /// `true` for a string field, `false` for an int field.
    pub is_string: bool,
    /// RFC 6901 JSON Pointer to this cell's value leaf inside [`DbModel::doc`].
    ptr: String,
}

impl Cell {
    /// True when the user changed this cell from its loaded value.
    pub fn is_changed(&self) -> bool {
        self.value != self.original
    }
}

/// One data row of a type: its editable display name (+ pointer) plus one [`Cell`] per data field.
#[derive(Clone)]
pub struct DbRow {
    /// The row's stable id (its index in the type's data), shown for orientation.
    pub id: usize,
    /// The editable row name (the first grid column).
    pub name: String,
    /// The name as loaded (read-only, for change detection).
    pub name_original: String,
    /// JSON Pointer to this row's `name` leaf inside [`DbModel::doc`].
    name_ptr: String,
    /// One cell per data field, in column order.
    pub cells: Vec<Cell>,
}

impl DbRow {
    /// How many of this row's editable leaves changed (name counts as one).
    pub fn changed_count(&self) -> usize {
        let n = usize::from(self.name != self.name_original);
        n + self.cells.iter().filter(|c| c.is_changed()).count()
    }
}

/// One database type (タイプ), a table like "Skill", "Item", "Enemy": its display name, the data
/// field column names (in order), and its data rows.
pub struct DbType {
    /// The type's display name (e.g. `技能 / Skill`).
    pub name: String,
    /// The data field column names, in order (the grid header, after the row-name column).
    pub fields: Vec<String>,
    /// The data rows.
    pub rows: Vec<DbRow>,
}

impl DbType {
    /// How many editable leaves the user changed across this type.
    pub fn changed_count(&self) -> usize {
        self.rows.iter().map(DbRow::changed_count).sum()
    }
}

/// The loaded, editable view of a database: where it came from (the `.project`, with the `.dat`
/// paired by extension), the read-only kind/encoding badges, and the types.
///
/// The full parsed JSON document is NOT kept resident. It is the heaviest part of a large database
/// (every value and a repeated key per row, plus map overhead), so save/export rebuild it on demand
/// from the base file and apply the edits then. The editable grid keeps only what a user can change
/// (cell values + row names) plus each leaf's JSON pointer.
pub struct DbModel {
    /// The on-disk `.project` this was loaded from (the [`save`] in-place target, `.dat` is sibling).
    pub project: PathBuf,
    /// The DB kind label (`UDB` / `CDB` / `SDB`), read-only.
    pub kind: String,
    /// The text encoding badge (`UTF-8` / `Shift-JIS`), read-only.
    pub encoding: String,
    /// The types (tables), in order.
    pub types: Vec<DbType>,
}

impl DbModel {
    /// Total data rows across every type.
    pub fn total_rows(&self) -> usize {
        self.types.iter().map(|t| t.rows.len()).sum()
    }

    /// How many editable leaves the user changed across the whole model.
    pub fn changed_count(&self) -> usize {
        self.types.iter().map(DbType::changed_count).sum()
    }

    /// True when anything was edited (so the Save button can gate on it).
    pub fn dirty(&self) -> bool {
        self.changed_count() > 0
    }
}

/// The per-stem `kind` label, matching the CLI's `db_json_one` exactly.
fn kind_for(proj: &Path) -> &'static str {
    match proj.file_stem().and_then(|s| s.to_str()) {
        Some("DataBase") => "UDB",
        Some("CDataBase") => "CDB",
        Some("SysDatabase") => "SDB",
        _ => "DB",
    }
}

/// Escape one path token for an RFC 6901 JSON Pointer (`~` -> `~0`, `/` -> `~1`). Field keys can
/// contain `/` (e.g. `発動回数/武器の影響`) so this must run on every dynamic segment.
fn esc(token: &str) -> String {
    token.replace('~', "~0").replace('/', "~1")
}

/// Read and parse the `.project`+`.dat` pair into the editable grid model, reusing [`Database::read`]
/// + [`database_to_json`] (the CLI's `db-json` path) with the same per-stem `kind` label. The
/// returned model keeps the parsed JSON so a later [`save`] rewrites only the edited leaves.
pub fn load(project: &Path) -> Result<DbModel, String> {
    let dat = project.with_extension("dat");
    let pb = std::fs::read(project)
        .map_err(|e| format!("cannot read {}: {e}", project.display()))?;
    let db_ = std::fs::read(&dat).map_err(|e| format!("cannot read {}: {e}", dat.display()))?;
    let db = Database::read(&pb, &db_).map_err(|e| format!("database parse failed: {e}"))?;
    let kind = kind_for(project);
    let glossary = wolf_decompiler::symbols::load_embedded_engine_glossary();
    let json = database_to_json(&db, kind, &glossary);
    let doc: Value = serde_json::from_str(&json).map_err(|e| format!("invalid DB JSON: {e}"))?;

    let kind_s = doc
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or(kind)
        .to_string();
    let encoding = doc
        .get("encoding")
        .and_then(Value::as_str)
        .unwrap_or("UTF-8")
        .to_string();

    let types = types_from_doc(&doc);
    // `doc` is dropped here: the grid carries everything editable, and save/export rebuild the doc
    // from the base file when needed, so it is not held for the session.
    Ok(DbModel {
        project: project.to_path_buf(),
        kind: kind_s,
        encoding,
        types,
    })
}

/// Build the editable types/rows/cells (each carrying its JSON pointer) from the parsed document.
fn types_from_doc(doc: &Value) -> Vec<DbType> {
    let mut out = Vec::new();
    let Some(types) = doc.get("types").and_then(Value::as_array) else {
        return out;
    };
    for (idx, t) in types.iter().enumerate() {
        let ti = t.get("id").and_then(Value::as_u64).map(|n| n as usize).unwrap_or(idx);
        let type_name = display_name(t);

        // The data field columns are the keys of the FIRST row's `values` object, in order (only the
        // `fields_size` data fields appear there, schema-only fields are absent, matching the export).
        // We derive the column order + each cell's string/int kind from the `fields` schema, keyed by
        // the same `values` key (unique field name, else `#<id>`), so a missing first row still works.
        let columns = value_columns(t);
        let field_labels: Vec<String> = columns.iter().map(|c| c.label.clone()).collect();

        let mut rows = Vec::new();
        if let Some(rs) = t.get("rows").and_then(Value::as_array) {
            for r in rs {
                let ri = r.get("id").and_then(Value::as_u64).unwrap_or(0) as usize;
                let name = r.get("name").and_then(Value::as_str).unwrap_or("").to_string();
                let mut cells = Vec::with_capacity(columns.len());
                for col in &columns {
                    let v = r.get("values").and_then(|vv| vv.get(&col.key));
                    let value = match v {
                        Some(Value::String(s)) => s.clone(),
                        Some(Value::Number(n)) => n.to_string(),
                        Some(other) => other.to_string(),
                        None => String::new(),
                    };
                    cells.push(Cell {
                        field: col.label.clone(),
                        original: value.clone(),
                        value,
                        is_string: col.is_string,
                        ptr: format!("/types/{ti}/rows/{ri}/values/{}", esc(&col.key)),
                    });
                }
                rows.push(DbRow {
                    id: ri,
                    name_original: name.clone(),
                    name,
                    name_ptr: format!("/types/{ti}/rows/{ri}/name"),
                    cells,
                });
            }
        }

        out.push(DbType {
            name: type_name,
            fields: field_labels,
            rows,
        });
    }
    out
}

/// A data column derived from a type's schema: the `values` key, a friendly label, and the kind.
struct Column {
    /// The key as it appears in each row's `values` object.
    key: String,
    /// A friendly column label (`name_en` when present, else the JP `name`).
    label: String,
    /// `true` for a string field.
    is_string: bool,
}

/// Derive the ordered data columns from a type's `fields` schema. A field carries row data unless it
/// is tagged `schemaOnly: true`. Its `values` key is its unique field name, else `#<id>`, the same
/// rule `value_slots`/`database_to_json` use, so the keys always match the row objects.
fn value_columns(t: &Value) -> Vec<Column> {
    let Some(fields) = t.get("fields").and_then(Value::as_array) else {
        return Vec::new();
    };
    // Count name occurrences among data-bearing fields so duplicates fall back to `#<id>`.
    let data_fields: Vec<&Value> = fields
        .iter()
        .filter(|f| !f.get("schemaOnly").and_then(Value::as_bool).unwrap_or(false))
        .collect();
    let mut name_counts: std::collections::HashMap<&str, u32> = std::collections::HashMap::new();
    for f in &data_fields {
        let n = f.get("name").and_then(Value::as_str).unwrap_or("");
        if !n.is_empty() {
            *name_counts.entry(n).or_default() += 1;
        }
    }
    let mut out = Vec::with_capacity(data_fields.len());
    for f in &data_fields {
        let fi = f.get("id").and_then(Value::as_u64).unwrap_or(0) as usize;
        let jp = f.get("name").and_then(Value::as_str).unwrap_or("");
        let en = f.get("name_en").and_then(Value::as_str);
        let key = if jp.is_empty() || name_counts.get(jp).copied().unwrap_or(0) > 1 {
            format!("#{fi}")
        } else {
            jp.to_string()
        };
        let label = match en {
            Some(e) if !e.is_empty() && e != jp => format!("{jp} / {e}"),
            _ if jp.is_empty() => format!("#{fi}"),
            _ => jp.to_string(),
        };
        let is_string = f.get("kind").and_then(Value::as_str) == Some("string");
        out.push(Column { key, label, is_string });
    }
    out
}

/// A friendly display name for a type/row: `name_en` appended when present (`JP / EN`), else JP.
fn display_name(v: &Value) -> String {
    let jp = v.get("name").and_then(Value::as_str).unwrap_or("");
    match v.get("name_en").and_then(Value::as_str) {
        Some(en) if !en.is_empty() && en != jp => format!("{jp} / {en}"),
        _ => jp.to_string(),
    }
}

// ----------------------------------------------------------------------------
// Save / export: rebuild the doc from the base, patch in the edits, apply + write
// ----------------------------------------------------------------------------

/// Push each row's edited name + cell values into `doc` (a freshly rebuilt `database_to_json`
/// document), via each leaf's JSON pointer, so the document is current before it is fed to
/// `apply_database_edit`. Int cells write a JSON number (so the apply path's `as_i64` accepts them).
/// String cells write a JSON string. An int cell that does not parse is a hard error here with a
/// clear field reference.
fn apply_edits_to_doc(model: &DbModel, doc: &mut Value) -> Result<(), String> {
    for t in &model.types {
        for r in &t.rows {
            if r.name != r.name_original {
                if let Some(slot) = doc.pointer_mut(&r.name_ptr) {
                    *slot = Value::String(r.name.clone());
                }
            }
            for c in &r.cells {
                if !c.is_changed() {
                    continue;
                }
                let Some(slot) = doc.pointer_mut(&c.ptr) else {
                    continue;
                };
                if c.is_string {
                    *slot = Value::String(c.value.clone());
                } else {
                    let n: i64 = c.value.trim().parse().map_err(|_| {
                        format!(
                            "field {:?} in type {:?} row {} ({:?}): {:?} is not a whole number",
                            c.field, t.name, r.id, r.name, c.value
                        )
                    })?;
                    *slot = Value::Number(n.into());
                }
            }
        }
    }
    Ok(())
}

/// Rebuild the full `database_to_json` document from the base `.project`+`.dat` and patch in the
/// grid's edits. The doc is not kept resident, so this re-reads the base (deterministic, same
/// structure as load) and applies the edits via their pointers. Returns the edited doc plus the base
/// bytes, so [`save`] can apply onto the same bytes without a second read.
fn edited_doc(model: &DbModel) -> Result<(Value, Vec<u8>, Vec<u8>), String> {
    let base_proj = &model.project;
    let base_dat = base_proj.with_extension("dat");
    let pb = std::fs::read(base_proj)
        .map_err(|e| format!("cannot read base {}: {e}", base_proj.display()))?;
    let db_ = std::fs::read(&base_dat)
        .map_err(|e| format!("cannot read base {}: {e}", base_dat.display()))?;
    let db = Database::read(&pb, &db_).map_err(|e| format!("base parse failed: {e}"))?;
    let glossary = wolf_decompiler::symbols::load_embedded_engine_glossary();
    let json = database_to_json(&db, kind_for(base_proj), &glossary);
    let mut doc: Value = serde_json::from_str(&json).map_err(|e| format!("invalid DB JSON: {e}"))?;
    apply_edits_to_doc(model, &mut doc)?;
    Ok((doc, pb, db_))
}

/// Apply an edits JSON onto a fresh base, verify the result re-parses, then write the `.project`+
/// `.dat` pair (backing up existing halves first when asked). The shared tail of [`save`] and
/// [`import_json`]. `base_pb`/`base_dat_bytes`, when supplied, are the already-read base bytes (save
/// reuses them); pass `None` to read the base here (import).
fn apply_and_write(
    base_project: &Path,
    edited_json: &str,
    out_project: &Path,
    backup: bool,
    base_bytes: Option<(Vec<u8>, Vec<u8>)>,
) -> Result<SaveOutcome, String> {
    let base_dat = base_project.with_extension("dat");
    let out_dat = out_project.with_extension("dat");
    let (pb, db_) = match base_bytes {
        Some(b) => b,
        None => (
            std::fs::read(base_project)
                .map_err(|e| format!("cannot read base {}: {e}", base_project.display()))?,
            std::fs::read(&base_dat)
                .map_err(|e| format!("cannot read base {}: {e}", base_dat.display()))?,
        ),
    };
    let mut db = Database::read(&pb, &db_).map_err(|e| format!("base parse failed: {e}"))?;
    let changed =
        apply_database_edit(edited_json, &mut db).map_err(|e| format!("apply failed: {e}"))?;

    let (out_pb, out_db) = db.write();
    // Re-parse the output to verify it still round-trips before committing it. Never ship a
    // structurally-corrupt pair.
    Database::read(&out_pb, &out_db)
        .map_err(|e| format!("internal error: edited database no longer parses ({e})"))?;
    let byte_identical = out_pb == pb && out_db == db_;

    let mut backups = Vec::new();
    if backup {
        for half in [out_project, out_dat.as_path()] {
            if half.exists() {
                let bak = backup_path(half);
                std::fs::copy(half, &bak)
                    .map_err(|e| format!("backup failed ({}): {e}", bak.display()))?;
                backups.push(bak);
            }
        }
    }
    if let Some(parent) = out_project.parent() {
        if !parent.as_os_str().is_empty() {
            let _ = std::fs::create_dir_all(parent);
        }
    }
    if let (Err(e), _) | (_, Err(e)) = (
        std::fs::write(out_project, &out_pb),
        std::fs::write(&out_dat, &out_db),
    ) {
        return Err(format!("write failed: {e}"));
    }
    Ok(SaveOutcome {
        changed,
        byte_identical,
        out_project: out_project.to_path_buf(),
        out_dat,
        backups,
    })
}

/// Export the on-disk database as a pretty-printed `database_to_json` document for editing outside
/// the GUI (re-import with [`import_json`]). Reads only the base path, so it runs on a worker without
/// borrowing the live grid. Grid edits are NOT included here, so Save first to bake them in.
pub fn export_json(base_project: &Path, out: &Path) -> Result<(), String> {
    let base_dat = base_project.with_extension("dat");
    let pb = std::fs::read(base_project)
        .map_err(|e| format!("cannot read {}: {e}", base_project.display()))?;
    let db_ = std::fs::read(&base_dat)
        .map_err(|e| format!("cannot read {}: {e}", base_dat.display()))?;
    let db = Database::read(&pb, &db_).map_err(|e| format!("database parse failed: {e}"))?;
    let glossary = wolf_decompiler::symbols::load_embedded_engine_glossary();
    let json = database_to_json(&db, kind_for(base_project), &glossary);
    let doc: Value = serde_json::from_str(&json).map_err(|e| format!("invalid DB JSON: {e}"))?;
    let pretty = serde_json::to_string_pretty(&doc).map_err(|e| e.to_string())?;
    std::fs::write(out, pretty.as_bytes())
        .map_err(|e| format!("cannot write {}: {e}", out.display()))?;
    Ok(())
}

/// Import an edited `database_to_json` document (full or patch-style), apply it onto `base_project`'s
/// pair, and write to `out_project`. The same verify-then-write guard as [`save`].
pub fn import_json(
    base_project: &Path,
    json_path: &Path,
    out_project: &Path,
    backup: bool,
) -> Result<SaveOutcome, String> {
    let json = std::fs::read_to_string(json_path)
        .map_err(|e| format!("cannot read {}: {e}", json_path.display()))?;
    apply_and_write(base_project, &json, out_project, backup, None)
}

/// Where a backup goes for an in-place save of one half.
fn backup_path(file: &Path) -> PathBuf {
    let mut name = file.file_name().map(|s| s.to_os_string()).unwrap_or_default();
    name.push(".bak");
    file.with_file_name(name)
}

/// The outcome of a [`save`] run, for the log.
pub struct SaveOutcome {
    /// How many cells/names `apply_database_edit` actually changed.
    pub changed: usize,
    /// True when both output halves are byte-identical to the base (a no-op save, or edits that net
    /// to the original values).
    pub byte_identical: bool,
    /// Where the `.project` was written.
    pub out_project: PathBuf,
    /// Where the `.dat` was written.
    pub out_dat: PathBuf,
    /// The backup paths made (`.project.bak`, `.dat.bak`), if any.
    pub backups: Vec<PathBuf>,
}

/// Apply the grid's edits onto the base database and write the `.project`+`.dat` pair to
/// `out_project` (+ its sibling `.dat`), mirroring the CLI's `db-apply`: patch the parsed doc with
/// the edited leaves, [`apply_database_edit`] it onto a freshly-read base, **re-parse the
/// [`Database::write`] output to verify it round-trips** before writing, and report the change count
/// + byte-identity. When `backup` is set and an output half already exists, the original is copied to
/// `<half>.bak` first.
///
/// Byte-exactness: `apply_database_edit` only rewrites cells whose value changed (it skips unchanged
/// strings to dodge the empty-string / trailing-NUL re-encode ambiguity), so untouched data
/// re-serializes verbatim and a no-change save reproduces both halves byte-for-byte.
pub fn save(model: &DbModel, out_project: &Path, backup: bool) -> Result<SaveOutcome, String> {
    let (doc, pb, db_) = edited_doc(model)?;
    let edited_json = serde_json::to_string(&doc).map_err(|e| e.to_string())?;
    apply_and_write(&model.project, &edited_json, out_project, backup, Some((pb, db_)))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A unique temp dir for scratch output (never a game folder or the fixtures root).
    fn tmp_dir(tag: &str) -> PathBuf {
        let p = std::env::temp_dir().join(format!(
            "wolfdawn_db_{tag}_{}_{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        ));
        let _ = std::fs::create_dir_all(&p);
        p
    }

    /// Resolve a fixture by its clean relative path under `WOLFDAWN_TEST_DATA`. Returns `None` when
    /// the var is unset or the file is missing, so the data-dependent tests skip gracefully.
    fn test_data(rel: &str) -> Option<PathBuf> {
        let base = std::env::var_os("WOLFDAWN_TEST_DATA")?;
        let p = std::path::Path::new(&base).join(rel);
        p.exists().then_some(p)
    }

    /// The shared DB fixture (`.project` plus its `.dat` sibling); tests skip when it is absent.
    fn fixture() -> Option<PathBuf> {
        test_data("chamber/Data/BasicData/DataBase.project")
            .filter(|p| p.with_extension("dat").exists())
    }

    /// Copy the `.project`+`.dat` pair into `dir`, returning the copied `.project` path.
    fn copy_pair(src_proj: &Path, dir: &Path) -> PathBuf {
        let stem = src_proj.file_name().unwrap();
        let dst_proj = dir.join(stem);
        let dst_dat = dst_proj.with_extension("dat");
        std::fs::copy(src_proj, &dst_proj).expect("copy .project");
        std::fs::copy(src_proj.with_extension("dat"), &dst_dat).expect("copy .dat");
        dst_proj
    }

    /// Load a real DB, edit one cell's value, save to a temp output, reload from the output: the
    /// edited cell shows the new value and an UNEDITED type/row is unchanged. Never touches the
    /// fixtures root (reads the fixture, copies + writes only into a temp dir).
    #[test]
    fn load_edit_cell_save_reload_round_trip() {
        let Some(src) = fixture() else {
            eprintln!("skip load_edit_cell_save_reload_round_trip: no DB fixture present");
            return;
        };
        let work = tmp_dir("rt");
        let base = copy_pair(&src, &work);

        let mut m = load(&base).expect("load");
        assert!(!m.types.is_empty(), "DB should have at least one type");
        assert!(m.total_rows() >= 1, "DB should have at least one data row");

        // Find a type with at least one row that has at least one cell, and edit the first cell.
        let (ti, ri, ci, new_value, is_string) = {
            let mut found = None;
            'outer: for (ti, t) in m.types.iter().enumerate() {
                for (ri, r) in t.rows.iter().enumerate() {
                    if !r.cells.is_empty() {
                        found = Some((ti, ri));
                        break 'outer;
                    }
                }
            }
            let (ti, ri) = found.expect("a type/row with at least one cell");
            let cell = &m.types[ti].rows[ri].cells[0];
            // For a string cell, append a marker. For an int cell, bump it by 1 (stays a valid int).
            let new = if cell.is_string {
                format!("{}_EDIT", cell.value)
            } else {
                let cur: i64 = cell.value.trim().parse().unwrap_or(0);
                (cur + 1).to_string()
            };
            (ti, ri, 0usize, new, cell.is_string)
        };
        // Record an UNEDITED reference cell elsewhere (a different row, or a different type).
        let reference = {
            let mut chosen = None;
            'r: for (oti, t) in m.types.iter().enumerate() {
                for (ori, r) in t.rows.iter().enumerate() {
                    if (oti, ori) != (ti, ri) && !r.cells.is_empty() {
                        chosen = Some((oti, ori, r.cells[0].value.clone()));
                        break 'r;
                    }
                }
            }
            chosen
        };

        m.types[ti].rows[ri].cells[ci].value = new_value.clone();
        assert_eq!(m.changed_count(), 1, "exactly one cell changed");

        let out = work.join("edited.project");
        let outcome = save(&mut m, &out, false).expect("save");
        assert_eq!(outcome.changed, 1, "apply should report one cell changed");
        assert!(!outcome.byte_identical, "an edited save differs from base");
        assert!(out.with_extension("dat").exists(), "the .dat half was written");

        // Reload from the OUTPUT pair: the edited cell shows the new value.
        let re = load(&out).expect("reload");
        let got = &re.types[ti].rows[ri].cells[ci];
        assert_eq!(got.value, new_value, "edited cell shows the new value");
        assert_eq!(got.is_string, is_string, "cell kind preserved");

        // The unedited reference cell is unchanged.
        if let Some((oti, ori, orig)) = reference {
            assert_eq!(
                re.types[oti].rows[ori].cells[0].value, orig,
                "an unedited cell must be unchanged after the round-trip"
            );
        }

        let _ = std::fs::remove_dir_all(&work);
    }

    /// A no-change save is byte-exact: load -> save with no edits -> both output halves are
    /// byte-identical to the inputs (lossless-pointer + db-apply's byte-exact pairing).
    #[test]
    fn no_change_save_is_byte_exact() {
        let Some(src) = fixture() else {
            eprintln!("skip no_change_save_is_byte_exact: no DB fixture present");
            return;
        };
        let work = tmp_dir("noop");
        let base = copy_pair(&src, &work);
        let in_proj = std::fs::read(&base).unwrap();
        let in_dat = std::fs::read(base.with_extension("dat")).unwrap();

        let mut m = load(&base).expect("load");
        assert_eq!(m.changed_count(), 0, "nothing edited yet");

        let out = work.join("out.project");
        let outcome = save(&mut m, &out, false).expect("save");
        assert_eq!(outcome.changed, 0, "no cells changed");
        assert!(outcome.byte_identical, "a no-change save must be byte-identical to base");
        assert_eq!(std::fs::read(&out).unwrap(), in_proj, ".project is byte-identical");
        assert_eq!(
            std::fs::read(out.with_extension("dat")).unwrap(),
            in_dat,
            ".dat is byte-identical"
        );

        let _ = std::fs::remove_dir_all(&work);
    }

    /// In-place save with backups: both `.project.bak` and `.dat.bak` hold the original bytes.
    #[test]
    fn in_place_save_backs_up_both_halves() {
        let Some(src) = fixture() else {
            eprintln!("skip in_place_save_backs_up_both_halves: no DB fixture present");
            return;
        };
        let work = tmp_dir("bak");
        let base = copy_pair(&src, &work);
        let orig_proj = std::fs::read(&base).unwrap();
        let orig_dat = std::fs::read(base.with_extension("dat")).unwrap();

        let mut m = load(&base).expect("load");
        // Edit a row name so a save actually rewrites bytes.
        let row = m
            .types
            .iter_mut()
            .find(|t| !t.rows.is_empty())
            .map(|t| &mut t.rows[0])
            .expect("a row");
        row.name = format!("{}_X", row.name);

        let outcome = save(&mut m, &base, true).expect("save in place");
        assert_eq!(outcome.backups.len(), 2, "both halves backed up");
        assert_eq!(std::fs::read(&outcome.backups[0]).unwrap(), orig_proj);
        assert_eq!(std::fs::read(&outcome.backups[1]).unwrap(), orig_dat);

        let _ = std::fs::remove_dir_all(&work);
    }
}
