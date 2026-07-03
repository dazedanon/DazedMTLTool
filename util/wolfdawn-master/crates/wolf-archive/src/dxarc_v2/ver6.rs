//! DXArchive VER6: Wolf RPG Editor 2.20.
//!
//! 64-bit offsets and a 64-byte file head (a bridge toward the v8 format). Unlike VER5, the
//! header and tables are keyed at stream position 0 and file data at position `DataSize`
//! (not the file offset). Same keycode-LZSS as VER5. Verified byte-exact against the Wolf
//! 2.20 sample-game `Data.wolf`.

use super::common::{decode_lz, key_conv, key_create, name, u64at, KEYLEN};

/// VER6 version-table key.
const KEYS: &[&[u8; KEYLEN]] = &[
    &[
        0x38, 0x50, 0x40, 0x28, 0x72, 0x4f, 0x21, 0x70, 0x3b, 0x73, 0x35, 0x38,
    ], // v2.20
];

pub(super) fn try_extract(data: &[u8]) -> Option<Vec<(String, Vec<u8>)>> {
    KEYS.iter().find_map(|ks| decode(data, &key_create(*ks)))
}

fn decode(data: &[u8], key: &[u8; KEYLEN]) -> Option<Vec<(String, Vec<u8>)>> {
    let head = key_conv(key, data.get(0..48)?, 0);
    if u16::from_le_bytes([head[0], head[1]]) != 0x5844
        || u16::from_le_bytes([head[2], head[3]]) != 6
    {
        return None;
    }
    let head_size = u32::from_le_bytes([head[4], head[5], head[6], head[7]]) as usize;
    let data_start = u64at(&head, 8)? as usize;
    let name_tbl = u64at(&head, 16)? as usize;
    let file_tbl = u64at(&head, 24)? as usize;
    let dir_tbl = u64at(&head, 32)? as usize;
    // Header + tables are keyed at position 0.
    let tbl = key_conv(key, data.get(name_tbl..name_tbl + head_size)?, 0);

    let mut out = Vec::new();
    walk(
        data,
        &tbl,
        key,
        file_tbl,
        dir_tbl,
        data_start,
        0,
        String::new(),
        &mut out,
    )?;
    Some(out)
}

#[allow(clippy::too_many_arguments)]
fn walk(
    data: &[u8],
    tbl: &[u8],
    key: &[u8; KEYLEN],
    file_tbl: usize,
    dir_tbl: usize,
    data_start: usize,
    dir_off: usize,
    path: String,
    out: &mut Vec<(String, Vec<u8>)>,
) -> Option<()> {
    let fhn = u64at(tbl, dir_tbl + dir_off + 16)? as usize; // FileHeadNum
    let fha = u64at(tbl, dir_tbl + dir_off + 24)? as usize; // FileHeadAddress
    const FH: usize = 64; // sizeof(DARC_FILEHEAD_VER6)
    for i in 0..fhn {
        let fh = file_tbl + fha + i * FH;
        let name_addr = u64at(tbl, fh)? as usize;
        let attr = u64at(tbl, fh + 8)?;
        let data_addr = u64at(tbl, fh + 40)? as usize;
        let data_size = u64at(tbl, fh + 48)? as usize;
        let press_size = u64at(tbl, fh + 56)?;
        let nm = name(tbl, name_addr)?;

        if attr & 0x10 != 0 {
            walk(
                data,
                tbl,
                key,
                file_tbl,
                dir_tbl,
                data_start,
                data_addr,
                format!("{path}{nm}\\"),
                out,
            )?;
        } else {
            let start = data_start + data_addr;
            // File data is keyed at stream position == DataSize.
            let content = if press_size != 0xffff_ffff_ffff_ffff {
                let enc = key_conv(
                    key,
                    data.get(start..start + press_size as usize)?,
                    data_size,
                );
                decode_lz(&enc, data_size)?
            } else {
                key_conv(key, data.get(start..start + data_size)?, data_size)
            };
            out.push((format!("{path}{nm}"), content));
        }
    }
    Some(())
}
