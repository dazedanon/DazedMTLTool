//! External event-text `.txt` files. Some GamePro games keep every line of dialogue and
//! narration in plain Shift-JIS (or, for newer games, UTF-8) `.txt` files that the engine reads
//! at runtime, one file per scene. The `Evtext*.wolf` archives unpack to thousands of them. The
//! command-stream extractor in `strings.rs` never sees this text, so without this module it is
//! the single biggest recall gap for those games.
//!
//! The format is line-based. A line that starts with `/` is an engine command or a `//` comment
//! (CG control, page break, a stat tweak like `/胸+1`, and so on) and is never shown to the
//! player. A blank line is spacing. Every other non-blank line is displayed text. So a line is
//! translatable exactly when it does not start with `/` and is not blank.
//!
//! Extraction emits only the translatable lines, each tagged with its 0-based line index so
//! injection knows which line to replace. Command, comment, and blank lines are reconstructed
//! from the base on inject, so they round-trip byte-exact. A no-op inject (every `text` equal to
//! its `source`) reproduces the base file byte-for-byte, including the original line endings, the
//! original encoding, and a missing trailing newline.

use std::fmt::Write as _;

use serde_json::Value;

// ----------------------------------------------------------------------------
// Decoding + line splitting
// ----------------------------------------------------------------------------

/// The file's text encoding. A `.txt` event file is Shift-JIS for the older GamePro games and
/// UTF-8 for newer ones. We detect rather than guess so both round-trip.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Enc {
    Sjis,
    Utf8,
}

impl Enc {
    fn tag(self) -> &'static str {
        match self {
            Enc::Sjis => "sjis",
            Enc::Utf8 => "utf8",
        }
    }
}

/// Decode the raw bytes, choosing the encoding. Valid UTF-8 wins (it is the stricter test, and a
/// genuine Shift-JIS file with high bytes is almost never accidentally valid UTF-8), otherwise we
/// fall back to Shift-JIS, which the older games use. A UTF-8 BOM, if present, is treated as part
/// of the first line's bytes so it survives the round-trip untouched.
fn decode(bytes: &[u8]) -> (String, Enc) {
    match std::str::from_utf8(bytes) {
        Ok(s) => (s.to_owned(), Enc::Utf8),
        Err(_) => {
            let (text, _, _) = encoding_rs::SHIFT_JIS.decode(bytes);
            (text.into_owned(), Enc::Sjis)
        }
    }
}

/// Re-encode decoded text in the chosen encoding. Returns `None` when the text has a char the
/// encoding cannot represent (a non-Shift-JIS char hand-typed into a Shift-JIS file), mirroring
/// the encoding guard `text.rs` uses for the command-stream path.
fn encode(text: &str, enc: Enc) -> Option<Vec<u8>> {
    match enc {
        Enc::Utf8 => Some(text.as_bytes().to_vec()),
        Enc::Sjis => {
            let (bytes, _, had_err) = encoding_rs::SHIFT_JIS.encode(text);
            (!had_err).then(|| bytes.into_owned())
        }
    }
}

/// One physical line: its content (no terminator) and the exact terminator that followed it. The
/// terminator is `"\r\n"`, `"\n"`, `"\r"`, or `""` for the last line when the file has no trailing
/// newline. Capturing the real terminator per line, rather than assuming one EOL for the whole
/// file, keeps reconstruction byte-exact even if a file mixes line endings.
struct Line<'a> {
    content: &'a str,
    eol: &'a str,
}

/// Split decoded text into lines, recording each line's exact terminator. A final segment with no
/// terminator (no trailing newline at EOF) is kept as a last line with an empty terminator, so it
/// re-joins without inventing a newline. An empty input yields no lines.
fn split_lines(text: &str) -> Vec<Line<'_>> {
    let mut lines = Vec::new();
    let bytes = text.as_bytes();
    let mut start = 0;
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'\n' => {
                lines.push(Line {
                    content: &text[start..i],
                    eol: "\n",
                });
                i += 1;
                start = i;
            }
            b'\r' => {
                let eol = if bytes.get(i + 1) == Some(&b'\n') {
                    "\r\n"
                } else {
                    "\r"
                };
                lines.push(Line {
                    content: &text[start..i],
                    eol,
                });
                i += eol.len();
                start = i;
            }
            _ => i += 1,
        }
    }
    if start < bytes.len() {
        // Trailing segment with no terminator (file does not end in a newline).
        lines.push(Line {
            content: &text[start..],
            eol: "",
        });
    }
    lines
}

/// A line is translatable when it is not blank and does not start with `/`. The `/` test is on
/// the first byte with no whitespace stripping. The real game files never indent a command, and a
/// displayed line that genuinely begins with a leading space (full sentences sometimes do) keeps
/// that space as part of its on-screen text, so trimming first would be wrong on both counts.
fn is_translatable(content: &str) -> bool {
    !content.is_empty() && !content.starts_with('/')
}

/// The dominant EOL for the document metadata. Reports `crlf` if any line ends in `\r\n`, else
/// `lf`. Only informational. Reconstruction always uses each line's captured terminator.
fn dominant_eol(lines: &[Line<'_>]) -> &'static str {
    if lines.iter().any(|l| l.eol == "\r\n") {
        "crlf"
    } else {
        "lf"
    }
}

// ----------------------------------------------------------------------------
// Extraction
// ----------------------------------------------------------------------------

/// Extract the translatable lines of an event-text `.txt` file as a translation JSON document.
///
/// The shape is `{ "kind":"txt", "encoding":"sjis|utf8", "eol":"crlf|lf", "lines":[ {"i":<0-based
/// line index>, "source":"<line>", "text":"<same as source initially>"} ... ] }`. Only the
/// translatable lines get an entry. Command, comment, and blank lines carry no entry because
/// inject rebuilds them from the base. `text` starts equal to `source`. A translator edits
/// `text`. `source` is kept for the inject drift guard.
pub fn extract_txt_events(bytes: &[u8]) -> String {
    let (text, enc) = decode(bytes);
    let lines = split_lines(&text);
    let eol = dominant_eol(&lines);

    let mut s = String::new();
    s.push_str("{\n");
    let _ = write!(s, "  \"kind\": \"txt\",\n");
    let _ = write!(s, "  \"encoding\": {},\n", jstr(enc.tag()));
    let _ = write!(s, "  \"eol\": {},\n", jstr(eol));
    s.push_str("  \"lines\": [\n");
    let keep: Vec<(usize, &str)> = lines
        .iter()
        .enumerate()
        .filter(|(_, l)| is_translatable(l.content))
        .map(|(i, l)| (i, l.content))
        .collect();
    for (n, (i, content)) in keep.iter().enumerate() {
        let _ = write!(
            s,
            "    {{\"i\": {}, \"source\": {}, \"text\": {}}}",
            i,
            jstr(content),
            jstr(content)
        );
        s.push_str(if n + 1 == keep.len() { "\n" } else { ",\n" });
    }
    s.push_str("  ]\n}\n");
    s
}

// ----------------------------------------------------------------------------
// Injection
// ----------------------------------------------------------------------------

/// Apply an edited translation JSON back onto the base `.txt` bytes, byte-exact.
///
/// The base is re-decoded into lines, so command, comment, and blank lines (and the exact line
/// terminators) come straight from the original. Each translatable line `i` is replaced with its
/// `text` only when `text` differs from `source` and the base line still holds `source` (a drift
/// guard). The lines are re-joined with their original terminators and re-encoded in the original
/// encoding. A no-op (every `text` equal to its `source`) reproduces the base byte-for-byte.
///
/// A translation is skipped, leaving the base line untouched, when it contains a newline (that
/// would split one line into two) or when it is not representable in the file's encoding
/// (Shift-JIS). Both cases print a warning, the same way the command-stream `write_translation`
/// guards encoding, and the rest of the batch still applies.
pub fn inject_txt_events(json: &str, base_bytes: &[u8]) -> Result<Vec<u8>, String> {
    let root: Value = serde_json::from_str(json).map_err(|e| format!("invalid JSON: {e}"))?;
    let (text, enc) = decode(base_bytes);
    let lines = split_lines(&text);
    // Each line starts as its original content. Edits overwrite the content of translatable lines.
    let mut content: Vec<String> = lines.iter().map(|l| l.content.to_owned()).collect();

    let entries = root
        .get("lines")
        .and_then(Value::as_array)
        .ok_or("txt translation JSON has no `lines` array")?;
    for ln in entries {
        let i = ln
            .get("i")
            .and_then(Value::as_u64)
            .ok_or("txt line entry has no integer `i`")? as usize;
        let source = ln.get("source").and_then(Value::as_str).unwrap_or("");
        let text_new = ln.get("text").and_then(Value::as_str).unwrap_or(source);
        if text_new == source {
            continue;
        }
        let Some(cur) = content.get_mut(i) else {
            eprintln!("txt line {i}: out of range in base (drifted); skipping");
            continue;
        };
        // Drift guard: only overwrite if the base line still holds the recorded source.
        if cur != source {
            eprintln!("txt line {i}: base no longer holds the recorded source (drifted); skipping");
            continue;
        }
        // A newline in the translation would split one line into two and desync every later
        // index. Reject it and keep the original line.
        if text_new.contains('\n') || text_new.contains('\r') {
            eprintln!("txt line {i}: translation contains a newline; skipping (keep it on one line)");
            continue;
        }
        // The translated line must be representable in the file's encoding (Shift-JIS games).
        if encode(text_new, enc).is_none() {
            eprintln!(
                "txt line {i}: text not representable in {}: {text_new:?}; choose an encodable equivalent",
                enc.tag()
            );
            continue;
        }
        *cur = text_new.to_owned();
    }

    // Re-join with the original per-line terminators, then re-encode.
    let mut rebuilt = String::with_capacity(text.len());
    for (l, c) in lines.iter().zip(content.iter()) {
        rebuilt.push_str(c);
        rebuilt.push_str(l.eol);
    }
    encode(&rebuilt, enc).ok_or_else(|| {
        format!(
            "rebuilt text not representable in {} (this should not happen after the per-line guard)",
            enc.tag()
        )
    })
}

// ----------------------------------------------------------------------------
// Directory (folder of .txt files) combined document
// ----------------------------------------------------------------------------

/// Build one combined translation JSON for a folder of event-text files. Each `(name, bytes)`
/// pair is extracted and embedded under a `files` array with its `file` name, so a single document
/// covers a whole `Evtext` folder and `inject_txt_dir` can route each entry back to its base file.
/// The caller supplies the files in the order they should appear (sorted by name for stability).
pub fn extract_txt_dir(files: &[(String, Vec<u8>)]) -> String {
    let mut entries = Vec::with_capacity(files.len());
    for (name, bytes) in files {
        let mut obj: Value = serde_json::from_str(&extract_txt_events(bytes))
            .expect("extract_txt_events always emits valid JSON");
        if let Value::Object(map) = &mut obj {
            // Put `file` first by rebuilding the map with it at the front.
            let mut with_name = serde_json::Map::new();
            with_name.insert("file".to_string(), Value::String(name.clone()));
            for (k, v) in map.iter() {
                with_name.insert(k.clone(), v.clone());
            }
            obj = Value::Object(with_name);
        }
        entries.push(obj);
    }
    let doc = serde_json::json!({ "kind": "txt-dir", "files": entries });
    // Pretty-print so a translator can edit it by hand, matching the readable single-file output.
    serde_json::to_string_pretty(&doc).unwrap_or_else(|_| "{}".to_string()) + "\n"
}

/// One file's edits parsed out of a combined `txt-dir` document: its base file name and the
/// per-file JSON to feed to [`inject_txt_events`]. Returned in document order.
pub fn split_txt_dir(json: &str) -> Result<Vec<(String, String)>, String> {
    let root: Value = serde_json::from_str(json).map_err(|e| format!("invalid JSON: {e}"))?;
    let files = root
        .get("files")
        .and_then(Value::as_array)
        .ok_or("txt-dir JSON has no `files` array")?;
    let mut out = Vec::with_capacity(files.len());
    for entry in files {
        let name = entry
            .get("file")
            .and_then(Value::as_str)
            .ok_or("a files[] entry has no `file` name")?
            .to_owned();
        out.push((name, entry.to_string()));
    }
    Ok(out)
}

// ----------------------------------------------------------------------------
// JSON string escaping (matches the other extractors)
// ----------------------------------------------------------------------------

fn jstr(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extracted_texts(json: &str) -> Vec<String> {
        let v: Value = serde_json::from_str(json).unwrap();
        v["lines"]
            .as_array()
            .unwrap()
            .iter()
            .map(|l| l["source"].as_str().unwrap().to_owned())
            .collect()
    }

    #[test]
    fn noop_is_byte_exact_crlf_with_commands_and_blanks() {
        // CRLF, a `//` comment, a `/` command, blank lines, CJK dialogue, no trailing newline.
        let text = "//tag comment\r\n/evcg,a0\r\nアイリス：\r\nこんにちは\r\n\r\n/b\r\n最後の行";
        let bytes = encoding_rs::SHIFT_JIS.encode(text).0.into_owned();
        let json = extract_txt_events(&bytes);
        let out = inject_txt_events(&json, &bytes).unwrap();
        assert_eq!(out, bytes, "no-op inject must be byte-exact");
    }

    #[test]
    fn extraction_excludes_commands_and_blanks() {
        let text = "//comment\r\n/evcg,a0\r\nアイリス：\r\n本当のセリフ\r\n\r\n/b\r\n";
        let bytes = encoding_rs::SHIFT_JIS.encode(text).0.into_owned();
        let json = extract_txt_events(&bytes);
        let got = extracted_texts(&json);
        assert_eq!(got, vec!["アイリス：".to_string(), "本当のセリフ".to_string()]);
        assert!(!json.contains("/evcg"), "command line must not be extracted");
        assert!(!json.contains("//comment"), "comment line must not be extracted");
    }

    #[test]
    fn edit_round_trip_keeps_commands_intact() {
        let text = "/evcg,a0\r\nアイリス：\r\n元のセリフ\r\n/b\r\n";
        let bytes = encoding_rs::SHIFT_JIS.encode(text).0.into_owned();
        let json = extract_txt_events(&bytes);
        // Change the line whose source is `元のセリフ`.
        let edited = json.replacen(
            r#""source": "元のセリフ", "text": "元のセリフ""#,
            r#""source": "元のセリフ", "text": "新しいセリフ""#,
            1,
        );
        assert_ne!(edited, json, "the replacement should have matched");
        let out = inject_txt_events(&edited, &bytes).unwrap();
        let re = extract_txt_events(&out);
        assert!(extracted_texts(&re).contains(&"新しいセリフ".to_string()));
        let (decoded, _) = decode(&out);
        assert!(decoded.contains("/evcg,a0"), "command line must survive");
        assert!(decoded.contains("/b"), "page-break command must survive");
        assert!(!decoded.contains("元のセリフ"), "old text should be gone");
    }

    #[test]
    fn lf_only_and_leading_space_line_and_utf8() {
        // LF endings, a UTF-8 file, a dialogue line that starts with a real leading space, and a
        // command line. The leading-space line is text (the space is part of it), the `/` line is
        // not.
        let text = "/cmd\n line with leading space\nnormal\n";
        let bytes = text.as_bytes().to_vec();
        let json = extract_txt_events(&bytes);
        let v: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["encoding"], "utf8");
        assert_eq!(v["eol"], "lf");
        let got = extracted_texts(&json);
        assert_eq!(got, vec![" line with leading space".to_string(), "normal".to_string()]);
        assert_eq!(inject_txt_events(&json, &bytes).unwrap(), bytes);
    }

    #[test]
    fn newline_in_translation_is_rejected() {
        let text = "せりふ\n";
        let bytes = text.as_bytes().to_vec();
        let edit = r#"{"kind":"txt","encoding":"utf8","eol":"lf","lines":[{"i":0,"source":"せりふ","text":"two\nlines"}]}"#;
        let out = inject_txt_events(edit, &bytes).unwrap();
        // Rejected, so the base line is untouched.
        assert_eq!(out, bytes);
    }

    #[test]
    fn unrepresentable_sjis_is_skipped() {
        // A Shift-JIS base, translation contains an emoji (not SJIS-encodable). The line is left
        // untouched and the rest of the file is unchanged.
        let text = "あいうえお\r\n";
        let bytes = encoding_rs::SHIFT_JIS.encode(text).0.into_owned();
        let edit = r#"{"kind":"txt","encoding":"sjis","eol":"crlf","lines":[{"i":0,"source":"あいうえお","text":"🎮"}]}"#;
        let out = inject_txt_events(edit, &bytes).unwrap();
        assert_eq!(out, bytes, "unrepresentable line is skipped, base preserved");
    }

    #[test]
    fn empty_file_round_trips() {
        let bytes: Vec<u8> = Vec::new();
        let json = extract_txt_events(&bytes);
        assert!(extracted_texts(&json).is_empty());
        assert_eq!(inject_txt_events(&json, &bytes).unwrap(), bytes);
    }

    #[test]
    fn lone_cr_line_ending_round_trips() {
        // A stray old-Mac `\r` terminator must survive byte-exact.
        let bytes = b"text one\rtext two".to_vec();
        let json = extract_txt_events(&bytes);
        assert_eq!(inject_txt_events(&json, &bytes).unwrap(), bytes);
    }
}
