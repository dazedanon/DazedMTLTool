//! Probe that reports and never asserts. Runs the decompiler and recompiler against the Wolf-Pro
//! game's 1300 v3.5 common events and maps. Reports (1) byte-exact recompile coverage, (2) any
//! command ids missing from the spec, and (3) how readable the output is (pretty vs @raw
//! fallback), driven by the per-command v3.5 trailing blob.
//!   cargo test -p wolf-decompiler --test gamepro_decompile -- --nocapture

use std::collections::BTreeMap;
use std::path::PathBuf;

use wolf_decompiler::{compile_commands, decompile_commands, spec};
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::map::Map;

fn pro() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
        .join("GamePro_Data")
}

#[test]
fn recompile_pro_common_events() {
    let p = pro().join("BasicData").join("CommonEvent.dat");
    let Ok(bytes) = std::fs::read(&p) else {
        eprintln!("missing {}", p.display());
        return;
    };
    let ce = CommonEventsFile::read(&bytes).expect("parse Pro CommonEvent.dat");
    eprintln!(
        "Pro CommonEvent.dat: v35={} events={}",
        ce.v35,
        ce.events.len()
    );

    let mut ok = 0usize;
    let mut fail = 0usize;
    let mut unknown_cids: BTreeMap<u32, usize> = BTreeMap::new();
    let mut blob_sizes: BTreeMap<usize, usize> = BTreeMap::new();
    let mut pretty_lines = 0usize;
    let mut raw_lines = 0usize;
    let mut failures: Vec<(u32, String)> = Vec::new();

    for ev in &ce.events {
        for c in &ev.commands {
            if spec::command(c.cid).is_none() {
                *unknown_cids.entry(c.cid).or_default() += 1;
            }
            let bl = c.v35_blob.as_ref().map(|b| b.len()).unwrap_or(usize::MAX);
            if bl != usize::MAX {
                *blob_sizes.entry(bl).or_default() += 1;
            }
        }

        let text = decompile_commands(&ev.commands);
        for line in text.lines() {
            let t = line.trim_start();
            if t.is_empty() {
                continue;
            }
            if t.starts_with("@raw ") {
                raw_lines += 1;
            } else {
                pretty_lines += 1;
            }
        }

        match compile_commands(&text) {
            Ok(back) if back == ev.commands => ok += 1,
            Ok(back) => {
                fail += 1;
                let idx = back.iter().zip(&ev.commands).position(|(a, b)| a != b);
                let detail = match idx {
                    Some(i) => format!(
                        "cmd#{i} cid{}: orig {:?} vs back {:?}",
                        ev.commands[i].cid, ev.commands[i], back[i]
                    ),
                    None => format!("length {} vs {}", back.len(), ev.commands.len()),
                };
                failures.push((ev.int_id, detail));
            }
            Err(e) => {
                fail += 1;
                failures.push((ev.int_id, format!("compile error: {e}")));
            }
        }
    }

    eprintln!(
        "recompile byte-exact: {ok}/{} (fail {fail})",
        ce.events.len()
    );
    eprintln!("readability: pretty lines={pretty_lines}  @raw lines={raw_lines}");
    eprintln!("v35 blob size distribution (size: count): {blob_sizes:?}");
    if unknown_cids.is_empty() {
        eprintln!("unknown command ids: NONE - every cid is in the spec");
    } else {
        eprintln!("unknown command ids (cid: occurrences): {unknown_cids:?}");
    }
    eprintln!("--- all {} failures ---", failures.len());
    for (id, detail) in &failures {
        eprintln!("  event {id}: {detail}");
    }

    // Dump a couple of examples of each unknown command id, with arg shape, to identify them.
    for &cid in &[242u32, 252, 260] {
        let mut shown = 0;
        for ev in &ce.events {
            for c in &ev.commands {
                if c.cid == cid && shown < 3 {
                    eprintln!(
                        "  ex cid{cid}: ints={:?} strs={:?}",
                        c.int_args,
                        c.str_args
                            .iter()
                            .map(|s| String::from_utf8_lossy(s.as_bytes())
                                .trim_end_matches('\0')
                                .to_string())
                            .collect::<Vec<_>>()
                    );
                    shown += 1;
                }
            }
        }
    }

    assert_eq!(
        ok,
        ce.events.len(),
        "all Pro common events must recompile byte-exact"
    );
}

#[test]
fn scan_pro_map_commands() {
    let dir = pro().join("MapData");
    let Ok(entries) = std::fs::read_dir(&dir) else {
        return;
    };
    let mut unknown: BTreeMap<u32, usize> = BTreeMap::new();
    let mut cmds = 0usize;
    let mut maps = 0usize;
    for e in entries {
        let path = e.unwrap().path();
        if path.extension().and_then(|s| s.to_str()) != Some("mps") {
            continue;
        }
        let bytes = std::fs::read(&path).unwrap();
        let Ok(m) = Map::read(&bytes) else { continue };
        maps += 1;
        for ev in &m.events {
            for pg in &ev.pages {
                for c in &pg.commands {
                    cmds += 1;
                    if spec::command(c.cid).is_none() {
                        *unknown.entry(c.cid).or_default() += 1;
                    }
                }
            }
        }
    }
    eprintln!("Pro maps scanned: {maps}, commands: {cmds}");
    if unknown.is_empty() {
        eprintln!("unknown map command ids: NONE");
    } else {
        eprintln!("unknown map command ids: {unknown:?}");
    }
}
