//! Incremental translation merge, a translation memory. Carries an existing translation over to a
//! freshly re-extracted set of strings when a game updates (for example v1.00 to v1.10), so the
//! translator only has to touch genuinely new or changed lines.
//!
//! The extractor's outputs (scenes, db, names, gamedat) all share one leaf shape: a JSON object
//! carrying a string `source` and a string `text`, where `text == source` means untranslated and
//! the translator edits `text`. This module does not model each schema. It walks every JSON object
//! generically and acts on any object that has both fields, the same walker pattern
//! [`crate::names::check_name_conflicts`] uses.
//!
//! Matching is by exact source string, not by locator (event/cmd/row index). A line that moved to
//! a different scene in the update still inherits its translation, which is more robust than
//! locator-matching across versions. The trade-off is that two different lines that share an
//! identical source get the same carried translation. That is acceptable and consistent with how
//! the rest of the toolchain treats `source` as the translation key.
//!
//! Pipeline:
//!   1. [`build_memory`] over the old (already-translated) JSONs builds a `source -> text` map of
//!      every real translation (`text != source`), plus a list of any sources that diverged across
//!      files.
//!   2. [`apply_memory`] over each new (freshly extracted) JSON returns the same JSON with
//!      carried-over translations filled in, plus [`MergeStats`] (carried, still_new,
//!      kept_existing).
//!   3. [`dropped_sources`] reports which old translations no longer apply because the line was
//!      removed in the update.
//!
//! Only `text` values are ever changed. Every other field and the document structure are
//! preserved exactly, and the result is re-serialized pretty-printed with serde_json's stable key
//! order.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use serde_json::Value;

// ----------------------------------------------------------------------------
// Generic source/text walker (shared shape across scenes, db, names, gamedat)
// ----------------------------------------------------------------------------

/// Pull every `(source, text)` pair out of one parsed translation JSON, regardless of schema. Any
/// object that has both a string `source` and a string `text` is a translation leaf. Mirrors
/// [`crate::names`]'s `collect_source_text_pairs` so the merge sees exactly the same leaves the
/// rest of the toolchain treats as translatable.
fn collect_source_text_pairs(v: &Value, out: &mut Vec<(String, String)>) {
    match v {
        Value::Object(map) => {
            if let (Some(Value::String(s)), Some(Value::String(t))) =
                (map.get("source"), map.get("text"))
            {
                out.push((s.clone(), t.clone()));
            }
            for child in map.values() {
                collect_source_text_pairs(child, out);
            }
        }
        Value::Array(arr) => {
            for child in arr {
                collect_source_text_pairs(child, out);
            }
        }
        _ => {}
    }
}

/// Collect just the `source` strings of every translation leaf (translated or not) in one parsed
/// JSON, into `out`. Empty sources are skipped. They are never a memory key.
fn collect_sources(v: &Value, out: &mut BTreeSet<String>) {
    match v {
        Value::Object(map) => {
            if let (Some(Value::String(s)), Some(Value::String(_))) =
                (map.get("source"), map.get("text"))
            {
                if !s.is_empty() {
                    out.insert(s.clone());
                }
            }
            for child in map.values() {
                collect_sources(child, out);
            }
        }
        Value::Array(arr) => {
            for child in arr {
                collect_sources(child, out);
            }
        }
        _ => {}
    }
}

// ----------------------------------------------------------------------------
// Build the translation memory from the old (translated) JSONs
// ----------------------------------------------------------------------------

/// Build the translation memory from the old (already-translated) extraction JSONs.
///
/// Walks every input generically and collects `source -> text` for each leaf that is a real
/// translation (`text != source`). `source == ""` is skipped. If the same `source` is given two
/// or more distinct `text` values across the inputs, the first one seen wins (inputs in order,
/// leaves in document order), and the source is reported in the returned conflicts vec together
/// with its divergent values (the kept value first, sorted thereafter).
///
/// An input that fails to parse is skipped, so one stray file cannot sink the whole memory.
///
/// Returns `(memory, conflicts)` where `conflicts` is `(source, distinct_texts)` per divergent
/// source, sorted by source for stable output.
// The return tuple is the documented public API shape: a source->text map plus a per-source
// variant list.
#[allow(clippy::type_complexity)]
pub fn build_memory(old_jsons: &[&str]) -> (HashMap<String, String>, Vec<(String, Vec<String>)>) {
    // source -> kept text (first seen), and source -> ordered set of all distinct texts seen.
    let mut memory: HashMap<String, String> = HashMap::new();
    // BTreeMap and BTreeSet keep conflict reporting deterministic and de-duplicated.
    let mut variants: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    // Preserve the kept first-seen value separately so it can lead the reported variant list.
    let mut kept: BTreeMap<String, String> = BTreeMap::new();

    for json in old_jsons {
        let Ok(root) = serde_json::from_str::<Value>(json) else {
            continue; // skip unparseable inputs rather than failing the whole build.
        };
        let mut pairs = Vec::new();
        collect_source_text_pairs(&root, &mut pairs);
        for (source, text) in pairs {
            if source.is_empty() || text == source {
                continue; // empty key or untranslated leaf, not a memory entry.
            }
            // First real translation for this source wins and is the kept value.
            memory.entry(source.clone()).or_insert_with(|| text.clone());
            kept.entry(source.clone()).or_insert_with(|| text.clone());
            variants
                .entry(source.clone())
                .or_default()
                .insert(text.clone());
        }
    }

    // A source with two or more distinct translations is a conflict. Report the kept value first,
    // then the remaining distinct values in sorted order.
    let mut conflicts = Vec::new();
    for (source, texts) in variants {
        if texts.len() < 2 {
            continue;
        }
        let keep = kept.get(&source).cloned().unwrap_or_default();
        let mut list = Vec::with_capacity(texts.len());
        list.push(keep.clone());
        for t in texts {
            if t != keep {
                list.push(t);
            }
        }
        conflicts.push((source, list));
    }

    (memory, conflicts)
}

// ----------------------------------------------------------------------------
// Apply the memory to a NEW (freshly extracted) JSON
// ----------------------------------------------------------------------------

/// What [`apply_memory`] did to one new extraction file.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct MergeStats {
    /// Leaves that were untranslated in the new file and got a translation carried over from memory.
    pub carried: usize,
    /// Leaves that are still untranslated (no memory hit). Genuinely new or changed text to do.
    pub still_new: usize,
    /// Leaves the new file already had its own translation for (`text != source`). Left untouched.
    pub kept_existing: usize,
}

/// Apply a translation memory to one new (freshly extracted) extraction JSON.
///
/// Parses the JSON, walks it generically, and for every leaf object with a string `source` and
/// `text`:
///   * If `text != source` already (the new file carries its own translation), leave it and add
///     to `kept_existing`.
///   * Else if `source` is in `memory`, set `text = memory[source]` and add to `carried`.
///   * Else leave it untranslated and add to `still_new`.
///
/// All other fields and the overall structure are preserved exactly. Only `text` values may
/// change. The result is re-serialized pretty-printed via serde_json with stable key order.
///
/// Returns the re-serialized JSON plus the [`MergeStats`], or an error string if the input does
/// not parse as JSON.
pub fn apply_memory(
    new_json: &str,
    memory: &HashMap<String, String>,
) -> Result<(String, MergeStats), String> {
    let mut root: Value = serde_json::from_str(new_json).map_err(|e| format!("invalid JSON: {e}"))?;
    let mut stats = MergeStats::default();
    apply_to_value(&mut root, memory, &mut stats);
    let out = serde_json::to_string_pretty(&root).map_err(|e| format!("serialize failed: {e}"))?;
    Ok((out, stats))
}

/// Recurse a parsed value, rewriting `text` on each translation leaf per the merge rule.
fn apply_to_value(v: &mut Value, memory: &HashMap<String, String>, stats: &mut MergeStats) {
    match v {
        Value::Object(map) => {
            // Decide this object's leaf action on an immutable read first, then mutate.
            let leaf = match (map.get("source"), map.get("text")) {
                (Some(Value::String(s)), Some(Value::String(t))) => Some((s.clone(), t.clone())),
                _ => None,
            };
            if let Some((source, text)) = leaf {
                if text != source {
                    stats.kept_existing += 1;
                } else if let Some(carried) = memory.get(&source) {
                    map.insert("text".to_string(), Value::String(carried.clone()));
                    stats.carried += 1;
                } else {
                    stats.still_new += 1;
                }
            }
            // Recurse into children regardless. Nested leaves, such as a speaker sub-object, still
            // get their own pass.
            for child in map.values_mut() {
                apply_to_value(child, memory, stats);
            }
        }
        Value::Array(arr) => {
            for child in arr.iter_mut() {
                apply_to_value(child, memory, stats);
            }
        }
        _ => {}
    }
}

// ----------------------------------------------------------------------------
// Reporting: which old translations no longer apply (removed in the update)
// ----------------------------------------------------------------------------

/// The memory sources present in none of the new extraction JSONs. These are lines that were
/// removed, or whose source text changed, in the update, so their translation cannot carry over.
/// Reporting only, sorted for stable output. Unparseable new files are skipped.
pub fn dropped_sources(memory: &HashMap<String, String>, new_jsons: &[&str]) -> Vec<String> {
    let mut present: BTreeSet<String> = BTreeSet::new();
    for json in new_jsons {
        if let Ok(root) = serde_json::from_str::<Value>(json) {
            collect_sources(&root, &mut present);
        }
    }
    let mut dropped: Vec<String> = memory
        .keys()
        .filter(|s| !present.contains(*s))
        .cloned()
        .collect();
    dropped.sort();
    dropped
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_memory_keeps_real_translations_only() {
        // A translated names file: あ is translated to A, い is untranslated (text==source).
        let names = r#"{"kind":"names","names":[
            {"source":"あ","text":"A","occurrences":3,"note":"Monster"},
            {"source":"い","text":"い","occurrences":1,"note":"Item"}
        ]}"#;
        let (mem, conflicts) = build_memory(&[names]);
        assert_eq!(mem.get("あ").map(String::as_str), Some("A"));
        assert!(!mem.contains_key("い"), "untranslated source is excluded");
        assert_eq!(mem.len(), 1);
        assert!(conflicts.is_empty());
    }

    #[test]
    fn build_memory_skips_empty_source() {
        let json = r#"{"lines":[{"source":"","text":"X"},{"source":"a","text":"B"}]}"#;
        let (mem, _) = build_memory(&[json]);
        assert!(!mem.contains_key(""));
        assert_eq!(mem.get("a").map(String::as_str), Some("B"));
    }

    #[test]
    fn build_memory_reports_conflict_and_keeps_first() {
        // Same source translated two different ways across two files is a conflict. First wins.
        let f1 = r#"{"lines":[{"source":"剣","text":"Sword"}]}"#;
        let f2 = r#"{"lines":[{"source":"剣","text":"Blade"}]}"#;
        let (mem, conflicts) = build_memory(&[f1, f2]);
        assert_eq!(mem.get("剣").map(String::as_str), Some("Sword"), "first kept");
        assert_eq!(conflicts.len(), 1);
        assert_eq!(conflicts[0].0, "剣");
        // Kept value leads the reported variants. Both distinct values are present.
        assert_eq!(conflicts[0].1.first().map(String::as_str), Some("Sword"));
        assert!(conflicts[0].1.iter().any(|t| t == "Blade"));
        assert_eq!(conflicts[0].1.len(), 2);
    }

    #[test]
    fn build_memory_same_text_is_not_a_conflict() {
        // The same translation in two files is consistent, not divergent.
        let f1 = r#"{"lines":[{"source":"剣","text":"Sword"}]}"#;
        let f2 = r#"{"lines":[{"source":"剣","text":"Sword"}]}"#;
        let (_, conflicts) = build_memory(&[f1, f2]);
        assert!(conflicts.is_empty());
    }

    #[test]
    fn apply_memory_carries_and_marks_still_new() {
        // New scenes extraction: あ matches memory (carried), う has no memory entry (still new).
        let new = r#"{"scenes":[{"lines":[
            {"source":"あ","text":"あ","speaker":"NPC"},
            {"source":"う","text":"う","speaker":"NPC"}
        ]}]}"#;
        let mut mem = HashMap::new();
        mem.insert("あ".to_string(), "A".to_string());
        let (out, stats) = apply_memory(new, &mem).unwrap();
        assert_eq!(stats.carried, 1);
        assert_eq!(stats.still_new, 1);
        assert_eq!(stats.kept_existing, 0);
        // Re-parse and confirm the carried translation landed and the still-new one is unchanged.
        let v: Value = serde_json::from_str(&out).unwrap();
        let mut pairs = Vec::new();
        collect_source_text_pairs(&v, &mut pairs);
        let map: HashMap<_, _> = pairs.into_iter().collect();
        assert_eq!(map.get("あ").map(String::as_str), Some("A"));
        assert_eq!(map.get("う").map(String::as_str), Some("う"));
    }

    #[test]
    fn apply_memory_keeps_existing_translation_untouched() {
        // The new file already translated あ to "Already". Even with a different memory entry, its
        // own translation is kept and counted as kept_existing, never overwritten.
        let new = r#"{"lines":[{"source":"あ","text":"Already"}]}"#;
        let mut mem = HashMap::new();
        mem.insert("あ".to_string(), "FromMemory".to_string());
        let (out, stats) = apply_memory(new, &mem).unwrap();
        assert_eq!(stats.kept_existing, 1);
        assert_eq!(stats.carried, 0);
        assert_eq!(stats.still_new, 0);
        let v: Value = serde_json::from_str(&out).unwrap();
        let mut pairs = Vec::new();
        collect_source_text_pairs(&v, &mut pairs);
        assert_eq!(pairs[0].1, "Already");
    }

    #[test]
    fn apply_memory_empty_memory_preserves_everything() {
        // With an empty memory, nothing is carried. Every text and non-text field is preserved.
        let new = r#"{"scenes":[{"event":7,"lines":[
            {"cmd":3,"str":0,"row":2,"speaker":"勇者","source":"あ","text":"あ"}
        ]}]}"#;
        let before: Value = serde_json::from_str(new).unwrap();
        let (out, stats) = apply_memory(new, &HashMap::new()).unwrap();
        assert_eq!(stats.carried, 0);
        assert_eq!(stats.kept_existing, 0);
        assert_eq!(stats.still_new, 1);
        let after: Value = serde_json::from_str(&out).unwrap();
        // Logical content is identical. serde_json::Value compares structurally.
        assert_eq!(before, after, "empty memory is a structural no-op");
    }

    #[test]
    fn apply_memory_bad_json_errors() {
        assert!(apply_memory("{not json", &HashMap::new()).is_err());
    }

    #[test]
    fn dropped_sources_reports_removed_only() {
        let mut mem = HashMap::new();
        mem.insert("あ".to_string(), "A".to_string());
        mem.insert("い".to_string(), "I".to_string());
        // The new file only still contains あ. い was removed in the update.
        let new = r#"{"lines":[{"source":"あ","text":"あ"}]}"#;
        let dropped = dropped_sources(&mem, &[new]);
        assert_eq!(dropped, vec!["い".to_string()]);
    }
}
