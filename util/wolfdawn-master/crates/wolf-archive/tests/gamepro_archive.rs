//! New wolf-crypt (v3.31) decode against the real GameProData.wolf (1.26 GB).
//!   WOLF_GOLDEN=1 cargo test -p wolf-archive --test gamepro_archive -- --nocapture
use std::path::PathBuf;

#[test]
fn gamepro_archive_decodes() {
    if std::env::var_os("WOLF_GOLDEN").is_none() {
        eprintln!("set WOLF_GOLDEN=1 to run the (heavy) GameProData.wolf test");
        return;
    }
    let p = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
        .join("GameProData.wolf");
    let Ok(data) = std::fs::read(&p) else {
        eprintln!("no GameProData.wolf");
        return;
    };
    eprintln!("read {} bytes", data.len());

    let paths = wolf_archive::list_archive(&data, wolf_archive::DEFAULT_WOLF_PRO_KEY)
        .expect("new-crypt (v3.31) table decode");
    eprintln!("new-crypt table decode OK: {} files", paths.len());
    assert!(paths.len() > 1000, "expected a populated Pro archive");

    // The loose GamePro_Data/ tree is this archive's extraction. Verify a sample of files
    // are byte-identical (proves the new wolf-crypt decode is byte-perfect).
    let loose = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
        .join("GamePro_Data");
    let samples = [
        "BasicData\\CommonEvent.dat",
        "BasicData\\DataBase.dat",
        "BasicData\\CDataBase.dat",
        "BasicData\\SysDatabase.dat",
        "BasicData\\Game.dat",
        "BasicData\\TileSetData.dat",
        "MapData\\Map001.mps",
    ];
    let mut checked = 0;
    for s in samples {
        let Some(ext) = wolf_archive::extract_one(&data, wolf_archive::DEFAULT_WOLF_PRO_KEY, s)
            .expect("extract")
        else {
            continue;
        };
        let Ok(disk) = std::fs::read(loose.join(s.replace('\\', "/"))) else {
            continue;
        };
        assert_eq!(
            ext, disk,
            "{s} must extract byte-identical to loose GamePro_Data"
        );
        eprintln!("  byte-exact: {s} ({} bytes)", ext.len());
        checked += 1;
    }
    assert!(checked > 0, "no sample files compared");
}
