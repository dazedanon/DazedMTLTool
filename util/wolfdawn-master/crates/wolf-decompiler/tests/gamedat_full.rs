//! Full Game.dat field editing (`dump_game_dat` / `apply_game_dat`): byte-exact no-op round-trip,
//! editing a scalar field, editing the Title (length change), and the `None`-optional omission
//! invariant. Uses an unpacked original Game.dat if present (the `WOLFDAWN_TEST_DATA` fixture first,
//! the corpus `Data/BasicData/Game.dat` as a fallback). Skips gracefully if neither is available.

use wolf_decompiler::{apply_game_dat, dump_game_dat};
use wolf_formats::game_dat::GameDat;

mod common;
use common::test_data;

/// Locate an unpacked original Game.dat: the fixtures copy first, then the workspace corpus.
fn fixture() -> Option<Vec<u8>> {
    let candidates = [
        test_data("chamber/Data/BasicData/Game.dat"),
        Some(
            std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../../Data/BasicData/Game.dat"),
        ),
    ];
    candidates
        .into_iter()
        .flatten()
        .find_map(|p| std::fs::read(&p).ok())
}

#[test]
fn dump_apply_write_is_byte_exact_noop() {
    let Some(bytes) = fixture() else {
        eprintln!("no Game.dat fixture, skipping");
        return;
    };
    let mut gd = GameDat::read(&bytes).expect("parse Game.dat");
    let json = dump_game_dat(&gd);
    // The dump is valid JSON.
    let _: serde_json::Value = serde_json::from_str(&json).expect("dump is valid JSON");
    // Applying the dump back onto the file changes nothing...
    let changed = apply_game_dat(&mut gd, &json).expect("apply dump");
    assert_eq!(changed, 0, "round-tripping the dump must change no fields");
    // ...and the write is byte-exact.
    assert!(
        gd.write() == bytes,
        "dump -> apply -> write must reproduce the file byte-exact"
    );
}

#[test]
fn edit_font_round_trips_and_leaves_other_fields_intact() {
    let Some(bytes) = fixture() else {
        return;
    };
    let original = GameDat::read(&bytes).expect("parse base");

    // Build an edit JSON from the dump, swapping only the Font.
    let dump = dump_game_dat(&original);
    let mut root: serde_json::Value = serde_json::from_str(&dump).unwrap();
    root["Font"] = serde_json::Value::String("TestFont".to_string());
    let edit = serde_json::to_string(&root).unwrap();

    let mut gd = GameDat::read(&bytes).unwrap();
    let changed = apply_game_dat(&mut gd, &edit).expect("apply edit");
    assert_eq!(changed, 1, "only the Font should change");

    let out = gd.write();
    let reread = GameDat::read(&out).expect("edited Game.dat must re-parse");

    // Font reads back as the new value.
    let reread_json: serde_json::Value =
        serde_json::from_str(&dump_game_dat(&reread)).unwrap();
    assert_eq!(reread_json["Font"], "TestFont", "Font must read the new text");

    // Every other field is byte-identical to the original struct.
    assert_eq!(reread.title, original.title, "title intact");
    assert_eq!(reread.title_plus, original.title_plus, "title_plus intact");
    assert_eq!(reread.sub_fonts, original.sub_fonts, "sub_fonts intact");
    assert_eq!(
        reread.default_pc_graphic, original.default_pc_graphic,
        "default_pc_graphic intact"
    );
    assert_eq!(reread.road_img, original.road_img, "road_img intact");
    assert_eq!(reread.gauge_img, original.gauge_img, "gauge_img intact");
    assert_eq!(reread.start_up_msg, original.start_up_msg, "start_up_msg intact");
    assert_eq!(reread.title_msg, original.title_msg, "title_msg intact");
    assert_eq!(
        reread.unknown_string14, original.unknown_string14,
        "unknown_string14 intact"
    );
    assert_eq!(reread.decrypt_key, original.decrypt_key, "decrypt key intact");
    assert_eq!(reread.magic_string, original.magic_string, "magic string intact");
    assert_eq!(
        reread.unknown_word_data, original.unknown_word_data,
        "word data intact"
    );
}

#[test]
fn edit_title_length_change_round_trips() {
    let Some(bytes) = fixture() else {
        return;
    };
    let original = GameDat::read(&bytes).unwrap();
    let old_title = {
        let d: serde_json::Value = serde_json::from_str(&dump_game_dat(&original)).unwrap();
        d["Title"].as_str().unwrap().to_string()
    };

    // A new title of a clearly different length, to exercise the housekeeping-offset shift.
    let new_title = format!("{old_title} -- WolfDawn Full Edit Demo");
    assert_ne!(new_title.len(), old_title.len(), "fixture sanity: length differs");

    let mut root: serde_json::Value = serde_json::from_str(&dump_game_dat(&original)).unwrap();
    root["Title"] = serde_json::Value::String(new_title.clone());
    let edit = serde_json::to_string(&root).unwrap();

    let mut gd = GameDat::read(&bytes).unwrap();
    let changed = apply_game_dat(&mut gd, &edit).expect("apply title edit");
    assert_eq!(changed, 1, "only the Title should change");

    let out = gd.write();
    // The file must re-parse cleanly despite the length change (offsets shifted correctly).
    let reread = GameDat::read(&out).expect("re-parse after length-changing Title edit");
    let reread_title = {
        let d: serde_json::Value = serde_json::from_str(&dump_game_dat(&reread)).unwrap();
        d["Title"].as_str().unwrap().to_string()
    };
    assert_eq!(reread_title, new_title, "Title must read the new (longer) text");
    // Non-title fields still intact.
    assert_eq!(reread.font, original.font, "font intact after title resize");
    assert_eq!(
        reread.default_pc_graphic, original.default_pc_graphic,
        "graphic intact after title resize"
    );
}

#[test]
fn dump_omits_none_optionals_and_includes_present() {
    let Some(bytes) = fixture() else {
        return;
    };
    let gd = GameDat::read(&bytes).unwrap();
    let json = dump_game_dat(&gd);
    let root: serde_json::Value = serde_json::from_str(&json).unwrap();
    let obj = root.as_object().unwrap();

    // Fixed scalars, the array, and the encoding marker are always present.
    assert!(obj.contains_key("encoding"), "encoding marker present");
    assert!(obj.contains_key("Title"), "Title always present");
    assert!(obj.contains_key("Font"), "Font always present");
    assert!(obj.contains_key("DefaultPcGraphic"), "graphic always present");
    assert!(root["SubFonts"].is_array(), "SubFonts is an array");
    assert_eq!(
        root["SubFonts"].as_array().unwrap().len(),
        gd.sub_fonts.len(),
        "SubFonts array length matches the struct"
    );

    // Each optional key appears in the JSON iff the struct cell is Some.
    let checks: [(&str, bool); 6] = [
        ("TitlePlus", gd.title_plus.is_some()),
        ("RoadImg", gd.road_img.is_some()),
        ("GaugeImg", gd.gauge_img.is_some()),
        ("StartUpMsg", gd.start_up_msg.is_some()),
        ("TitleMsg", gd.title_msg.is_some()),
        ("UnknownString14", gd.unknown_string14.is_some()),
    ];
    for (key, present) in checks {
        assert_eq!(
            obj.contains_key(key),
            present,
            "`{key}` key presence must match the optional cell"
        );
    }

    // The read-only encoding marker must match the file.
    assert_eq!(
        root["encoding"].as_str().unwrap(),
        if gd.utf8 { "utf8" } else { "shiftjis" }
    );
}
