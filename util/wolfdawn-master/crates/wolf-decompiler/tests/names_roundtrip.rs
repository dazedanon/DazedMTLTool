//! Project-level name glossary round-trip, against the real corpus at `<workspace>/Data`
//! (resolved via `CARGO_MANIFEST_DIR/../../../Data`). Skips gracefully when the corpus is absent.
//!
//! Gates:
//!   (a) Extract then no-op inject (every `text == source`) leaves every DB pair, CommonEvent,
//!       and map byte-identical.
//!   (b) Translating one name and injecting rewrites it in every place it appears: its stored
//!       `DbData.name`, every name/display cell that held it, and every command by-name reference.
//!       All other strings and every other file's bytes stay untouched, and every file still
//!       re-parses.
//!   (c) Extraction is deterministic (byte-identical across runs).

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use serde_json::Value;
use wolf_decompiler::text::decode_wstr;
use wolf_decompiler::{
    extract_db_name_cells, extract_db_strings, extract_names, inject_names, InjectOptions,
};
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::database::Database;
use wolf_formats::map::Map;

/// The BasicData dir of the corpus, or `None` when the corpus is not present.
fn corpus_basic() -> Option<PathBuf> {
    let base = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../Data/BasicData");
    base.join("DataBase.project").exists().then_some(base)
}

fn map_data_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../Data/MapData")
}

/// A loaded database with the original on-disk bytes kept for byte-identity checks.
struct LoadedDb {
    proj: Vec<u8>,
    dat: Vec<u8>,
    db: Database,
    stem: &'static str,
}

fn load_dbs(basic: &Path) -> Vec<LoadedDb> {
    let mut out = Vec::new();
    for stem in ["DataBase", "CDataBase", "SysDatabase"] {
        let proj = basic.join(format!("{stem}.project"));
        let dat = basic.join(format!("{stem}.dat"));
        if let (Ok(p), Ok(d)) = (std::fs::read(&proj), std::fs::read(&dat)) {
            if let Ok(db) = Database::read(&p, &d) {
                out.push(LoadedDb {
                    proj: p,
                    dat: d,
                    db,
                    stem,
                });
            }
        }
    }
    out
}

fn load_ce(basic: &Path) -> Option<(Vec<u8>, CommonEventsFile)> {
    let b = std::fs::read(basic.join("CommonEvent.dat")).ok()?;
    let ce = CommonEventsFile::read(&b).ok()?;
    Some((b, ce))
}

fn load_maps() -> Vec<(Vec<u8>, Map)> {
    let mut out = Vec::new();
    let Ok(rd) = std::fs::read_dir(map_data_dir()) else {
        return out;
    };
    let mut paths: Vec<PathBuf> = rd
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().and_then(|s| s.to_str()) == Some("mps"))
        .collect();
    paths.sort();
    for p in paths {
        if let Ok(b) = std::fs::read(&p) {
            if let Ok(m) = Map::read(&b) {
                out.push((b, m));
            }
        }
    }
    out
}

fn glossary() -> HashMap<String, String> {
    wolf_decompiler::symbols::load_embedded_engine_glossary()
}

/// Run extract over the loaded corpus.
fn extract(dbs: &[LoadedDb], ce: Option<&CommonEventsFile>, maps: &[(Vec<u8>, Map)]) -> String {
    let db_vec: Vec<Database> = dbs.iter().map(|l| l.db.clone()).collect();
    let ce_refs: Vec<&CommonEventsFile> = ce.into_iter().collect();
    let map_vec: Vec<Map> = maps.iter().map(|(_, m)| m.clone()).collect();
    extract_names(&db_vec, &ce_refs, &map_vec, &glossary())
}

#[test]
fn extract_then_noop_inject_is_byte_identical() {
    let Some(basic) = corpus_basic() else {
        eprintln!("no corpus, skipping");
        return;
    };
    let dbs = load_dbs(&basic);
    let ce = load_ce(&basic);
    let maps = load_maps();
    assert!(!dbs.is_empty(), "corpus DBs must load");

    // Extract is the identity glossary (every text == source), so injecting it must be a no-op.
    let names_json = extract(&dbs, ce.as_ref().map(|(_, c)| c), &maps);

    let mut db_vec: Vec<Database> = dbs.iter().map(|l| l.db.clone()).collect();
    let mut ce_clone = ce.as_ref().map(|(_, c)| c.clone());
    let mut ce_refs: Vec<&mut CommonEventsFile> = ce_clone.as_mut().into_iter().collect();
    let mut map_vec: Vec<Map> = maps.iter().map(|(_, m)| m.clone()).collect();

    let st = inject_names(
        &names_json,
        &mut db_vec,
        &mut ce_refs,
        &mut map_vec,
        &InjectOptions::default(),
        &glossary(),
    )
    .expect("inject");
    assert_eq!(
        st.applied, 0,
        "a no-op (identity) glossary must apply zero changes"
    );

    // Every file must re-serialize byte-identical to its original on-disk bytes.
    for (l, db) in dbs.iter().zip(&db_vec) {
        let (p, d) = db.write();
        assert!(
            p == l.proj && d == l.dat,
            "{}: no-op inject changed the DB bytes",
            l.stem
        );
    }
    if let (Some((b, _)), Some(c)) = (&ce, &ce_clone) {
        assert!(
            &c.write() == b,
            "no-op inject changed the CommonEvent bytes"
        );
    }
    for ((b, _), m) in maps.iter().zip(&map_vec) {
        assert!(&m.write() == b, "no-op inject changed a map's bytes");
    }
}

/// Count how many times `source` appears as: a stored row name, a string cell value (any field),
/// and a by-name command reference (cid250/252 str2, cid251 str1, cid112 any str).
struct Occ {
    row_names: usize,
    cell_values: usize,
    refs: usize,
}

fn count_occ(
    source: &str,
    dbs: &[Database],
    ce: Option<&CommonEventsFile>,
    maps: &[Map],
) -> Occ {
    let mut o = Occ {
        row_names: 0,
        cell_values: 0,
        refs: 0,
    };
    for db in dbs {
        let utf8 = db.utf8;
        for t in &db.types {
            for row in &t.data {
                if decode_wstr(&row.name, utf8) == source {
                    o.row_names += 1;
                }
                for w in &row.string_values {
                    if decode_wstr(w, utf8) == source {
                        o.cell_values += 1;
                    }
                }
            }
        }
    }
    let count_refs = |cmds: &[wolf_formats::command::RawCommand], utf8: bool, o: &mut Occ| {
        for cmd in cmds {
            let idx: Vec<usize> = match cmd.cid {
                250 | 252 => vec![2],
                251 => vec![1],
                112 => (0..cmd.str_args.len()).collect(),
                _ => vec![],
            };
            for si in idx {
                if let Some(w) = cmd.str_args.get(si) {
                    if decode_wstr(w, utf8) == source {
                        o.refs += 1;
                    }
                }
            }
        }
    };
    if let Some(ce) = ce {
        for ev in &ce.events {
            count_refs(&ev.commands, ce.utf8, &mut o);
        }
    }
    for m in maps {
        for ev in &m.events {
            for pg in &ev.pages {
                count_refs(&pg.commands, m.utf8, &mut o);
            }
        }
    }
    o
}

#[test]
fn translate_one_name_updates_all_mirrors_consistently() {
    let Some(basic) = corpus_basic() else {
        eprintln!("no corpus, skipping");
        return;
    };
    let dbs = load_dbs(&basic);
    let ce = load_ce(&basic);
    let maps = load_maps();

    let names_json = extract(&dbs, ce.as_ref().map(|(_, c)| c), &maps);
    let root: Value = serde_json::from_str(&names_json).unwrap();
    let names = root["names"].as_array().unwrap();

    let db_snap: Vec<Database> = dbs.iter().map(|l| l.db.clone()).collect();
    let ce_snap = ce.as_ref().map(|(_, c)| c.clone());
    let map_snap: Vec<Map> = maps.iter().map(|(_, m)| m.clone()).collect();

    // Pick a target name that lives in both a stored row name and a by-name command reference,
    // the cross-mirror case the glossary exists to keep consistent. In the sample corpus these
    // are the CDB variable rows looked up by `cid250` data-name.
    let target = names
        .iter()
        .map(|e| e["source"].as_str().unwrap().to_string())
        .find(|s| {
            let o = count_occ(s, &db_snap, ce_snap.as_ref(), &map_snap);
            o.row_names >= 1 && o.refs >= 1
        })
        .expect("a name occurring as both a row name and a by-name reference");
    let before = count_occ(&target, &db_snap, ce_snap.as_ref(), &map_snap);

    // A translation representable in both UTF-8 and Shift-JIS (ASCII) so the encoding guard never
    // skips it, and not already present in the corpus.
    let translated = "WOLFDAWN_NAME_X";
    assert!(
        count_occ(translated, &db_snap, ce_snap.as_ref(), &map_snap).row_names
            + count_occ(translated, &db_snap, ce_snap.as_ref(), &map_snap).cell_values
            == 0,
        "sentinel must not pre-exist"
    );

    // Build a one-entry glossary translating only the target.
    let one = serde_json::json!({
        "kind": "names",
        "names": [ { "source": target, "text": translated, "occurrences": 0, "note": "" } ]
    })
    .to_string();

    // Inject onto fresh clones.
    let mut db_vec: Vec<Database> = dbs.iter().map(|l| l.db.clone()).collect();
    let mut ce_clone = ce.as_ref().map(|(_, c)| c.clone());
    let mut ce_refs: Vec<&mut CommonEventsFile> = ce_clone.as_mut().into_iter().collect();
    let mut map_vec: Vec<Map> = maps.iter().map(|(_, m)| m.clone()).collect();
    let st = inject_names(
        &one,
        &mut db_vec,
        &mut ce_refs,
        &mut map_vec,
        &InjectOptions::default(),
        &glossary(),
    )
    .expect("inject");

    // Every mirror that held the source now holds the translation. The source is gone.
    let after_src = count_occ(&target, &db_vec, ce_clone.as_ref(), &map_vec);
    let after_dst = count_occ(translated, &db_vec, ce_clone.as_ref(), &map_vec);

    assert_eq!(
        after_src.row_names, 0,
        "the source row name must be rewritten"
    );
    assert_eq!(
        after_src.refs, 0,
        "every by-name reference to the source must be rewritten"
    );
    assert_eq!(
        after_src.cell_values, 0,
        "every cell holding the source must be rewritten"
    );
    assert_eq!(
        after_dst.row_names, before.row_names,
        "row-name mirror count preserved under translation"
    );
    assert_eq!(
        after_dst.refs, before.refs,
        "by-name reference count preserved under translation"
    );
    assert_eq!(
        after_dst.cell_values, before.cell_values,
        "cell-value mirror count preserved under translation"
    );
    // The applied count is at least the number of mirrors that changed (DB cells, row names, and
    // refs). The reference mirror is the headline cross-file guarantee.
    assert!(before.refs >= 1 && before.row_names >= 1);
    assert!(
        st.applied >= before.row_names + before.refs,
        "applied ({}) must cover every rewritten mirror (row names {} + refs {})",
        st.applied,
        before.row_names,
        before.refs
    );

    // Every file still re-parses (never ship a structurally-corrupt file).
    for db in &db_vec {
        let (p, d) = db.write();
        Database::read(&p, &d).expect("injected DB re-parses");
    }
    if let Some(c) = &ce_clone {
        CommonEventsFile::read(&c.write()).expect("injected CommonEvent re-parses");
    }
    for m in &map_vec {
        Map::read(&m.write()).expect("injected map re-parses");
    }

    // Untouched files: a file with no occurrence of the target must be byte-identical to the base.
    for (l, db) in dbs.iter().zip(&db_vec) {
        let touched = count_occ(&target, std::slice::from_ref(&l.db), None, &[]).row_names
            + count_occ(&target, std::slice::from_ref(&l.db), None, &[]).cell_values
            > 0;
        if !touched {
            let (p, d) = db.write();
            assert!(
                p == l.proj && d == l.dat,
                "{}: a DB with no target occurrence must be byte-identical",
                l.stem
            );
        }
    }
}

#[test]
fn extraction_is_deterministic() {
    let Some(basic) = corpus_basic() else {
        eprintln!("no corpus, skipping");
        return;
    };
    let dbs = load_dbs(&basic);
    let ce = load_ce(&basic);
    let maps = load_maps();

    let a = extract(&dbs, ce.as_ref().map(|(_, c)| c), &maps);
    let b = extract(&dbs, ce.as_ref().map(|(_, c)| c), &maps);
    assert_eq!(a, b, "extraction must be byte-identical across runs");
    assert!(
        a.contains("\"kind\": \"names\""),
        "names glossary has the expected shape"
    );
    assert!(a.matches("\"source\"").count() > 0, "corpus yields names");
}

/// The disjoint-ownership invariant: every DB string cell is extracted by at most one path,
/// either db-strings (per-file content) or the glossary (per-cell name). On the real corpus, no
/// `(type, row, field)` locator may appear in both `extract_db_strings` and the glossary's
/// `extract_db_name_cells`.
#[test]
fn db_string_cells_have_disjoint_ownership() {
    let Some(basic) = corpus_basic() else {
        eprintln!("no corpus, skipping");
        return;
    };
    let dbs = load_dbs(&basic);
    assert!(!dbs.is_empty(), "corpus DBs must load");
    let g = glossary();
    let mut checked_cells = 0usize;
    for l in &dbs {
        // db-strings (content) cell locators.
        let content: HashSet<(usize, usize, usize)> = extract_db_strings(&l.db, &g)
            .iter()
            .flat_map(|grp| grp.lines.iter().map(|ln| (ln.type_id, ln.row, ln.field)))
            .collect();
        // glossary (name) cell locators.
        let names: HashSet<(usize, usize, usize)> =
            extract_db_name_cells(&l.db, &g).into_iter().collect();
        checked_cells += content.len() + names.len();
        let overlap: Vec<_> = content.intersection(&names).collect();
        assert!(
            overlap.is_empty(),
            "{}: {} DB cell(s) extracted by BOTH db-strings and the glossary: {:?}",
            l.stem,
            overlap.len(),
            overlap.into_iter().take(8).collect::<Vec<_>>()
        );
    }
    assert!(
        checked_cells > 0,
        "corpus must yield some DB cells to make the disjointness check meaningful"
    );
}
