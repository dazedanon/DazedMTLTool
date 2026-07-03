//! Shared primitives for the DXArchive VER5/VER6 (Wolf 2.0x) decoders: the 12-byte key
//! derivation and `KeyConv`, the keycode-LZSS decompressor, and file-name extraction. These
//! are byte-for-byte identical between VER5 and VER6. Only the table/struct layout differs.

pub(super) const KEYLEN: usize = 12;
const MIN_COMPRESS: usize = 4;

/// `KeyCreate`: loop the source string to 12 bytes, then a fixed per-byte transform.
pub(super) fn key_create(source: &[u8]) -> [u8; KEYLEN] {
    let mut k = [0xaau8; KEYLEN];
    if !source.is_empty() {
        for (i, b) in k.iter_mut().enumerate() {
            *b = source[i % source.len()];
        }
    }
    k[0] = !k[0];
    k[1] = (k[1] >> 4) | (k[1] << 4);
    k[2] ^= 0x8a;
    k[3] = !((k[3] >> 4) | (k[3] << 4));
    k[4] = !k[4];
    k[5] ^= 0xac;
    k[6] = !k[6];
    k[7] = !((k[7] >> 3) | (k[7] << 5));
    k[8] = (k[8] >> 5) | (k[8] << 3);
    k[9] ^= 0x7f;
    k[10] = ((k[10] >> 4) | (k[10] << 4)) ^ 0xd6;
    k[11] ^= 0xcc;
    k
}

/// XOR `buf` with the key starting at stream position `pos` (DXLib `KeyConv`).
pub(super) fn key_conv(key: &[u8; KEYLEN], buf: &[u8], pos: usize) -> Vec<u8> {
    buf.iter()
        .enumerate()
        .map(|(i, &b)| b ^ key[(pos + i) % KEYLEN])
        .collect()
}

pub(super) fn u32at(d: &[u8], o: usize) -> Option<u32> {
    d.get(o..o + 4)
        .map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
}

pub(super) fn u64at(d: &[u8], o: usize) -> Option<u64> {
    d.get(o..o + 8)
        .map(|b| u64::from_le_bytes(b.try_into().unwrap()))
}

/// The original (display) file name: at `name_addr + 4 + packs*4`, NUL-terminated, Shift-JIS.
pub(super) fn name(d: &[u8], name_addr: usize) -> Option<String> {
    let packs = u16::from_le_bytes([*d.get(name_addr)?, *d.get(name_addr + 1)?]) as usize;
    let start = name_addr + 4 + packs * 4;
    let end = d[start..].iter().position(|&b| b == 0).map(|p| start + p)?;
    Some(crate::decode_filename(&d[start..end]))
}

/// The keycode-LZSS used by both VER5 and VER6: `[destSize u32][srcSize u32][keycode u8][stream]`.
pub(super) fn decode_lz(src: &[u8], dest_size: usize) -> Option<Vec<u8>> {
    if src.len() < 9 {
        return None;
    }
    let mut remaining = (u32at(src, 4)? as usize).checked_sub(9)?;
    let keycode = src[8];
    let mut out: Vec<u8> = Vec::with_capacity(dest_size);
    let mut sp = 9usize;

    while remaining > 0 {
        let b = *src.get(sp)?;
        if b != keycode {
            out.push(b);
            sp += 1;
            remaining -= 1;
            continue;
        }
        if *src.get(sp + 1)? == keycode {
            out.push(keycode);
            sp += 2;
            remaining -= 2;
            continue;
        }
        let mut code = *src.get(sp + 1)? as u32;
        if code > keycode as u32 {
            code -= 1;
        }
        sp += 2;
        remaining -= 2;

        let mut conbo = (code >> 3) as usize;
        if code & 0x4 != 0 {
            conbo |= (*src.get(sp)? as usize) << 5;
            sp += 1;
            remaining -= 1;
        }
        conbo += MIN_COMPRESS;

        let mut index = match code & 0x3 {
            0 => {
                let v = *src.get(sp)? as usize;
                sp += 1;
                remaining -= 1;
                v
            }
            1 => {
                let v = u16::from_le_bytes([*src.get(sp)?, *src.get(sp + 1)?]) as usize;
                sp += 2;
                remaining -= 2;
                v
            }
            _ => {
                let v = u16::from_le_bytes([*src.get(sp)?, *src.get(sp + 1)?]) as usize
                    | ((*src.get(sp + 2)? as usize) << 16);
                sp += 3;
                remaining -= 3;
                v
            }
        };
        index += 1;

        if index > out.len() {
            return None; // back-reference before start
        }
        if index < conbo {
            // Overlapping run via doubling memcpy (matches DXLib exactly).
            let mut num = index;
            let mut left = conbo;
            while left > num {
                let s = out.len() - num;
                for j in 0..num {
                    let v = out[s + j];
                    out.push(v);
                }
                left -= num;
                num += num;
            }
            if left != 0 {
                let s = out.len() - num;
                for j in 0..left {
                    let v = out[s + j];
                    out.push(v);
                }
            }
        } else {
            let s = out.len() - index;
            for j in 0..conbo {
                let v = out[s + j];
                out.push(v);
            }
        }
    }
    Some(out)
}
