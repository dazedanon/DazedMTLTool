//! Subcommand implementations for the `wolf` CLI.

use std::path::{Path, PathBuf};
use std::process::ExitCode;

use wolf_decompiler::{
    apply_database_edit, apply_game_dat, apply_memory, audit_common_events_to_json,
    audit_db_to_json, audit_map_to_json, build_memory, check_name_conflicts,
    compile_common_events_edit, compile_map_edit, database_to_json, db_strings_to_json,
    decompile_common_events, decompile_common_events_edit_annotated, decompile_map,
    decompile_map_edit_annotated, dropped_sources, dump_game_dat, extract_common_events,
    extract_db_strings, extract_game_dat, extract_map, extract_names, extract_txt_events,
    inject_common_events, inject_db_strings, inject_game_dat, inject_map, inject_names,
    inject_txt_events, scenes_to_json, update_save, InjectOptions, InjectStats, MergeStats,
    SymbolTable,
};
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::database::Database;
use wolf_formats::game_dat::GameDat;
use wolf_formats::map::Map;

pub(crate) fn cmd_decompile(args: &[String]) -> ExitCode {
    let mut input: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    let mut edit = false;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next().map(PathBuf::from),
            "--mode" => edit = it.next().map(String::as_str) == Some("edit"),
            "--edit" => edit = true,
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let Some(input) = input else {
        eprintln!("decompile: missing input file");
        return ExitCode::from(64);
    };

    let result = if edit {
        decompile_edit_path(&input)
    } else {
        decompile_path(&input)
    };
    let text = match result {
        Ok(t) => t,
        Err(e) => {
            eprintln!("decompile failed for {}: {e}", input.display());
            return ExitCode::from(4);
        }
    };

    match output {
        Some(out) => {
            if let Err(e) = std::fs::write(&out, text) {
                eprintln!("could not write {}: {e}", out.display());
                return ExitCode::from(4);
            }
            eprintln!("wrote {}", out.display());
        }
        None => {
            // Ignore a broken pipe (e.g. piping into `head`) instead of panicking.
            use std::io::Write;
            let _ = std::io::stdout().write_all(text.as_bytes());
        }
    }
    ExitCode::SUCCESS
}

/// `wolf export-names <data-dir>`. Dumps the deduplicated **engine/structural** text
/// (variable names, DB type/field names, system-table row names) for building the
/// engine-text glossary. Excludes player-facing content (item/skill/actor display names).
pub(crate) fn cmd_export_names(args: &[String]) -> ExitCode {
    use std::collections::BTreeSet;

    let dir = PathBuf::from(args.first().map(String::as_str).unwrap_or("."));
    let basic = if dir.join("CommonEvent.dat").exists() {
        dir.clone()
    } else if dir.join("BasicData").join("CommonEvent.dat").exists() {
        dir.join("BasicData")
    } else {
        dir.clone()
    };

    let mut symbols = SymbolTable::new();
    if let Ok(b) = std::fs::read(basic.join("CommonEvent.dat")) {
        if let Ok(ce) = CommonEventsFile::read(&b) {
            symbols.add_common_events(&ce);
        }
    }
    add_databases(&mut symbols, Some(&basic));

    fn consider(set: &mut BTreeSet<String>, s: &str) {
        let t = s.trim();
        let has_jp = t.chars().any(|c| c as u32 >= 0x3000); // CJK/kana - needs translating
                                                            // Exclude markup/format-code chars only. `/`, `=`, `(`, `)` are legitimate in stock
                                                            // engine variable/field names (e.g. "[読]ﾈｯﾄ/状態 -1失敗 0通信中 1終了"), so they stay.
        let noisy = t.contains(['\\', '<', '>', '▼', '★', '※']);
        if !t.is_empty() && t.chars().count() <= 60 && has_jp && !noisy {
            set.insert(t.to_string());
        }
    }

    let mut set = BTreeSet::new();
    for ce in symbols.common_events.values() {
        for v in ce.self_vars.values() {
            consider(&mut set, v);
        }
        for v in &ce.inputs {
            consider(&mut set, v);
        }
    }
    for v in symbols
        .globals
        .normal
        .values()
        .chain(symbols.globals.string.values())
        .chain(symbols.globals.system.values())
    {
        consider(&mut set, v);
    }
    for db in &symbols.databases {
        for t in &db.types {
            consider(&mut set, &t.name);
            for f in &t.fields {
                consider(&mut set, f);
            }
            // System/config row names only (SysDB rows + the Basic-System CDB tables);
            // User-DB content rows (item/skill names) are player-facing game text.
            let system_rows = db.kind == "SDB" || (db.kind == "CDB" && t.name.contains("基本"));
            if system_rows {
                for d in &t.data {
                    consider(&mut set, d);
                }
            }
        }
    }

    for s in &set {
        println!("{s}");
    }
    eprintln!("{} unique engine-text strings", set.len());
    ExitCode::SUCCESS
}

/// `wolf xref <ref> <data-dir>`. Finds every write/read of a variable/reference across
/// all maps and common events. Answers "where is this value set?".
pub(crate) fn cmd_xref(args: &[String]) -> ExitCode {
    let Some(reff) = args.first() else {
        eprintln!("xref: usage: wolf xref \"<ref>\" <data-dir>");
        return ExitCode::from(64);
    };
    let dir = PathBuf::from(args.get(1).map(String::as_str).unwrap_or("."));

    let mut files: Vec<PathBuf> = Vec::new();
    collect(&dir, &mut files);
    files.sort();

    let mut writes = 0usize;
    let mut reads = 0usize;
    for path in &files {
        if !matches!(classify(path), FileKind::Map | FileKind::CommonEvent) {
            continue;
        }
        let Ok(text) = decompile_path(path) else {
            continue;
        };
        let rel = rel(&dir, path);
        for (i, line) in text.lines().enumerate() {
            if !line.contains(reff.as_str()) {
                continue;
            }
            let t = line.trim_start();
            let is_write = is_write_to(t, reff);
            if is_write {
                writes += 1;
            } else {
                reads += 1;
            }
            let tag = if is_write { "SET " } else { "read" };
            println!("{tag}  {rel}:{}  {t}", i + 1);
        }
    }
    println!("\n{reff}: {writes} write(s), {reads} read(s)");
    ExitCode::SUCCESS
}

/// True if the decompiled line assigns to `reff` (a write site).
pub(crate) fn is_write_to(line: &str, reff: &str) -> bool {
    line.starts_with(&format!("SetVariable {reff} "))
        || line.starts_with(&format!("SetString {reff} ="))
        || line.starts_with(&format!("{reff} =")) // DB-read / GetXXX-into form
}

/// Debug: dump raw (cid, indent, int args, string count) per command. Ground truth for
/// validating the decompiler's argument decoding.
pub(crate) fn cmd_raw(args: &[String]) -> ExitCode {
    let Some(input) = args.first() else {
        eprintln!("raw: missing input file");
        return ExitCode::from(64);
    };
    let path = PathBuf::from(input);
    let bytes = match std::fs::read(&path) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("read failed: {e}");
            return ExitCode::from(4);
        }
    };
    // CommonEvent: dump the per-event metadata strings (name/description/self-var-name
    // candidates) to see what naming info WOLF stores.
    if matches!(classify(&path), FileKind::Database) {
        let proj = if path.extension().and_then(|s| s.to_str()) == Some("project") {
            path.clone()
        } else {
            path.with_extension("project")
        };
        let dat = proj.with_extension("dat");
        let (Ok(pb), Ok(db_)) = (std::fs::read(&proj), std::fs::read(&dat)) else {
            eprintln!("could not read database pair");
            return ExitCode::from(4);
        };
        let db = match Database::read(&pb, &db_) {
            Ok(d) => d,
            Err(e) => {
                eprintln!("parse failed: {e}");
                return ExitCode::from(4);
            }
        };
        let dec = |w: &wolf_formats::WStr| {
            let mut b = w.as_bytes();
            if b.last() == Some(&0) {
                b = &b[..b.len() - 1];
            }
            String::from_utf8_lossy(b).into_owned()
        };
        for (ti, t) in db.types.iter().enumerate() {
            println!(
                "type {ti} \"{}\"  ({} fields, {} data rows)",
                dec(&t.name),
                t.fields.len(),
                t.data.len()
            );
            let fields: Vec<String> = t.fields.iter().map(|f| dec(&f.name)).collect();
            println!("  fields: {}", fields.join(" | "));
            let sample: Vec<String> = t.data.iter().take(8).map(|d| dec(&d.name)).collect();
            println!("  data:   {}", sample.join(" | "));
        }
        return ExitCode::SUCCESS;
    }

    if matches!(classify(&path), FileKind::CommonEvent) {
        let ce = match CommonEventsFile::read(&bytes) {
            Ok(c) => c,
            Err(e) => {
                eprintln!("parse failed: {e}");
                return ExitCode::from(4);
            }
        };
        let want: Vec<u32> = args[1..].iter().filter_map(|s| s.parse().ok()).collect();
        for ev in &ce.events {
            if !want.is_empty() && !want.contains(&ev.int_id) {
                continue;
            }
            let dec = |w: &wolf_formats::WStr| {
                let mut b = w.as_bytes();
                if b.last() == Some(&0) {
                    b = &b[..b.len() - 1];
                }
                String::from_utf8_lossy(b).into_owned()
            };
            println!(
                "commonEvent {} \"{}\"  ({} commands)",
                ev.int_id,
                dec(&ev.name),
                ev.commands.len()
            );
            println!("  description: {:?}", dec(&ev.description));
            let nonempty = |label: &str, v: &[wolf_formats::WStr]| {
                let items: Vec<String> = v
                    .iter()
                    .enumerate()
                    .filter(|(_, w)| !dec(w).is_empty())
                    .map(|(i, w)| format!("{i}:{:?}", dec(w)))
                    .collect();
                if !items.is_empty() {
                    println!("  {label} ({}): {}", v.len(), items.join("  "));
                }
            };
            nonempty("unknown3", &ev.unknown3);
            nonempty("unknown8", &ev.unknown8);
            for (i, group) in ev.unknown5.iter().enumerate() {
                nonempty(&format!("unknown5[{i}]"), group);
            }
            println!();
        }
        return ExitCode::SUCCESS;
    }

    let map = match Map::read(&bytes) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("parse failed: {e}");
            return ExitCode::from(4);
        }
    };
    for ev in &map.events {
        println!("event {} {:?}", ev.id, ev.name.to_lossy());
        for (pi, page) in ev.pages.iter().enumerate() {
            println!("  page {pi}");
            for c in &page.commands {
                println!(
                    "    i{} cid={} {} ints={:?} strs={}",
                    c.indent,
                    c.cid,
                    wolf_decompiler::spec::command_name(c.cid),
                    c.int_args,
                    c.str_args.len()
                );
            }
        }
    }
    ExitCode::SUCCESS
}

pub(crate) fn decompile_path(path: &Path) -> Result<String, String> {
    let bytes = std::fs::read(path).map_err(|e| e.to_string())?;
    match classify(path) {
        FileKind::Map => {
            let map = Map::read(&bytes).map_err(|e| e.to_string())?;
            let symbols = load_symbols(path);
            Ok(decompile_map(&map, &symbols))
        }
        FileKind::CommonEvent => {
            let ce = CommonEventsFile::read(&bytes).map_err(|e| e.to_string())?;
            let mut symbols = SymbolTable::new();
            symbols.add_common_events(&ce);
            add_databases(&mut symbols, path.parent());
            symbols.set_glossary(wolf_decompiler::symbols::load_embedded_glossary());
            symbols.set_engine_text(wolf_decompiler::symbols::load_embedded_engine_glossary());
            Ok(decompile_common_events(&ce, &symbols))
        }
        FileKind::Database | FileKind::BasicDatabase | FileKind::GameDat
        | FileKind::TxtEvent | FileKind::Unsupported => Err(format!(
            "{} is not a code-bearing file (decompile supports .mps and CommonEvent.dat)",
            path.display()
        )),
    }
}

/// Decompile to the **edit** document (recompilable, identity-delimited), the form `wolf
/// compile` consumes. Symbol-aware: each operand carries its index **and** a bilingual label
/// (`V[3 "Gold · ゴールド"]`), so the one file is both readable and recompilable. The recompiler
/// strips the labels and round-trips byte-exact. `--numeric` (handled by the caller) falls back
/// to the bare-index form.
pub(crate) fn decompile_edit_path(path: &Path) -> Result<String, String> {
    let bytes = std::fs::read(path).map_err(|e| e.to_string())?;
    match classify(path) {
        FileKind::Map => {
            let map = Map::read(&bytes).map_err(|e| e.to_string())?;
            Ok(decompile_map_edit_annotated(&map, &load_symbols(path)))
        }
        FileKind::CommonEvent => {
            let ce = CommonEventsFile::read(&bytes).map_err(|e| e.to_string())?;
            let mut symbols = SymbolTable::new();
            symbols.add_common_events(&ce);
            add_databases(&mut symbols, path.parent());
            symbols.set_glossary(wolf_decompiler::symbols::load_embedded_glossary());
            symbols.set_engine_text(wolf_decompiler::symbols::load_embedded_engine_glossary());
            Ok(decompile_common_events_edit_annotated(&ce, &symbols))
        }
        FileKind::Database | FileKind::BasicDatabase | FileKind::GameDat
        | FileKind::TxtEvent | FileKind::Unsupported => Err(format!(
            "{} is not a code-bearing file (edit mode supports .mps and CommonEvent.dat)",
            path.display()
        )),
    }
}

/// `wolf compile <doc.wscript> --base <orig.mps|CommonEvent.dat> -o <out>`. Recompiles an
/// edit document back into a runnable file. The base supplies all opaque metadata. Only the
/// command bodies are swapped in. With code untouched the output is byte-identical to base.
pub(crate) fn cmd_compile(args: &[String]) -> ExitCode {
    let mut input: Option<PathBuf> = None;
    let mut base: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next().map(PathBuf::from),
            "-b" | "--base" => base = it.next().map(PathBuf::from),
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let (Some(input), Some(base)) = (input, base) else {
        eprintln!("compile: usage: wolf compile <doc> --base <orig> -o <out>");
        return ExitCode::from(64);
    };

    let text = match std::fs::read_to_string(&input) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("compile: cannot read {}: {e}", input.display());
            return ExitCode::from(4);
        }
    };
    let base_bytes = match std::fs::read(&base) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("compile: cannot read base {}: {e}", base.display());
            return ExitCode::from(4);
        }
    };

    let out_bytes = match classify(&base) {
        FileKind::CommonEvent => {
            let mut ce = match CommonEventsFile::read(&base_bytes) {
                Ok(c) => c,
                Err(e) => {
                    eprintln!("compile: base parse failed: {e}");
                    return ExitCode::from(4);
                }
            };
            if let Err(e) = compile_common_events_edit(&text, &mut ce) {
                eprintln!("compile failed: {e}");
                return ExitCode::from(2);
            }
            ce.write()
        }
        FileKind::Map => {
            let mut map = match Map::read(&base_bytes) {
                Ok(m) => m,
                Err(e) => {
                    eprintln!("compile: base parse failed: {e}");
                    return ExitCode::from(4);
                }
            };
            if let Err(e) = compile_map_edit(&text, &mut map) {
                eprintln!("compile failed: {e}");
                return ExitCode::from(2);
            }
            map.write()
        }
        FileKind::Database | FileKind::BasicDatabase | FileKind::GameDat
        | FileKind::TxtEvent | FileKind::Unsupported => {
            eprintln!("compile: base must be a .mps or CommonEvent.dat");
            return ExitCode::from(64);
        }
    };

    let Some(out) = output else {
        eprintln!("compile: missing -o <out>");
        return ExitCode::from(64);
    };
    if let Err(e) = std::fs::write(&out, &out_bytes) {
        eprintln!("compile: cannot write {}: {e}", out.display());
        return ExitCode::from(4);
    }
    let same = out_bytes == base_bytes;
    eprintln!(
        "wrote {} ({} bytes{})",
        out.display(),
        out_bytes.len(),
        if same { ", byte-identical to base" } else { "" }
    );
    ExitCode::SUCCESS
}

/// `wolf db-json <X.project | X.dat | data-dir> [-o out]`. Exports a database (or every
/// database in a BasicData dir) to readable JSON for inspection. A single file writes to
/// `-o file` (or stdout). A directory writes one `<stem>.json` per DB into `-o <dir>` (default `.`).
pub(crate) fn cmd_db_json(args: &[String]) -> ExitCode {
    let mut input: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next().map(PathBuf::from),
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let Some(input) = input else {
        eprintln!("db-json: usage: wolf db-json <X.project | data-dir> [-o out]");
        return ExitCode::from(64);
    };

    if input.is_dir() {
        let dir = output.unwrap_or_else(|| PathBuf::from("."));
        if let Err(e) = std::fs::create_dir_all(&dir) {
            eprintln!("db-json: cannot create {}: {e}", dir.display());
            return ExitCode::from(4);
        }
        let mut n = 0;
        for stem in ["DataBase", "CDataBase", "SysDatabase"] {
            let proj = input.join(format!("{stem}.project"));
            if !proj.exists() {
                continue;
            }
            match db_json_one(&proj) {
                Ok(json) => {
                    let out = dir.join(format!("{stem}.json"));
                    if let Err(e) = std::fs::write(&out, &json) {
                        eprintln!("db-json: cannot write {}: {e}", out.display());
                        return ExitCode::from(4);
                    }
                    eprintln!("wrote {} ({} bytes)", out.display(), json.len());
                    n += 1;
                }
                Err(e) => eprintln!("db-json: {stem}: {e}"),
            }
        }
        if n == 0 {
            eprintln!("db-json: no databases found under {}", input.display());
            return ExitCode::from(4);
        }
        return ExitCode::SUCCESS;
    }

    let proj = if input.extension().and_then(|s| s.to_str()) == Some("dat") {
        input.with_extension("project")
    } else {
        input.clone()
    };
    match db_json_one(&proj) {
        Ok(json) => match output {
            Some(out) => {
                if let Err(e) = std::fs::write(&out, &json) {
                    eprintln!("db-json: cannot write {}: {e}", out.display());
                    return ExitCode::from(4);
                }
                eprintln!("wrote {} ({} bytes)", out.display(), json.len());
                ExitCode::SUCCESS
            }
            None => {
                use std::io::Write;
                let _ = std::io::stdout().write_all(json.as_bytes());
                ExitCode::SUCCESS
            }
        },
        Err(e) => {
            eprintln!("db-json failed: {e}");
            ExitCode::from(4)
        }
    }
}

/// Read a `.project` (+ sibling `.dat`) and render it to JSON, labelling the kind by stem.
/// Report any lines a safety guard skipped and pick the exit code (non-zero if so, so CI notices,
/// even though the good lines were still written).
fn guard_report(st: &InjectStats) -> ExitCode {
    if st.code_mismatch > 0 || st.unrepresentable > 0 {
        eprintln!(
            "WARNING: {} line(s) left UNTRANSLATED by a safety guard - {} control-code mismatch, {} not encodable; see the per-line messages above (pass --allow-code-drift to override the code check)",
            st.code_mismatch + st.unrepresentable,
            st.code_mismatch,
            st.unrepresentable,
        );
        ExitCode::from(2)
    } else {
        ExitCode::SUCCESS
    }
}

/// Apply DB translations onto a `.project`+`.dat` pair, writing both halves byte-exact.
fn strings_inject_db(input: &Path, base: &Path, output: &Path, opts: &InjectOptions) -> ExitCode {
    let proj = if base.extension().and_then(|s| s.to_str()) == Some("project") {
        base.to_path_buf()
    } else {
        base.with_extension("project")
    };
    let base_dat = proj.with_extension("dat");
    let out_dat = output.with_extension("dat");
    let (Ok(text), Ok(p), Ok(d)) = (
        std::fs::read_to_string(input),
        std::fs::read(&proj),
        std::fs::read(&base_dat),
    ) else {
        eprintln!("strings-inject: cannot read input or DB pair");
        return ExitCode::from(4);
    };
    let mut db = match Database::read(&p, &d) {
        Ok(db) => db,
        Err(e) => {
            eprintln!("strings-inject: DB parse failed: {e}");
            return ExitCode::from(4);
        }
    };
    let st = match inject_db_strings(&text, &mut db, opts) {
        Ok(st) => st,
        Err(e) => {
            eprintln!("strings-inject failed: {e}");
            return ExitCode::from(2);
        }
    };
    let (op, od) = db.write();
    // Post-inject re-parse: never ship a structurally-corrupt file.
    if let Err(e) = Database::read(&op, &od) {
        eprintln!("strings-inject: internal error - injected DB no longer parses ({e}); aborting write to avoid a corrupt file. Please report.");
        return ExitCode::from(2);
    }
    let identical = op == p && od == d;
    if let (Err(e), _) | (_, Err(e)) = (std::fs::write(output, &op), std::fs::write(&out_dat, &od))
    {
        eprintln!("strings-inject: write failed: {e}");
        return ExitCode::from(4);
    }
    eprintln!(
        "applied {} translation(s) ({} untranslated, {} drifted); wrote {} + {}{}",
        st.applied,
        st.untranslated,
        st.drifted,
        output.display(),
        out_dat.display(),
        if identical {
            " (byte-identical to base)"
        } else {
            ""
        }
    );
    guard_report(&st)
}

/// Collect the `.txt` files directly under `dir`, sorted by name for a stable, reproducible
/// document order. Event-text folders are flat, so this is a shallow scan, not recursive.
fn list_txt_files(dir: &Path) -> Vec<PathBuf> {
    let mut out: Vec<PathBuf> = match std::fs::read_dir(dir) {
        Ok(rd) => rd
            .flatten()
            .map(|e| e.path())
            .filter(|p| {
                p.is_file()
                    && p.extension().and_then(|s| s.to_str()).map(str::to_ascii_lowercase)
                        == Some("txt".to_string())
            })
            .collect(),
        Err(_) => Vec::new(),
    };
    out.sort();
    out
}

/// `strings-extract <dir-of-txt>`. Extract every `.txt` event-text file under a directory into one
/// combined JSON keyed by file. Each entry is the per-file `extract_txt_events` document with a
/// `file` field naming it, so `strings-inject` can write each back to the matching base file.
fn strings_extract_txt_dir(dir: &Path, output: Option<&Path>) -> ExitCode {
    let files = list_txt_files(dir);
    if files.is_empty() {
        eprintln!("strings-extract: no .txt files in {}", dir.display());
        return ExitCode::from(4);
    }
    let mut named: Vec<(String, Vec<u8>)> = Vec::with_capacity(files.len());
    for path in &files {
        let bytes = match std::fs::read(path) {
            Ok(b) => b,
            Err(e) => {
                eprintln!("strings-extract: cannot read {}: {e}", path.display());
                return ExitCode::from(4);
            }
        };
        let fname = path.file_name().and_then(|s| s.to_str()).unwrap_or("").to_owned();
        named.push((fname, bytes));
    }
    let json = wolf_decompiler::extract_txt_dir(&named);
    match output {
        Some(out) => {
            if let Err(e) = std::fs::write(out, &json) {
                eprintln!("strings-extract: write failed: {e}");
                return ExitCode::from(4);
            }
            eprintln!("wrote {} ({} txt file(s))", out.display(), files.len());
        }
        None => {
            use std::io::Write;
            let _ = std::io::stdout().write_all(json.as_bytes());
        }
    }
    ExitCode::SUCCESS
}

/// `strings-inject <edited.json> --base <file.txt> -o <out.txt>` for a single event-text file.
/// Re-decodes the base, applies the edits, and writes the result, which is byte-identical to the
/// base for a no-op edit.
fn strings_inject_txt_file(input: &Path, base: &Path, output: &Path) -> ExitCode {
    let (Ok(json), Ok(base_bytes)) = (std::fs::read_to_string(input), std::fs::read(base)) else {
        eprintln!("strings-inject: cannot read input/base");
        return ExitCode::from(4);
    };
    let out_bytes = match inject_txt_events(&json, &base_bytes) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("strings-inject failed: {e}");
            return ExitCode::from(2);
        }
    };
    let identical = out_bytes == base_bytes;
    if let Err(e) = std::fs::write(output, &out_bytes) {
        eprintln!("strings-inject: write failed: {e}");
        return ExitCode::from(4);
    }
    eprintln!(
        "wrote {}{}",
        output.display(),
        if identical { " (byte-identical to base)" } else { "" }
    );
    ExitCode::SUCCESS
}

/// `strings-inject <combined.json> --base <dir-of-txt> -o <out-dir>` for a folder of event-text
/// files. The combined JSON is a `txt-dir` document. Each `files[]` entry is injected against its
/// matching base file and written to `<out-dir>` under the same name. Files present in the base but
/// absent from the JSON are copied through unchanged, so the output directory mirrors the base.
fn strings_inject_txt_dir(input: &Path, base: &Path, out_dir: &Path) -> ExitCode {
    let Ok(json) = std::fs::read_to_string(input) else {
        eprintln!("strings-inject: cannot read {}", input.display());
        return ExitCode::from(4);
    };
    let entries = match wolf_decompiler::split_txt_dir(&json) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("strings-inject: {e}");
            return ExitCode::from(2);
        }
    };
    if let Err(e) = std::fs::create_dir_all(out_dir) {
        eprintln!("strings-inject: cannot create {}: {e}", out_dir.display());
        return ExitCode::from(4);
    }
    let mut named: std::collections::HashSet<String> = std::collections::HashSet::new();
    let mut written = 0usize;
    for (fname, per_file) in &entries {
        named.insert(fname.clone());
        let base_path = base.join(fname);
        let base_bytes = match std::fs::read(&base_path) {
            Ok(b) => b,
            Err(e) => {
                eprintln!("strings-inject: cannot read base {}: {e}", base_path.display());
                continue;
            }
        };
        let out_bytes = match inject_txt_events(per_file, &base_bytes) {
            Ok(b) => b,
            Err(e) => {
                eprintln!("strings-inject: {fname}: {e}");
                continue;
            }
        };
        if let Err(e) = std::fs::write(out_dir.join(fname), &out_bytes) {
            eprintln!("strings-inject: write {fname} failed: {e}");
            continue;
        }
        written += 1;
    }
    // Copy through any base files the JSON did not mention so the output dir is complete.
    let mut copied = 0usize;
    for path in list_txt_files(base) {
        let fname = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
        if named.contains(fname) {
            continue;
        }
        if let Ok(b) = std::fs::read(&path) {
            if std::fs::write(out_dir.join(fname), &b).is_ok() {
                copied += 1;
            }
        }
    }
    eprintln!(
        "wrote {written} injected + {copied} passed-through txt file(s) to {}",
        out_dir.display()
    );
    ExitCode::SUCCESS
}

/// `wolf strings-extract <CommonEvent.dat|map.mps> -o <out.json>`. Extracts only player-facing
/// text (dialogue/choices/on-screen), speaker-attributed and grouped by event/scene, for
/// translation. The `text` field starts equal to `source`. Translators edit `text`.
pub(crate) fn cmd_strings_extract(args: &[String]) -> ExitCode {
    let mut input: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next().map(PathBuf::from),
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let Some(input) = input else {
        eprintln!(
            "strings-extract: usage: wolf strings-extract <CommonEvent.dat|map.mps|dir-of-txt> -o <out.json>"
        );
        return ExitCode::from(64);
    };
    // A directory is treated as a folder of external event-text `.txt` files (unpacked Evtext).
    // One combined JSON keyed by file is produced.
    if input.is_dir() {
        return strings_extract_txt_dir(&input, output.as_deref());
    }
    let bytes = match std::fs::read(&input) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("strings-extract: cannot read {}: {e}", input.display());
            return ExitCode::from(4);
        }
    };
    let fname = input.file_name().and_then(|s| s.to_str()).unwrap_or("");
    let json = match classify(&input) {
        FileKind::TxtEvent => extract_txt_events(&bytes),
        FileKind::CommonEvent => match CommonEventsFile::read(&bytes) {
            Ok(ce) => scenes_to_json(fname, "common", &extract_common_events(&ce)),
            Err(e) => {
                eprintln!("strings-extract: parse failed: {e}");
                return ExitCode::from(4);
            }
        },
        FileKind::Map => match Map::read(&bytes) {
            Ok(m) => scenes_to_json(fname, "map", &extract_map(&m)),
            Err(e) => {
                eprintln!("strings-extract: parse failed: {e}");
                return ExitCode::from(4);
            }
        },
        FileKind::GameDat => match GameDat::read(&bytes) {
            Ok(gd) => extract_game_dat(&gd),
            Err(e) => {
                eprintln!("strings-extract: parse failed: {e}");
                return ExitCode::from(4);
            }
        },
        FileKind::Database => {
            let proj = if input.extension().and_then(|s| s.to_str()) == Some("project") {
                input.clone()
            } else {
                input.with_extension("project")
            };
            let dat = proj.with_extension("dat");
            let (Ok(p), Ok(d)) = (std::fs::read(&proj), std::fs::read(&dat)) else {
                eprintln!(
                    "strings-extract: cannot read DB pair for {}",
                    input.display()
                );
                return ExitCode::from(4);
            };
            match Database::read(&p, &d) {
                Ok(db) => {
                    let glossary = wolf_decompiler::symbols::load_embedded_engine_glossary();
                    db_strings_to_json(fname, &extract_db_strings(&db, &glossary))
                }
                Err(e) => {
                    eprintln!("strings-extract: DB parse failed: {e}");
                    return ExitCode::from(4);
                }
            }
        }
        _ => {
            eprintln!("strings-extract: only CommonEvent.dat, .mps maps, .project databases, Game.dat, and event-text .txt files (or a folder of them) carry player text");
            return ExitCode::from(64);
        }
    };
    match output {
        Some(out) => {
            if let Err(e) = std::fs::write(&out, &json) {
                eprintln!("strings-extract: write failed: {e}");
                return ExitCode::from(4);
            }
            eprintln!("wrote {}", out.display());
        }
        None => {
            use std::io::Write;
            let _ = std::io::stdout().write_all(json.as_bytes());
        }
    }
    ExitCode::SUCCESS
}

/// `wolf strings-audit <CommonEvent.dat|map.mps|X.project> -o <out.json>`. QA coverage dump.
/// Lists every non-empty string arg / DB cell in the file, tagged with whether the player-text
/// extractor keeps it. Ground truth for precision (kept-but-not-text) plus recall (text-but-dropped).
pub(crate) fn cmd_strings_audit(args: &[String]) -> ExitCode {
    let mut input: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next().map(PathBuf::from),
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let Some(input) = input else {
        eprintln!("strings-audit: usage: wolf strings-audit <CommonEvent.dat|map.mps|X.project> -o <out.json>");
        return ExitCode::from(64);
    };
    let bytes = match std::fs::read(&input) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("strings-audit: cannot read {}: {e}", input.display());
            return ExitCode::from(4);
        }
    };
    let json = match classify(&input) {
        FileKind::CommonEvent => match CommonEventsFile::read(&bytes) {
            Ok(ce) => audit_common_events_to_json(&ce),
            Err(e) => {
                eprintln!("strings-audit: parse failed: {e}");
                return ExitCode::from(4);
            }
        },
        FileKind::Map => match Map::read(&bytes) {
            Ok(m) => audit_map_to_json(&m),
            Err(e) => {
                eprintln!("strings-audit: parse failed: {e}");
                return ExitCode::from(4);
            }
        },
        FileKind::Database => {
            let proj = if input.extension().and_then(|s| s.to_str()) == Some("project") {
                input.clone()
            } else {
                input.with_extension("project")
            };
            let dat = proj.with_extension("dat");
            let (Ok(p), Ok(d)) = (std::fs::read(&proj), std::fs::read(&dat)) else {
                eprintln!("strings-audit: cannot read DB pair for {}", input.display());
                return ExitCode::from(4);
            };
            match Database::read(&p, &d) {
                Ok(db) => {
                    let glossary = wolf_decompiler::symbols::load_embedded_engine_glossary();
                    audit_db_to_json(&db, &glossary)
                }
                Err(e) => {
                    eprintln!("strings-audit: DB parse failed: {e}");
                    return ExitCode::from(4);
                }
            }
        }
        _ => {
            eprintln!("strings-audit: only CommonEvent.dat, .mps maps, and .project databases");
            return ExitCode::from(64);
        }
    };
    match output {
        Some(out) => {
            if let Err(e) = std::fs::write(&out, &json) {
                eprintln!("strings-audit: write failed: {e}");
                return ExitCode::from(4);
            }
            eprintln!("wrote {}", out.display());
        }
        None => {
            use std::io::Write;
            let _ = std::io::stdout().write_all(json.as_bytes());
        }
    }
    ExitCode::SUCCESS
}

/// `wolf strings-inject <edited.json> --base <orig> -o <out>`. Applies edited translations back,
/// byte-exact. Only lines whose `text` differs from `source` (and still match the base) are
/// changed. Everything else re-serializes identically.
pub(crate) fn cmd_strings_inject(args: &[String]) -> ExitCode {
    let mut input: Option<PathBuf> = None;
    let mut base: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    let mut opts = InjectOptions::default();
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next().map(PathBuf::from),
            "-b" | "--base" => base = it.next().map(PathBuf::from),
            "--allow-code-drift" => opts.allow_code_drift = true,
            "--en-punct" => opts.normalize_punct = true,
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let (Some(input), Some(base), Some(output)) = (input, base, output) else {
        eprintln!(
            "strings-inject: usage: wolf strings-inject <edited.json> --base <orig> -o <out> [--allow-code-drift] [--en-punct]"
        );
        return ExitCode::from(64);
    };
    // Databases are a `.project`+`.dat` pair (write both).
    if matches!(classify(&base), FileKind::Database) {
        return strings_inject_db(&input, &base, &output, &opts);
    }
    // A directory base is a folder of external event-text `.txt` files (unpacked Evtext). The
    // input JSON is the combined keyed-by-file document, and each file is written under `-o`.
    if base.is_dir() {
        return strings_inject_txt_dir(&input, &base, &output);
    }
    // A single external event-text `.txt` file.
    if matches!(classify(&base), FileKind::TxtEvent) {
        return strings_inject_txt_file(&input, &base, &output);
    }
    let (Ok(text), Ok(base_bytes)) = (std::fs::read_to_string(&input), std::fs::read(&base)) else {
        eprintln!("strings-inject: cannot read input/base");
        return ExitCode::from(4);
    };
    let (out_bytes, st) = match classify(&base) {
        FileKind::CommonEvent => {
            let mut ce = match CommonEventsFile::read(&base_bytes) {
                Ok(c) => c,
                Err(e) => {
                    eprintln!("strings-inject: base parse failed: {e}");
                    return ExitCode::from(4);
                }
            };
            let st = match inject_common_events(&text, &mut ce, &opts) {
                Ok(st) => st,
                Err(e) => {
                    eprintln!("strings-inject failed: {e}");
                    return ExitCode::from(2);
                }
            };
            let out = ce.write();
            // Post-inject re-parse: never ship a structurally-corrupt file.
            if let Err(e) = CommonEventsFile::read(&out) {
                eprintln!("strings-inject: internal error - injected file no longer parses ({e}); aborting write to avoid a corrupt file. Please report.");
                return ExitCode::from(2);
            }
            (out, st)
        }
        FileKind::Map => {
            let mut m = match Map::read(&base_bytes) {
                Ok(m) => m,
                Err(e) => {
                    eprintln!("strings-inject: base parse failed: {e}");
                    return ExitCode::from(4);
                }
            };
            let st = match inject_map(&text, &mut m, &opts) {
                Ok(st) => st,
                Err(e) => {
                    eprintln!("strings-inject failed: {e}");
                    return ExitCode::from(2);
                }
            };
            let out = m.write();
            if let Err(e) = Map::read(&out) {
                eprintln!("strings-inject: internal error - injected file no longer parses ({e}); aborting write to avoid a corrupt file. Please report.");
                return ExitCode::from(2);
            }
            (out, st)
        }
        FileKind::GameDat => {
            let mut gd = match GameDat::read(&base_bytes) {
                Ok(g) => g,
                Err(e) => {
                    eprintln!("strings-inject: base parse failed: {e}");
                    return ExitCode::from(4);
                }
            };
            let st = match inject_game_dat(&text, &mut gd, &opts) {
                Ok(st) => st,
                Err(e) => {
                    eprintln!("strings-inject failed: {e}");
                    return ExitCode::from(2);
                }
            };
            let out = gd.write();
            if let Err(e) = GameDat::read(&out) {
                eprintln!("strings-inject: internal error - injected file no longer parses ({e}); aborting write to avoid a corrupt file. Please report.");
                return ExitCode::from(2);
            }
            (out, st)
        }
        _ => {
            eprintln!("strings-inject: base must be CommonEvent.dat, a .mps map, Game.dat, an event-text .txt file, or a folder of them");
            return ExitCode::from(64);
        }
    };
    let identical = out_bytes == base_bytes;
    if let Err(e) = std::fs::write(&output, &out_bytes) {
        eprintln!("strings-inject: write failed: {e}");
        return ExitCode::from(4);
    }
    eprintln!(
        "applied {} translation(s) ({} untranslated, {} drifted); wrote {}{}",
        st.applied,
        st.untranslated,
        st.drifted,
        output.display(),
        if identical {
            " (byte-identical to base)"
        } else {
            ""
        }
    );
    guard_report(&st)
}

/// `wolf db-apply <edited.json> --base <X.project> -o <out.project>`. Applies value/row-name
/// edits from a `db-json` export back onto a database, writing `<out.project>` and the sibling
/// `<out.dat>`. Only cell values and row names change. Schema edits are rejected. Untouched
/// data re-serializes byte-identical to the base.
pub(crate) fn cmd_db_apply(args: &[String]) -> ExitCode {
    let mut input: Option<PathBuf> = None;
    let mut base: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next().map(PathBuf::from),
            "-b" | "--base" => base = it.next().map(PathBuf::from),
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let (Some(input), Some(base), Some(output)) = (input, base, output) else {
        eprintln!(
            "db-apply: usage: wolf db-apply <edited.json> --base <X.project> -o <out.project>"
        );
        return ExitCode::from(64);
    };
    let base_dat = base.with_extension("dat");
    let out_dat = output.with_extension("dat");

    let text = match std::fs::read_to_string(&input) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("db-apply: cannot read {}: {e}", input.display());
            return ExitCode::from(4);
        }
    };
    let (pb, db_) = match (std::fs::read(&base), std::fs::read(&base_dat)) {
        (Ok(p), Ok(d)) => (p, d),
        _ => {
            eprintln!(
                "db-apply: cannot read base pair {} + {}",
                base.display(),
                base_dat.display()
            );
            return ExitCode::from(4);
        }
    };
    let mut db = match Database::read(&pb, &db_) {
        Ok(d) => d,
        Err(e) => {
            eprintln!("db-apply: base parse failed: {e}");
            return ExitCode::from(4);
        }
    };

    let changed = match apply_database_edit(&text, &mut db) {
        Ok(n) => n,
        Err(e) => {
            eprintln!("db-apply failed: {e}");
            return ExitCode::from(2);
        }
    };

    let (out_pb, out_db) = db.write();
    let byte_identical = out_pb == pb && out_db == db_;
    if let (Err(e), _) | (_, Err(e)) = (
        std::fs::write(&output, &out_pb),
        std::fs::write(&out_dat, &out_db),
    ) {
        eprintln!("db-apply: write failed: {e}");
        return ExitCode::from(4);
    }
    eprintln!(
        "wrote {} + {} ({changed} cell(s) changed{})",
        output.display(),
        out_dat.display(),
        if byte_identical {
            "; byte-identical to base"
        } else {
            ""
        }
    );
    ExitCode::SUCCESS
}

// ----------------------------------------------------------------------------
// gamedat-json / gamedat-apply: the FULL Game.dat field editor (all editable
// string fields, not just the player-text subset that strings-extract exposes)
// ----------------------------------------------------------------------------

/// `wolf gamedat-json <Game.dat> [-o out.json]`. Dumps *every* editable Game.dat string field to
/// JSON for inspection/editing (fonts, graphics, image paths and the player text). Structural
/// fields are not exposed. Writes to `-o` (or stdout).
pub(crate) fn cmd_gamedat_json(args: &[String]) -> ExitCode {
    let mut input: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next().map(PathBuf::from),
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let Some(input) = input else {
        eprintln!("gamedat-json: usage: wolf gamedat-json <Game.dat> [-o out.json]");
        return ExitCode::from(64);
    };

    let bytes = match std::fs::read(&input) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("gamedat-json: cannot read {}: {e}", input.display());
            return ExitCode::from(4);
        }
    };
    let gd = match GameDat::read(&bytes) {
        Ok(gd) => gd,
        Err(e) => {
            eprintln!("gamedat-json: parse failed: {e}");
            return ExitCode::from(4);
        }
    };
    let json = dump_game_dat(&gd);
    match output {
        Some(out) => {
            if let Err(e) = std::fs::write(&out, &json) {
                eprintln!("gamedat-json: cannot write {}: {e}", out.display());
                return ExitCode::from(4);
            }
            eprintln!("wrote {} ({} bytes)", out.display(), json.len());
            ExitCode::SUCCESS
        }
        None => {
            use std::io::Write;
            let _ = std::io::stdout().write_all(json.as_bytes());
            ExitCode::SUCCESS
        }
    }
}

/// `wolf gamedat-apply <edited.json> --base <Game.dat> -o <out>`. Applies full-field edits from a
/// `gamedat-json` dump back onto a Game.dat, writing `<out>`. The output is re-parsed with
/// `GameDat::read` to verify it round-trips before the write is reported. Untouched fields
/// re-serialize byte-exact.
pub(crate) fn cmd_gamedat_apply(args: &[String]) -> ExitCode {
    let mut input: Option<PathBuf> = None;
    let mut base: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next().map(PathBuf::from),
            "-b" | "--base" => base = it.next().map(PathBuf::from),
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let (Some(input), Some(base), Some(output)) = (input, base, output) else {
        eprintln!("gamedat-apply: usage: wolf gamedat-apply <edited.json> --base <Game.dat> -o <out>");
        return ExitCode::from(64);
    };

    let text = match std::fs::read_to_string(&input) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("gamedat-apply: cannot read {}: {e}", input.display());
            return ExitCode::from(4);
        }
    };
    let base_bytes = match std::fs::read(&base) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("gamedat-apply: cannot read base {}: {e}", base.display());
            return ExitCode::from(4);
        }
    };
    let mut gd = match GameDat::read(&base_bytes) {
        Ok(gd) => gd,
        Err(e) => {
            eprintln!("gamedat-apply: base parse failed: {e}");
            return ExitCode::from(4);
        }
    };

    let changed = match apply_game_dat(&mut gd, &text) {
        Ok(n) => n,
        Err(e) => {
            eprintln!("gamedat-apply failed: {e}");
            return ExitCode::from(2);
        }
    };

    let out = gd.write();
    // Re-parse the output to verify it still round-trips before we commit it to disk.
    if let Err(e) = GameDat::read(&out) {
        eprintln!("gamedat-apply: internal error - edited file no longer parses ({e}); aborting write to avoid a corrupt file. Please report.");
        return ExitCode::from(2);
    }
    let identical = out == base_bytes;
    if let Err(e) = std::fs::write(&output, &out) {
        eprintln!("gamedat-apply: write failed: {e}");
        return ExitCode::from(4);
    }
    eprintln!(
        "gamedat-apply: {changed} field(s) changed -> {}{}",
        output.display(),
        if identical {
            " (byte-identical to base)"
        } else {
            ""
        }
    );
    ExitCode::SUCCESS
}

// ----------------------------------------------------------------------------
// names-extract / names-inject: the project-level DB name glossary
// ----------------------------------------------------------------------------

/// A database loaded for inject: `(project path, dat path, original project bytes, original dat
/// bytes, parsed db)`. The original bytes let the caller report byte-identity. The parsed db is
/// mutated in place by the inject.
type LoadedDb = (PathBuf, PathBuf, Vec<u8>, Vec<u8>, Database);

/// The translatable files of a data dir, located the same way the other commands do: the three
/// standard DB pairs and `CommonEvent.dat` under `<dir>` or `<dir>/BasicData`, and every `*.mps`
/// map under `<dir>` or `<dir>/MapData`. Each entry keeps the on-disk paths so an inject can write
/// each file back to where it came from.
struct DataDirFiles {
    /// (`.project` path, `.dat` path) for each found database pair.
    dbs: Vec<(PathBuf, PathBuf)>,
    /// Path to `CommonEvent.dat`, if present.
    common_event: Option<PathBuf>,
    /// Every `*.mps` map path.
    maps: Vec<PathBuf>,
}

/// Resolve which of `dir` / `dir/BasicData` holds the BasicData files (`CommonEvent.dat` + DB
/// pairs), mirroring `cmd_export_names`.
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

/// Discover the translatable files under a data dir for the name glossary.
fn discover_data_dir(dir: &Path) -> DataDirFiles {
    let basic = basic_data_dir(dir);
    let mut dbs = Vec::new();
    for stem in ["DataBase", "CDataBase", "SysDatabase"] {
        let proj = basic.join(format!("{stem}.project"));
        let dat = basic.join(format!("{stem}.dat"));
        if proj.exists() && dat.exists() {
            dbs.push((proj, dat));
        }
    }
    let common_event = {
        let ce = basic.join("CommonEvent.dat");
        ce.exists().then_some(ce)
    };
    // Maps live in MapData (or directly under dir for a flattened layout).
    let mut maps = Vec::new();
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
    DataDirFiles {
        dbs,
        common_event,
        maps,
    }
}

/// `wolf names-extract <data-dir> -o names.json`. Builds the project-level DB **name glossary**:
/// every unique row name / name-display cell value across the dir's databases, with an occurrence
/// count (DB cells + row names + by-name command refs) and an originating-type hint. `text` starts
/// equal to `source`. A translator edits `text`, and `names-inject` applies it consistently.
pub(crate) fn cmd_names_extract(args: &[String]) -> ExitCode {
    let mut input: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next().map(PathBuf::from),
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let Some(dir) = input else {
        eprintln!("names-extract: usage: wolf names-extract <data-dir> -o <names.json>");
        return ExitCode::from(64);
    };

    let found = discover_data_dir(&dir);
    // Parse the databases.
    let mut dbs = Vec::new();
    for (proj, dat) in &found.dbs {
        match (std::fs::read(proj), std::fs::read(dat)) {
            (Ok(p), Ok(d)) => match Database::read(&p, &d) {
                Ok(db) => dbs.push(db),
                Err(e) => eprintln!("names-extract: skip {}: {e}", proj.display()),
            },
            _ => eprintln!("names-extract: cannot read {}", proj.display()),
        }
    }
    // Parse the common events (optional).
    let ce = found.common_event.as_ref().and_then(|p| {
        std::fs::read(p)
            .ok()
            .and_then(|b| CommonEventsFile::read(&b).ok())
    });
    // Parse the maps.
    let mut maps = Vec::new();
    for p in &found.maps {
        if let Ok(b) = std::fs::read(p) {
            if let Ok(m) = Map::read(&b) {
                maps.push(m);
            }
        }
    }

    if dbs.is_empty() {
        eprintln!(
            "names-extract: no databases found under {} (looked in {} and BasicData)",
            dir.display(),
            dir.display()
        );
        return ExitCode::from(4);
    }

    let ce_refs: Vec<&CommonEventsFile> = ce.iter().collect();
    let glossary = wolf_decompiler::symbols::load_embedded_engine_glossary();
    let json = extract_names(&dbs, &ce_refs, &maps, &glossary);

    // A small count of distinct names for the operator (`count` is also embedded in the JSON).
    let n = json.matches("\"source\"").count();
    match output {
        Some(out) => {
            if let Err(e) = std::fs::write(&out, &json) {
                eprintln!("names-extract: write failed: {e}");
                return ExitCode::from(4);
            }
            eprintln!(
                "wrote {} ({n} distinct name(s) from {} DB(s), {} map(s){})",
                out.display(),
                dbs.len(),
                maps.len(),
                if ce.is_some() { ", CommonEvent" } else { "" }
            );
        }
        None => {
            use std::io::Write;
            let _ = std::io::stdout().write_all(json.as_bytes());
        }
    }
    ExitCode::SUCCESS
}

/// `wolf names-inject <names.json> --data <data-dir> [-o <out-dir>]`. Applies the edited name
/// glossary consistently across the whole data dir: every stored row name, name-display cell
/// value, and by-name command reference that equals a translated source is rewritten together
/// (drift-/code-/encoding-guarded). Writes in place by default, or under `-o <out-dir>` mirroring
/// the input layout. Each written file is re-parsed to guarantee it is not structurally corrupt.
pub(crate) fn cmd_names_inject(args: &[String]) -> ExitCode {
    let mut input: Option<PathBuf> = None;
    let mut data: Option<PathBuf> = None;
    let mut out_dir: Option<PathBuf> = None;
    let mut opts = InjectOptions::default();
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--data" => data = it.next().map(PathBuf::from),
            "-o" | "--output" => out_dir = it.next().map(PathBuf::from),
            "--allow-code-drift" => opts.allow_code_drift = true,
            "--en-punct" => opts.normalize_punct = true,
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let (Some(input), Some(dir)) = (input, data) else {
        eprintln!(
            "names-inject: usage: wolf names-inject <names.json> --data <data-dir> [-o <out-dir>] [--allow-code-drift] [--en-punct]"
        );
        return ExitCode::from(64);
    };
    let names_json = match std::fs::read_to_string(&input) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("names-inject: cannot read {}: {e}", input.display());
            return ExitCode::from(4);
        }
    };

    let found = discover_data_dir(&dir);

    // Parse everything up front and abort on any read/parse failure, so a partial write can't
    // desync the name mirrors. The glossary exists to keep names consistent across files.
    let mut dbs: Vec<LoadedDb> = Vec::new();
    for (proj, dat) in &found.dbs {
        let (Ok(p), Ok(d)) = (std::fs::read(proj), std::fs::read(dat)) else {
            eprintln!("names-inject: cannot read DB pair {}", proj.display());
            return ExitCode::from(4);
        };
        match Database::read(&p, &d) {
            Ok(db) => dbs.push((proj.clone(), dat.clone(), p, d, db)),
            Err(e) => {
                eprintln!("names-inject: DB parse failed for {}: {e}", proj.display());
                return ExitCode::from(4);
            }
        }
    }
    let mut ce: Option<(PathBuf, Vec<u8>, CommonEventsFile)> = None;
    if let Some(p) = &found.common_event {
        let Ok(b) = std::fs::read(p) else {
            eprintln!("names-inject: cannot read {}", p.display());
            return ExitCode::from(4);
        };
        match CommonEventsFile::read(&b) {
            Ok(c) => ce = Some((p.clone(), b, c)),
            Err(e) => {
                eprintln!("names-inject: CommonEvent parse failed: {e}");
                return ExitCode::from(4);
            }
        }
    }
    let mut maps: Vec<(PathBuf, Vec<u8>, Map)> = Vec::new();
    for p in &found.maps {
        let Ok(b) = std::fs::read(p) else {
            eprintln!("names-inject: cannot read {}", p.display());
            return ExitCode::from(4);
        };
        match Map::read(&b) {
            Ok(m) => maps.push((p.clone(), b, m)),
            Err(e) => {
                eprintln!("names-inject: map parse failed for {}: {e}", p.display());
                return ExitCode::from(4);
            }
        }
    }
    if dbs.is_empty() {
        eprintln!("names-inject: no databases found under {}", dir.display());
        return ExitCode::from(4);
    }

    // Apply across all parsed files at once.
    let glossary = wolf_decompiler::symbols::load_embedded_engine_glossary();
    let st = {
        let mut db_vec: Vec<Database> = dbs.iter().map(|(_, _, _, _, db)| db.clone()).collect();
        let mut ce_vec: Vec<&mut CommonEventsFile> =
            ce.as_mut().map(|(_, _, c)| c).into_iter().collect();
        let mut map_vec: Vec<Map> = maps.iter().map(|(_, _, m)| m.clone()).collect();
        let st = match inject_names(
            &names_json,
            &mut db_vec,
            &mut ce_vec,
            &mut map_vec,
            &opts,
            &glossary,
        ) {
            Ok(st) => st,
            Err(e) => {
                eprintln!("names-inject failed: {e}");
                return ExitCode::from(2);
            }
        };
        // Move the mutated copies back into the path-keyed records.
        for ((_, _, _, _, db), new) in dbs.iter_mut().zip(db_vec) {
            *db = new;
        }
        for ((_, _, m), new) in maps.iter_mut().zip(map_vec) {
            *m = new;
        }
        st
    };

    // Compute output paths (in place, or remapped under -o mirroring the relative layout).
    let remap = |orig: &Path| -> PathBuf {
        match &out_dir {
            Some(od) => od.join(rel(&dir, orig)),
            None => orig.to_path_buf(),
        }
    };

    let mut written = 0usize;
    // Databases (write both halves, then re-parse to never ship a corrupt pair).
    for (proj, dat, _, _, db) in &dbs {
        let (op, od) = db.write();
        if Database::read(&op, &od).is_err() {
            eprintln!(
                "names-inject: internal error - injected DB {} no longer parses; aborting write to avoid corruption. Please report.",
                proj.display()
            );
            return ExitCode::from(2);
        }
        let (out_proj, out_dat) = (remap(proj), remap(dat));
        if let Some(parent) = out_proj.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        if let (Err(e), _) | (_, Err(e)) = (
            std::fs::write(&out_proj, &op),
            std::fs::write(&out_dat, &od),
        ) {
            eprintln!("names-inject: write failed: {e}");
            return ExitCode::from(4);
        }
        written += 1;
    }
    // CommonEvent.
    if let Some((p, _, c)) = &ce {
        let out = c.write();
        if CommonEventsFile::read(&out).is_err() {
            eprintln!("names-inject: internal error - injected CommonEvent no longer parses; aborting. Please report.");
            return ExitCode::from(2);
        }
        let outp = remap(p);
        if let Some(parent) = outp.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        if let Err(e) = std::fs::write(&outp, &out) {
            eprintln!("names-inject: write failed: {e}");
            return ExitCode::from(4);
        }
        written += 1;
    }
    // Maps.
    for (p, _, m) in &maps {
        let out = m.write();
        if Map::read(&out).is_err() {
            eprintln!(
                "names-inject: internal error - injected map {} no longer parses; aborting. Please report.",
                p.display()
            );
            return ExitCode::from(2);
        }
        let outp = remap(p);
        if let Some(parent) = outp.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        if let Err(e) = std::fs::write(&outp, &out) {
            eprintln!("names-inject: write failed: {e}");
            return ExitCode::from(4);
        }
        written += 1;
    }

    eprintln!(
        "applied {} name change(s) ({} drifted/unmatched); wrote {written} file(s){}",
        st.applied,
        st.drifted,
        match &out_dir {
            Some(od) => format!(" under {}", od.display()),
            None => " in place".to_string(),
        }
    );
    guard_report(&st)
}

/// `wolf names-check <file.json>...`. Checks a set of translation JSONs (names.json, db-strings,
/// scenes) for **name-translation conflicts**: a glossary name (a `names.json` source) that is
/// translated to two or more distinct values across the files. This is the consistency guard for
/// the disjoint-ownership split. A name must translate to ONE value everywhere or by-name DB
/// lookups break. Exits non-zero (2) if any conflict is found. Only exact, full-string name
/// matches count (a name inside a dialogue sentence is a different source, never a conflict).
pub(crate) fn cmd_names_check(args: &[String]) -> ExitCode {
    let paths: Vec<PathBuf> = args.iter().map(PathBuf::from).collect();
    if paths.is_empty() {
        eprintln!("names-check: usage: wolf names-check <file.json>...");
        return ExitCode::from(64);
    }

    // Load every file up front (so the conflict scan sees them all). A read failure is fatal.
    let mut loaded: Vec<(String, String)> = Vec::new();
    for p in &paths {
        match std::fs::read_to_string(p) {
            Ok(text) => loaded.push((p.display().to_string(), text)),
            Err(e) => {
                eprintln!("names-check: cannot read {}: {e}", p.display());
                return ExitCode::from(4);
            }
        }
    }
    let refs: Vec<(String, &str)> = loaded
        .iter()
        .map(|(name, text)| (name.clone(), text.as_str()))
        .collect();

    let conflicts = check_name_conflicts(&refs);
    if conflicts.is_empty() {
        eprintln!(
            "names-check: OK - no name-translation conflicts across {} file(s)",
            loaded.len()
        );
        return ExitCode::SUCCESS;
    }

    eprintln!(
        "names-check: FOUND {} name(s) translated inconsistently:\n",
        conflicts.len()
    );
    for c in &conflicts {
        eprintln!("  {:?} has {} divergent translations:", c.source, c.variants.len());
        for v in &c.variants {
            eprintln!("      -> {:?}   (in {})", v.text, v.files.join(", "));
        }
    }
    eprintln!(
        "\nEach conflicting name must translate to ONE value everywhere, or by-name DB lookups break."
    );
    ExitCode::from(2)
}

// ----------------------------------------------------------------------------
// translations-merge: incremental translation memory across a game update
// ----------------------------------------------------------------------------

/// Collect every `*.json` under `path` (recursively) if it is a directory, or `path` itself if it
/// is a single `.json` file. Sorted for deterministic memory-build order.
fn collect_json_files(path: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    if path.is_dir() {
        let mut all = Vec::new();
        collect(path, &mut all);
        for p in all {
            if p.extension().and_then(|s| s.to_str()) == Some("json") {
                out.push(p);
            }
        }
    } else if path.extension().and_then(|s| s.to_str()) == Some("json") {
        out.push(path.to_path_buf());
    }
    out.sort();
    out
}

/// `wolf translations-merge --old <path>... --new <dir> -o <out-dir>`. Incremental **translation
/// memory**: carry the translations from an OLD (already-translated) extraction over into a freshly
/// re-extracted NEW set, matched by exact source string, so only genuinely new/changed lines stay
/// untranslated after a game update.
///
/// `--old` takes one or more files or directories (dirs are walked for `*.json`). ALL of them build
/// one global memory. For each `*.json` under `--new <dir>` (recursive), the memory is applied and
/// the result written to `<out-dir>/<same relative path>`. Prints a per-file line plus a TOTAL, the
/// count of memory sources dropped (removed in the update), and a conflict count. Exits 0 normally.
pub(crate) fn cmd_translations_merge(args: &[String]) -> ExitCode {
    let mut old_paths: Vec<PathBuf> = Vec::new();
    let mut new_dir: Option<PathBuf> = None;
    let mut out_dir: Option<PathBuf> = None;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            // --old greedily takes every following token until the next flag.
            "--old" => {
                while let Some(next) = it.clone().next() {
                    if next.starts_with('-') {
                        break;
                    }
                    old_paths.push(PathBuf::from(it.next().unwrap()));
                }
            }
            "--new" => new_dir = it.next().map(PathBuf::from),
            "-o" | "--output" => out_dir = it.next().map(PathBuf::from),
            _ => old_paths.push(PathBuf::from(a)),
        }
    }
    let (Some(new_dir), Some(out_dir)) = (new_dir, out_dir) else {
        eprintln!(
            "translations-merge: usage: wolf translations-merge --old <path>... --new <dir> -o <out-dir>"
        );
        return ExitCode::from(64);
    };
    if old_paths.is_empty() {
        eprintln!("translations-merge: --old needs at least one file or directory");
        return ExitCode::from(64);
    }

    // Build ONE global memory from every old JSON (files + every *.json under old dirs).
    let mut old_files: Vec<PathBuf> = Vec::new();
    for p in &old_paths {
        old_files.extend(collect_json_files(p));
    }
    old_files.sort();
    old_files.dedup();
    if old_files.is_empty() {
        eprintln!("translations-merge: no *.json found under the --old path(s)");
        return ExitCode::from(4);
    }
    let mut old_texts: Vec<String> = Vec::with_capacity(old_files.len());
    for p in &old_files {
        match std::fs::read_to_string(p) {
            Ok(t) => old_texts.push(t),
            Err(e) => {
                eprintln!("translations-merge: cannot read {}: {e}", p.display());
                return ExitCode::from(4);
            }
        }
    }
    let old_refs: Vec<&str> = old_texts.iter().map(String::as_str).collect();
    let (memory, conflicts) = build_memory(&old_refs);

    // Apply the memory to every *.json under --new, writing to <out-dir>/<relative path>.
    let new_files = collect_json_files(&new_dir);
    if new_files.is_empty() {
        eprintln!(
            "translations-merge: no *.json found under --new {}",
            new_dir.display()
        );
        return ExitCode::from(4);
    }

    let mut total = MergeStats::default();
    let mut new_texts: Vec<String> = Vec::with_capacity(new_files.len());
    for path in &new_files {
        let text = match std::fs::read_to_string(path) {
            Ok(t) => t,
            Err(e) => {
                eprintln!("translations-merge: cannot read {}: {e}", path.display());
                return ExitCode::from(4);
            }
        };
        let (merged, stats) = match apply_memory(&text, &memory) {
            Ok(r) => r,
            Err(e) => {
                eprintln!("translations-merge: {}: {e}", path.display());
                return ExitCode::from(4);
            }
        };
        new_texts.push(text);

        let out_path = out_dir.join(rel(&new_dir, path));
        if let Some(parent) = out_path.parent() {
            if let Err(e) = std::fs::create_dir_all(parent) {
                eprintln!("translations-merge: cannot create {}: {e}", parent.display());
                return ExitCode::from(4);
            }
        }
        if let Err(e) = std::fs::write(&out_path, &merged) {
            eprintln!("translations-merge: write failed for {}: {e}", out_path.display());
            return ExitCode::from(4);
        }
        println!(
            "{}: carried={} still_new={} kept_existing={}",
            rel(&new_dir, path),
            stats.carried,
            stats.still_new,
            stats.kept_existing
        );
        total.carried += stats.carried;
        total.still_new += stats.still_new;
        total.kept_existing += stats.kept_existing;
    }

    // Reporting: memory sources that no new file still contains (removed in the update).
    let new_refs: Vec<&str> = new_texts.iter().map(String::as_str).collect();
    let dropped = dropped_sources(&memory, &new_refs);

    println!(
        "TOTAL: carried={} still_new={} kept_existing={} (memory={} entries, {} new file(s))",
        total.carried,
        total.still_new,
        total.kept_existing,
        memory.len(),
        new_files.len()
    );
    println!("dropped (removed in update): {}", dropped.len());
    println!("conflicts: {}", conflicts.len());
    for (source, variants) in conflicts.iter().take(5) {
        println!("  {source:?} -> kept {:?} (also {:?})", variants[0], &variants[1..]);
    }
    if conflicts.len() > 5 {
        println!("  ... and {} more", conflicts.len() - 5);
    }
    ExitCode::SUCCESS
}

// ----------------------------------------------------------------------------
// save-update: refresh a baked save's title + player-facing strings for the translation
// ----------------------------------------------------------------------------

/// Read the `Title` entry out of a translated `Game.dat` (via the existing GameDat support plus
/// `extract_game_dat`), to use as the save's new baked title. `extract_game_dat` always emits the
/// `Title` line first, decoded in the file's encoding. We pull its `source` text out of that JSON.
fn title_from_game_dat(path: &Path) -> Result<String, String> {
    let bytes = std::fs::read(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    let gd = GameDat::read(&bytes).map_err(|e| format!("Game.dat parse failed: {e}"))?;
    let json = extract_game_dat(&gd);
    // wolf-cli has no JSON dep. The gamedat extraction has a fixed line shape
    // (`{"key": "Title", "source": "...", ...}`), so scan for the Title line's `source` value.
    extract_json_string_after(&json, "\"key\": \"Title\"", "\"source\":")
        .ok_or_else(|| format!("{} has no Title entry", path.display()))
}

/// Minimal forward scan: find `marker`, then the next `field` after it, and unescape the JSON
/// string value that follows. Sufficient for the fixed, machine-generated `extract_game_dat` shape.
/// Avoids pulling serde_json into the CLI crate. Returns `None` if the shape is unexpected.
fn extract_json_string_after(json: &str, marker: &str, field: &str) -> Option<String> {
    let after_marker = &json[json.find(marker)?..];
    // Advance past the field token itself (e.g. `"source":`). The value's opening quote is next.
    let field_at = after_marker.find(field)?;
    let after_field = &after_marker[field_at + field.len()..];
    let open = after_field.find('"')? + 1; // first byte of the value, after its opening quote
    let rest = &after_field[open..];
    let mut out = String::new();
    let mut chars = rest.chars();
    while let Some(c) = chars.next() {
        match c {
            '"' => return Some(out),
            '\\' => match chars.next()? {
                'n' => out.push('\n'),
                'r' => out.push('\r'),
                't' => out.push('\t'),
                '"' => out.push('"'),
                '\\' => out.push('\\'),
                '/' => out.push('/'),
                'u' => {
                    let hex: String = chars.by_ref().take(4).collect();
                    let code = u32::from_str_radix(&hex, 16).ok()?;
                    out.push(char::from_u32(code)?);
                }
                other => out.push(other),
            },
            _ => out.push(c),
        }
    }
    None
}

/// Build the `source -> target` baked-string map from the same translation JSONs used for the
/// game, by reusing [`build_memory`]. `--translations` takes files and/or directories (dirs are
/// walked for `*.json`). Reports any divergent sources but keeps the first (memory) value.
fn build_save_string_map(paths: &[PathBuf]) -> Result<std::collections::HashMap<String, String>, ExitCode> {
    let mut files: Vec<PathBuf> = Vec::new();
    for p in paths {
        files.extend(collect_json_files(p));
    }
    files.sort();
    files.dedup();
    let mut texts: Vec<String> = Vec::with_capacity(files.len());
    for p in &files {
        match std::fs::read_to_string(p) {
            Ok(t) => texts.push(t),
            Err(e) => {
                eprintln!("save-update: cannot read {}: {e}", p.display());
                return Err(ExitCode::from(4));
            }
        }
    }
    let refs: Vec<&str> = texts.iter().map(String::as_str).collect();
    let (memory, conflicts) = build_memory(&refs);
    if !conflicts.is_empty() {
        eprintln!(
            "save-update: note: {} source(s) had divergent translations across files; kept the first",
            conflicts.len()
        );
    }
    Ok(memory)
}

/// A short timestamp (`YYYYmmdd_HHMMSS`) from the system clock, for the backup dir name. Avoids a
/// chrono dependency by formatting the civil date from the Unix epoch seconds directly.
fn backup_stamp() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let days = secs / 86_400;
    let tod = secs % 86_400;
    let (hh, mm, ss) = (tod / 3600, (tod % 3600) / 60, tod % 60);
    // Civil-from-days (Howard Hinnant's algorithm), giving a stable, monotonic, unique-enough stamp.
    let z = days as i64 + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if m <= 2 { y + 1 } else { y };
    format!("{year:04}{m:02}{d:02}_{hh:02}{mm:02}{ss:02}")
}

/// `wolf save-update <save.sav|dir> [-o <out>] [--title <text> | --game <Game.dat>]
/// [--translations <file-or-dir>...]`. Rewrites the baked title to match the translated build and
/// refreshes the baked player-facing strings using the same translation JSONs applied to the game,
/// so an old/Japanese save loads cleanly. A directory input updates every `*.sav` inside it. A file
/// updates just that file. Default output is in place (originals backed up to
/// `<dir>/save_backup_<stamp>/` first), or `-o <path-or-dir>` writes copies elsewhere. Both the
/// standard codec and the GamePro Pro (marker-3) codec are supported. A buffer that is neither
/// is reported and skipped, never mangled.
pub(crate) fn cmd_save_update(args: &[String]) -> ExitCode {
    let mut input: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    let mut title: Option<String> = None;
    let mut game: Option<PathBuf> = None;
    let mut translations: Vec<PathBuf> = Vec::new();
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next().map(PathBuf::from),
            "--title" => title = it.next().cloned(),
            "--game" => game = it.next().map(PathBuf::from),
            // --translations greedily takes every following token until the next flag.
            "--translations" => {
                while let Some(next) = it.clone().next() {
                    if next.starts_with('-') {
                        break;
                    }
                    translations.push(PathBuf::from(it.next().unwrap()));
                }
            }
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let Some(input) = input else {
        eprintln!(
            "save-update: usage: wolf save-update <save.sav|dir> [-o <out>] \
             [--title <text> | --game <Game.dat>] [--translations <file-or-dir>...]"
        );
        return ExitCode::from(64);
    };
    if title.is_some() && game.is_some() {
        eprintln!("save-update: pass at most one of --title / --game");
        return ExitCode::from(64);
    }

    // Resolve the new title (literal, or read from a translated Game.dat), if any.
    let new_title: Option<String> = match (&title, &game) {
        (Some(t), _) => Some(t.clone()),
        (None, Some(g)) => match title_from_game_dat(g) {
            Ok(t) => {
                eprintln!("save-update: title from {} = {t:?}", g.display());
                Some(t)
            }
            Err(e) => {
                eprintln!("save-update: {e}");
                return ExitCode::from(4);
            }
        },
        (None, None) => None,
    };

    // Build the baked-string translation map (empty if --translations was not given).
    let strings = if translations.is_empty() {
        std::collections::HashMap::new()
    } else {
        match build_save_string_map(&translations) {
            Ok(m) => m,
            Err(code) => return code,
        }
    };
    if new_title.is_none() && strings.is_empty() {
        eprintln!("save-update: nothing to do (give --title/--game and/or --translations)");
        return ExitCode::from(64);
    }

    // Discover the save files to process.
    let saves: Vec<PathBuf> = if input.is_dir() {
        let mut v: Vec<PathBuf> = std::fs::read_dir(&input)
            .into_iter()
            .flatten()
            .flatten()
            .map(|e| e.path())
            .filter(|p| p.is_file() && p.extension().and_then(|s| s.to_str()) == Some("sav"))
            .collect();
        v.sort();
        v
    } else {
        vec![input.clone()]
    };
    if saves.is_empty() {
        eprintln!("save-update: no *.sav files found under {}", input.display());
        return ExitCode::from(4);
    }

    // Resolve where each save's output goes, and (for in-place) back up the originals first.
    let dir_input = input.is_dir();
    let in_place = output.is_none();
    if in_place {
        // Back up the originals before overwriting (mirrors the reference tool).
        let backup_root = if dir_input {
            input.join(format!("save_backup_{}", backup_stamp()))
        } else {
            let parent = input.parent().unwrap_or(Path::new("."));
            parent.join(format!("save_backup_{}", backup_stamp()))
        };
        if let Err(e) = std::fs::create_dir_all(&backup_root) {
            eprintln!("save-update: cannot create backup dir {}: {e}", backup_root.display());
            return ExitCode::from(4);
        }
        for src in &saves {
            let name = src.file_name().unwrap_or_default();
            if let Err(e) = std::fs::copy(src, backup_root.join(name)) {
                eprintln!("save-update: backup failed for {}: {e}", src.display());
                return ExitCode::from(4);
            }
        }
        eprintln!("save-update: backed up {} original(s) to {}", saves.len(), backup_root.display());
    } else if dir_input {
        // -o <dir> for a directory input: ensure it exists.
        if let Some(od) = &output {
            if let Err(e) = std::fs::create_dir_all(od) {
                eprintln!("save-update: cannot create output dir {}: {e}", od.display());
                return ExitCode::from(4);
            }
        }
    }

    let mut updated = 0usize;
    let mut skipped = 0usize;
    let mut had_error = false;
    for src in &saves {
        let name = src
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("?")
            .to_string();
        let raw = match std::fs::read(src) {
            Ok(b) => b,
            Err(e) => {
                eprintln!("{name}: read failed: {e}");
                had_error = true;
                continue;
            }
        };
        match update_save(&raw, new_title.as_deref(), &strings) {
            Ok((out_bytes, stats)) => {
                let dest = match &output {
                    None => src.clone(), // in place
                    Some(o) if dir_input => o.join(&name),
                    Some(o) => o.clone(), // single-file -o <file>
                };
                if let Some(parent) = dest.parent() {
                    let _ = std::fs::create_dir_all(parent);
                }
                if let Err(e) = std::fs::write(&dest, &out_bytes) {
                    eprintln!("{name}: write failed: {e}");
                    had_error = true;
                    continue;
                }
                println!(
                    "{name}: title={} strings={} enc={}",
                    u8::from(stats.title_changed),
                    stats.strings_replaced,
                    stats.encoding
                );
                updated += 1;
            }
            Err(_) => {
                // Err means the buffer is neither a standard 0x19 save nor a detectable GamePro
                // Pro (marker-3) save. Report and skip, never write.
                println!("{name}: SKIPPED (unsupported save encryption)");
                skipped += 1;
            }
        }
    }

    eprintln!("save-update: {updated} updated, {skipped} skipped");
    if had_error {
        ExitCode::from(4)
    } else {
        ExitCode::SUCCESS
    }
}

fn db_json_one(proj: &Path) -> Result<String, String> {
    let dat = proj.with_extension("dat");
    let pb = std::fs::read(proj).map_err(|e| e.to_string())?;
    let db_ = std::fs::read(&dat).map_err(|e| e.to_string())?;
    let db = Database::read(&pb, &db_).map_err(|e| e.to_string())?;
    let kind = match proj.file_stem().and_then(|s| s.to_str()) {
        Some("DataBase") => "UDB",
        Some("CDataBase") => "CDB",
        Some("SysDatabase") => "SDB",
        Some(other) => other,
        None => "DB",
    };
    let glossary = wolf_decompiler::symbols::load_embedded_engine_glossary();
    Ok(database_to_json(&db, kind, &glossary))
}

/// `wolf pack <dir> -o <out.wolf>`. Packs a directory tree into an unencrypted, engine-
/// loadable DXArchive (VER8). The archive round-trips byte-exact through `wolf unpack`.
pub(crate) fn cmd_pack(args: &[String]) -> ExitCode {
    let mut input: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    let mut encrypt = false;
    let mut version: u16 = 0x12C; // v3.00 default when --encrypt is given without --version
    let mut pwd: Option<[u8; 15]> = None;
    let mut like: Option<PathBuf> = None;
    let mut format: Option<String> = None; // "ver5" | "ver6" for the legacy 2.0x containers
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next().map(PathBuf::from),
            "--no-encrypt" => encrypt = false,
            "--encrypt" => encrypt = true,
            "--format" => format = it.next().cloned(),
            // Inherit cryptVersion + embedded password from an existing archive (turnkey repack).
            "--like" => like = it.next().map(PathBuf::from),
            "--version" => {
                if let Some(v) = it.next() {
                    let v = v.trim_start_matches("0x");
                    match u16::from_str_radix(v, 16).or_else(|_| v.parse()) {
                        Ok(n) => version = n,
                        Err(_) => {
                            eprintln!("pack: bad --version {v:?}");
                            return ExitCode::from(64);
                        }
                    }
                }
            }
            "--pwd" => pwd = it.next().and_then(|h| parse_pwd15(h)),
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let (Some(input), Some(output)) = (input, output) else {
        eprintln!(
            "pack: usage: wolf pack <dir> -o <out.wolf> \
             [--encrypt --version 0x14b [--pwd <30hex>]] | [--like <orig.wolf>]"
        );
        return ExitCode::from(64);
    };

    // `--like` inherits the original archive's cryptVersion + embedded password.
    if let Some(orig) = &like {
        match std::fs::read(orig)
            .ok()
            .and_then(|d| wolf_archive::archive_crypt_params(&d))
        {
            Some((cv, p)) => {
                version = cv;
                pwd = Some(p);
                encrypt = true;
            }
            None => {
                eprintln!("pack: could not read crypt params from {}", orig.display());
                return ExitCode::from(4);
            }
        }
    }

    let mut files: Vec<(String, Vec<u8>)> = Vec::new();
    if let Err(e) = gather_files(&input, &input, &mut files) {
        eprintln!("pack: {e}");
        return ExitCode::from(4);
    }
    if files.is_empty() {
        eprintln!("pack: no files found under {}", input.display());
        return ExitCode::from(4);
    }
    files.sort();

    // Default new-crypt password (used only when --encrypt a new-crypt version without --pwd
    // or --like). Self-describing: the archive embeds whatever password it was built with.
    let default_pwd: [u8; 15] = *b"WolfDawnRepack!";
    let result = match format.as_deref() {
        Some("ver5") => wolf_archive::pack_ver5(&files),
        Some("ver6") => wolf_archive::pack_ver6(&files),
        Some(other) => Err(format!("pack: unknown --format {other:?} (use ver5|ver6)")),
        None if !encrypt => wolf_archive::pack_plaintext(&files),
        None if matches!(version, 0x14B | 0x15E) => {
            wolf_archive::pack_newcrypt(&files, version, &pwd.unwrap_or(default_pwd))
        }
        None => wolf_archive::pack_encrypted(&files, version),
    };
    let bytes = match result {
        Ok(b) => b,
        Err(e) => {
            eprintln!("pack failed: {e}");
            return ExitCode::from(4);
        }
    };
    if let Err(e) = std::fs::write(&output, &bytes) {
        eprintln!("pack: cannot write {}: {e}", output.display());
        return ExitCode::from(4);
    }
    let mode = match format.as_deref() {
        Some(f) => format!("{f} (Wolf 2.0x)"),
        None if encrypt => {
            let src = if like.is_some() { " (--like)" } else { "" };
            format!("encrypted cryptVersion={version:#x}{src}")
        }
        None => "unencrypted".to_string(),
    };
    eprintln!(
        "packed {} files -> {} ({} bytes, {mode})",
        files.len(),
        output.display(),
        bytes.len()
    );
    ExitCode::SUCCESS
}

/// Parse a 30-hex-char string into a 15-byte WolfPro password.
fn parse_pwd15(h: &str) -> Option<[u8; 15]> {
    let h = h.trim();
    if h.len() != 30 {
        return None;
    }
    let mut out = [0u8; 15];
    for (i, b) in out.iter_mut().enumerate() {
        *b = u8::from_str_radix(&h[i * 2..i * 2 + 2], 16).ok()?;
    }
    Some(out)
}

/// Extract one already-read archive into `out_dir`, preserving the inner tree. Each inner path is
/// sanitised (drop empty/`.`/`..` segments and any drive/leading separator) so a malformed archive
/// entry can never write outside `out_dir`. Returns the file count on success.
fn unpack_archive_to(data: &[u8], out_dir: &Path) -> Result<usize, String> {
    let files =
        wolf_archive::extract_archive(data, b"").map_err(|e| format!("not a readable archive ({e})"))?;
    for (path, bytes) in &files {
        let safe: PathBuf = path
            .split(['\\', '/'])
            .filter(|s| !s.is_empty() && *s != "." && *s != "..")
            .collect();
        let target = out_dir.join(safe);
        if let Some(parent) = target.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        std::fs::write(&target, bytes)
            .map_err(|e| format!("cannot write {}: {e}", target.display()))?;
    }
    Ok(files.len())
}

/// True for a readable file whose extension is `.wolf` (case-insensitive).
fn is_wolf_file(p: &Path) -> bool {
    p.is_file()
        && p.extension()
            .and_then(|e| e.to_str())
            .map(|e| e.eq_ignore_ascii_case("wolf"))
            .unwrap_or(false)
}

/// The `.wolf` archives directly inside `dir`, sorted by name for a stable, reproducible order.
fn list_wolf_files(dir: &Path) -> Vec<PathBuf> {
    let mut v: Vec<PathBuf> = std::fs::read_dir(dir)
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .filter(|p| is_wolf_file(p))
        .collect();
    v.sort();
    v
}

/// `wolf unpack <archive.wolf> -o <dir>`. Extracts every file from a `.wolf` into `dir`,
/// preserving the inner directory tree. Handles any supported crypt regime.
pub(crate) fn cmd_unpack(args: &[String]) -> ExitCode {
    let mut input: Option<PathBuf> = None;
    let mut output: Option<PathBuf> = None;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next().map(PathBuf::from),
            _ => input = Some(PathBuf::from(a)),
        }
    }
    let Some(input) = input else {
        eprintln!("unpack: usage: wolf unpack <archive.wolf> -o <dir>");
        return ExitCode::from(64);
    };
    let out_dir = output.unwrap_or_else(|| PathBuf::from("unpacked"));

    let data = match std::fs::read(&input) {
        Ok(d) => d,
        Err(e) => {
            eprintln!("unpack: cannot read {}: {e}", input.display());
            return ExitCode::from(4);
        }
    };
    match unpack_archive_to(&data, &out_dir) {
        Ok(n) => {
            eprintln!("unpacked {n} files -> {}", out_dir.display());
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("unpack failed: {e}");
            ExitCode::from(4)
        }
    }
}

/// `wolf unpack-all <data-dir|archive.wolf>... [-o <out-dir>]`. Unpacks every `.wolf` among the
/// given paths. A directory argument is expanded to the `.wolf` files directly inside it, so the
/// whole split data set of a per-category game (BasicData.wolf, MapData.wolf, Evtext.wolf, ...)
/// comes apart in one call. Each `Name.wolf` lands in `<out>/Name/`, mirroring how the engine maps
/// a category archive to a `Name/` folder, so the result is a loose data tree the game can load.
/// With no `-o`, each archive unpacks beside itself (`<archive-dir>/Name/`). One bad archive does
/// not stop the rest, and the exit code is failure only when nothing unpacked.
pub(crate) fn cmd_unpack_all(args: &[String]) -> ExitCode {
    let mut inputs: Vec<PathBuf> = Vec::new();
    let mut output: Option<PathBuf> = None;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" | "--output" => output = it.next().map(PathBuf::from),
            _ => inputs.push(PathBuf::from(a)),
        }
    }
    if inputs.is_empty() {
        eprintln!("unpack-all: usage: wolf unpack-all <data-dir|archive.wolf>... [-o <out-dir>]");
        return ExitCode::from(64);
    }
    // Expand directory args to the .wolf files inside them, keep .wolf file args as-is.
    let mut archives: Vec<PathBuf> = Vec::new();
    for p in &inputs {
        if p.is_dir() {
            archives.extend(list_wolf_files(p));
        } else if is_wolf_file(p) {
            archives.push(p.clone());
        } else {
            eprintln!("unpack-all: skipping {} (not a .wolf or directory)", p.display());
        }
    }
    if archives.is_empty() {
        eprintln!("unpack-all: no .wolf archives found in the given paths");
        return ExitCode::from(4);
    }

    let mut total_files = 0usize;
    let (mut ok, mut failed) = (0usize, 0usize);
    for arc in &archives {
        let stem = arc.file_stem().and_then(|s| s.to_str()).unwrap_or("archive");
        let dest_root = output
            .clone()
            .or_else(|| arc.parent().map(Path::to_path_buf))
            .unwrap_or_default();
        let out_dir = dest_root.join(stem);
        let name = arc.file_name().and_then(|s| s.to_str()).unwrap_or(stem);
        match std::fs::read(arc)
            .map_err(|e| e.to_string())
            .and_then(|d| unpack_archive_to(&d, &out_dir))
        {
            Ok(n) => {
                total_files += n;
                ok += 1;
                eprintln!("  {name} -> {} ({n} files)", out_dir.display());
            }
            Err(e) => {
                failed += 1;
                eprintln!("  {name} FAILED: {e}");
            }
        }
    }
    eprintln!(
        "unpack-all: {ok} archive(s), {total_files} files{}",
        if failed > 0 {
            format!(", {failed} failed")
        } else {
            String::new()
        }
    );
    if ok == 0 {
        ExitCode::from(4)
    } else {
        ExitCode::SUCCESS
    }
}

/// Recursively gather `(relative-path, bytes)` for every file under `dir`.
fn gather_files(base: &Path, dir: &Path, out: &mut Vec<(String, Vec<u8>)>) -> std::io::Result<()> {
    for entry in std::fs::read_dir(dir)? {
        let p = entry?.path();
        if p.is_dir() {
            gather_files(base, &p, out)?;
        } else {
            let rel = p
                .strip_prefix(base)
                .unwrap_or(&p)
                .to_string_lossy()
                .replace('\\', "/");
            out.push((rel, std::fs::read(&p)?));
        }
    }
    Ok(())
}

/// Build a symbol table for a map by locating the game's BasicData folder
/// (`.../Data/MapData/X.mps` -> `.../Data/BasicData`) and loading CommonEvent + databases.
pub(crate) fn load_symbols(map_path: &Path) -> SymbolTable {
    let mut symbols = SymbolTable::new();
    let basic_data = map_path
        .parent()
        .and_then(|p| p.parent())
        .map(|data| data.join("BasicData"));
    let Some(basic) = basic_data else {
        return symbols;
    };

    if let Ok(bytes) = std::fs::read(basic.join("CommonEvent.dat")) {
        if let Ok(ce) = CommonEventsFile::read(&bytes) {
            symbols.add_common_events(&ce);
        }
    }
    add_databases(&mut symbols, Some(&basic));
    symbols.set_glossary(wolf_decompiler::symbols::load_embedded_glossary());
    symbols.set_engine_text(wolf_decompiler::symbols::load_embedded_engine_glossary());
    symbols
}

/// Load the three standard databases from `basic_data` into the symbol table.
pub(crate) fn add_databases(symbols: &mut SymbolTable, basic_data: Option<&Path>) {
    let Some(dir) = basic_data else { return };
    for (kind, stem) in [
        ("UDB", "DataBase"),
        ("CDB", "CDataBase"),
        ("SDB", "SysDatabase"),
    ] {
        let proj = dir.join(format!("{stem}.project"));
        let dat = dir.join(format!("{stem}.dat"));
        if let (Ok(p), Ok(d)) = (std::fs::read(&proj), std::fs::read(&dat)) {
            if let Ok(db) = Database::read(&p, &d) {
                symbols.add_database(kind, &db);
            }
        }
    }
}

// ----------------------------------------------------------------------------
// verify-roundtrip
// ----------------------------------------------------------------------------

pub(crate) fn cmd_verify(args: &[String]) -> ExitCode {
    if args.first().map(String::as_str) == Some("--corpus") {
        let Some(dir) = args.get(1) else {
            eprintln!("verify-roundtrip --corpus: missing data dir");
            return ExitCode::from(64);
        };
        return verify_corpus(Path::new(dir));
    }
    let Some(path) = args.first() else {
        eprintln!("verify-roundtrip: missing file");
        return ExitCode::from(64);
    };
    let path = PathBuf::from(path);
    match roundtrip_path(&path) {
        Ok(true) => {
            println!("OK  byte-exact  {}", path.display());
            ExitCode::SUCCESS
        }
        Ok(false) => {
            println!("DIFF  {}", path.display());
            ExitCode::from(2)
        }
        Err(e) => {
            eprintln!("ERR  {}: {e}", path.display());
            ExitCode::from(4)
        }
    }
}

pub(crate) fn verify_corpus(dir: &Path) -> ExitCode {
    let mut ok = 0usize;
    let mut diff = 0usize;
    let mut err = 0usize;

    let mut files: Vec<PathBuf> = Vec::new();
    collect(dir, &mut files);
    files.sort();

    for path in files {
        match classify(&path) {
            FileKind::Unsupported => continue,
            // The .dat half of a database is verified via its .project. Skip the lone .dat.
            FileKind::Database | FileKind::BasicDatabase
                if path.extension().and_then(|s| s.to_str()) == Some("dat") =>
            {
                continue
            }
            _ => {}
        }
        match roundtrip_path(&path) {
            Ok(true) => {
                ok += 1;
                println!("OK    {}", rel(dir, &path));
            }
            Ok(false) => {
                diff += 1;
                println!("DIFF  {}", rel(dir, &path));
            }
            Err(e) => {
                err += 1;
                println!("ERR   {}  ({e})", rel(dir, &path));
            }
        }
    }

    println!("\n{ok} ok, {diff} diff, {err} error");
    if diff == 0 && err == 0 {
        ExitCode::SUCCESS
    } else if diff > 0 {
        ExitCode::from(2)
    } else {
        ExitCode::from(4)
    }
}

/// Returns Ok(true) if `write(read(bytes)) == bytes`.
pub(crate) fn roundtrip_path(path: &Path) -> Result<bool, String> {
    let bytes = std::fs::read(path).map_err(|e| e.to_string())?;
    match classify(path) {
        FileKind::Map => {
            let m = Map::read(&bytes).map_err(|e| e.to_string())?;
            Ok(m.write() == bytes)
        }
        FileKind::CommonEvent => {
            let ce = CommonEventsFile::read(&bytes).map_err(|e| e.to_string())?;
            Ok(ce.write() == bytes)
        }
        FileKind::GameDat => {
            let gd = GameDat::read(&bytes).map_err(|e| e.to_string())?;
            Ok(gd.write() == bytes)
        }
        FileKind::Database => {
            // `path` is the .project. Pair it with the sibling .dat.
            let dat = path.with_extension("dat");
            let proj_bytes = bytes;
            let dat_bytes = std::fs::read(&dat).map_err(|e| e.to_string())?;
            let db = Database::read(&proj_bytes, &dat_bytes).map_err(|e| e.to_string())?;
            let (proj_out, dat_out) = db.write();
            Ok(proj_out == proj_bytes && dat_out == dat_bytes)
        }
        FileKind::BasicDatabase => {
            // Legacy basic DB: schema `.project` + opaque `.dat`, paired by the `.project`.
            let proj_path = path.with_extension("project");
            let dat_path = path.with_extension("dat");
            let proj_bytes = std::fs::read(&proj_path).map_err(|e| e.to_string())?;
            let dat_bytes = std::fs::read(&dat_path).map_err(|e| e.to_string())?;
            let db = wolf_formats::database::BasicDatabase::read(&proj_bytes, &dat_bytes)
                .map_err(|e| e.to_string())?;
            let (proj_out, dat_out) = db.write();
            Ok(proj_out == proj_bytes && dat_out == dat_bytes)
        }
        FileKind::TxtEvent => {
            // An external event-text file round-trips through a no-op extract/inject, which must
            // reproduce the bytes exactly (this is the byte-exactness guarantee the translation
            // pipeline relies on).
            let json = extract_txt_events(&bytes);
            let out = inject_txt_events(&json, &bytes).map_err(|e| e.to_string())?;
            Ok(out == bytes)
        }
        FileKind::Unsupported => Err("unsupported file type".into()),
    }
}

// ----------------------------------------------------------------------------
// file classification
// ----------------------------------------------------------------------------

pub(crate) enum FileKind {
    Map,
    CommonEvent,
    /// The per-game settings/title record (`Game.dat`).
    GameDat,
    /// Represented by the `.project` file (the `.dat` sibling is paired in).
    Database,
    /// Legacy `SysDataBaseBasic` (Wolf 2.x): schema-only `.project` + opaque magic-less `.dat`.
    BasicDatabase,
    /// An external event-text `.txt` file (Shift-JIS or UTF-8 dialogue, one scene per file). The
    /// `Evtext*.wolf` archives unpack to these. Handled by `txt_events`.
    TxtEvent,
    Unsupported,
}

pub(crate) fn classify(path: &Path) -> FileKind {
    let ext = path
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    let name = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();

    match ext.as_str() {
        "mps" => FileKind::Map,
        // The legacy basic system DB is keyed by its fixed file name.
        "project" if name == "sysdatabasebasic.project" => FileKind::BasicDatabase,
        "dat" if name == "sysdatabasebasic.dat" => FileKind::BasicDatabase,
        "project" => FileKind::Database,
        "dat" if name == "commonevent.dat" => FileKind::CommonEvent,
        "dat" if name == "game.dat" => FileKind::GameDat,
        // A .dat with a sibling .project is the value half of a database.
        "dat" if path.with_extension("project").exists() => FileKind::Database,
        // External event-text. The only `.txt` use in a Wolf game is unpacked Evtext scene files.
        "txt" => FileKind::TxtEvent,
        _ => FileKind::Unsupported,
    }
}

pub(crate) fn collect(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let p = entry.path();
        if p.is_dir() {
            collect(&p, out);
        } else {
            out.push(p);
        }
    }
}

pub(crate) fn rel(base: &Path, path: &Path) -> String {
    path.strip_prefix(base)
        .unwrap_or(path)
        .display()
        .to_string()
}

// ----------------------------------------------------------------------------
// gui: launch WolfDawn Studio (the eframe desktop GUI), if it sits next to us
// ----------------------------------------------------------------------------

/// `wolf gui`. Launches the `wolf-gui` desktop app from beside the current executable. This crate
/// has no eframe dependency. It only *spawns* the separately-built `wolf-gui` binary. If that
/// binary is not found next to `wolf`, print how to build/run it and exit non-fatally.
pub(crate) fn cmd_gui(args: &[String]) -> ExitCode {
    let exe = match std::env::current_exe() {
        Ok(p) => p,
        Err(e) => {
            eprintln!("gui: cannot locate the current executable: {e}");
            return ExitCode::from(4);
        }
    };
    let dir = exe.parent().unwrap_or(Path::new("."));
    let gui_name = if cfg!(windows) { "wolf-gui.exe" } else { "wolf-gui" };
    let gui_path = dir.join(gui_name);

    if !gui_path.exists() {
        eprintln!(
            "gui: WolfDawn Studio ({}) was not found next to {}.\n\
             Build and run it with:  cargo run --release -p wolf-gui",
            gui_name,
            exe.display()
        );
        return ExitCode::SUCCESS; // non-fatal: nothing went wrong, the GUI just isn't built
    }

    match std::process::Command::new(&gui_path).args(args).spawn() {
        Ok(_) => {
            eprintln!("launched {}", gui_path.display());
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("gui: failed to launch {}: {e}", gui_path.display());
            ExitCode::from(4)
        }
    }
}
