//! Byte-exact round-trip gate over the local plaintext corpus.
//! For every sample file: `write(read(bytes)) == bytes`.

use std::path::PathBuf;

use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::database::Database;
use wolf_formats::map::Map;

/// `Wolf/Data`, three levels up from this crate (`Wolf/wolf-dawn/crates/wolf-formats`).
fn data_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
        .join("Data")
}

fn assert_byte_exact(name: &str, original: &[u8], rewritten: &[u8]) {
    if original == rewritten {
        return;
    }
    let first_diff = original
        .iter()
        .zip(rewritten.iter())
        .position(|(a, b)| a != b);
    panic!(
        "round-trip mismatch for {name}: original {} bytes, rewritten {} bytes, first differing offset = {:?}",
        original.len(),
        rewritten.len(),
        first_diff
    );
}

#[test]
fn maps_round_trip_byte_exact() {
    let dir = data_dir().join("MapData");
    let mut checked = 0;

    let entries =
        std::fs::read_dir(&dir).unwrap_or_else(|e| panic!("cannot read {}: {e}", dir.display()));

    for entry in entries {
        let path = entry.unwrap().path();
        if path.extension().and_then(|s| s.to_str()) != Some("mps") {
            continue;
        }
        let name = path.file_name().unwrap().to_string_lossy().into_owned();
        let original = std::fs::read(&path).unwrap();

        let map = Map::read(&original).unwrap_or_else(|e| panic!("failed to parse {name}: {e}"));
        let rewritten = map.write();

        assert_byte_exact(&name, &original, &rewritten);
        checked += 1;
    }

    assert!(checked > 0, "no .mps files found in {}", dir.display());
    eprintln!("round-tripped {checked} map(s) byte-exact");
}

#[test]
fn common_events_round_trip_byte_exact() {
    let path = data_dir().join("BasicData").join("CommonEvent.dat");
    let original =
        std::fs::read(&path).unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));

    let ce = CommonEventsFile::read(&original)
        .unwrap_or_else(|e| panic!("failed to parse CommonEvent.dat: {e}"));
    let rewritten = ce.write();

    assert_byte_exact("CommonEvent.dat", &original, &rewritten);
    eprintln!(
        "round-tripped CommonEvent.dat ({} events) byte-exact",
        ce.events.len()
    );
}

#[test]
fn databases_round_trip_byte_exact() {
    let dir = data_dir().join("BasicData");
    // (project, dat) pairs present in the sample game.
    let pairs = [
        ("DataBase.project", "DataBase.dat"),
        ("CDataBase.project", "CDataBase.dat"),
        ("SysDatabase.project", "SysDatabase.dat"),
    ];

    let mut checked = 0;
    for (proj, dat) in pairs {
        let proj_path = dir.join(proj);
        let dat_path = dir.join(dat);
        if !proj_path.exists() || !dat_path.exists() {
            continue;
        }
        let proj_bytes = std::fs::read(&proj_path).unwrap();
        let dat_bytes = std::fs::read(&dat_path).unwrap();

        let db = Database::read(&proj_bytes, &dat_bytes)
            .unwrap_or_else(|e| panic!("failed to parse {proj}/{dat}: {e}"));
        let (proj_out, dat_out) = db.write();

        assert_byte_exact(proj, &proj_bytes, &proj_out);
        assert_byte_exact(dat, &dat_bytes, &dat_out);
        eprintln!(
            "round-tripped {proj} + {dat} ({} types) byte-exact",
            db.types.len()
        );
        checked += 1;
    }
    assert!(checked > 0, "no database pairs found in {}", dir.display());
}
