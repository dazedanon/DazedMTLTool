//! End-to-end gate: unpack `Data.wolf` (the real DXArchive/Wolf v3.14 container) and prove
//! the extracted inner files are *complete, valid* Wolf files by parsing them and
//! round-tripping them byte-exact through `wolf-formats`. This proves the archive decode
//! (key + Huffman + LZSS) is byte-perfect even where the loose `Data/` is a different build.
//!   cargo test -p wolf-formats --test archive_end_to_end -- --nocapture

use std::path::PathBuf;

use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::database::Database;
use wolf_formats::map::Map;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
}

#[test]
fn data_wolf_inner_files_parse_and_roundtrip() {
    let Ok(bytes) = std::fs::read(root().join("Data.wolf")) else {
        eprintln!("Data.wolf not present, skipping");
        return;
    };
    let files = wolf_archive::extract_archive(&bytes, wolf_archive::DEFAULT_WOLF_PRO_KEY)
        .expect("decode Data.wolf");
    let get = |name: &str| -> Vec<u8> {
        files
            .iter()
            .find(|(p, _)| p.replace('\\', "/") == name)
            .unwrap_or_else(|| panic!("{name} not found in archive"))
            .1
            .clone()
    };

    // CommonEvent.dat: parse + byte-exact round-trip.
    let ce_bytes = get("BasicData/CommonEvent.dat");
    let ce = CommonEventsFile::read(&ce_bytes).expect("parse extracted CommonEvent.dat");
    assert_eq!(
        ce.write(),
        ce_bytes,
        "extracted CommonEvent.dat must round-trip byte-exact"
    );
    eprintln!(
        "CommonEvent.dat: {} events, {} bytes, round-trip OK",
        ce.events.len(),
        ce_bytes.len()
    );

    // Every map: parse + byte-exact round-trip.
    let mut maps = 0;
    for (path, data) in &files {
        if !path.to_ascii_lowercase().ends_with(".mps") {
            continue;
        }
        let m = Map::read(data).unwrap_or_else(|e| panic!("parse {path}: {e}"));
        assert_eq!(
            &m.write(),
            data,
            "extracted {path} must round-trip byte-exact"
        );
        maps += 1;
    }
    eprintln!("maps: {maps} parsed + round-tripped byte-exact");
    assert!(maps > 0, "expected maps in the archive");

    // The three databases: parse + byte-exact round-trip.
    for (proj, dat) in [
        ("BasicData/DataBase.project", "BasicData/DataBase.dat"),
        ("BasicData/CDataBase.project", "BasicData/CDataBase.dat"),
        ("BasicData/SysDatabase.project", "BasicData/SysDatabase.dat"),
    ] {
        let (pb, db_bytes) = (get(proj), get(dat));
        let db = Database::read(&pb, &db_bytes).unwrap_or_else(|e| panic!("parse {dat}: {e}"));
        let (po, dout) = db.write();
        assert_eq!(po, pb, "{proj} round-trip");
        assert_eq!(dout, db_bytes, "{dat} round-trip");
    }
    eprintln!("3 databases parsed + round-tripped byte-exact");
}
