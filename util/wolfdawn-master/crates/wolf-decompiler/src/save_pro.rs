//! GamePro Pro (marker-3) `.sav` codec. The newer Wolf RPG "Pro" save encryption used by some
//! GamePro-Pro titles. Where the standard outer codec ([`wolf_core::codec::wolfsave`]) is a 3-pass
//! MSVCRT-`rand` XOR, the Pro path layers an MT19937-keyed XOR keystream, a self-inverse 20-byte
//! block swap, and an LZ4-compressed body, plus a checksum-derived 16-bit key the game validates
//! on load.
//!
//! Verified to decrypt a real GamePro-Pro save identically to the game and to round-trip
//! encrypt then decrypt. The algorithm is summarised inline below.
//!
//! ## On-disk layout
//! `[0x00..0x14] plaintext header` then the encrypted body
//! `[u32-LE uncompLen][u32-LE compLen][LZ4 block]`. The body, everything from `0x14`, is
//! enciphered. The decrypted inner save begins with the `0x19` title marker at offset 0, not at
//! `0x14` as in a standard save. The `u16` title length sits at `inner[1..3]` and the title bytes
//! follow at `inner[3..]`.
//!
//! ## Pipeline
//! * seed3 = `{file[0], file[1], file[5]}`. If all three are zero the body is plain, no cipher.
//! * MT seed = `combined = (s0<<16)|(s1<<8)|s2` folded through one xorshift32 round.
//! * padtable[128] = the low byte of each of the first 128 MT19937 outputs.
//! * block_swap = swap `file[0x16..0x2a]` with `file[0x5c..0x70]`, self-inverse.
//! * xor = `buf[off] ^= padtable[off & 0x7f]` for `off` in `0x14..len`.
//! * Decrypt: block_swap, then xor, then LZ4-decompress the framed body.
//! * Encrypt: LZ4-compress, frame, write key16 into the header, xor, then block_swap.

use wolf_core::codec::lz4;

/// First body offset. Bytes `0x00..0x14` (the header) are never enciphered.
const BODY_OFFSET: usize = 0x14;
/// The two 20-byte regions exchanged by [`block_swap`]: `file[0x16..0x2a]` and `file[0x5c..0x70]`.
const SWAP_A: usize = 0x16;
const SWAP_B: usize = 0x5c;
const SWAP_LEN: usize = 0x14;
/// `block_swap`, and therefore the whole Pro cipher, needs at least this many bytes.
const MIN_FILE_SIZE: usize = SWAP_B + SWAP_LEN; // 0x70
/// The XOR pad table length. Indexed by `off & 0x7f`.
const PAD_LEN: usize = 128;
/// The decrypted inner save's valid-save marker, at inner offset 0.
pub const INNER_MARKER: u8 = 0x19;

// ---------------------------------------------------------------------------------------------
// MT19937 + seeding
// ---------------------------------------------------------------------------------------------

const N: usize = 624;
const M: usize = 397;
const MATRIX_A: u32 = 0x9908_b0df;
const UPPER_MASK: u32 = 0x8000_0000;
const LOWER_MASK: u32 = 0x7fff_ffff;

/// Standard MT19937. Init constant 1812433253, temper masks 0x9d2c5680 and 0xefc60000.
struct Mt19937 {
    mt: [u32; N],
    idx: usize,
}

impl Mt19937 {
    fn new(seed: u32) -> Self {
        let mut mt = [0u32; N];
        mt[0] = seed;
        for i in 1..N {
            mt[i] = 1_812_433_253u32
                .wrapping_mul(mt[i - 1] ^ (mt[i - 1] >> 30))
                .wrapping_add(i as u32);
        }
        Mt19937 { mt, idx: N }
    }

    fn next_u32(&mut self) -> u32 {
        if self.idx >= N {
            for i in 0..N {
                let y = (self.mt[i] & UPPER_MASK) | (self.mt[(i + 1) % N] & LOWER_MASK);
                let mut next = self.mt[(i + M) % N] ^ (y >> 1);
                if y & 1 != 0 {
                    next ^= MATRIX_A;
                }
                self.mt[i] = next;
            }
            self.idx = 0;
        }
        let mut y = self.mt[self.idx];
        self.idx += 1;
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c_5680;
        y ^= (y << 15) & 0xefc6_0000;
        y ^= y >> 18;
        y
    }
}

/// Derive the MT seed from the three header seed bytes. Assemble big-endian
/// `combined = (s0<<16)|(s1<<8)|s2`, then run one xorshift32 round (`x^=x<<13`, `x^=x>>17`,
/// `x^=x<<5`).
fn mt_seed_from_bytes(s0: u8, s1: u8, s2: u8) -> u32 {
    let mut x = ((s0 as u32) << 16) | ((s1 as u32) << 8) | (s2 as u32);
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    x
}

/// Build the 128-byte XOR pad table from the low byte of each of the first 128 MT19937 outputs.
fn build_padtable(s0: u8, s1: u8, s2: u8) -> [u8; PAD_LEN] {
    let mut mt = Mt19937::new(mt_seed_from_bytes(s0, s1, s2));
    let mut pad = [0u8; PAD_LEN];
    for slot in pad.iter_mut() {
        *slot = (mt.next_u32() & 0xff) as u8;
    }
    pad
}

// ---------------------------------------------------------------------------------------------
// block swap and xor cipher (both operate in place)
// ---------------------------------------------------------------------------------------------

/// Swap the two 20-byte blocks `buf[0x16..0x2a]` and `buf[0x5c..0x70]`. Self-inverse, so the same
/// call appears in both the decrypt and encrypt pipelines. The caller guarantees `buf.len() >=
/// 0x70`.
fn block_swap(buf: &mut [u8]) {
    debug_assert!(buf.len() >= MIN_FILE_SIZE);
    for i in 0..SWAP_LEN {
        buf.swap(SWAP_A + i, SWAP_B + i);
    }
}

/// XOR the body (`buf[0x14..]`) with the repeating 128-byte pad, indexed by `off & 0x7f`.
fn xor_cipher(buf: &mut [u8], pad: &[u8; PAD_LEN]) {
    for (off, byte) in buf.iter_mut().enumerate().skip(BODY_OFFSET) {
        *byte ^= pad[off & (PAD_LEN - 1)];
    }
}

// ---------------------------------------------------------------------------------------------
// key16 (the game validates this on marker-3 load, and a mismatch fails the load)
// ---------------------------------------------------------------------------------------------

/// Fold the decompressed inner save into the 16-bit key the game stores at
/// `header[7] | header[4]<<8`.
///
/// `v5` is the XOR of the 16-byte-aligned prefix `inner[0 .. 16*(len/16)]`. `v13` is the XOR of
/// every inner byte. Both are taken as 16-bit values with a zero high byte. `a4 = header[9]`, and
/// `a4 % 3` selects one of three polynomials.
pub fn key16(inner: &[u8], a4: u8) -> u16 {
    let aligned = (inner.len() / 16) * 16;
    let mut v5: u32 = 0;
    for &b in &inner[..aligned] {
        v5 ^= b as u32;
    }
    let mut v13 = v5;
    for &b in &inner[aligned..] {
        v13 ^= b as u32;
    }
    v5 &= 0xffff;
    v13 &= 0xffff;

    let a4 = a4 as u32;
    let na = !a4; // ~a4 over u32
    let key = match a4 % 3 {
        0 => 7u32.wrapping_mul(v13 ^ a4).wrapping_add(17),
        1 => a4.wrapping_add(v13 ^ (((16 * a4) | (a4 >> 4)) ^ 0x55)),
        _ => a4 ^ (3u32.wrapping_mul((v5 ^ na).wrapping_add(51)) & 0xffff),
    };
    (key & 0xffff) as u16
}

// ---------------------------------------------------------------------------------------------
// public codec API
// ---------------------------------------------------------------------------------------------

/// Decrypt a raw Pro (marker-3) `.sav` buffer into its inner save: the LZ4-decompressed
/// plaintext, beginning with the `0x19` title marker at offset 0.
///
/// Returns `Err` if the buffer is too small for the Pro cipher, the framed lengths are
/// inconsistent, or LZ4 decompression fails. If the three seed bytes are all zero the body is
/// stored plain and the framed body is decompressed directly.
pub fn decrypt_pro(raw: &[u8]) -> Result<Vec<u8>, String> {
    if raw.len() < BODY_OFFSET {
        return Err(format!(
            "pro save too small ({} bytes; need at least {BODY_OFFSET})",
            raw.len()
        ));
    }
    let (s0, s1, s2) = (raw[0], raw[1], raw[5]);

    let mut buf = raw.to_vec();
    // No cipher when the seed bytes are all zero. The body is stored plain. The block_swap regions
    // only exist for files of at least 0x70 bytes, and an enciphered file is always larger.
    if (s0 | s1 | s2) != 0 {
        if raw.len() < MIN_FILE_SIZE {
            return Err(format!(
                "pro save too small for the block swap ({} bytes; need at least {MIN_FILE_SIZE})",
                raw.len()
            ));
        }
        let pad = build_padtable(s0, s1, s2);
        block_swap(&mut buf); // unscramble.
        xor_cipher(&mut buf, &pad); // xor-decrypt the body.
    }

    decompress_framed(&buf)
}

/// Decompress the framed body `[u32 uncompLen][u32 compLen][LZ4 block]` at offset `0x14`.
fn decompress_framed(buf: &[u8]) -> Result<Vec<u8>, String> {
    let frame = buf
        .get(BODY_OFFSET..)
        .ok_or_else(|| "pro save: missing body".to_string())?;
    if frame.len() < 8 {
        return Err("pro save: body shorter than the 8-byte LZ4 frame header".to_string());
    }
    let uncomp_len = u32::from_le_bytes([frame[0], frame[1], frame[2], frame[3]]) as usize;
    let comp_len = u32::from_le_bytes([frame[4], frame[5], frame[6], frame[7]]) as usize;
    let block = frame
        .get(8..8 + comp_len)
        .ok_or_else(|| "pro save: compressed body runs past end of buffer".to_string())?;
    lz4::decompress_block(block, uncomp_len).map_err(|e| format!("pro save: LZ4 decode failed: {e}"))
}

/// Re-encrypt an inner save back into a raw Pro (marker-3) `.sav`, reusing the original 20-byte
/// `header20` (seed bytes, format markers, `a4`, and so on) and stamping in the freshly computed
/// `key16` so the game's load-time validation passes.
///
/// `header20` must be at least 20 bytes. The first 20 are used. This is the inverse of
/// [`decrypt_pro`]: LZ4-compress the inner, frame it, write `key16` into `header[7]`/`header[4]`,
/// xor-encrypt the body, then block_swap.
pub fn encrypt_pro(inner: &[u8], header20: &[u8]) -> Result<Vec<u8>, String> {
    if header20.len() < BODY_OFFSET {
        return Err(format!(
            "pro save: header is {} bytes; need at least {BODY_OFFSET}",
            header20.len()
        ));
    }
    let mut header = header20[..BODY_OFFSET].to_vec();
    let (s0, s1, s2) = (header[0], header[1], header[5]);
    let a4 = header[9];

    // The key the game validates folds the decompressed inner.
    let key = key16(inner, a4);
    header[7] = (key & 0xff) as u8;
    header[4] = ((key >> 8) & 0xff) as u8;

    // LZ4-compress the inner and build the framed body [u32 uncompLen][u32 compLen][block].
    let block = lz4::compress_block(inner);
    let mut buf = Vec::with_capacity(BODY_OFFSET + 8 + block.len());
    buf.extend_from_slice(&header);
    buf.extend_from_slice(&(inner.len() as u32).to_le_bytes());
    buf.extend_from_slice(&(block.len() as u32).to_le_bytes());
    buf.extend_from_slice(&block);

    // Inverse cipher order: xor-encrypt the body, then block_swap. The block_swap regions only
    // exist when the file is at least 0x70 bytes. A seedless save with no cipher has no such floor.
    if (s0 | s1 | s2) != 0 {
        if buf.len() < MIN_FILE_SIZE {
            return Err(format!(
                "pro save: enciphered output too small ({} bytes; block_swap needs at least \
                 {MIN_FILE_SIZE})",
                buf.len()
            ));
        }
        let pad = build_padtable(s0, s1, s2);
        xor_cipher(&mut buf, &pad);
        block_swap(&mut buf);
    }
    Ok(buf)
}

/// Detect a Pro (marker-3) save. Attempts the Pro decrypt and confirms the inner save begins with
/// the `0x19` title marker. It does not trust a header magic byte alone, so it returns `false` for
/// standard saves and for malformed input.
pub fn is_pro_save(raw: &[u8]) -> bool {
    matches!(decrypt_pro(raw), Ok(inner) if inner.first() == Some(&INNER_MARKER))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mt_seed_matches_reference() {
        // {0x05, 0xb2, 0xdb} are the real GamePro-Pro seed bytes.
        let seed = mt_seed_from_bytes(0x05, 0xb2, 0xdb);
        // combined = 0x05b2db, then one xorshift32 round.
        let mut x = 0x05b2dbu32;
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        assert_eq!(seed, x);
    }

    #[test]
    fn block_swap_is_self_inverse() {
        let mut buf: Vec<u8> = (0..0x80u8).collect();
        let orig = buf.clone();
        block_swap(&mut buf);
        assert_ne!(buf, orig, "swap must change the buffer");
        block_swap(&mut buf);
        assert_eq!(buf, orig, "swap is self-inverse");
    }

    #[test]
    fn xor_cipher_is_self_inverse() {
        let pad = build_padtable(1, 2, 3);
        let mut buf: Vec<u8> = (0..200u8).collect();
        let orig = buf.clone();
        xor_cipher(&mut buf, &pad);
        assert_ne!(&buf[BODY_OFFSET..], &orig[BODY_OFFSET..]);
        assert_eq!(&buf[..BODY_OFFSET], &orig[..BODY_OFFSET], "head untouched");
        xor_cipher(&mut buf, &pad);
        assert_eq!(buf, orig);
    }

    #[test]
    fn roundtrip_synthetic_inner() {
        // A synthetic inner save, which must start with the 0x19 marker.
        let mut inner = vec![INNER_MARKER, 0x05, 0x00, b'A', b'B', b'C', b'D', 0x00];
        inner.extend((0..2000u32).map(|i| (i % 251) as u8));

        // A header with nonzero seeds so the cipher actually runs.
        let mut header = vec![0u8; BODY_OFFSET];
        header[0] = 0x05;
        header[1] = 0xb2;
        header[5] = 0xdb;
        header[9] = 0x32;

        let enc = encrypt_pro(&inner, &header).expect("encrypt");
        assert!(is_pro_save(&enc), "produced save must be detected as Pro");
        let dec = decrypt_pro(&enc).expect("decrypt");
        assert_eq!(dec, inner, "encrypt then decrypt must be identity");

        // key16 stored in the header must validate against the inner.
        let stored = enc[7] as u16 | ((enc[4] as u16) << 8);
        assert_eq!(stored, key16(&inner, header[9]));
    }

    #[test]
    fn seedless_save_is_plain_body() {
        // All-zero seeds: the body is plain with no cipher, but still LZ4-framed.
        let mut inner = vec![INNER_MARKER, 0x01, 0x00, b'X', 0x00];
        inner.extend(std::iter::repeat(0xAB).take(300));
        let header = vec![0u8; BODY_OFFSET]; // seeds s0,s1,s5 all zero
        let enc = encrypt_pro(&inner, &header).expect("encrypt");
        let dec = decrypt_pro(&enc).expect("decrypt");
        assert_eq!(dec, inner);
    }
}
