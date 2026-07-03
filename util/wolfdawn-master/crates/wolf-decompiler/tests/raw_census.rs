//! Census of which commands still fall back to `@raw` (the lossy-pretty set to drive to zero),
//! across both games' common events and maps.
//!   cargo test -p wolf-decompiler --test raw_census -- --nocapture

use std::collections::BTreeMap;
use std::path::PathBuf;

use wolf_decompiler::{decompile_commands, spec};
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::map::Map;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
}

fn count(cmds: &[wolf_formats::command::RawCommand], hist: &mut BTreeMap<u32, usize>) {
    let text = decompile_commands(cmds);
    // Re-walk: a line is @raw for the command at that position. Simplest: re-render each
    // command alone is wrong (loses block ctx), so scan the produced lines and attribute
    // each @raw line to its cid (the cid is the first token after `@raw `).
    for line in text.lines() {
        let t = line.trim_start();
        if let Some(rest) = t.strip_prefix("@raw ") {
            if let Some(cid) = rest
                .split_whitespace()
                .next()
                .and_then(|s| s.parse::<u32>().ok())
            {
                *hist.entry(cid).or_default() += 1;
            }
        }
    }
}

#[test]
fn census() {
    let mut hist: BTreeMap<u32, usize> = BTreeMap::new();
    let mut total_cmds = 0usize;

    for game in ["Data", "GamePro_Data"] {
        let ce_path = root().join(game).join("BasicData").join("CommonEvent.dat");
        if let Ok(b) = std::fs::read(&ce_path) {
            let ce = CommonEventsFile::read(&b).unwrap();
            for ev in &ce.events {
                total_cmds += ev.commands.len();
                count(&ev.commands, &mut hist);
            }
        }
        let map_dir = root().join(game).join("MapData");
        if let Ok(entries) = std::fs::read_dir(&map_dir) {
            for e in entries {
                let p = e.unwrap().path();
                if p.extension().and_then(|s| s.to_str()) != Some("mps") {
                    continue;
                }
                let Ok(m) = Map::read(&std::fs::read(&p).unwrap()) else {
                    continue;
                };
                for ev in &m.events {
                    for pg in &ev.pages {
                        total_cmds += pg.commands.len();
                        count(&pg.commands, &mut hist);
                    }
                }
            }
        }
    }

    let total_raw: usize = hist.values().sum();
    eprintln!("total commands scanned: {total_cmds}");
    eprintln!("total @raw lines: {total_raw}");
    eprintln!("--- @raw by cid (cid name: count) ---");
    let mut by_count: Vec<_> = hist.into_iter().collect();
    by_count.sort_by_key(|(_, n)| std::cmp::Reverse(*n));
    for (cid, n) in by_count {
        eprintln!("  {cid:5} {:24} {n}", spec::command_name(cid));
    }

    // Every command must have a lossless pretty form. No `@raw` fallbacks in the corpus.
    assert_eq!(
        total_raw, 0,
        "every command must render without an @raw fallback"
    );
}
