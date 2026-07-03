//! `.sav` auto-update tests. These exercise the real outer codec and the `update_save` pipeline
//! against actual game saves where present (skipping gracefully when the fixtures are absent), plus
//! a synthetic codec round-trip that always runs.

use std::collections::HashMap;

use wolf_core::codec::wolfsave;
use wolf_decompiler::save::{read_title, update_save};

mod common;
use common::test_data;

const CHAMBER_SAVE: &str = "chamber/SaveData01.sav";
const PACHIMON_SAVE: &str = "pachimon/SaveData01.sav";

const START_OFFSET: usize = 0x14;
const VALID_MARKER: u8 = 0x19;

fn load(rel: &str) -> Option<Vec<u8>> {
    let p = test_data(rel)?;
    Some(std::fs::read(&p).expect("read save fixture"))
}

/// (a) The codec round-trips a real save byte-for-byte. If the stored checksum already matches the
/// body (the normal case), `encrypt(decrypt(raw)) == raw` exactly. If it does not, we still require
/// the structural invariant (`[0x14] == 0x19`) and that a second decrypt of the re-encrypted bytes
/// reproduces the same plaintext (the checksum byte is the only possible difference).
#[test]
fn codec_roundtrips_real_chamber_save() {
    let Some(raw) = load(CHAMBER_SAVE) else {
        eprintln!("skip: chamber save fixture not present");
        return;
    };
    let plain = wolfsave::decrypt(&raw);
    assert!(plain.len() > START_OFFSET);
    assert_eq!(plain[START_OFFSET], VALID_MARKER, "chamber save must be a valid 0x19 save");

    let calc = plain[START_OFFSET..]
        .iter()
        .fold(0u8, |a, &b| a.wrapping_add(b));
    let reenc = wolfsave::encrypt(&plain);
    if calc == plain[2] {
        assert_eq!(reenc, raw, "stored checksum matches body -> encrypt(decrypt(raw)) is byte-exact");
    } else {
        // Checksum byte was stale on disk. Re-encrypt normalises it. Plaintext must still match.
        assert_eq!(wolfsave::decrypt(&reenc), plain, "re-decrypt reproduces the same plaintext");
    }
}

/// (b) `update_save` with an empty map and no new title re-encrypts to a buffer that decrypts back
/// to the original plaintext.
#[test]
fn update_save_noop_preserves_plaintext() {
    let Some(raw) = load(CHAMBER_SAVE) else {
        eprintln!("skip: chamber save fixture not present");
        return;
    };
    let plain = wolfsave::decrypt(&raw);
    let (out, stats) = update_save(&raw, None, &HashMap::new()).expect("supported save");
    assert!(!stats.title_changed);
    assert_eq!(stats.strings_replaced, 0);
    assert_eq!(wolfsave::decrypt(&out), plain, "no-op update preserves the plaintext");
}

/// (c) Setting a new title, then re-decrypting, reads the new value back at 0x15, and the 0x14
/// marker is still intact.
#[test]
fn update_save_sets_new_title() {
    let Some(raw) = load(CHAMBER_SAVE) else {
        eprintln!("skip: chamber save fixture not present");
        return;
    };
    let new = "Translated Title (Test)";
    let (out, stats) = update_save(&raw, Some(new), &HashMap::new()).expect("supported save");
    assert!(stats.title_changed);
    let plain = wolfsave::decrypt(&out);
    assert_eq!(plain[START_OFFSET], VALID_MARKER, "marker survives the title length shift");
    assert_eq!(read_title(&plain).as_deref(), Some(new));
}

/// (d) Synthetic codec unit test (always runs, no fixtures). Build a buffer with a correct
/// checksum, encrypt then decrypt, and confirm identity plus that the body actually changed.
#[test]
fn codec_roundtrips_synthetic() {
    let mut plain: Vec<u8> = (0u8..=255).cycle().take(START_OFFSET + 301).collect();
    plain[0] = 0x11;
    plain[3] = 0x22;
    plain[9] = 0x33;
    wolfsave::fix_checksum(&mut plain);
    let enc = wolfsave::encrypt(&plain);
    assert_eq!(wolfsave::decrypt(&enc), plain);
    assert_ne!(&enc[START_OFFSET..], &plain[START_OFFSET..], "body is actually enciphered");
    assert_eq!(&enc[..START_OFFSET], &plain[..START_OFFSET], "head carried verbatim");
}

/// The GamePro Pro (marker-3) save does not present as a standard save after the outer decrypt
/// (`[0x14] != 0x19`), but is handled by the Pro path. `update_save` accepts it and a re-decrypt
/// of the result reads the new title back. The Pro codec itself is exercised in
/// `save_pro_roundtrip.rs`.
#[test]
fn pachimon_save_handled_by_pro_path() {
    let Some(raw) = load(PACHIMON_SAVE) else {
        eprintln!("skip: pachimon save fixture not present");
        return;
    };
    // It is not a standard save: the standard decrypt does not yield the 0x19 marker at 0x14.
    let plain = wolfsave::decrypt(&raw);
    assert_ne!(plain[START_OFFSET], VALID_MARKER, "Pro save is not a standard 0x19 save");

    // But update_save now succeeds via the Pro path and writes the requested title.
    let (out, stats) = update_save(&raw, Some("X"), &HashMap::new())
        .expect("pro save must now be supported");
    assert!(stats.title_changed);
    assert_eq!(stats.encoding, "utf8");
    let inner = wolf_decompiler::save_pro::decrypt_pro(&out).expect("re-decrypt produced inner");
    assert_eq!(inner[0], VALID_MARKER, "inner 0x19 marker intact");
    assert_eq!(
        wolf_decompiler::save::read_title_at(&inner, 0, true).as_deref(),
        Some("X")
    );
}
