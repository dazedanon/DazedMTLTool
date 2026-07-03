//! GamePro Pro (marker-3) save codec tests. The fixture-backed cases gate on the real GamePro-Pro
//! save and the ground-truth decrypted inner. They skip gracefully when those files are absent. The
//! LZ4 and pure-synthetic round-trips always run.

use std::collections::HashMap;

use wolf_core::codec::lz4;
use wolf_decompiler::save::{read_title_at, update_save};
use wolf_decompiler::save_pro::{self, decrypt_pro, encrypt_pro, is_pro_save, key16};

mod common;
use common::test_data;

const PACHIMON_SAVE: &str = "pachimon/SaveData01.sav";
const GROUND_TRUTH: &str = "pachimon/decrypted.bin";
const CHAMBER_SAVE: &str = "chamber/SaveData01.sav";

fn load(rel: &str) -> Option<Vec<u8>> {
    let p = test_data(rel)?;
    Some(std::fs::read(&p).expect("read fixture"))
}

/// Read the 16-bit key the encoder stamps into a produced save: `header[7] | header[4]<<8`.
fn stored_key16(save: &[u8]) -> u16 {
    save[7] as u16 | ((save[4] as u16) << 8)
}

/// (1) The hard gate: `decrypt_pro(real save)` is byte-exact with the ground-truth `decrypted.bin`.
#[test]
fn decrypt_matches_ground_truth() {
    let (Some(raw), Some(truth)) = (load(PACHIMON_SAVE), load(GROUND_TRUTH)) else {
        eprintln!("skip: pachimon save and/or ground-truth fixture not present");
        return;
    };
    let inner = decrypt_pro(&raw).expect("decrypt the real Pro save");
    assert_eq!(inner.len(), truth.len(), "inner length matches ground truth");
    assert_eq!(inner, truth, "decrypt_pro(real save) == decrypted.bin (byte-exact)");
    assert_eq!(inner[0], 0x19, "inner starts with the 0x19 title marker");
}

/// (2) Detection: the real Pro save is detected as Pro, and a standard (chamber) save is not.
#[test]
fn detection_pro_vs_standard() {
    if let Some(raw) = load(PACHIMON_SAVE) {
        assert!(is_pro_save(&raw), "real Pro save must be detected as Pro");
    } else {
        eprintln!("skip: pachimon save fixture not present");
    }
    if let Some(chamber) = load(CHAMBER_SAVE) {
        assert!(!is_pro_save(&chamber), "standard chamber save must not be Pro");
    } else {
        eprintln!("skip: chamber save fixture not present");
    }
}

/// (3) Round-trip on the real inner: `decrypt_pro(encrypt_pro(inner, header)) == inner`.
/// (4) key16 of the produced save validates against `header[7] | header[4]<<8`.
#[test]
fn roundtrip_real_inner_and_key16() {
    let Some(raw) = load(PACHIMON_SAVE) else {
        eprintln!("skip: pachimon save fixture not present");
        return;
    };
    let inner = decrypt_pro(&raw).expect("decrypt");
    let enc = encrypt_pro(&inner, &raw[..20]).expect("encrypt");
    let back = decrypt_pro(&enc).expect("re-decrypt");
    assert_eq!(back, inner, "encrypt->decrypt is identity on the real inner");

    // key16 the encoder stored must equal the fold of the inner with a4 = header[9].
    assert_eq!(stored_key16(&enc), key16(&inner, raw[9]), "produced key16 validates");
}

/// (5) Modified-inner round-trip: flip a byte in the inner, encrypt, then decrypt, which equals
/// the modified inner, and the stored key16 re-validates for the modified payload.
#[test]
fn modified_inner_roundtrip() {
    let Some(raw) = load(PACHIMON_SAVE) else {
        eprintln!("skip: pachimon save fixture not present");
        return;
    };
    let mut inner = decrypt_pro(&raw).expect("decrypt");
    // Flip a byte well past the header so the title marker stays intact.
    let i = inner.len() / 2;
    inner[i] ^= 0xFF;

    let enc = encrypt_pro(&inner, &raw[..20]).expect("encrypt modified");
    let back = decrypt_pro(&enc).expect("re-decrypt modified");
    assert_eq!(back, inner, "modified inner round-trips");
    assert_eq!(stored_key16(&enc), key16(&inner, raw[9]), "key16 valid for modified inner");
}

/// (6) LZ4: compress then decompress is identity on several buffers, including the ~1MB real inner.
#[test]
fn lz4_compress_decompress_identity() {
    let mut cases: Vec<Vec<u8>> = vec![
        Vec::new(),
        b"a".to_vec(),
        b"hello world hello world".to_vec(),
        vec![0u8; 5000],
        (0..4096u32).map(|i| (i % 251) as u8).collect(),
    ];
    if let Some(truth) = load(GROUND_TRUTH) {
        cases.push(truth); // the ~1MB real inner
    } else {
        eprintln!("note: ground-truth inner absent; testing smaller buffers only");
    }
    for data in &cases {
        let block = lz4::compress_block(data);
        let back = lz4::decompress_block(&block, data.len()).expect("lz4 decompress");
        assert_eq!(&back, data, "lz4 round-trip failed for {}-byte buffer", data.len());
    }
}

/// (7) End-to-end via `update_save` on the real Pro save: setting `--title "X"` updates it rather
/// than skipping, and re-decrypting yields an inner whose title reads "X" with the 0x19 marker
/// intact.
#[test]
fn update_save_pro_end_to_end() {
    let Some(raw) = load(PACHIMON_SAVE) else {
        eprintln!("skip: pachimon save fixture not present");
        return;
    };
    let (out, stats) = update_save(&raw, Some("X"), &HashMap::new())
        .expect("Pro save is now supported by update_save");
    assert!(stats.title_changed, "title was changed");
    assert_eq!(stats.encoding, "utf8");

    let inner = decrypt_pro(&out).expect("re-decrypt the updated Pro save");
    assert_eq!(inner[0], save_pro::INNER_MARKER, "0x19 marker intact in the updated inner");
    assert_eq!(read_title_at(&inner, 0, true).as_deref(), Some("X"), "title reads back as X");
    // The stored key16 still validates after the edit.
    assert_eq!(stored_key16(&out), key16(&inner, raw[9]));
}
