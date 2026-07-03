//! DXArchive VER5: Wolf RPG Editor 2.01 / 2.10.
//!
//! 32-bit offsets and a 44-byte file head. For header version < 5 every region (header,
//! tables, file data) is keyed by its file offset, so the whole archive decrypts as one
//! continuous XOR stream. Verified byte-exact against the Wolf 2.01 sample-game `Data.wolf`.

use super::common::{decode_lz, key_create, name, u32at, KEYLEN};

/// VER5 version-table keys.
const KEYS: &[&[u8; KEYLEN]] = &[
    &[
        0x0f, 0x53, 0xe1, 0x3e, 0x04, 0x37, 0x12, 0x17, 0x60, 0x0f, 0x53, 0xe1,
    ], // v2.01
    &[
        0x4c, 0xd9, 0x2a, 0xb7, 0x28, 0x9b, 0xac, 0x07, 0x3e, 0x77, 0xec, 0x4c,
    ], // v2.10
];

pub(super) fn try_extract(data: &[u8]) -> Option<Vec<(String, Vec<u8>)>> {
    KEYS.iter().find_map(|ks| decode(data, &key_create(*ks)))
}

fn decode(data: &[u8], key: &[u8; KEYLEN]) -> Option<Vec<(String, Vec<u8>)>> {
    // Header version < 5: every region is keyed by file offset, so it is one XOR stream.
    let mut d = data.to_vec();
    for (i, b) in d.iter_mut().enumerate() {
        *b ^= key[i % KEYLEN];
    }
    if u16::from_le_bytes([*d.first()?, *d.get(1)?]) != 0x5844 {
        return None; // not a DX archive under this key
    }
    if u16::from_le_bytes([d[2], d[3]]) >= 5 {
        return None; // v>=5 keys files at DataSize, not file offset. That is VER6's job.
    }
    let data_start = u32at(&d, 8)? as usize;
    let name_tbl = u32at(&d, 12)? as usize;
    let file_p = name_tbl + u32at(&d, 16)? as usize;
    let dir_p = name_tbl + u32at(&d, 20)? as usize;

    let mut out = Vec::new();
    walk(
        &d,
        name_tbl,
        file_p,
        dir_p,
        data_start,
        0,
        String::new(),
        &mut out,
    )?;
    Some(out)
}

#[allow(clippy::too_many_arguments)]
fn walk(
    d: &[u8],
    name_p: usize,
    file_p: usize,
    dir_p: usize,
    data_start: usize,
    dir_off: usize,
    path: String,
    out: &mut Vec<(String, Vec<u8>)>,
) -> Option<()> {
    let fhn = u32at(d, dir_p + dir_off + 8)? as usize; // FileHeadNum
    let fha = u32at(d, dir_p + dir_off + 12)? as usize; // FileHeadAddress
    const FH: usize = 44; // sizeof(DARC_FILEHEAD_VER5)
    for i in 0..fhn {
        let fh = file_p + fha + i * FH;
        let name_addr = u32at(d, fh)? as usize;
        let attr = u32at(d, fh + 4)?;
        let data_addr = u32at(d, fh + 32)? as usize;
        let data_size = u32at(d, fh + 36)? as usize;
        let press_size = u32at(d, fh + 40)?;
        let nm = name(d, name_p + name_addr)?;

        if attr & 0x10 != 0 {
            walk(
                d,
                name_p,
                file_p,
                dir_p,
                data_start,
                data_addr,
                format!("{path}{nm}\\"),
                out,
            )?;
        } else {
            let start = data_start + data_addr;
            let content = if press_size != 0xffff_ffff {
                decode_lz(d.get(start..start + press_size as usize)?, data_size)?
            } else {
                d.get(start..start + data_size)?.to_vec()
            };
            out.push((format!("{path}{nm}"), content));
        }
    }
    Some(())
}
