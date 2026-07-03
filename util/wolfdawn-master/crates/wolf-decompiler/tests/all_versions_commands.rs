//! Cross-version command coverage: scan every Wolf version's CommonEvent + maps for command
//! ids not named in commands.json (rendered as `Cmd<cid>`), and per-version route-command ids.
//!   cargo test -p wolf-decompiler --test all_versions_commands -- --nocapture
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use wolf_decompiler::spec;
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::map::Map;

fn roots() -> Vec<PathBuf> {
    let base = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..");
    vec![
        base.join("ALLWOLFVERSIONS"),
        base.join("Data"),
        base.join("GamePro_Data"),
    ]
}

fn walk(dir: &Path, ext: &str, out: &mut Vec<PathBuf>) {
    let Ok(rd) = std::fs::read_dir(dir) else {
        return;
    };
    for e in rd.flatten() {
        let p = e.path();
        if p.is_dir() {
            walk(&p, ext, out);
        } else if p.file_name().and_then(|s| s.to_str()) == Some(ext)
            || p.extension().and_then(|s| s.to_str()) == Some(ext)
        {
            out.push(p);
        }
    }
}

#[test]
fn command_coverage_all_versions() {
    let mut unknown_cmd: BTreeMap<u32, usize> = BTreeMap::new();
    let mut unknown_route: BTreeMap<u32, usize> = BTreeMap::new();
    let mut all_cids: std::collections::BTreeSet<u32> = Default::default();
    let mut ce_files = 0;
    let mut map_files = 0;

    let mut consider = |cmds: &[wolf_formats::command::RawCommand],
                        uc: &mut BTreeMap<u32, usize>,
                        ur: &mut BTreeMap<u32, usize>,
                        all: &mut std::collections::BTreeSet<u32>| {
        for c in cmds {
            all.insert(c.cid);
            if spec::command(c.cid).is_none() {
                *uc.entry(c.cid).or_default() += 1;
            }
            if let Some(mr) = &c.move_route {
                for rc in &mr.commands {
                    if spec::route_name(rc.id as u32).starts_with("route") {
                        *ur.entry(rc.id as u32).or_default() += 1;
                    }
                }
            }
        }
    };

    for root in roots() {
        let mut ces = Vec::new();
        walk(&root, "CommonEvent.dat", &mut ces);
        for p in ces {
            let Ok(b) = std::fs::read(&p) else { continue };
            let Ok(ce) = CommonEventsFile::read(&b) else {
                continue;
            };
            ce_files += 1;
            for ev in &ce.events {
                consider(
                    &ev.commands,
                    &mut unknown_cmd,
                    &mut unknown_route,
                    &mut all_cids,
                );
            }
        }
        let mut maps = Vec::new();
        walk(&root, "mps", &mut maps);
        for p in maps {
            let Ok(b) = std::fs::read(&p) else { continue };
            let Ok(m) = Map::read(&b) else { continue };
            map_files += 1;
            for ev in &m.events {
                for pg in &ev.pages {
                    consider(
                        &pg.commands,
                        &mut unknown_cmd,
                        &mut unknown_route,
                        &mut all_cids,
                    );
                }
            }
        }
    }

    eprintln!(
        "scanned {ce_files} CommonEvent files + {map_files} maps; {} distinct command ids",
        all_cids.len()
    );
    eprintln!("all command ids seen: {:?}", all_cids);
    if unknown_cmd.is_empty() {
        eprintln!("UNNAMED command ids: NONE - every command across every version is named");
    } else {
        eprintln!("UNNAMED command ids (cid: count): {unknown_cmd:?}");
    }
    if unknown_route.is_empty() {
        eprintln!("UNNAMED route-command ids: NONE");
    } else {
        eprintln!("UNNAMED route-command ids: {unknown_route:?}");
    }
}
