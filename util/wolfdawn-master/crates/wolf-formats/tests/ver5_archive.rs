//! Verify the DXArchive VER5 decoder against the real Wolf 2.01 sample-game Data.wolf:
//! extracted inner files must parse + round-trip byte-exact through wolf-formats.
//!   cargo test -p wolf-formats --test ver5_archive -- --nocapture
use std::path::{Path, PathBuf};

use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::map::Map;

fn find_wolf(dir: &Path) -> Option<PathBuf> {
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else {
            continue;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.extension().and_then(|s| s.to_str()) == Some("wolf") {
                return Some(p);
            }
        }
    }
    None
}

#[test]
fn ver5_ver6_archives_parse() {
    // VER5 = Wolf 2.01, VER6 = Wolf 2.20.
    for editor in ["WolfRPGEditor_201", "WolfRPGEditor_220"] {
        let base = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("..")
            .join("ALLWOLFVERSIONS")
            .join(editor);
        let Some(arc) = find_wolf(&base) else {
            eprintln!("{editor}: no Data.wolf, skipping");
            continue;
        };
        let data = std::fs::read(&arc).expect("read Data.wolf");
        let files = wolf_archive::extract_archive(&data, wolf_archive::DEFAULT_WOLF_PRO_KEY)
            .unwrap_or_else(|e| panic!("{editor}: archive decode failed: {e}"));
        eprintln!("{editor}: extracted {} files", files.len());
        assert!(files.len() > 100, "{editor}: expected a populated archive");

        // CommonEvent.dat was LZ-compressed: parse + round-trip proves keycode-LZSS + key decode.
        let ce = files
            .iter()
            .find(|(p, _)| p.replace('\\', "/").ends_with("BasicData/CommonEvent.dat"))
            .unwrap_or_else(|| panic!("{editor}: CommonEvent.dat not in archive"));
        let parsed = CommonEventsFile::read(&ce.1)
            .unwrap_or_else(|e| panic!("{editor}: parse CommonEvent: {e}"));
        assert_eq!(parsed.write(), ce.1, "{editor}: CommonEvent.dat round-trip");
        eprintln!(
            "  CommonEvent.dat: {} events, {} bytes, round-trip OK",
            parsed.events.len(),
            ce.1.len()
        );

        let mut maps = 0;
        for (p, b) in &files {
            if !p.to_ascii_lowercase().ends_with(".mps") {
                continue;
            }
            let m = Map::read(b).unwrap_or_else(|e| panic!("{editor}: parse {p}: {e}"));
            assert_eq!(&m.write(), b, "{editor}: map {p} round-trip");
            maps += 1;
        }
        eprintln!("  maps round-tripped byte-exact: {maps}");
        assert!(maps > 0, "{editor}: expected maps");
    }
}
