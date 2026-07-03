//! Wolf RPG `.sav` outer encryption: a 3-pass MSVCRT-`rand` XOR stream over the file body
//! (everything from offset `0x14` to EOF), keyed by three seed bytes pulled from the file head.
//!
//! This is the outer layer only. It leaves the decrypted plaintext (header, baked title,
//! length-prefixed strings, variable database, and so on) for a higher layer to interpret. The
//! codec is byte-exact: [`encrypt`]`(`[`decrypt`]`(raw)) == raw` for any real save whose stored
//! checksum already matches its body. That is the common case, see [`fix_checksum`].
//!
//! The MSVCRT generator is reproduced exactly. `state = state*214013 + 2531011` then
//! `out = (state >> 16) & 0x7FFF`, with `srand(seed)` setting `state = seed`. Each XOR byte is
//! `(rand() >> 12) & 0xFF`.

/// Body starts here. Bytes `0x00..0x14` (seeds, checksum, flags) are never XORed.
pub const START_OFFSET: usize = 0x14;

/// MSVCRT `rand`/`srand`. `state` seeds directly from `srand`'s argument.
struct MsvcRand {
    state: u32,
}

impl MsvcRand {
    fn new(seed: u8) -> Self {
        // srand takes an int. The engine seeds it with a single header byte (0..=255).
        MsvcRand { state: seed as u32 }
    }

    fn next(&mut self) -> u16 {
        self.state = self.state.wrapping_mul(214013).wrapping_add(2531011);
        ((self.state >> 16) & 0x7FFF) as u16
    }
}

/// XOR one pass over the body in place: `srand(seed)`, then for every `step`-th byte from
/// `START_OFFSET` to the end, `data[j] ^= (rand() >> 12) & 0xFF`.
fn xor_stream(data: &mut [u8], seed: u8, step: usize) {
    let mut rng = MsvcRand::new(seed);
    let mut j = START_OFFSET;
    while j < data.len() {
        data[j] ^= ((rng.next() >> 12) & 0xFF) as u8;
        j += step;
    }
}

/// Decrypt a raw `.sav` buffer into its plaintext form.
///
/// Seeds are `s0 = data[0]`, `s1 = data[3]`, `s2 = data[9]`. The passes run in that order with
/// increments `[1, 2, 5]`. A buffer too small to have a body (`len <= START_OFFSET`) is returned
/// unchanged.
pub fn decrypt(raw: &[u8]) -> Vec<u8> {
    let mut data = raw.to_vec();
    if data.len() <= START_OFFSET {
        return data;
    }
    let (s0, s1, s2) = (data[0], data[3], data[9]);
    xor_stream(&mut data, s0, 1);
    xor_stream(&mut data, s1, 2);
    xor_stream(&mut data, s2, 5);
    data
}

/// Recompute the body checksum: `data[2] = sum(data[0x14..]) & 0xFF`. Call before [`encrypt`]
/// whenever the body may have changed. No-op for a buffer with no body.
// `&mut Vec<u8>` (rather than `&mut [u8]`) is the public signature for this codec.
#[allow(clippy::ptr_arg)]
pub fn fix_checksum(data: &mut Vec<u8>) {
    if data.len() > START_OFFSET {
        let sum = data[START_OFFSET..]
            .iter()
            .fold(0u8, |acc, &b| acc.wrapping_add(b));
        data[2] = sum;
    }
}

/// Encrypt a plaintext buffer back into a raw `.sav`.
///
/// This is the exact inverse of [`decrypt`]. The checksum is recomputed first, then the three
/// XOR passes run in reverse seed order (`s0 = data[9]`, `s1 = data[3]`, `s2 = data[0]`) with
/// increments `[5, 2, 1]`. Because the seeds are read from the never-XORed head bytes, decrypt
/// and encrypt key off identical seed values, so the passes cancel and
/// `encrypt(decrypt(raw)) == raw` for any save whose stored checksum already equals its body
/// checksum.
pub fn encrypt(plain: &[u8]) -> Vec<u8> {
    let mut data = plain.to_vec();
    if data.len() <= START_OFFSET {
        return data;
    }
    fix_checksum(&mut data);
    let (s0, s1, s2) = (data[9], data[3], data[0]);
    xor_stream(&mut data, s0, 5);
    xor_stream(&mut data, s1, 2);
    xor_stream(&mut data, s2, 1);
    data
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn msvc_rand_matches_reference_sequence() {
        // After srand(1), the first few rand() values from the canonical MSVCRT generator.
        let mut r = MsvcRand::new(1);
        assert_eq!(r.next(), 41);
        assert_eq!(r.next(), 18467);
        assert_eq!(r.next(), 6334);
    }

    #[test]
    fn roundtrip_on_synthetic_data() {
        // Build a buffer with a body, give it a correct checksum, encrypt then decrypt: identical.
        let mut plain: Vec<u8> = (0u8..=200).cycle().take(0x14 + 137).collect();
        // Vary the seed bytes so all three passes use distinct seeds.
        plain[0] = 0x37;
        plain[3] = 0x9A;
        plain[9] = 0x04;
        fix_checksum(&mut plain);

        let enc = encrypt(&plain);
        let dec = decrypt(&enc);
        assert_eq!(dec, plain, "decrypt(encrypt(plain)) must be identity");

        // And the body actually changed under encryption (not a no-op).
        assert_ne!(&enc[START_OFFSET..], &plain[START_OFFSET..]);
        // The head (seeds/checksum/flags) is never XORed, so it is carried verbatim.
        assert_eq!(&enc[..START_OFFSET], &plain[..START_OFFSET]);
    }

    #[test]
    fn fix_checksum_sets_byte2() {
        let mut data = vec![0u8; 0x14 + 4];
        data[0x14] = 10;
        data[0x15] = 20;
        data[0x16] = 30;
        data[0x17] = 40;
        fix_checksum(&mut data);
        assert_eq!(data[2], 100);
    }

    #[test]
    fn tiny_buffer_is_untouched() {
        let raw = vec![1u8, 2, 3];
        assert_eq!(decrypt(&raw), raw);
        assert_eq!(encrypt(&raw), raw);
    }
}
