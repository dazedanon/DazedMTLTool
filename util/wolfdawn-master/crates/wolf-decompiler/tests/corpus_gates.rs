//! Permanent corpus gates. Across every sample or game file reachable from the workspace root,
//! (1) the readable decompile must contain no generic/fallthrough renderings (no `Self*[`,
//! `route<n>`, `cmp<n>`, `Cmd<n>`, `@raw`, or `argN`), and (2) every command list must round-trip
//! byte-exactly through the gated recompile path. Guards the "nothing generic, fully readable,
//! never lossy" contract for maps and common events at all engine versions.

use wolf_decompiler::{
    compile_commands_enc, decompile_commands_annotated, decompile_commands_enc,
    decompile_common_events, decompile_map, SymbolTable,
};
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::database::Database;
use wolf_formats::map::Map;

/// Build a real symbol table for a code file (CE self-vars, the sibling databases' variable
/// names, and the engine glossary), mirroring the CLI so the annotate path resolves real names.
fn symbols_for(path: &std::path::Path, ce: Option<&CommonEventsFile>) -> SymbolTable {
    let mut sym = SymbolTable::new();
    if let Some(ce) = ce {
        sym.add_common_events(ce);
    }
    if let Some(dir) = path.parent() {
        let basic = if dir.join("DataBase.project").exists() {
            dir.to_path_buf()
        } else {
            dir.join("BasicData")
        };
        for (stem, kind) in [
            ("DataBase", "UDB"),
            ("CDataBase", "CDB"),
            ("SysDatabase", "SDB"),
        ] {
            let proj = basic.join(format!("{stem}.project"));
            let dat = basic.join(format!("{stem}.dat"));
            if let (Ok(p), Ok(d)) = (std::fs::read(&proj), std::fs::read(&dat)) {
                if let Ok(db) = Database::read(&p, &d) {
                    sym.add_database(kind, &db);
                }
            }
        }
    }
    sym.set_engine_text(wolf_decompiler::symbols::load_embedded_engine_glossary());
    sym
}

fn corpus_files() -> Vec<std::path::PathBuf> {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let mut stack = vec![root];
    let mut out = Vec::new();
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else {
            continue;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                stack.push(p);
            } else {
                let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("");
                let ext = p.extension().and_then(|s| s.to_str()).unwrap_or("");
                if name == "CommonEvent.dat" || ext.eq_ignore_ascii_case("mps") {
                    out.push(p);
                }
            }
        }
    }
    out
}

/// A generic/fallthrough token that should never appear in readable output.
fn fallthrough_hits(text: &str) -> Vec<String> {
    let mut hits = Vec::new();
    for line in text.lines() {
        let l = line.trim();
        if l.contains("Self*[")
            || l.contains("@raw ")
            || prefixed_num(l, "route")
            || prefixed_num(l, "cmp")
            || prefixed_num(l, "Cmd")
            || generic_argn(l)
        {
            hits.push(l.to_string());
        }
    }
    hits
}

/// `prefix` immediately followed by a digit, not preceded by an alphanumeric (so `route47`
/// matches but `@route(` and `strcmp` do not).
fn prefixed_num(line: &str, prefix: &str) -> bool {
    line.match_indices(prefix).any(|(i, _)| {
        let before_ok = line[..i]
            .chars()
            .last()
            .map_or(true, |c| !c.is_alphanumeric() && c != '@');
        before_ok
            && line[i + prefix.len()..]
                .chars()
                .next()
                .map_or(false, |c| c.is_ascii_digit())
    })
}

fn generic_argn(line: &str) -> bool {
    line.match_indices("arg").any(|(i, _)| {
        let before_ok = line[..i]
            .chars()
            .last()
            .map_or(true, |c| !c.is_alphanumeric());
        let after = &line[i + 3..];
        before_ok
            && after.chars().next().map_or(false, |c| c.is_ascii_digit())
            && after
                .split_once('=')
                .map_or(false, |(k, _)| k.chars().all(|c| c.is_ascii_digit()))
    })
}

#[test]
fn no_fallthrough_renderings() {
    let sym = SymbolTable::new();
    let mut total = 0usize;
    let mut bad = 0usize;
    for p in corpus_files() {
        let bytes = std::fs::read(&p).unwrap_or_default();
        let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("");
        let text = if name == "CommonEvent.dat" {
            match CommonEventsFile::read(&bytes) {
                Ok(ce) => decompile_common_events(&ce, &sym),
                Err(_) => continue, // encrypted or out-of-scope inputs
            }
        } else {
            match Map::read(&bytes) {
                Ok(m) => decompile_map(&m, &sym),
                Err(_) => continue,
            }
        };
        total += 1;
        let hits = fallthrough_hits(&text);
        if !hits.is_empty() {
            bad += 1;
            eprintln!(
                "{} fallthrough(s) in {:?}; e.g. {}",
                hits.len(),
                p.file_name().unwrap(),
                hits[0]
            );
        }
    }
    eprintln!("scanned {total} readable files");
    assert!(total > 0, "corpus not found");
    assert_eq!(bad, 0, "files with generic/fallthrough renderings");
}

#[test]
fn annotate_roundtrip_byte_exact() {
    // The unified read-plus-edit form (index-anchored bilingual names) must round-trip byte-exact
    // with real symbols loaded. The recompiler strips the labels. The index is the authority.
    let mut lists = 0usize;
    let mut mismatch = 0usize;
    let mut annotated = 0usize;
    for p in corpus_files() {
        let bytes = std::fs::read(&p).unwrap_or_default();
        let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("");
        if name == "CommonEvent.dat" {
            let Ok(ce) = CommonEventsFile::read(&bytes) else {
                continue;
            };
            let sym = symbols_for(&p, Some(&ce));
            for ev in &ce.events {
                lists += 1;
                let text =
                    decompile_commands_annotated(&ev.commands, ce.utf8, &sym, Some(ev.int_id));
                if text.contains("[0 \"") || text.contains("\" ] ") || text.matches('"').count() > 0
                {
                    annotated += text
                        .lines()
                        .filter(|l| l.contains("[") && l.contains("\""))
                        .count();
                }
                match compile_commands_enc(&text, ce.utf8) {
                    Ok(back) if back == ev.commands => {}
                    _ => {
                        mismatch += 1;
                        if mismatch <= 5 {
                            eprintln!(
                                "annotate mismatch in {:?} CE {}",
                                p.file_name().unwrap(),
                                ev.int_id
                            );
                        }
                    }
                }
            }
        } else if p.extension().and_then(|s| s.to_str()) == Some("mps") {
            let Ok(m) = Map::read(&bytes) else { continue };
            let sym = symbols_for(&p, None);
            for ev in &m.events {
                for pg in &ev.pages {
                    lists += 1;
                    let text = decompile_commands_annotated(&pg.commands, m.utf8, &sym, None);
                    match compile_commands_enc(&text, m.utf8) {
                        Ok(back) if back == pg.commands => {}
                        _ => {
                            mismatch += 1;
                            if mismatch <= 5 {
                                eprintln!("annotate mismatch in {:?}", p.file_name().unwrap());
                            }
                        }
                    }
                }
            }
        }
    }
    eprintln!("annotate: round-tripped {lists} lists, ~{annotated} annotated lines seen");
    assert!(lists > 0, "corpus not found");
    assert_eq!(
        mismatch, 0,
        "annotated command lists that did not round-trip byte-exactly"
    );
}

#[test]
fn byte_exact_roundtrip() {
    let mut lists = 0usize;
    let mut mismatch = 0usize;
    for p in corpus_files() {
        let bytes = std::fs::read(&p).unwrap_or_default();
        let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("");
        let programs: Vec<(bool, Vec<_>)> = if name == "CommonEvent.dat" {
            match CommonEventsFile::read(&bytes) {
                Ok(ce) => ce
                    .events
                    .into_iter()
                    .map(|ev| (ce.utf8, ev.commands))
                    .collect(),
                Err(_) => continue,
            }
        } else {
            match Map::read(&bytes) {
                Ok(m) => m
                    .events
                    .into_iter()
                    .flat_map(|ev| ev.pages.into_iter().map(move |pg| (m.utf8, pg.commands)))
                    .collect(),
                Err(_) => continue,
            }
        };
        for (utf8, cmds) in programs {
            lists += 1;
            let text = decompile_commands_enc(&cmds, utf8);
            match compile_commands_enc(&text, utf8) {
                Ok(back) if back == cmds => {}
                Ok(_) => {
                    mismatch += 1;
                    if mismatch <= 5 {
                        eprintln!("structural mismatch in {:?}", p.file_name().unwrap());
                    }
                }
                Err(e) => {
                    mismatch += 1;
                    if mismatch <= 5 {
                        eprintln!("compile error in {:?}: {e}", p.file_name().unwrap());
                    }
                }
            }
        }
    }
    eprintln!("round-tripped {lists} command lists");
    assert!(lists > 0, "corpus not found");
    assert_eq!(
        mismatch, 0,
        "command lists that did not round-trip byte-exactly"
    );
}
