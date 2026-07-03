//! External event-text `.txt` round-trip. A no-op inject reproduces the base byte-for-byte, an
//! edit changes only its line while the surrounding `/` command lines stay intact, and extraction
//! drops every command/comment/blank line while keeping dialogue and speaker lines.
//!
//! The real-data cases use the `WOLFDAWN_TEST_DATA` fixture (`g210/Evtext/hev_a000h.txt`) and skip
//! gracefully when it is absent. The synthetic cases always run.

use wolf_decompiler::{extract_txt_events, inject_txt_events};

mod common;
use common::test_data;

/// Parse the `source` strings out of an extracted document, in order.
fn sources(json: &str) -> Vec<String> {
    let v: serde_json::Value = serde_json::from_str(json).unwrap();
    v["lines"]
        .as_array()
        .unwrap()
        .iter()
        .map(|l| l["source"].as_str().unwrap().to_owned())
        .collect()
}

/// A synthetic Shift-JIS event file with CRLF endings, a `//` comment, a `/` command, a speaker
/// line, dialogue, blank-line spacing, and no trailing newline. Mirrors the real format.
fn synthetic_sjis() -> Vec<u8> {
    let text = "//おねだり_コメント\r\n\
                /evcg,a0,b0,c0\r\n\
                /胸+1\r\n\
                アイリス：\r\n\
                こんにちは、世界\r\n\
                \r\n\
                /b\r\n\
                最後の行に改行なし";
    encoding_rs::SHIFT_JIS.encode(text).0.into_owned()
}

#[test]
fn synthetic_noop_is_byte_exact() {
    let bytes = synthetic_sjis();
    let json = extract_txt_events(&bytes);
    let out = inject_txt_events(&json, &bytes).expect("inject");
    assert_eq!(out, bytes, "no-op inject must reproduce the base byte-for-byte");
}

#[test]
fn synthetic_extraction_excludes_commands_and_blanks() {
    let bytes = synthetic_sjis();
    let json = extract_txt_events(&bytes);
    let got = sources(&json);
    assert_eq!(
        got,
        vec![
            "アイリス：".to_string(),
            "こんにちは、世界".to_string(),
            "最後の行に改行なし".to_string(),
        ],
        "only the non-command, non-blank lines are extracted"
    );
    // Confirm no command/comment line leaked into the document.
    for forbidden in ["/evcg", "/胸+1", "/b", "//おねだり"] {
        assert!(
            !json.contains(forbidden),
            "command/comment {forbidden} must not be extracted"
        );
    }
}

#[test]
fn synthetic_edit_round_trip_keeps_command_intact() {
    let bytes = synthetic_sjis();
    let json = extract_txt_events(&bytes);
    // Edit the dialogue line, leaving its neighbour command `/evcg` and `/b` untouched.
    let edited = json.replacen(
        r#""source": "こんにちは、世界", "text": "こんにちは、世界""#,
        r#""source": "こんにちは、世界", "text": "やあ、世界""#,
        1,
    );
    assert_ne!(edited, json, "edit must have matched a line");
    let out = inject_txt_events(&edited, &bytes).expect("inject");
    // Re-extract and confirm the new text landed.
    let re = extract_txt_events(&out);
    assert!(
        sources(&re).contains(&"やあ、世界".to_string()),
        "edited text must be present after re-extraction"
    );
    // The command lines next to it must be byte-intact.
    let (decoded, _, _) = encoding_rs::SHIFT_JIS.decode(&out);
    assert!(decoded.contains("/evcg,a0,b0,c0"), "the /evcg command must survive");
    assert!(decoded.contains("/b"), "the /b page break must survive");
    assert!(!decoded.contains("こんにちは、世界"), "old text should be gone");
}

#[test]
fn synthetic_unrepresentable_and_newline_are_skipped() {
    // A translation with a char SJIS cannot encode, and one with an embedded newline, are both
    // skipped, leaving the file byte-exact.
    let text = "せりふいち\r\nせりふに\r\n";
    let bytes = encoding_rs::SHIFT_JIS.encode(text).0.into_owned();
    let json = extract_txt_events(&bytes);
    // Line 0 -> an emoji (not SJIS), line 1 -> a two-line value.
    let edited = json
        .replacen(
            r#""source": "せりふいち", "text": "せりふいち""#,
            r#""source": "せりふいち", "text": "🎮""#,
            1,
        )
        .replacen(
            r#""source": "せりふに", "text": "せりふに""#,
            r#""source": "せりふに", "text": "a\nb""#,
            1,
        );
    let out = inject_txt_events(&edited, &bytes).expect("inject");
    assert_eq!(out, bytes, "both guarded edits are skipped, base preserved");
}

#[test]
fn real_file_noop_is_byte_exact_and_keeps_dialogue() {
    let Some(path) = test_data("g210/Evtext/hev_a000h.txt") else {
        eprintln!("no g210/Evtext fixture, skipping real-file txt test");
        return;
    };
    let bytes = std::fs::read(&path).expect("read fixture");

    // No-op inject is byte-for-byte identical.
    let json = extract_txt_events(&bytes);
    let out = inject_txt_events(&json, &bytes).expect("inject");
    assert_eq!(out, bytes, "real-file no-op inject must be byte-exact");

    // Extraction excludes every `/`-prefixed and blank line, and keeps the speaker line.
    let srcs = sources(&json);
    assert!(!srcs.is_empty(), "the real file has dialogue to extract");
    assert!(
        srcs.iter().all(|s| !s.is_empty() && !s.starts_with('/')),
        "no command/comment/blank line should be extracted"
    );
    assert!(
        srcs.iter().any(|s| s.starts_with("アイリス")),
        "the アイリス： speaker line should be extracted"
    );

    // Edit one dialogue line and confirm it lands while a command line stays intact.
    let target = srcs.iter().find(|s| !s.starts_with("アイリス")).unwrap().clone();
    let needle = format!("\"source\": {0}, \"text\": {0}", serde_json::Value::String(target.clone()));
    let replacement = format!(
        "\"source\": {}, \"text\": {}",
        serde_json::Value::String(target.clone()),
        serde_json::Value::String("WOLFDAWN_TXT_TR".to_string())
    );
    let edited = json.replacen(&needle, &replacement, 1);
    assert_ne!(edited, json, "edit must have matched a line");
    let out2 = inject_txt_events(&edited, &bytes).expect("inject edit");
    let re = extract_txt_events(&out2);
    assert!(
        sources(&re).contains(&"WOLFDAWN_TXT_TR".to_string()),
        "edited text must be present after re-extraction"
    );
    let (decoded, _, _) = encoding_rs::SHIFT_JIS.decode(&out2);
    assert!(decoded.contains("/evcg"), "an /evcg command line must remain intact");
}
