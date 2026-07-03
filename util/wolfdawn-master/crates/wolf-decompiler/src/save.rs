//! Wolf RPG `.sav` auto-update. Rewrites the baked game title and refreshes the baked
//! player-facing strings so a pre-translation save loads cleanly in the translated build.
//!
//! A `.sav` bakes in two things that go stale after a fan translation:
//!   1. The game identity/title. The translated build compares it against its own `Game.dat`
//!      title and rejects a mismatch ("trying to load from another game").
//!   2. Player-facing strings (item, skill, and mode names shown on the save-load screen) that
//!      still read in the original language.
//!
//! [`update_save`] decrypts the save with [`wolf_core::codec::wolfsave`], optionally splices in a
//! new title, replaces every baked length-prefixed string that exactly matches a translation
//! source, then re-encrypts. It reuses the same `source -> target` translation map the rest of
//! the pipeline applies to the game itself, so the save stays consistent with the translated
//! data files.
//!
//! ## Save plaintext layout used here
//! After the outer decrypt the buffer is plaintext. Byte `6 == 0x55` marks UTF-8 strings,
//! otherwise Shift-JIS. Byte `0x14 == 0x19` marks a valid, parseable save. The title follows at
//! `0x15` as a `u16` little-endian byte-length (counting a trailing NUL) plus that many bytes.
//! The body further contains many `[u32 le byteLen][bytes][NUL]` records (the u32 counts the
//! NUL) for the variable database and baked strings.
//!
//! ## GamePro Pro (marker-3) saves
//! If the standard decrypt does not yield a valid save (`byte[0x14] != 0x19`) but the buffer is a
//! GamePro Pro (marker-3) save (see [`save_pro`](crate::save_pro)), [`update_save`] decrypts the
//! Pro inner, applies the same title-fix and baked-string refresh to it, then re-encrypts with
//! [`save_pro::encrypt_pro`]. In the inner the `0x19` marker sits at offset 0, the title `u16`
//! length at `inner[1..3]`, and the title bytes at `inner[3..]`. Only a buffer that is neither a
//! standard save nor a detectable Pro save is refused with an `Err`.

use std::collections::HashMap;

use wolf_core::codec::wolfsave;

use crate::save_pro;

/// Marker byte (`0x19`) of a valid, parseable save. The title record follows immediately after.
const VALID_MARKER: u8 = 0x19;
/// Marker offset for a standard save's plaintext. The body marker lives at `0x14`.
const STD_MARKER_OFFSET: usize = wolfsave::START_OFFSET; // 0x14
/// Marker offset for a Pro inner save. The `0x19` marker lives at offset 0.
const PRO_MARKER_OFFSET: usize = 0;
/// Decrypted `byte[6] == 0x55` means strings are UTF-8, otherwise Shift-JIS. Only meaningful for
/// the standard plaintext. The Pro inner carries no such head and is always UTF-8.
const UTF8_FLAG_OFFSET: usize = 6;
const UTF8_FLAG_VALUE: u8 = 0x55;
/// Upper bound on a baked-string record's declared length.
const MAX_RECORD_LEN: usize = 1024 * 1024;

/// Which save codec a buffer uses, as reported by [`inspect_save`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SaveFormat {
    /// The standard Wolf RPG `.sav` (the `0x19` body marker at `0x14` after the outer decrypt).
    Standard,
    /// A GamePro Pro (marker-3) save (see [`save_pro`](crate::save_pro)).
    GameProPro,
    /// Neither a standard save nor a detectable GamePro Pro save. Editing is not supported.
    Unsupported,
}

impl SaveFormat {
    /// A short human label for the format badge.
    pub fn label(self) -> &'static str {
        match self {
            SaveFormat::Standard => "Standard",
            SaveFormat::GameProPro => "GamePro Pro",
            SaveFormat::Unsupported => "Unsupported",
        }
    }
}

/// The read-only contents of a save, for listing or editing in a UI before an [`update_save`]
/// write.
///
/// Produced by [`inspect_save`]: the detected [`format`](Self::format), the baked
/// [`title`](Self::title), the string [`encoding`](Self::encoding) (`"utf8"` or `"sjis"`), and
/// every baked length-prefixed [`strings`](Self::strings) record found in the body. These are the
/// same records [`update_save`] can replace.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SaveInfo {
    /// Which codec the save uses.
    pub format: SaveFormat,
    /// The baked game title (empty for an `Unsupported` save).
    pub title: String,
    /// The save's string encoding: `"utf8"` or `"sjis"`.
    pub encoding: &'static str,
    /// Every baked, length-prefixed string in the body, in file order. Deduplication is the
    /// caller's choice. Empty for an `Unsupported` save.
    pub strings: Vec<String>,
}

/// What [`update_save`] did to one save file.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SaveUpdateStats {
    /// The baked title was rewritten.
    pub title_changed: bool,
    /// How many baked length-prefixed strings were replaced via the translation map.
    pub strings_replaced: usize,
    /// The save's string encoding: `"utf8"` or `"sjis"`.
    pub encoding: &'static str,
}

/// Update a single raw `.sav` buffer. Decrypt, optionally set a new title, refresh baked strings
/// from `strings` (encoding-aware), and re-encrypt.
///
/// * `raw`: the on-disk encrypted save bytes.
/// * `new_title`: `Some(title)` to rewrite the baked title literally, `None` to leave it.
/// * `strings`: a `source -> target` map. Any baked record whose decoded text exactly equals a
///   `source` is replaced with the encoded `target`, re-prefixed. Entries where `source ==
///   target` or either side is empty are inert.
///
/// Returns the re-encrypted bytes plus [`SaveUpdateStats`], or `Err` if the save uses an
/// unsupported encryption (`byte[0x14] != 0x19` after decrypt) or is too small to be a valid
/// save.
pub fn update_save(
    raw: &[u8],
    new_title: Option<&str>,
    strings: &HashMap<String, String>,
) -> Result<(Vec<u8>, SaveUpdateStats), String> {
    let mut plain = wolfsave::decrypt(raw);

    // Standard save: the body marker `0x19` is at 0x14, with the title length field after it.
    if plain.len() > STD_MARKER_OFFSET + 2 && plain[STD_MARKER_OFFSET] == VALID_MARKER {
        let utf8 = plain.get(UTF8_FLAG_OFFSET) == Some(&UTF8_FLAG_VALUE);
        let title_changed = match new_title {
            Some(t) => set_title(&mut plain, STD_MARKER_OFFSET, t, utf8)?,
            None => false,
        };
        let strings_replaced = replace_baked_strings(&mut plain, strings, utf8);
        let out = wolfsave::encrypt(&plain);
        return Ok((
            out,
            SaveUpdateStats {
                title_changed,
                strings_replaced,
                encoding: if utf8 { "utf8" } else { "sjis" },
            },
        ));
    }

    // GamePro Pro (marker-3) save: the standard decrypt produced no valid save, so try the Pro
    // path. The Pro inner starts with the `0x19` marker at offset 0 and is always UTF-8.
    if save_pro::is_pro_save(raw) {
        let mut inner = save_pro::decrypt_pro(raw)?;
        let utf8 = true;
        let title_changed = match new_title {
            Some(t) => set_title(&mut inner, PRO_MARKER_OFFSET, t, utf8)?,
            None => false,
        };
        let strings_replaced = replace_baked_strings(&mut inner, strings, utf8);
        let out = save_pro::encrypt_pro(&inner, &raw[..STD_MARKER_OFFSET])?;
        return Ok((
            out,
            SaveUpdateStats {
                title_changed,
                strings_replaced,
                encoding: "utf8",
            },
        ));
    }

    Err(
        "unsupported save encryption (not a standard 0x19 save and not a detectable GamePro Pro \
         marker-3 save); skipping to avoid corruption"
            .to_string(),
    )
}

/// Inspect a raw `.sav` buffer read-only. Detects its [`SaveFormat`], decodes the baked title,
/// and lists every baked length-prefixed string in the body. Reuses the same decrypt, title-read,
/// and record-scan as [`update_save`], so what `inspect_save` lists is exactly what `update_save`
/// can rewrite.
///
/// Never panics. A save whose format is handled returns `Ok(SaveInfo{ format:
/// Standard|GameProPro, .. })`. A buffer that is neither a standard `0x19` save nor a detectable
/// GamePro Pro save returns `Ok(SaveInfo{ format: Unsupported, title: "", encoding: "utf8",
/// strings: [] })` rather than an error, so a UI can show a clear "not supported" state. The only
/// `Err` is a Pro-marker buffer whose inner decrypt itself fails (a corrupt or truncated Pro
/// save).
pub fn inspect_save(raw: &[u8]) -> Result<SaveInfo, String> {
    let plain = wolfsave::decrypt(raw);

    // Standard save: the body marker `0x19` is at 0x14.
    if plain.len() > STD_MARKER_OFFSET + 2 && plain[STD_MARKER_OFFSET] == VALID_MARKER {
        let utf8 = plain.get(UTF8_FLAG_OFFSET) == Some(&UTF8_FLAG_VALUE);
        let title = read_title_at(&plain, STD_MARKER_OFFSET, utf8).unwrap_or_default();
        let strings = collect_baked_strings(&plain, utf8);
        return Ok(SaveInfo {
            format: SaveFormat::Standard,
            title,
            encoding: if utf8 { "utf8" } else { "sjis" },
            strings,
        });
    }

    // GamePro Pro (marker-3) save. The Pro inner starts with `0x19` at offset 0 and is always UTF-8.
    if save_pro::is_pro_save(raw) {
        let inner = save_pro::decrypt_pro(raw)?;
        let utf8 = true;
        let title = read_title_at(&inner, PRO_MARKER_OFFSET, utf8).unwrap_or_default();
        let strings = collect_baked_strings(&inner, utf8);
        return Ok(SaveInfo {
            format: SaveFormat::GameProPro,
            title,
            encoding: "utf8",
            strings,
        });
    }

    // Neither codec handled it. Report Unsupported rather than erroring, so the UI can disable
    // editing with a clear note instead of failing.
    Ok(SaveInfo {
        format: SaveFormat::Unsupported,
        title: String::new(),
        encoding: "utf8",
        strings: Vec::new(),
    })
}

/// Read the baked title of a standard decrypted save (marker at `0x14`). Returns the decoded
/// title with its trailing NUL stripped, or `None` for an unsupported or malformed buffer. Used
/// by tests and callers that want to confirm a title write landed. For a Pro inner, use
/// [`read_title_at`]`(inner, 0)`.
pub fn read_title(plain: &[u8]) -> Option<String> {
    let utf8 = plain.get(UTF8_FLAG_OFFSET) == Some(&UTF8_FLAG_VALUE);
    read_title_at(plain, STD_MARKER_OFFSET, utf8)
}

/// Read the baked title given the marker offset (`0x14` for a standard plaintext, `0` for a Pro
/// inner) and the file's string encoding. The title length `u16` sits at `marker+1` and the title
/// bytes follow at `marker+3`. Returns the decoded title with its trailing NUL stripped.
pub fn read_title_at(plain: &[u8], marker_offset: usize, utf8: bool) -> Option<String> {
    let len_off = marker_offset + 1;
    if plain.len() <= len_off + 1 || plain.get(marker_offset) != Some(&VALID_MARKER) {
        return None;
    }
    let size = u16::from_le_bytes([plain[len_off], plain[len_off + 1]]) as usize;
    let start = len_off + 2;
    let end = start.checked_add(size)?;
    if end > plain.len() {
        return None;
    }
    let body = plain[start..end].strip_suffix(&[0u8])?; // the length counts a trailing NUL.
    Some(decode(body, utf8))
}

/// Splice a new title into a decrypted buffer, shifting the remainder. `marker_offset` is `0x14`
/// for a standard plaintext or `0` for a Pro inner. The title length `u16` lives at `marker+1`
/// and the title bytes at `marker+3`. The on-disk form is `u16(len(bytes_with_nul)) +
/// bytes_with_nul` in the file encoding. Returns `Ok(true)` on success, `Err` if the new title is
/// not representable in the file's encoding.
fn set_title(
    plain: &mut Vec<u8>,
    marker_offset: usize,
    title: &str,
    utf8: bool,
) -> Result<bool, String> {
    let len_off = marker_offset + 1;
    let old_size = u16::from_le_bytes([plain[len_off], plain[len_off + 1]]) as usize;
    let old_start = len_off + 2;
    let old_end = old_start
        .checked_add(old_size)
        .filter(|&e| e <= plain.len())
        .ok_or_else(|| "save title length runs past end of buffer".to_string())?;

    let mut title_bytes = encode(title, utf8).ok_or_else(|| {
        format!(
            "new title not representable in {}: {title:?}",
            if utf8 { "UTF-8" } else { "Shift-JIS" }
        )
    })?;
    title_bytes.push(0); // the stored length counts the trailing NUL.
    let len: u16 = title_bytes
        .len()
        .try_into()
        .map_err(|_| "new title is too long to encode as a u16 length".to_string())?;

    let mut replacement = Vec::with_capacity(2 + title_bytes.len());
    replacement.extend_from_slice(&len.to_le_bytes());
    replacement.extend_from_slice(&title_bytes);
    // Splice from the old length field, inclusive, through the old title bytes, shifting the rest.
    plain.splice(len_off..old_end, replacement);
    Ok(true)
}

/// Try to decode the `[u32 le byteLen][bytes][NUL]` record starting at `offset`. Returns
/// `Some((text, end))` when `offset` begins a valid record, else `None`. The tuple is the
/// cleanly-decoded payload text with NUL stripped and the byte index one past the record. A
/// record is valid when its declared length is `0 < len <= MAX_RECORD_LEN`, the record fits the
/// buffer, the payload ends in exactly one NUL with none interior, and it decodes cleanly in the
/// file encoding. This is the shared scan step used by both the read-only [`inspect_save`] walk
/// and the replacing [`replace_baked_strings`] walk, so the two never disagree about what counts
/// as a string record.
fn read_record_at(plain: &[u8], offset: usize, utf8: bool) -> Option<(String, usize)> {
    if offset + 5 > plain.len() {
        return None;
    }
    let size = u32::from_le_bytes([
        plain[offset],
        plain[offset + 1],
        plain[offset + 2],
        plain[offset + 3],
    ]) as usize;
    let end = offset + 4 + size;
    if size == 0 || size > MAX_RECORD_LEN || end > plain.len() {
        return None;
    }
    let payload = &plain[offset + 4..end];
    // Exactly one trailing NUL, none interior.
    if payload.last() != Some(&0) || payload[..payload.len() - 1].contains(&0) {
        return None;
    }
    let text = decode_strict(&payload[..payload.len() - 1], utf8)?;
    Some((text, end))
}

/// Collect every baked length-prefixed string in the decrypted buffer, in file order, using the
/// same record scan [`replace_baked_strings`] uses. Drives [`inspect_save`]'s string list.
fn collect_baked_strings(plain: &[u8], utf8: bool) -> Vec<String> {
    let mut out = Vec::new();
    let mut offset = 0usize;
    while offset + 5 <= plain.len() {
        if let Some((text, end)) = read_record_at(plain, offset, utf8) {
            out.push(text);
            offset = end;
        } else {
            offset += 1;
        }
    }
    out
}

/// Scan the decrypted buffer for `[u32 le byteLen][bytes][NUL]` records and replace any whose
/// decoded text exactly matches a translation `source` with the encoded `target`, re-prefixed.
///
/// Uses the shared [`read_record_at`] scan step. The walk continues past each replacement using
/// the new record's length, so adjacent records are still seen. Returns the number of records
/// replaced.
fn replace_baked_strings(
    plain: &mut Vec<u8>,
    strings: &HashMap<String, String>,
    utf8: bool,
) -> usize {
    // Pre-encode the replacement records once. Skip no-op, empty, or unrepresentable entries.
    let records: HashMap<String, Vec<u8>> = strings
        .iter()
        .filter(|(s, t)| !s.is_empty() && !t.is_empty() && s != t)
        .filter_map(|(s, t)| encode_record(t, utf8).map(|rec| (s.clone(), rec)))
        .collect();
    if records.is_empty() {
        return 0;
    }

    let mut count = 0usize;
    let mut offset = 0usize;
    while offset + 5 <= plain.len() {
        match read_record_at(plain, offset, utf8) {
            Some((text, end)) => {
                if let Some(replacement) = records.get(&text) {
                    let rep_len = replacement.len();
                    plain.splice(offset..end, replacement.iter().copied());
                    offset += rep_len;
                    count += 1;
                } else {
                    // Valid record but no translation hit. Skip the whole record.
                    offset = end;
                }
            }
            None => offset += 1,
        }
    }
    count
}

/// Build a length-prefixed record for `text`: `u32 le (bytes+NUL len) + bytes + NUL`. Returns
/// `None` if `text` is not representable in the file encoding.
fn encode_record(text: &str, utf8: bool) -> Option<Vec<u8>> {
    let mut bytes = encode(text, utf8)?;
    bytes.push(0);
    let len = u32::try_from(bytes.len()).ok()?;
    let mut rec = Vec::with_capacity(4 + bytes.len());
    rec.extend_from_slice(&len.to_le_bytes());
    rec.extend_from_slice(&bytes);
    Some(rec)
}

/// Encode `text` into the file encoding (UTF-8 as-is, or Shift-JIS/CP932). `None` if a character
/// is not representable in Shift-JIS.
fn encode(text: &str, utf8: bool) -> Option<Vec<u8>> {
    if utf8 {
        Some(text.as_bytes().to_vec())
    } else {
        let (bytes, _, had_err) = encoding_rs::SHIFT_JIS.encode(text);
        (!had_err).then(|| bytes.into_owned())
    }
}

/// Lossy decode for display (used to read a title back).
fn decode(bytes: &[u8], utf8: bool) -> String {
    if utf8 {
        String::from_utf8_lossy(bytes).into_owned()
    } else {
        encoding_rs::SHIFT_JIS.decode(bytes).0.into_owned()
    }
}

/// Strict decode used by the record scanner. `None` if the bytes do not decode cleanly in the
/// file encoding, so a binary record is never mistaken for a translatable string.
fn decode_strict(bytes: &[u8], utf8: bool) -> Option<String> {
    if utf8 {
        std::str::from_utf8(bytes).ok().map(str::to_owned)
    } else {
        let (text, _, had_err) = encoding_rs::SHIFT_JIS.decode(bytes);
        (!had_err).then(|| text.into_owned())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Resolve a fixture by its clean relative path under `WOLFDAWN_TEST_DATA`. Returns `None` when
    /// the var is unset or the file is missing, so the fixture-backed tests skip gracefully.
    fn test_data(rel: &str) -> Option<std::path::PathBuf> {
        let base = std::env::var_os("WOLFDAWN_TEST_DATA")?;
        let p = std::path::Path::new(&base).join(rel);
        p.exists().then_some(p)
    }

    /// Assemble a minimal synthetic decrypted save: a 0x14-byte head with the markers set, a
    /// title record at 0x15, then `body` such as baked string records. Encoding is UTF-8.
    fn build_plain(title: &str, body: &[u8]) -> Vec<u8> {
        let mut p = vec![0u8; wolfsave::START_OFFSET];
        p[UTF8_FLAG_OFFSET] = UTF8_FLAG_VALUE; // UTF-8 flag
        p.push(VALID_MARKER); // byte 0x14, valid-save marker
        // Title record at 0x15.
        let mut tb = title.as_bytes().to_vec();
        tb.push(0);
        p.extend_from_slice(&(tb.len() as u16).to_le_bytes());
        p.extend_from_slice(&tb);
        p.extend_from_slice(body);
        p
    }

    fn record(text: &str) -> Vec<u8> {
        encode_record(text, true).unwrap()
    }

    #[test]
    fn title_read_back_after_set() {
        let mut p = build_plain("元のタイトル", &[]);
        assert_eq!(read_title(&p).as_deref(), Some("元のタイトル"));
        set_title(&mut p, STD_MARKER_OFFSET, "New Title", true).unwrap();
        assert_eq!(read_title(&p).as_deref(), Some("New Title"));
        // Marker still intact after the length shift.
        assert_eq!(p[STD_MARKER_OFFSET], VALID_MARKER);
    }

    #[test]
    fn baked_string_replacement_shifts_and_continues() {
        // Two adjacent records. Only the first is translated. The scan must still see the second.
        let mut body = record("こんにちは");
        body.extend_from_slice(&record("Keep me"));
        let mut p = build_plain("T", &body);

        let mut map = HashMap::new();
        map.insert("こんにちは".to_string(), "Hello".to_string());
        let n = replace_baked_strings(&mut p, &map, true);
        assert_eq!(n, 1);

        // The replaced record now decodes to the target. "Keep me" is untouched and still present.
        // Re-scan for "Hello" by reading the record right after the title.
        let len_off = STD_MARKER_OFFSET + 1;
        let title_len = u16::from_le_bytes([p[len_off], p[len_off + 1]]) as usize;
        let mut off = len_off + 2 + title_len;
        let size =
            u32::from_le_bytes([p[off], p[off + 1], p[off + 2], p[off + 3]]) as usize;
        let payload = &p[off + 4..off + 4 + size];
        assert_eq!(&payload[..payload.len() - 1], b"Hello");
        off += 4 + size;
        let size2 =
            u32::from_le_bytes([p[off], p[off + 1], p[off + 2], p[off + 3]]) as usize;
        let payload2 = &p[off + 4..off + 4 + size2];
        assert_eq!(&payload2[..payload2.len() - 1], b"Keep me");
    }

    #[test]
    fn update_save_roundtrips_with_no_changes() {
        let mut p = build_plain("チャンバーゲーム", &record("アイテム"));
        // Give the synthetic plaintext a correct checksum so a no-op re-encrypt is byte-exact.
        // A real save already has this. `update_save` recomputes byte 2 on every write.
        wolfsave::fix_checksum(&mut p);
        let raw = wolfsave::encrypt(&p);
        let (out, stats) = update_save(&raw, None, &HashMap::new()).unwrap();
        assert!(!stats.title_changed);
        assert_eq!(stats.strings_replaced, 0);
        assert_eq!(stats.encoding, "utf8");
        // Decrypting the output reproduces the original plaintext.
        assert_eq!(wolfsave::decrypt(&out), p);
    }

    #[test]
    fn update_save_rejects_unsupported() {
        // byte[0x14] != 0x19 is unsupported.
        let mut p = build_plain("T", &[]);
        p[wolfsave::START_OFFSET] = 0x68;
        let raw = wolfsave::encrypt(&p);
        let err = update_save(&raw, Some("X"), &HashMap::new()).unwrap_err();
        assert!(err.contains("unsupported"), "got: {err}");
    }

    #[test]
    fn update_save_sets_title_and_replaces() {
        let p = build_plain("旧題", &record("ルビー"));
        let raw = wolfsave::encrypt(&p);
        let mut map = HashMap::new();
        map.insert("ルビー".to_string(), "Ruby".to_string());
        let (out, stats) = update_save(&raw, Some("Translated Title"), &map).unwrap();
        assert!(stats.title_changed);
        assert_eq!(stats.strings_replaced, 1);
        let plain = wolfsave::decrypt(&out);
        assert_eq!(read_title(&plain).as_deref(), Some("Translated Title"));
    }

    /// `inspect_save` on a synthetic standard save reports the format, encoding, title, and the
    /// baked strings. `update_save` with an `{old->new}` map drawn from that list round-trips, so
    /// a re-inspect shows the new string and title.
    #[test]
    fn inspect_then_update_round_trips_synthetic() {
        let mut body = record("アイテム");
        body.extend_from_slice(&record("スキル"));
        let p = build_plain("元のタイトル", &body);
        let raw = wolfsave::encrypt(&p);

        let info = inspect_save(&raw).expect("inspect");
        assert_eq!(info.format, SaveFormat::Standard);
        assert_eq!(info.encoding, "utf8");
        assert_eq!(info.title, "元のタイトル");
        assert!(info.strings.contains(&"アイテム".to_string()));
        assert!(info.strings.contains(&"スキル".to_string()));

        // Build the {old->new} map from inspect's own list, then update the title and one string.
        let original = info.strings[0].clone();
        let mut map = HashMap::new();
        map.insert(original.clone(), "Item".to_string());
        let (out, stats) = update_save(&raw, Some("New Title"), &map).unwrap();
        assert!(stats.title_changed);
        assert_eq!(stats.strings_replaced, 1);

        // Re-inspect the written bytes. The new title and string are present, the old string is gone.
        let re = inspect_save(&out).expect("re-inspect");
        assert_eq!(re.format, SaveFormat::Standard);
        assert_eq!(re.title, "New Title");
        assert!(re.strings.contains(&"Item".to_string()));
        assert!(!re.strings.contains(&original));
    }

    /// `inspect_save` returns `Unsupported` for a non-save buffer, never panicking or erroring.
    #[test]
    fn inspect_unsupported_buffer() {
        // byte[0x14] != 0x19 and not a Pro save is Unsupported.
        let mut p = build_plain("T", &[]);
        p[wolfsave::START_OFFSET] = 0x68;
        let raw = wolfsave::encrypt(&p);
        let info = inspect_save(&raw).expect("inspect should not error");
        assert_eq!(info.format, SaveFormat::Unsupported);
        assert!(info.title.is_empty());
        assert!(info.strings.is_empty());
    }

    /// On a real save fixture, skipped if absent, `inspect_save` returns a non-empty title and the
    /// `update_save` map drawn from `inspect_save(...).strings` round-trips through a re-inspect.
    #[test]
    fn inspect_then_update_round_trips_real_save() {
        let candidates = ["chamber/SaveData01.sav", "pachimon/SaveData01.sav"];
        let mut ran = 0;
        for rel in candidates {
            let Some(path) = test_data(rel) else {
                continue;
            };
            let Ok(raw) = std::fs::read(&path) else {
                continue;
            };
            let path = path.display();
            let info = match inspect_save(&raw) {
                Ok(i) if i.format != SaveFormat::Unsupported => i,
                _ => continue,
            };
            ran += 1;
            assert!(!info.title.is_empty(), "{path}: title should not be empty");

            // Pick the first baked string that can re-encode in this save's encoding and rewrite it.
            let new_title = format!("{} [T]", info.title);
            let mut map = HashMap::new();
            let mut chosen: Option<String> = None;
            for s in &info.strings {
                if s.is_empty() || s.contains('[') {
                    continue;
                }
                let edited = format!("{s} X");
                if encode(&edited, info.encoding == "utf8").is_some() {
                    map.insert(s.clone(), edited.clone());
                    chosen = Some(edited);
                    break;
                }
            }

            let (out, stats) =
                update_save(&raw, Some(&new_title), &map).expect("update real save");
            assert!(stats.title_changed);
            assert_eq!(stats.encoding, info.encoding);

            let re = inspect_save(&out).expect("re-inspect real save");
            assert_eq!(re.format, info.format, "{path}: format must be preserved");
            assert_eq!(re.title, new_title, "{path}: new title should re-inspect");
            if let Some(edited) = chosen {
                // The same baked text can appear in several save slots. All matching records are
                // replaced, so assert at least one rather than exactly one.
                assert!(stats.strings_replaced >= 1);
                assert!(
                    re.strings.contains(&edited),
                    "{path}: the edited baked string should re-inspect"
                );
            }
        }
        if ran == 0 {
            eprintln!("skip inspect_then_update_round_trips_real_save: no save fixture present");
        }
    }
}
