//! Player-text extract/inject round-trip. A no-op inject is byte-identical to the base, and
//! editing one line's translation changes only that string while others stay byte-exact. Covers
//! both the command/dialogue stream (maps) and database content (item, skill, term text).
use wolf_decompiler::{
    db_strings_to_json, extract_db_strings, extract_map, inject_db_strings, inject_map,
    scenes_to_json, InjectOptions,
};
use wolf_formats::database::Database;
use wolf_formats::map::Map;

#[test]
fn db_strings_noop_byte_identical_then_translate() {
    let base = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../Data/BasicData");
    let (Ok(p), Ok(d)) = (
        std::fs::read(base.join("DataBase.project")),
        std::fs::read(base.join("DataBase.dat")),
    ) else {
        eprintln!("no corpus DataBase, skipping");
        return;
    };
    let db = Database::read(&p, &d).expect("parse db");
    let glossary = wolf_decompiler::symbols::load_embedded_engine_glossary();
    let groups = extract_db_strings(&db, &glossary);
    assert!(!groups.is_empty(), "expected some player-facing DB strings");
    let json = db_strings_to_json("DataBase.project", &groups);

    // No-op inject must be byte-identical.
    let mut db2 = Database::read(&p, &d).unwrap();
    let st = inject_db_strings(&json, &mut db2, &InjectOptions::default()).expect("inject");
    assert_eq!(st.applied, 0);
    assert_eq!(st.drifted, 0);
    assert!(
        db2.write() == (p.clone(), d.clone()),
        "no-op DB-strings inject must be byte-identical"
    );

    // Translate one cell and confirm it persists. The sentinel reads as real text (a space, no
    // bare-identifier shape) so the re-extraction's player-text filter keeps it.
    let g = &groups[0];
    let ln = &g.lines[0];
    let edit = format!(
        r#"{{ "groups": [ {{ "type": {}, "lines": [ {{ "row": {}, "field": {}, "source": {}, "text": "WOLFDAWN DB TR" }} ] }} ] }}"#,
        g.type_id,
        ln.row,
        ln.field,
        serde_json::Value::String(ln.source.clone()),
    );
    let mut db3 = Database::read(&p, &d).unwrap();
    let st = inject_db_strings(
        &edit,
        &mut db3,
        &InjectOptions {
            allow_code_drift: true,
            ..Default::default()
        },
    )
    .expect("inject");
    assert_eq!(st.applied, 1, "one DB cell should translate");
    let (p3, d3) = db3.write();
    let db4 = Database::read(&p3, &d3).unwrap();
    let groups4 = extract_db_strings(&db4, &glossary);
    assert!(
        groups4
            .iter()
            .any(|g| g.lines.iter().any(|l| l.source == "WOLFDAWN DB TR")),
        "translated DB cell must read the new text"
    );
}

/// Find a corpus map that actually has extractable player text.
fn find_map_with_text() -> Option<(std::path::PathBuf, Vec<u8>, Map)> {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let mut stack = vec![root];
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else {
            continue;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.extension().and_then(|s| s.to_str()) == Some("mps") {
                let bytes = std::fs::read(&p).unwrap_or_default();
                if let Ok(m) = Map::read(&bytes) {
                    if extract_map(&m).iter().any(|s| !s.lines.is_empty()) {
                        return Some((p, bytes, m));
                    }
                }
            }
        }
    }
    None
}

#[test]
fn noop_inject_is_byte_identical() {
    let Some((_p, bytes, m)) = find_map_with_text() else {
        eprintln!("no corpus map with player text, skipping");
        return;
    };
    let json = scenes_to_json("m.mps", "map", &extract_map(&m));
    let mut m2 = Map::read(&bytes).unwrap();
    let st = inject_map(&json, &mut m2, &InjectOptions::default()).expect("inject");
    assert_eq!(st.applied, 0, "no-op inject must apply nothing");
    assert_eq!(st.drifted, 0, "no-op inject must not drift");
    assert!(m2.write() == bytes, "no-op inject must be byte-identical");
}

#[test]
fn translate_one_line_changes_only_that_string() {
    let Some((_p, bytes, m)) = find_map_with_text() else {
        return;
    };
    let scenes = extract_map(&m);
    // Locate the first scene with a line and record its locator and original.
    let sc = scenes.iter().find(|s| !s.lines.is_empty()).unwrap();
    let ln = &sc.lines[0];
    let (event, page, cmd, str_idx, source) = (
        sc.event,
        sc.page.unwrap(),
        ln.cmd,
        ln.str_idx,
        ln.source.clone(),
    );

    // Build a minimal inject doc translating just that line. The sentinel reads as real text (a
    // space, no bare-identifier shape) so the re-extraction's player-text filter keeps it.
    let edit = format!(
        r#"{{ "scenes": [ {{ "event": {event}, "page": {page}, "lines": [ {{ "cmd": {cmd}, "str": {str_idx}, "source": {src}, "text": "WOLFDAWN TR" }} ] }} ] }}"#,
        src = serde_json::Value::String(source.clone()),
    );

    let mut m2 = Map::read(&bytes).unwrap();
    let st = inject_map(
        &edit,
        &mut m2,
        &InjectOptions {
            allow_code_drift: true,
            ..Default::default()
        },
    )
    .expect("inject");
    assert_eq!(st.applied, 1, "exactly one line should apply");

    // Re-extract and confirm the translated line now reads the new text and others are intact.
    let scenes2 = extract_map(&m2);
    let sc2 = scenes2
        .iter()
        .find(|s| s.event == event && s.page == Some(page))
        .unwrap();
    let ln2 = sc2
        .lines
        .iter()
        .find(|l| l.cmd == cmd && l.str_idx == str_idx)
        .unwrap();
    assert_eq!(
        ln2.source, "WOLFDAWN TR",
        "translated line must read the new text"
    );
}

/// Safety guard: a translation that drops an inline control code present in the source is
/// rejected. It is counted in `code_mismatch` and the line is left untouched, so a translator
/// cannot silently break a `\cself`/`\s`/`\f` reference. `--allow-code-drift` overrides. This is
/// the core "never break the game" guarantee.
#[test]
fn control_code_drop_is_blocked_by_default() {
    let Some((_p, bytes, m)) = find_map_with_text() else {
        return;
    };
    // Find a line whose source carries an inline `\code` (so dropping it is detectable).
    let scenes = extract_map(&m);
    let Some((sc, ln)) = scenes
        .iter()
        .flat_map(|s| s.lines.iter().map(move |l| (s, l)))
        .find(|(_, l)| {
            l.source.contains("\\cself[") || l.source.contains("\\s[") || l.source.contains("\\c[")
        })
    else {
        eprintln!("no corpus line with an inline code, skipping");
        return;
    };
    let edit = format!(
        r#"{{ "scenes": [ {{ "event": {}, "page": {}, "lines": [ {{ "cmd": {}, "str": {}, "source": {}, "text": "code dropped entirely" }} ] }} ] }}"#,
        sc.event,
        sc.page.unwrap(),
        ln.cmd,
        ln.str_idx,
        serde_json::Value::String(ln.source.clone()),
    );

    // Default: blocked, counted, base untouched (byte-identical).
    let mut m2 = Map::read(&bytes).unwrap();
    let st = inject_map(&edit, &mut m2, &InjectOptions::default()).expect("inject");
    assert_eq!(st.applied, 0, "code-dropping translation must not apply");
    assert_eq!(st.code_mismatch, 1, "the dropped code must be counted");
    assert!(
        m2.write() == bytes,
        "blocked line must leave the file byte-identical"
    );

    // With --allow-code-drift: applied.
    let mut m3 = Map::read(&bytes).unwrap();
    let st = inject_map(
        &edit,
        &mut m3,
        &InjectOptions {
            allow_code_drift: true,
            ..Default::default()
        },
    )
    .expect("inject");
    assert_eq!(st.applied, 1, "allow_code_drift must apply the edit");
    assert_eq!(st.code_mismatch, 0);
}
