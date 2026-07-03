//! DB value-edit round-trip. Applying the export unchanged is byte-identical to the base. Editing
//! a single int and a single string changes only those cells and reloads correctly.
use wolf_decompiler::{apply_database_edit, database_to_json};
use wolf_formats::database::Database;

fn load() -> Option<(Vec<u8>, Vec<u8>, Database)> {
    let base = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../Data/BasicData");
    let (proj, dat) = (base.join("DataBase.project"), base.join("DataBase.dat"));
    let (Ok(p), Ok(d)) = (std::fs::read(&proj), std::fs::read(&dat)) else {
        eprintln!("no corpus DataBase, skipping");
        return None;
    };
    let db = Database::read(&p, &d).expect("parse db");
    Some((p, d, db))
}

#[test]
fn noop_apply_is_byte_identical() {
    let Some((p, d, db)) = load() else { return };
    let glossary = wolf_decompiler::symbols::load_embedded_engine_glossary();
    let json = database_to_json(&db, "UDB", &glossary);

    let mut db2 = Database::read(&p, &d).unwrap();
    let changed = apply_database_edit(&json, &mut db2).expect("apply");
    assert_eq!(
        changed, 0,
        "round-tripping the export unchanged must change nothing"
    );
    let (p2, d2) = db2.write();
    assert!(
        p2 == p && d2 == d,
        "no-op apply must be byte-identical to base"
    );
}

#[test]
fn edit_one_int_and_one_string_roundtrips() {
    let Some((p, d, db)) = load() else { return };

    // Pick a type with rows, and (via the shared key derivation) an int and a string slot.
    let (ti, int_key, int_slot, str_key, str_slot) = db
        .types
        .iter()
        .enumerate()
        .find_map(|(ti, t)| {
            if t.data.is_empty() {
                return None;
            }
            let fs = (t.dat_fields_size as usize).min(t.fields.len());
            let slots = wolf_decompiler::json::value_slots(t, fs, db.utf8);
            let ik = slots.iter().find(|(_, is_str, _)| !is_str)?;
            let sk = slots.iter().find(|(_, is_str, _)| *is_str)?;
            Some((ti, ik.0.clone(), ik.2, sk.0.clone(), sk.2))
        })
        .expect("a type with int+string slots and rows");

    let edit = format!(
        r#"{{ "types": [ {{ "id": {ti}, "rows": [ {{ "id": 0, "values": {{ {ik}: 31337, {sk}: "WOLFDAWN_EDIT" }} }} ] }} ] }}"#,
        ik = serde_json::Value::String(int_key),
        sk = serde_json::Value::String(str_key),
    );

    let mut db2 = Database::read(&p, &d).unwrap();
    let changed = apply_database_edit(&edit, &mut db2).expect("apply");
    assert!(changed >= 1, "expected at least one changed cell");
    let (p2, d2) = db2.write();

    let db3 = Database::read(&p2, &d2).expect("re-read edited");
    let t3 = &db3.types[ti];
    assert_eq!(
        t3.data[0].int_values[int_slot], 31337,
        "int edit must persist"
    );
    assert_eq!(
        wolf_decompiler::text::decode_wstr(&t3.data[0].string_values[str_slot], db3.utf8),
        "WOLFDAWN_EDIT",
        "string edit must persist"
    );
    assert_eq!(
        p2, p,
        ".project must be unchanged when only .dat values are edited"
    );
}
