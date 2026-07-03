//! Game.dat support: byte-exact round-trip, Title extraction, and translated-Title inject.
//! Uses the corpus `Data/BasicData/Game.dat`. Skips gracefully if it is absent.

use wolf_decompiler::{extract_game_dat, inject_game_dat, InjectOptions};
use wolf_formats::game_dat::GameDat;

fn corpus_game_dat() -> Option<Vec<u8>> {
    let path =
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../Data/BasicData/Game.dat");
    std::fs::read(&path).ok()
}

#[test]
fn read_write_is_byte_exact() {
    let Some(bytes) = corpus_game_dat() else {
        eprintln!("no corpus Game.dat, skipping");
        return;
    };
    let gd = GameDat::read(&bytes).expect("parse Game.dat");
    assert!(
        gd.write() == bytes,
        "Game.dat round-trip must be byte-exact for an unmodified file"
    );
}

#[test]
fn extract_yields_nonempty_title() {
    let Some(bytes) = corpus_game_dat() else {
        return;
    };
    let gd = GameDat::read(&bytes).unwrap();
    let json = extract_game_dat(&gd);
    let root: serde_json::Value = serde_json::from_str(&json).unwrap();
    let title = root["lines"]
        .as_array()
        .unwrap()
        .iter()
        .find(|l| l["key"] == "Title")
        .expect("a Title line");
    assert!(
        !title["source"].as_str().unwrap_or("").is_empty(),
        "extracted Title must be non-empty"
    );
}

#[test]
fn inject_translated_title_persists_and_reparses() {
    let Some(bytes) = corpus_game_dat() else {
        return;
    };
    let gd = GameDat::read(&bytes).unwrap();
    let title_src = {
        let json = extract_game_dat(&gd);
        let root: serde_json::Value = serde_json::from_str(&json).unwrap();
        root["lines"]
            .as_array()
            .unwrap()
            .iter()
            .find(|l| l["key"] == "Title")
            .unwrap()["source"]
            .as_str()
            .unwrap()
            .to_string()
    };

    // No-op inject (text == source) must leave the file byte-identical.
    let edit_noop = format!(
        r#"{{ "lines": [ {{ "key": "Title", "source": {0}, "text": {0} }} ] }}"#,
        serde_json::Value::String(title_src.clone())
    );
    let mut gd_noop = GameDat::read(&bytes).unwrap();
    let st = inject_game_dat(&edit_noop, &mut gd_noop, &InjectOptions::default()).expect("inject");
    assert_eq!(st.applied, 0);
    assert_eq!(st.drifted, 0);
    assert!(
        gd_noop.write() == bytes,
        "no-op Game.dat inject must be byte-identical"
    );

    // Translate the Title and confirm it persists, the file re-parses, and other fields are intact.
    let edit = format!(
        r#"{{ "lines": [ {{ "key": "Title", "source": {}, "text": "WolfDawn Title" }} ] }}"#,
        serde_json::Value::String(title_src.clone())
    );
    let mut gd2 = GameDat::read(&bytes).unwrap();
    let st = inject_game_dat(&edit, &mut gd2, &InjectOptions::default()).expect("inject");
    assert_eq!(st.applied, 1, "the Title should translate");

    let out = gd2.write();
    let gd3 = GameDat::read(&out).expect("injected Game.dat must re-parse");
    let json3 = extract_game_dat(&gd3);
    let root3: serde_json::Value = serde_json::from_str(&json3).unwrap();
    let new_title = root3["lines"]
        .as_array()
        .unwrap()
        .iter()
        .find(|l| l["key"] == "Title")
        .unwrap()["source"]
        .as_str()
        .unwrap();
    assert_eq!(new_title, "WolfDawn Title", "Title must read the new text");

    // Other non-title fields are untouched. The decrypt key, font, and the housekeeping
    // word-data carry over verbatim.
    assert_eq!(gd3.decrypt_key, gd.decrypt_key, "decrypt key intact");
    assert_eq!(gd3.font, gd.font, "font intact");
    assert_eq!(
        gd3.unknown_word_data, gd.unknown_word_data,
        "word data intact"
    );
}
