//! DB to JSON export sanity gate: valid, balanced, faithful JSON for a real database.
use wolf_decompiler::database_to_json;
use wolf_formats::database::Database;

#[test]
fn exports_valid_json_for_corpus_db() {
    let base = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../Data/BasicData");
    let (proj, dat) = (base.join("DataBase.project"), base.join("DataBase.dat"));
    let (Ok(p), Ok(d)) = (std::fs::read(&proj), std::fs::read(&dat)) else {
        eprintln!("no corpus DataBase, skipping");
        return;
    };
    let db = Database::read(&p, &d).expect("parse db");
    let glossary = wolf_decompiler::symbols::load_embedded_engine_glossary();
    let json = database_to_json(&db, "UDB", &glossary);
    // Bilingual lookup: structural names the glossary covers carry a `name_en`, so a modder
    // reading the English code can find the entry. Absent for player-facing content.
    assert!(
        json.contains("\"name_en\":"),
        "expected at least one English name_en in the UDB export"
    );

    // Structurally valid: starts and ends as an object, braces and brackets balanced, key fields present.
    assert!(json.trim_start().starts_with('{') && json.trim_end().ends_with('}'));
    assert!(json.contains("\"kind\": \"UDB\""));
    assert!(json.contains("\"types\"") && json.contains("\"rows\""));
    let bal = |o: char, c: char| {
        let mut depth = 0i64;
        let mut in_str = false;
        let mut esc = false;
        for ch in json.chars() {
            if esc {
                esc = false;
                continue;
            }
            match ch {
                '\\' if in_str => esc = true,
                '"' => in_str = !in_str,
                x if x == o && !in_str => depth += 1,
                x if x == c && !in_str => depth -= 1,
                _ => {}
            }
        }
        depth
    };
    assert_eq!(bal('{', '}'), 0, "unbalanced braces");
    assert_eq!(bal('[', ']'), 0, "unbalanced brackets");
    eprintln!("UDB JSON: {} bytes, {} types", json.len(), db.types.len());
}
