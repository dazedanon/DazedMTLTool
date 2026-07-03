//! Cross-version recompiler gate: for every Wolf editor version's CommonEvent.dat, prove
//! compile(decompile(cmds)) == cmds for every common event.
//!   cargo test -p wolf-decompiler --test all_versions_recompile -- --nocapture
use std::path::{Path, PathBuf};

use wolf_decompiler::{compile_commands, decompile_commands};
use wolf_formats::common_event::CommonEventsFile;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
        .join("ALLWOLFVERSIONS")
}

fn find_ce(dir: &Path) -> Option<PathBuf> {
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else {
            continue;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.file_name().and_then(|s| s.to_str()) == Some("CommonEvent.dat") {
                return Some(p);
            }
        }
    }
    None
}

#[test]
fn recompile_all_versions() {
    let Ok(dirs) = std::fs::read_dir(root()) else {
        eprintln!("no ALLWOLFVERSIONS");
        return;
    };
    let mut editors: Vec<PathBuf> = dirs
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.is_dir())
        .collect();
    editors.sort();

    let mut versions_ok = 0;
    let mut versions_total = 0;
    for ed in &editors {
        let name = ed.file_name().unwrap().to_string_lossy().into_owned();
        let Some(p) = find_ce(ed) else { continue };
        let Ok(bytes) = std::fs::read(&p) else {
            continue;
        };
        let Ok(ce) = CommonEventsFile::read(&bytes) else {
            eprintln!("  {name}: CommonEvent parse failed");
            continue;
        };
        versions_total += 1;

        let mut ok = 0;
        let total = ce.events.len();
        let mut first_fail = String::new();
        for ev in &ce.events {
            let text = decompile_commands(&ev.commands);
            match compile_commands(&text) {
                Ok(back) if back == ev.commands => ok += 1,
                Ok(_) if first_fail.is_empty() => {
                    first_fail = format!("event {} mismatch", ev.int_id)
                }
                Err(e) if first_fail.is_empty() => {
                    first_fail = format!("event {} err: {}", ev.int_id, e)
                }
                _ => {}
            }
        }
        if ok == total {
            versions_ok += 1;
            eprintln!("  OK   {name:22} v=0x{:02x}  {ok}/{total}", ce.version);
        } else {
            eprintln!(
                "  FAIL {name:22} v=0x{:02x}  {ok}/{total}  ({first_fail})",
                ce.version
            );
        }
    }
    eprintln!("\nversions fully recompiling: {versions_ok}/{versions_total}");
    if versions_total > 0 {
        assert_eq!(
            versions_ok, versions_total,
            "some version's common events did not recompile byte-exact"
        );
    }
}
