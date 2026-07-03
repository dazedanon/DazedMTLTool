//! Incremental translation-merge (translation memory) round-trip tests. No corpus is needed.
//! Every fixture is a tiny hand-built JSON, exercising the generic `source`/`text` walker across
//! the different document shapes (names, scenes, db-like).
//!
//! Gates:
//!   (a) build_memory keeps only real translations (drops `text == source`) and reports a source
//!       that diverges across two files as a conflict, keeping the first value.
//!   (b) apply_memory carries a memory hit into an untranslated leaf, leaves a no-match leaf
//!       untranslated (still_new), and never overwrites a leaf the new file already translated
//!       (kept_existing).
//!   (c) Structure preservation: an empty memory leaves every `text` unchanged and re-parses to
//!       the same logical content, and non-`source`/`text` fields are preserved exactly.

use std::collections::HashMap;

use serde_json::Value;
use wolf_decompiler::{apply_memory, build_memory, dropped_sources, MergeStats};

/// Collect `source -> text` from a parsed value, generically (any object with both string fields).
fn pairs(v: &Value) -> HashMap<String, String> {
    fn walk(v: &Value, out: &mut HashMap<String, String>) {
        match v {
            Value::Object(m) => {
                if let (Some(Value::String(s)), Some(Value::String(t))) =
                    (m.get("source"), m.get("text"))
                {
                    out.insert(s.clone(), t.clone());
                }
                for c in m.values() {
                    walk(c, out);
                }
            }
            Value::Array(a) => {
                for c in a {
                    walk(c, out);
                }
            }
            _ => {}
        }
    }
    let mut out = HashMap::new();
    walk(v, &mut out);
    out
}

// ---------------------------------------------------------------------------
// (a) build_memory
// ---------------------------------------------------------------------------

#[test]
fn build_memory_excludes_untranslated() {
    // {names:[{source:"あ",text:"A"},{source:"い",text:"い"}]} yields {"あ":"A"} only.
    let names = r#"{"kind":"names","names":[
        {"source":"あ","text":"A","occurrences":2,"note":"Monster"},
        {"source":"い","text":"い","occurrences":1,"note":"Item"}
    ]}"#;
    let (mem, conflicts) = build_memory(&[names]);
    assert_eq!(mem.len(), 1);
    assert_eq!(mem.get("あ").map(String::as_str), Some("A"));
    assert!(!mem.contains_key("い"), "untranslated entry excluded");
    assert!(conflicts.is_empty());
}

#[test]
fn build_memory_divergent_source_is_conflict_first_kept() {
    // Same source, two distinct translations across two files is a conflict. The first is kept.
    let f1 = r#"{"scenes":[{"lines":[{"source":"あ","text":"A1"}]}]}"#;
    let f2 = r#"{"scenes":[{"lines":[{"source":"あ","text":"A2"}]}]}"#;
    let (mem, conflicts) = build_memory(&[f1, f2]);
    assert_eq!(mem.get("あ").map(String::as_str), Some("A1"), "first input wins");
    assert_eq!(conflicts.len(), 1);
    let (src, variants) = &conflicts[0];
    assert_eq!(src, "あ");
    assert_eq!(variants.first().map(String::as_str), Some("A1"), "kept value leads");
    assert!(variants.iter().any(|t| t == "A2"));
    assert_eq!(variants.len(), 2);
}

// ---------------------------------------------------------------------------
// (b) apply_memory
// ---------------------------------------------------------------------------

#[test]
fn apply_memory_carries_and_keeps() {
    // New scenes: あ matches memory (carried), う has no entry (still_new), and a pre-translated
    // entry (text != source) is kept untouched (kept_existing).
    let new = r#"{"scenes":[{"lines":[
        {"cmd":0,"str":0,"speaker":"NPC","source":"あ","text":"あ"},
        {"cmd":1,"str":0,"speaker":"NPC","source":"う","text":"う"},
        {"cmd":2,"str":0,"speaker":"NPC","source":"え","text":"AlreadyDone"}
    ]}]}"#;
    let mut mem = HashMap::new();
    mem.insert("あ".to_string(), "A".to_string());
    // A memory entry for え exists too, but the new file already translated it, so it must not override.
    mem.insert("え".to_string(), "ShouldNotWin".to_string());

    let (out, stats) = apply_memory(new, &mem).unwrap();
    assert_eq!(
        stats,
        MergeStats {
            carried: 1,
            still_new: 1,
            kept_existing: 1
        }
    );
    let v: Value = serde_json::from_str(&out).unwrap();
    let p = pairs(&v);
    assert_eq!(p.get("あ").map(String::as_str), Some("A"), "carried");
    assert_eq!(p.get("う").map(String::as_str), Some("う"), "still untranslated");
    assert_eq!(
        p.get("え").map(String::as_str),
        Some("AlreadyDone"),
        "existing translation kept, not overwritten by memory"
    );
}

// ---------------------------------------------------------------------------
// (c) structure preservation
// ---------------------------------------------------------------------------

#[test]
fn apply_empty_memory_is_structural_noop() {
    // Applying an empty memory leaves every `text` unchanged and preserves all sibling fields
    // (speaker, cmd, row, and so on). The re-serialized JSON parses to the same logical content.
    let new = r#"{"kind":"map","scenes":[{"event":4,"lines":[
        {"cmd":3,"str":1,"row":2,"speaker":"勇者","speaker_src":"勇者","source":"あ","text":"あ"},
        {"cmd":4,"str":0,"row":5,"speaker":"魔王","speaker_src":"魔王","source":"い","text":"い"}
    ]}]}"#;
    let before: Value = serde_json::from_str(new).unwrap();
    let (out, stats) = apply_memory(new, &HashMap::new()).unwrap();
    assert_eq!(stats.carried, 0);
    assert_eq!(stats.kept_existing, 0);
    assert_eq!(stats.still_new, 2);
    let after: Value = serde_json::from_str(&out).unwrap();
    assert_eq!(before, after, "empty-memory apply must be a logical no-op");
}

#[test]
fn non_source_text_fields_survive_a_carry() {
    // When a carry happens, only `text` changes. Every other field on the leaf is preserved.
    let new = r#"{"groups":[{"type":0,"lines":[
        {"row":7,"field":2,"rowName":"Slime","fieldName":"Name","source":"あ","text":"あ"}
    ]}]}"#;
    let mut mem = HashMap::new();
    mem.insert("あ".to_string(), "A".to_string());
    let (out, _) = apply_memory(new, &mem).unwrap();
    let v: Value = serde_json::from_str(&out).unwrap();
    let leaf = &v["groups"][0]["lines"][0];
    assert_eq!(leaf["text"], Value::String("A".into()), "text carried");
    assert_eq!(leaf["row"], Value::from(7));
    assert_eq!(leaf["field"], Value::from(2));
    assert_eq!(leaf["rowName"], Value::String("Slime".into()));
    assert_eq!(leaf["fieldName"], Value::String("Name".into()));
    assert_eq!(leaf["source"], Value::String("あ".into()), "source unchanged");
}

// ---------------------------------------------------------------------------
// dropped reporting
// ---------------------------------------------------------------------------

#[test]
fn dropped_sources_lists_removed_in_update() {
    let old = r#"{"lines":[{"source":"あ","text":"A"},{"source":"い","text":"I"}]}"#;
    let (mem, _) = build_memory(&[old]);
    // The new extraction dropped い (removed in the update).
    let new = r#"{"lines":[{"source":"あ","text":"あ"}]}"#;
    let dropped = dropped_sources(&mem, &[new]);
    assert_eq!(dropped, vec!["い".to_string()]);
}
