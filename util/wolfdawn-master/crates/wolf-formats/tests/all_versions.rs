//! Cross-version format coverage: round-trip every Wolf editor version's loose Data/ files
//! (CommonEvent, maps, databases) byte-exact. Reveals decoder version gaps.
//!   cargo test -p wolf-formats --test all_versions -- --nocapture
use std::path::{Path, PathBuf};

use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::database::Database;
use wolf_formats::map::Map;

fn versions_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
        .join("ALLWOLFVERSIONS")
}

fn find(dir: &Path, name: &str) -> Option<PathBuf> {
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else {
            continue;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.file_name().and_then(|s| s.to_str()) == Some(name) {
                return Some(p);
            }
        }
    }
    None
}

fn find_all_mps(dir: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else {
            continue;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.extension().and_then(|s| s.to_str()) == Some("mps") {
                out.push(p);
            }
        }
    }
    out
}

#[test]
fn all_wolf_versions_round_trip() {
    let root = versions_root();
    let Ok(dirs) = std::fs::read_dir(&root) else {
        eprintln!("no ALLWOLFVERSIONS");
        return;
    };
    let mut editors: Vec<PathBuf> = dirs
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.is_dir())
        .collect();
    editors.sort();

    let mut total_ok = 0;
    let mut total_fail = 0;
    for ed in &editors {
        let name = ed.file_name().unwrap().to_string_lossy().into_owned();
        let mut ok = 0;
        let mut fails: Vec<String> = Vec::new();

        // CommonEvent.dat
        if let Some(p) = find(ed, "CommonEvent.dat") {
            match std::fs::read(&p)
                .map(|b| (CommonEventsFile::read(&b).map(|ce| ce.write() == b), b))
            {
                Ok((Ok(true), _)) => ok += 1,
                Ok((Ok(false), _)) => fails.push("CommonEvent:diff".into()),
                Ok((Err(e), b)) => fails.push(format!(
                    "CommonEvent:ERR(v{:#x}):{}",
                    b.get(10).copied().unwrap_or(0),
                    short(&e.to_string())
                )),
                _ => {}
            }
        }
        // Maps
        let mut map_ok = 0;
        let mut map_fail = 0;
        for mp in find_all_mps(ed) {
            let Ok(b) = std::fs::read(&mp) else { continue };
            match Map::read(&b) {
                Ok(m) if m.write() == b => map_ok += 1,
                Ok(_) => map_fail += 1,
                Err(_) => map_fail += 1,
            }
        }
        if map_fail == 0 && map_ok > 0 {
            ok += 1;
        } else if map_fail > 0 {
            fails.push(format!("maps:{map_ok}ok/{map_fail}fail"));
        }
        // Databases (name varies: SysDatabase vs SysDataBaseBasic)
        for (proj, dat) in db_candidates(ed) {
            let (Ok(pb), Ok(db)) = (std::fs::read(&proj), std::fs::read(&dat)) else {
                continue;
            };
            match Database::read(&pb, &db) {
                Ok(d) => {
                    let (po, dd) = d.write();
                    if po == pb && dd == db {
                        ok += 1;
                    } else {
                        fails.push(format!("{}:diff", stem(&dat)));
                    }
                }
                Err(e) => fails.push(format!("{}:ERR:{}", stem(&dat), short(&e.to_string()))),
            }
        }

        if fails.is_empty() {
            total_ok += 1;
            eprintln!("  OK   {name}  ({ok} file-groups)");
        } else {
            total_fail += 1;
            eprintln!("  FAIL {name}  ok={ok}  -> {}", fails.join(", "));
        }
    }
    let total = total_ok + total_fail;
    eprintln!(
        "\nversions fully round-tripping (excl. legacy v2 SysDataBaseBasic): {total_ok}/{total}"
    );
    if total > 0 {
        assert_eq!(
            total_fail, 0,
            "some Wolf version's core data did not round-trip byte-exact"
        );
    }
}

/// The standard databases. The legacy v2 `SysDataBaseBasic` is a different pre-v3 format
/// (no `OLUFM` magic) and is intentionally excluded. This is a documented known gap.
fn db_candidates(ed: &Path) -> Vec<(PathBuf, PathBuf)> {
    let mut out = Vec::new();
    for stem in ["DataBase", "CDataBase", "SysDatabase"] {
        if let Some(proj) = find(ed, &format!("{stem}.project")) {
            let dat = proj.with_extension("dat");
            if dat.exists() {
                out.push((proj, dat));
            }
        }
    }
    out
}

fn stem(p: &Path) -> String {
    p.file_stem().unwrap().to_string_lossy().into_owned()
}
fn short(s: &str) -> String {
    s.chars().take(40).collect()
}
