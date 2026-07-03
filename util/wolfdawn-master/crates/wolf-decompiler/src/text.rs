//! Shared string decoding for the readable layer. Wolf strings are raw bytes, either
//! Shift-JIS or UTF-8 depending on the file. Decode them to a UTF-8 `String` for
//! display and names.

use wolf_formats::WStr;

/// Decode a Wolf string to UTF-8, trimming the trailing NUL UTF-8 files carry.
pub fn decode_wstr(s: &WStr, utf8: bool) -> String {
    let mut bytes = s.as_bytes();
    if utf8 && bytes.last() == Some(&0) {
        bytes = &bytes[..bytes.len() - 1];
    }
    if utf8 {
        String::from_utf8_lossy(bytes).into_owned()
    } else {
        let (text, _, _) = encoding_rs::SHIFT_JIS.decode(bytes);
        text.into_owned()
    }
}

/// Decode and escape a string for a WolfScript double-quoted literal.
pub fn quote_wstr(s: &WStr, utf8: bool) -> String {
    escape_literal(&decode_wstr(s, utf8))
}

/// Render a Wolf string as a byte-exact WolfScript literal. Emits a readable `"text"` when
/// the bytes decode and re-encode identically in the file's encoding, otherwise a raw
/// `x"HEX"` literal carrying the exact bytes including the trailing NUL. The inverse is
/// [`text_to_wstr`] (or the hex path). Used by the recompilable renderer so strings
/// round-trip in any encoding, including inside block openers that bypass the per-command
/// `@raw` fallback.
pub fn wstr_to_literal(w: &WStr, utf8: bool) -> String {
    match clean_literal_text(w, utf8) {
        Some(text) => escape_literal(&text),
        None => format!("x\"{}\"", to_hex(w.as_bytes())),
    }
}

/// Encode already-unescaped literal text into a Wolf string (file encoding + trailing NUL).
/// Errors if the text can't be represented in the file's encoding (e.g. a non-Shift-JIS char
/// hand-typed into a Shift-JIS file).
pub fn text_to_wstr(text: &str, utf8: bool) -> Result<WStr, String> {
    let mut bytes = encode_body(text, utf8).ok_or_else(|| {
        format!(
            "text not representable in {}: {text:?}",
            if utf8 { "UTF-8" } else { "Shift-JIS" }
        )
    })?;
    bytes.push(0);
    Ok(WStr(bytes))
}

/// Decode a string for a readable literal only when it round-trips byte-exact, else `None` to
/// use hex.
fn clean_literal_text(w: &WStr, utf8: bool) -> Option<String> {
    let body = w.as_bytes().strip_suffix(&[0u8])?; // Wolf strings carry a trailing NUL.
    let text = if utf8 {
        std::str::from_utf8(body).ok()?.to_owned()
    } else {
        let (t, _, had_err) = encoding_rs::SHIFT_JIS.decode(body);
        if had_err {
            return None;
        }
        t.into_owned()
    };
    // Control chars other than tab/CR/LF have no readable escaped form. Keep them in hex.
    if text
        .chars()
        .any(|c| c.is_control() && !matches!(c, '\t' | '\n' | '\r'))
    {
        return None;
    }
    (encode_body(&text, utf8)?.as_slice() == body).then_some(text)
}

fn encode_body(text: &str, utf8: bool) -> Option<Vec<u8>> {
    if utf8 {
        Some(text.as_bytes().to_vec())
    } else {
        let (bytes, _, had_err) = encoding_rs::SHIFT_JIS.encode(text);
        (!had_err).then(|| bytes.into_owned())
    }
}

fn escape_literal(text: &str) -> String {
    let esc = text
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\r', "\\r")
        .replace('\n', "\\n")
        .replace('\t', "\\t");
    format!("\"{esc}\"")
}

fn to_hex(bytes: &[u8]) -> String {
    use std::fmt::Write;
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        let _ = write!(s, "{b:02x}");
    }
    s
}
