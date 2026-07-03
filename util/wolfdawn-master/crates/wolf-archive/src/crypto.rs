//! WolfPro crypto: the 7-byte DXLib key (`key_create`/`key_conv`/`crc32`), the 768-byte
//! stream cipher + its key schedule (`wolf_init_key`/`wolf_crypt`), the header-address
//! scramble, and the AES-128-CTR pass used by v3.5+ archives.

use crate::codec::{dxa_decode, huffman_decode};
use crate::*;

pub(crate) fn key_create(source: &[u8]) -> [u8; KEY_BYTES] {
    let mut src = nul_terminated(source).to_vec();
    if src.len() < 4 {
        src.extend_from_slice(DEFAULT_DXLIB_KEY);
    }
    let even: Vec<u8> = src.iter().step_by(2).copied().collect();
    let odd: Vec<u8> = src.iter().skip(1).step_by(2).copied().collect();
    let c0 = crc32(&even);
    let c1 = crc32(&odd);
    [
        c0 as u8,
        (c0 >> 8) as u8,
        (c0 >> 16) as u8,
        (c0 >> 24) as u8,
        c1 as u8,
        (c1 >> 8) as u8,
        (c1 >> 16) as u8,
    ]
}

pub(crate) fn nul_terminated(source: &[u8]) -> &[u8] {
    source
        .iter()
        .position(|&b| b == 0)
        .map(|end| &source[..end])
        .unwrap_or(source)
}

pub(crate) fn crc32(data: &[u8]) -> u32 {
    let mut table = [0u32; 256];
    for i in 0..256u32 {
        let mut v = i;
        for _ in 0..8 {
            let b = v & 1;
            v >>= 1;
            if b != 0 {
                v ^= 0xedb88320;
            }
        }
        table[i as usize] = v;
    }
    let mut crc = 0xffff_ffffu32;
    for &b in data {
        crc = table[((crc ^ b as u32) & 0xff) as usize] ^ (crc >> 8);
    }
    crc ^ 0xffff_ffff
}

pub(crate) fn key_conv(data: &mut [u8], key: &[u8; KEY_BYTES], pos: usize) {
    for (i, byte) in data.iter_mut().enumerate() {
        *byte ^= key[(pos + i) % KEY_BYTES];
    }
}

pub(crate) fn is_new_wolf_crypt(crypt_version: u16) -> bool {
    (crypt_version >= 331 && crypt_version < 1000) || crypt_version >= 1010
}

pub(crate) fn is_wolf_v35(crypt_version: u16) -> bool {
    (crypt_version >= 0x15e && crypt_version < 0x3e8) || crypt_version >= 0x3fc
}

pub(crate) fn candidate_matches_wolf_version(label: &str, crypt_version: u16) -> bool {
    label == "requested"
        || matches!(
            (crypt_version, label),
            (0x14b, "wolf-v3.31")
                | (0x15e, "wolf-v3.50")
                | (0x64, "wolf-chacha2")
                | (0xc8, "wolf-chacha2")
        )
}

#[derive(Clone, Copy)]
pub(crate) struct MsvcRand {
    state: u32,
}

impl MsvcRand {
    fn new(seed: u32) -> Self {
        Self { state: seed }
    }

    fn next(&mut self) -> u32 {
        self.state = self.state.wrapping_mul(214013).wrapping_add(2531011);
        (self.state >> 16) & 0x7fff
    }
}

pub(crate) fn wolf_init_key(
    crypt_version: u16,
    pwd: &[u8; 15],
    key2: Option<&[u8]>,
    other: bool,
    key_string: &[u8],
) -> [u8; 768] {
    let mut key = [0u8; 768];
    let mut fac = [0u8; 3];

    let s0 = pwd[2];
    let s1 = pwd[5];
    let s2 = pwd[12];
    let mut s3 = 0u8;

    if !other {
        let len = pwd[11] / 3;
        for i in 0..len {
            s3 = i ^ (s3 ^ pwd[i as usize % 15]).rotate_right(3);
        }
    } else {
        let len = pwd[8] / 4;
        for i in 0..len {
            s3 = i ^ (s3 ^ pwd[i as usize % 15]).rotate_right(2);
        }
    }

    let seed = (s0 as u32) * (s1 as u32) + (s2 as u32) + (s3 as u32);
    let mut rng = MsvcRand::new(seed);

    fac[s3 as usize % 3] = (rng.next() % 256) as u8;

    if !other && is_wolf_v35(crypt_version) {
        fac[1] = (rng.next() % 0xfb) as u8;
    }

    for i in 0..256 {
        let rn = (rng.next() & 0xffff) as u16;
        key[i] = fac[0] ^ (rng.next() as u8);
        key[i + 256] = fac[1] ^ (rn >> 8) as u8;
        key[i + 512] = fac[2] ^ rn as u8;
    }

    if let Some(key2) = key2 {
        for j in 0..128 {
            let rn = (rng.next() & 0xffff) as u16;
            key[j] ^= s3 ^ key2[2] ^ (rn >> 8) as u8;
            key[j + 256] ^= s3 ^ key2[0] ^ rn as u8;
        }
    }

    if other {
        let mut salt = [0u8; 128];
        let salt_source = if crypt_version == 0x15e {
            b"958".as_slice()
        } else {
            nul_terminated(key_string)
        };
        calc_wolf_salt(salt_source, &mut salt);

        let mut mod_factor = 7u8;
        if is_wolf_v35(crypt_version) {
            s3 = s3.wrapping_add(0x22);
            mod_factor = 16;
        }

        for i in 0..3usize {
            let mut t = s3 as i32;
            for j in 0..256usize {
                let mut skip = false;
                let cur_s = salt[j & 0x7f];
                let cur_s2 = salt[(j + i) % 0x80];
                let cur_k = key[i * 256 + j];
                let s_x_k = cur_s ^ cur_k;
                let round = (((cur_s2 as u16) | ((cur_s as u16) << 8)) % mod_factor as u16) as u8;
                let mut new_k = s_x_k;

                match round {
                    1 => {
                        if cur_s2 % 0x0b == 0 {
                            new_k = cur_k;
                        }
                    }
                    2 => {
                        if cur_s % 0x1d == 0 {
                            new_k = !s_x_k;
                        }
                    }
                    3 => {
                        if ((round as usize + j) % 0x25) == 0 {
                            new_k = cur_s2 ^ s_x_k;
                        }
                    }
                    4 => {
                        if ((cur_s as u16 + cur_s2 as u16) % 97) == 0 {
                            new_k = cur_s.wrapping_add(s_x_k);
                        }
                    }
                    5 => {
                        if ((j * round as usize) % 0x7b) == 0 {
                            new_k = s_x_k ^ t as u8;
                        }
                    }
                    6 => {
                        if cur_s == 0xff && cur_s2 == 0 {
                            new_k = 0;
                            skip = true;
                        }
                    }
                    7 => {
                        if crypt_version >= 0x154
                            && !(crypt_version > 0x3e8 && crypt_version < 0x3fc)
                            && (((round as usize + j) % 0x33) == 0 || crypt_version >= 0x3fc)
                        {
                            new_k ^= cur_s;
                        }
                    }
                    8 => {
                        if crypt_version >= 0x154
                            && !(crypt_version > 0x3e8 && crypt_version < 0x3fc)
                            && ((cur_s % 0x1d) == 0 || crypt_version >= 0x3fc)
                        {
                            new_k ^= cur_s;
                        }
                    }
                    _ => {}
                }

                if ((j + i) % (cur_s as usize % 5 + 1)) == 0 {
                    new_k ^= t as u8;
                } else if skip {
                    new_k = !s_x_k;
                }

                key[i * 256 + j] = new_k;
                t += i as i32;
            }
        }
    }

    key
}

pub(crate) fn calc_wolf_salt(source: &[u8], salt: &mut [u8; 128]) {
    let source = if source.is_empty() {
        DEFAULT_DXLIB_KEY
    } else {
        source
    };
    for i in 0..128 {
        salt[i] = (i / source.len()) as u8 + source[i % source.len()];
    }
}

pub(crate) fn wolf_crypt(key: &[u8; 768], data: &mut [u8], start: usize, crypt_version: u16) {
    let mut v1 = start % 256;
    let mut v2 = (start / 256) % 256;
    let mut v3 = (start / 0x10000) % 256;

    if is_wolf_v35(crypt_version) {
        let mut modded = [0u8; 512];
        for i in 0..512 {
            modded[i] = key[i % 256] ^ (7u8.wrapping_mul(i as u8));
        }
        for byte in data {
            *byte ^= modded[v1] ^ modded[v2 + 256];
            v1 += 1;
            if v1 == 256 {
                v1 = 0;
                v2 = (v2 + 1) % 256;
            }
        }
    } else {
        for byte in data {
            *byte ^= key[v1] ^ key[v2 + 256] ^ key[v3 + 512];
            v1 += 1;
            if v1 == 256 {
                v1 = 0;
                v2 += 1;
                if v2 == 256 {
                    v2 = 0;
                    v3 = (v3 + 1) % 256;
                }
            }
        }
    }
}

pub(crate) fn wolf_crypt_addresses(data: &mut [u8], pwd: &[u8; 15], crypt_version: u16) {
    if data.len() < 64 {
        return;
    }

    if is_wolf_v35(crypt_version) {
        let seed = 0x0c + pwd[9] as u32 * pwd[10] as u32 + pwd[3] as u32;
        let mut rng = MsvcRand::new(seed);
        let mut word = 4usize;
        for _ in 0..2 {
            for j in (0..4).rev() {
                xor_u16_at(data, (word + j) * 2, (rng.next() & 0xffff) as u16);
            }
            word += 4;
        }
        let r0 = (rng.next() as u64) << 17;
        let r1 = (rng.next() as u64) << 31;
        let v0 = ((r0 & 0xffff_ffff) | (r1 & 0xffff_ffff) | rng.next() as u64) as u32;
        let v1 = ((r0 >> 32) | (r1 >> 32)) as u32;
        xor_u32_at(data, word * 2, v0);
        xor_u32_at(data, word * 2 + 4, v1);
        word += 4;
        for j in (0..4).rev() {
            xor_u16_at(data, (word + j) * 2, (rng.next() & 0xffff) as u16);
        }
    } else {
        let seed = pwd[0] as u32 + pwd[7] as u32 * pwd[12] as u32;
        let mut rng = MsvcRand::new(seed);
        let mut word = 4usize;
        for _ in 0..4 {
            for j in (0..4).rev() {
                xor_u16_at(data, (word + j) * 2, (rng.next() & 0xffff) as u16);
            }
            word += 4;
        }
    }
}

pub(crate) fn xor_u16_at(data: &mut [u8], off: usize, value: u16) {
    if off + 2 <= data.len() {
        let v = read_u16(&data[off..]) ^ value;
        data[off..off + 2].copy_from_slice(&v.to_le_bytes());
    }
}

pub(crate) fn xor_u32_at(data: &mut [u8], off: usize, value: u32) {
    if off + 4 <= data.len() {
        let v = read_u32(&data[off..]) ^ value;
        data[off..off + 4].copy_from_slice(&v.to_le_bytes());
    }
}

pub(crate) fn wolf_aes_body_size(
    file_size: usize,
    crypt_version: u16,
    pwd: &[u8; 15],
    key2: Option<&[u8]>,
) -> usize {
    let body_len = file_size.saturating_sub(64);
    if body_len < 0x400 {
        return 0;
    }
    if !is_wolf_v35(crypt_version) {
        return 0x400;
    }

    let mut seed = if crypt_version >= 1020 {
        let key2 = key2.unwrap_or(&[0, 0, 0, 0]);
        key2[0] as u32 * key2[1] as u32 + pwd[2] as u32 * pwd[4] as u32 + pwd[11] as u32
    } else {
        pwd[2] as u32 * pwd[4] as u32 + pwd[12] as u32
    };
    if seed == 0 {
        seed = 1;
    }
    let mut xs = XorShift32::new(seed);
    let first = xs.next() % 500 + 800;
    if file_size >= first as usize {
        xs.next();
    }
    let mut body_size = body_len;
    let limit = xs.next() % 500 + 800;
    if body_size >= limit as usize {
        body_size = (xs.next() % 500 + 800) as usize;
    }
    body_size
}

pub(crate) struct XorShift32 {
    state: u32,
}

impl XorShift32 {
    fn new(seed: u32) -> Self {
        Self { state: seed }
    }

    fn next(&mut self) -> u32 {
        self.state ^= self.state << 0x0b;
        self.state ^= self.state >> 0x13;
        self.state ^= self.state << 0x07;
        self.state
    }
}

pub(crate) fn read_wolf_table(data: &[u8], head: &DxHead, wolf: &WolfContext) -> Option<Vec<u8>> {
    let start = head.name_table_start as usize;
    let no_key = (head.flags & 1) != 0;
    let no_head_press = (head.flags & 2) != 0;

    if no_head_press {
        let mut table = read_wolf_archive_slice(data, start, head.head_size as usize, wolf)?;
        if !no_key {
            wolf_crypt(&wolf.special_key, &mut table, 0, wolf.crypt_version);
        }
        Some(table)
    } else {
        let huff_len = data.len().checked_sub(start)?;
        let mut huff = read_wolf_archive_slice(data, start, huff_len, wolf)?;
        if !no_key {
            wolf_crypt(&wolf.special_key, &mut huff, 0, wolf.crypt_version);
        }
        let lz = huffman_decode(&huff).ok()?;
        dxa_decode(&lz).ok()
    }
}

pub(crate) fn read_wolf_archive_slice(
    data: &[u8],
    start: usize,
    len: usize,
    wolf: &WolfContext,
) -> Option<Vec<u8>> {
    let end = start.checked_add(len)?;
    let mut out = data.get(start..end)?.to_vec();
    let file_size = data.len();

    apply_wolf_stream_overlap(
        &mut out,
        start,
        64,
        file_size.saturating_sub(64),
        &wolf.other_key,
        wolf.crypt_version,
    );

    let pass1_end = 64usize.saturating_add(wolf.body_size).min(file_size);
    apply_aes_overlap(&mut out, start, 64, pass1_end, &wolf.aes_round_key, 0);

    if wolf.name_table_start < file_size {
        let body_blocks = (wolf.body_size + AES_BLOCK_LEN - 1) / AES_BLOCK_LEN;
        apply_aes_overlap(
            &mut out,
            start,
            wolf.name_table_start,
            file_size,
            &wolf.aes_round_key,
            body_blocks,
        );
    }

    Some(out)
}

pub(crate) fn apply_wolf_stream_overlap(
    out: &mut [u8],
    out_start: usize,
    range_start: usize,
    range_end: usize,
    key: &[u8; 768],
    crypt_version: u16,
) {
    let out_end = out_start.saturating_add(out.len());
    let begin = out_start.max(range_start);
    let end = out_end.min(range_end);
    if begin >= end {
        return;
    }
    let local = begin - out_start;
    wolf_crypt(
        key,
        &mut out[local..local + (end - begin)],
        begin,
        crypt_version,
    );
}

pub(crate) fn apply_aes_overlap(
    out: &mut [u8],
    out_start: usize,
    range_start: usize,
    range_end: usize,
    round_key: &[u8; AES_ROUND_KEY_SIZE],
    iv_block_offset: usize,
) {
    let out_end = out_start.saturating_add(out.len());
    let begin = out_start.max(range_start);
    let end = out_end.min(range_end);
    if begin >= end {
        return;
    }
    let local = begin - out_start;
    let stream_offset = begin - range_start;
    aes_ctr_xcrypt_at(
        &mut out[local..local + (end - begin)],
        round_key,
        stream_offset,
        iv_block_offset,
    );
}

pub(crate) const AES_SBOX: [u8; 256] = [
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
];
pub(crate) const AES_RCON: [u8; 11] = [
    0x8d, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36,
];

pub(crate) fn wolf_aes_init_round_key(
    pwd: &[u8; 15],
    pro_key: Option<&[u8]>,
    crypt_version: u16,
) -> [u8; AES_ROUND_KEY_SIZE] {
    let zero = [0u8; 4];
    let pro = pro_key.unwrap_or(&zero);
    let mut key = [0u8; AES_BLOCK_LEN];
    let mut iv = [0u8; AES_BLOCK_LEN];

    if is_wolf_v35(crypt_version) {
        for i in 0..15usize {
            let pro_elem = pro[i % 4];
            let key_idx = ((i * (pro_elem as usize % 5 + 7)) ^ (3 * pwd[i] as usize)) % 15;
            let iv_idx = (i * (pro[(i + 1) % 4] as usize % 7 + 0x0b)
                ^ (5 * pwd[(i + 3) % 15] as usize))
                % 15;

            key[i] ^= ((i as u8 ^ pro_elem)
                .wrapping_add(pwd[key_idx].wrapping_shl((i % 3) as u32)))
                % 0xfb;
            iv[i] ^= (pwd[iv_idx]
                .wrapping_shr((i % 2) as u32)
                .wrapping_add((i * i) as u8 ^ pro[(i + 2) % 4]))
                % 0xf6;
            key[15] ^= (7u16 * (pwd[i].wrapping_add((i as u8 + 1) ^ pro_elem)) as u16 % 0xfd) as u8;
            iv[15] ^= (11u16 * (pwd[i].wrapping_sub((i as u8 * 2) ^ pro[(i + 2) % 4])) as u16
                % 0x100) as u8;
        }
    } else if crypt_version == 0x3f2 {
        for i in 0..15usize {
            key[i] ^= pwd[(i * 7) % 15]
                .wrapping_add(pro[i & 3])
                .wrapping_mul((i * i) as u8);
            iv[i] ^= pwd[(i * 11) % 15]
                .wrapping_add(pro[(i + 2) % 4])
                .wrapping_sub((i * i) as u8);
            key[15] ^= (i as u8)
                .wrapping_mul(3)
                .wrapping_add(pwd[i])
                .wrapping_add(pro[i & 3]);
            iv[15] ^= (i as u8)
                .wrapping_mul(5)
                .wrapping_add(pwd[i])
                .wrapping_add(pro[(i + 2) % 4]);
        }
    } else {
        for i in 0..15usize {
            key[i] ^= pwd[(i * 7) % 15].wrapping_add((i * i) as u8);
            iv[i] ^= pwd[(i * 11) % 15].wrapping_sub((i * i) as u8);
            key[15] ^= pwd[i].wrapping_add((i * 3) as u8);
            iv[15] ^= pwd[i].wrapping_add((i * 5) as u8);
        }
    }

    key[0] ^= pro[0];
    iv[10] ^= pro[0];
    key[4] ^= pro[1];
    iv[1] ^= pro[1];
    key[8] ^= pro[2];
    iv[4] ^= pro[2];
    key[12] ^= pro[3];
    iv[7] ^= pro[3];

    let mut round_key = [0u8; AES_ROUND_KEY_SIZE];
    aes_key_expansion(&mut round_key[..AES_KEY_EXP_SIZE], &key);
    round_key[AES_KEY_EXP_SIZE..].copy_from_slice(&iv);
    round_key
}

pub(crate) fn aes_key_expansion(round_key: &mut [u8], key: &[u8; AES_BLOCK_LEN]) {
    for i in 0..4 {
        round_key[i * 4..i * 4 + 4].copy_from_slice(&key[i * 4..i * 4 + 4]);
    }

    for i in 4..44usize {
        let mut temp = [
            round_key[(i - 1) * 4],
            round_key[(i - 1) * 4 + 1],
            round_key[(i - 1) * 4 + 2],
            round_key[(i - 1) * 4 + 3],
        ];

        if i % 4 == 0 {
            temp.rotate_left(1);
            temp[0] = AES_SBOX[temp[0] as usize] ^ AES_RCON[i / 4];
            temp[1] = AES_SBOX[temp[1] as usize] >> 4;
            temp[2] = !AES_SBOX[temp[2] as usize];
            temp[3] = AES_SBOX[temp[3] as usize].rotate_right(7);
        }

        for j in 0..4 {
            round_key[i * 4 + j] = round_key[(i - 4) * 4 + j] ^ temp[j];
        }
    }
}

pub(crate) fn aes_ctr_xcrypt_at(
    data: &mut [u8],
    round_key: &[u8; AES_ROUND_KEY_SIZE],
    stream_offset: usize,
    iv_block_offset: usize,
) {
    let mut local_key = *round_key;
    let block_offset = stream_offset / AES_BLOCK_LEN + iv_block_offset;
    aes_advance_iv(&mut local_key[AES_KEY_EXP_SIZE..], block_offset);

    let mut state = [0u8; AES_BLOCK_LEN];
    let rem = stream_offset % AES_BLOCK_LEN;
    let mut bi = AES_BLOCK_LEN;
    if rem != 0 {
        aes_next_ctr_block(&mut local_key, &mut state);
        bi = rem;
    }

    for byte in data {
        if bi == AES_BLOCK_LEN {
            aes_next_ctr_block(&mut local_key, &mut state);
            bi = 0;
        }
        *byte ^= state[bi];
        bi += 1;
    }
}

pub(crate) fn aes_next_ctr_block(
    round_key: &mut [u8; AES_ROUND_KEY_SIZE],
    state: &mut [u8; AES_BLOCK_LEN],
) {
    state.copy_from_slice(&round_key[AES_KEY_EXP_SIZE..]);
    aes_cipher(state, &round_key[..AES_KEY_EXP_SIZE]);
    aes_increment_iv(&mut round_key[AES_KEY_EXP_SIZE..]);
}

pub(crate) fn aes_advance_iv(iv: &mut [u8], blocks: usize) {
    for _ in 0..blocks {
        aes_increment_iv(iv);
    }
}

pub(crate) fn aes_increment_iv(iv: &mut [u8]) {
    for byte in iv.iter_mut().rev() {
        if *byte == 0xff {
            *byte = 0;
        } else {
            *byte = byte.wrapping_add(1);
            break;
        }
    }
}

pub(crate) fn aes_cipher(state: &mut [u8; AES_BLOCK_LEN], round_key: &[u8]) {
    aes_add_round_key(state, 0, round_key);
    for round in 1..10u8 {
        aes_sub_bytes(state);
        aes_shift_rows(state);
        aes_mix_columns(state);
        aes_add_round_key(state, round, round_key);
    }
    aes_sub_bytes(state);
    aes_shift_rows(state);
    aes_add_round_key(state, 10, round_key);
}

pub(crate) fn aes_add_round_key(state: &mut [u8; AES_BLOCK_LEN], round: u8, round_key: &[u8]) {
    let start = round as usize * AES_BLOCK_LEN;
    for i in 0..AES_BLOCK_LEN {
        state[i] ^= round_key[start + i];
    }
}

pub(crate) fn aes_sub_bytes(state: &mut [u8; AES_BLOCK_LEN]) {
    for byte in state {
        *byte = AES_SBOX[*byte as usize];
    }
}

pub(crate) fn aes_shift_rows(state: &mut [u8; AES_BLOCK_LEN]) {
    let temp = state[1];
    state[1] = state[5];
    state[5] = state[9];
    state[9] = state[13];
    state[13] = temp;

    state.swap(2, 10);
    state.swap(6, 14);

    let temp = state[3];
    state[3] = state[15];
    state[15] = state[11];
    state[11] = state[7];
    state[7] = temp;
}

pub(crate) fn aes_xtime(x: u8) -> u8 {
    (x << 1) ^ (((x >> 7) & 1) * 0x1b)
}

pub(crate) fn aes_mix_columns(state: &mut [u8; AES_BLOCK_LEN]) {
    for col in 0..4 {
        let base = col * 4;
        let t = state[base];
        let tmp = state[base] ^ state[base + 1] ^ state[base + 2] ^ state[base + 3];
        state[base] ^= tmp ^ aes_xtime(state[base + 1] ^ state[base]);
        state[base + 1] ^= tmp ^ aes_xtime(state[base + 2] ^ state[base + 1]);
        state[base + 2] ^= tmp ^ aes_xtime(state[base + 2] ^ state[base + 3]);
        state[base + 3] ^= tmp ^ aes_xtime(state[base + 3] ^ t);
    }
}
