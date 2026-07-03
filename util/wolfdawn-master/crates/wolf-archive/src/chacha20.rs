//! ChaCha20 stream cipher for Wolf "ChaCha2" archives (cryptVersion `0x64` / `0xC8`).
//!
//! Standard RFC 8439 ChaCha20 with the block counter initialised to 1 and a position-addressed
//! keystream, so any byte offset can be decrypted independently. Also has the Wolf-specific
//! [`key_setup`] used by cv `0xC8`. The core is verified against the RFC 8439 §2.3.2 test
//! vector.

fn pack4(a: &[u8]) -> u32 {
    u32::from_le_bytes([a[0], a[1], a[2], a[3]])
}

fn rotl32(x: u32, n: u32) -> u32 {
    x.rotate_left(n)
}

fn init_block(key: &[u8; 32], nonce: &[u8; 12]) -> [u32; 16] {
    let magic = b"expand 32-byte k";
    let mut s = [0u32; 16];
    for i in 0..4 {
        s[i] = pack4(&magic[i * 4..]);
    }
    for i in 0..8 {
        s[4 + i] = pack4(&key[i * 4..]);
    }
    s[12] = 1; // counter starts at 1 (Wolf/RFC test-vector convention)
    for i in 0..3 {
        s[13 + i] = pack4(&nonce[i * 4..]);
    }
    s
}

macro_rules! qr {
    ($x:expr, $a:expr, $b:expr, $c:expr, $d:expr) => {
        $x[$a] = $x[$a].wrapping_add($x[$b]);
        $x[$d] = rotl32($x[$d] ^ $x[$a], 16);
        $x[$c] = $x[$c].wrapping_add($x[$d]);
        $x[$b] = rotl32($x[$b] ^ $x[$c], 12);
        $x[$a] = $x[$a].wrapping_add($x[$b]);
        $x[$d] = rotl32($x[$d] ^ $x[$a], 8);
        $x[$c] = $x[$c].wrapping_add($x[$d]);
        $x[$b] = rotl32($x[$b] ^ $x[$c], 7);
    };
}

fn block_next(state: &mut [u32; 16], ks: &mut [u32; 16]) {
    ks.copy_from_slice(state);
    for _ in 0..10 {
        qr!(ks, 0, 4, 8, 12);
        qr!(ks, 1, 5, 9, 13);
        qr!(ks, 2, 6, 10, 14);
        qr!(ks, 3, 7, 11, 15);
        qr!(ks, 0, 5, 10, 15);
        qr!(ks, 1, 6, 11, 12);
        qr!(ks, 2, 7, 8, 13);
        qr!(ks, 3, 4, 9, 14);
    }
    for i in 0..16 {
        ks[i] = ks[i].wrapping_add(state[i]);
    }
    state[12] = state[12].wrapping_add(1);
    if state[12] == 0 {
        state[13] = state[13].wrapping_add(1);
    }
}

#[inline]
fn ks_byte(ks: &[u32; 16], idx: usize) -> u8 {
    (ks[idx / 4] >> (8 * (idx % 4))) as u8
}

/// XOR the ChaCha20 keystream into `bytes`, addressing the stream at absolute byte
/// `position` (mirrors `DXArchive::KeyConv`'s ChaCha20 branch).
pub fn crypt(bytes: &mut [u8], key: &[u8; 32], nonce: &[u8; 12], position: u32) {
    let mut state = init_block(key, nonce);
    let mut ks = [0u32; 16];
    let mut pos = 0usize;
    let mut offset = (position % 64) as usize;
    state[12] = state[12].wrapping_add(position / 64);
    while pos < bytes.len() {
        let steps = core::cmp::min(64 - offset, bytes.len() - pos);
        block_next(&mut state, &mut ks);
        for i in 0..steps {
            bytes[pos + i] ^= ks_byte(&ks, offset + i);
        }
        pos += steps;
        offset = 0;
    }
}

/// Wolf cv-`0xC8` key derivation: expand 4 header bytes into a 64-byte key buffer
/// (`key[0..32]` = ChaCha key, `key[34..46]` = nonce).
pub fn key_setup(data: [u8; 4]) -> [u8; 64] {
    const MOD1: [u8; 4] = [0x3F, 0xA7, 0xD2, 0x1C];
    const MOD2: [u8; 4] = [0xB4, 0xE1, 0x9D, 0x58];
    const MOD3: [u8; 4] = [0x6A, 0x2B, 0x4C, 0x8E];
    let mut key = [0u8; 64];
    for i in 0..63usize {
        let index = i % 4;
        let mut temp = (data[index].wrapping_add(MOD2[index]))
            ^ (MOD1[index]
                .wrapping_add(i as u8)
                .wrapping_add(16u8.wrapping_mul(i as u8)));
        temp = if i % 2 == 0 {
            (temp >> 5) | (temp << 3)
        } else {
            (temp >> 2) | (temp << 6)
        };
        key[i] = !(temp ^ data[index] ^ MOD3[index]);
    }
    key
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rfc8439_keystream_block() {
        // RFC 8439 §2.3.2: key 00..1f, nonce 00 00 00 09 00 00 00 4a 00 00 00 00, counter 1.
        let mut key = [0u8; 32];
        for i in 0..32 {
            key[i] = i as u8;
        }
        let nonce: [u8; 12] = [0, 0, 0, 9, 0, 0, 0, 0x4a, 0, 0, 0, 0];
        let mut buf = [0u8; 64]; // XOR into zeros -> keystream
        crypt(&mut buf, &key, &nonce, 0);
        let expected: [u8; 64] = [
            0x10, 0xf1, 0xe7, 0xe4, 0xd1, 0x3b, 0x59, 0x15, 0x50, 0x0f, 0xdd, 0x1f, 0xa3, 0x20,
            0x71, 0xc4, 0xc7, 0xd1, 0xf4, 0xc7, 0x33, 0xc0, 0x68, 0x03, 0x04, 0x22, 0xaa, 0x9a,
            0xc3, 0xd4, 0x6c, 0x4e, 0xd2, 0x82, 0x64, 0x46, 0x07, 0x9f, 0xaa, 0x09, 0x14, 0xc2,
            0xd7, 0x05, 0xd9, 0x8b, 0x02, 0xa2, 0xb5, 0x12, 0x9c, 0xd1, 0xde, 0x16, 0x4e, 0xb9,
            0xcb, 0xd0, 0x83, 0xe8, 0xa2, 0x50, 0x3c, 0x4e,
        ];
        assert_eq!(
            buf, expected,
            "ChaCha20 keystream must match RFC 8439 §2.3.2"
        );
    }

    #[test]
    fn position_addressing_matches_contiguous() {
        // Decrypting in two position-addressed chunks == one contiguous pass.
        let key = [7u8; 32];
        let nonce = [3u8; 12];
        let mut whole: Vec<u8> = (0..200).map(|i| (i * 13) as u8).collect();
        let mut split = whole.clone();
        crypt(&mut whole, &key, &nonce, 0);
        let (a, b) = split.split_at_mut(80);
        crypt(a, &key, &nonce, 0);
        crypt(b, &key, &nonce, 80);
        assert_eq!(whole, split);
    }
}
