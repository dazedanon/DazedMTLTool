//! `wolf-archive`: Wolf RPG `Data.wolf` archives. Unpacks every DXArchive variant Wolf uses.
//!
//! Public API: [`extract_archive`] / [`list_archive`] / [`extract_one`] (bytes to files) and
//! the CLI [`run`]. The format and crypto live in submodules: [`dxarchive`] (the v8 container
//! plus key dispatch), [`crypto`] (WolfPro stream plus AES), [`codec`] (Huffman plus LZSS),
//! [`dxarc_v2`] (the old VER5/VER6 archives), and [`chacha20`].

use std::fs;
use std::io::{self, Read};
use std::path::PathBuf;

pub mod chacha20;
mod codec;
mod crypto;
pub mod dxarc_v2;
mod dxarchive;
pub mod pack;

pub use dxarc_v2::{pack_ver5, pack_ver6};
pub use pack::{archive_crypt_params, pack_chacha, pack_encrypted, pack_newcrypt, pack_plaintext};

use crypto::*;
use dxarchive::*;

pub(crate) const DX_HEAD: u16 = 0x5844;
pub(crate) const DX_VER_8: u16 = 0x0008;
pub(crate) const KEY_BYTES: usize = 7;
pub(crate) const NONE: u64 = u64::MAX;
pub(crate) const FILE_ATTRIBUTE_DIRECTORY: u64 = 0x10;
pub const DEFAULT_WOLF_PRO_KEY: &[u8] = b"WLFRPrO!p(;s5((8P@((UFWlu$#5(=";
pub(crate) const DEFAULT_DXLIB_KEY: &[u8] = b"DXBDXARC";
pub(crate) const DEFAULT_OLD_WOLF_KEY: &[u8] = b"8P@(rO!p;s5";
pub(crate) const DEFAULT_WOLF_V310_KEY: &[u8] = &[
    0x0f, 0x53, 0xe1, 0x3e, 0x8e, 0xb5, 0x41, 0x91, 0x52, 0x16, 0x55, 0xae, 0x34, 0xc9, 0x8f, 0x79,
    0x59, 0x2f, 0x59, 0x6b, 0x95, 0x19, 0x9b, 0x1b, 0x35, 0x9a, 0x2f, 0xde, 0xc9, 0x7c, 0x12, 0x96,
    0xc3, 0x14, 0xb5, 0x0f, 0x53, 0xe1, 0x3e, 0x8e, 0x00,
];
pub(crate) const DEFAULT_WOLF_V3173_KEY: &[u8] = &[
    0x31, 0xf9, 0x01, 0x36, 0xa3, 0xe3, 0x8d, 0x3c, 0x7b, 0xc3, 0x7d, 0x25, 0xad, 0x63, 0x28, 0x19,
    0x1b, 0xf7, 0x8e, 0x6c, 0xc4, 0xe5, 0xe2, 0x76, 0x82, 0xea, 0x4f, 0xed, 0x61, 0xda, 0xe0, 0x44,
    0x5b, 0xb6, 0x46, 0x3b, 0x06, 0xd5, 0xce, 0xb6, 0x78, 0x58, 0xd0, 0x7c, 0x82, 0x00,
];
pub(crate) const DEFAULT_WOLF_V331_KEY: &[u8] = &[
    0xca, 0x08, 0x4c, 0x5d, 0x17, 0x0d, 0xda, 0xa1, 0xd7, 0x27, 0xc8, 0x41, 0x54, 0x38, 0x82, 0x32,
    0x54, 0xb7, 0xf9, 0x46, 0x8e, 0x13, 0x6b, 0xca, 0xd0, 0x5c, 0x95, 0x95, 0xe2, 0xdc, 0x03, 0x53,
    0x60, 0x9b, 0x4a, 0x38, 0x17, 0xf3, 0x69, 0x59, 0xa4, 0xc7, 0x9a, 0x43, 0x63, 0xe6, 0x54, 0xaf,
    0xdb, 0xbb, 0x43, 0x58, 0x00,
];
pub(crate) const DEFAULT_WOLF_V350_KEY: &[u8] = &[
    0xd2, 0x84, 0xce, 0x28, 0xce, 0x88, 0x82, 0xe4, 0x2a, 0x18, 0x2e, 0x4c, 0x06, 0xb4, 0xea, 0x84,
    0x06, 0xb8, 0xc6, 0x88, 0x5a, 0xa0, 0x9e, 0x7c, 0x56, 0x40, 0xba, 0x34, 0x52, 0xcc, 0xc6, 0x7c,
    0x2e, 0x14, 0x12, 0x68, 0xfe, 0x5c, 0x76, 0x94, 0x86, 0x78, 0x8e, 0x4c, 0xbe, 0x88, 0x66, 0x9c,
    0x1e, 0xe0, 0x8e, 0x6c, 0x00,
];
pub(crate) const DEFAULT_WOLF_CHACHA2_KEY: &[u8] = &[
    0xc9, 0x82, 0xf8, 0xb4, 0x2c, 0x93, 0x9e, 0x83, 0x0e, 0xbc, 0xbc, 0x92, 0x68, 0x8d, 0x59, 0xa1,
    0x4a, 0x9e, 0x7f, 0xb0, 0xac, 0xaf, 0x1d, 0x8f, 0x8e, 0xb8, 0x3b, 0x9e, 0xe8, 0x89, 0xd9, 0xad,
    0xff, 0xbc, 0x2d, 0xab, 0x9d, 0x8b, 0x0f, 0xb4, 0xbb, 0x9a, 0x69, 0x85, 0x00,
];
pub(crate) const DEFAULT_ONE_WAY_KEY: &[u8] = b"nGui9('&1=@3#a";
pub(crate) const DEFAULT_ONE_WAY_FULL_KEY: &[u8] = b"Ph=X3^]o2A(,1=@3#a";
pub(crate) const MAX_DECODE_SIZE: usize = 2 * 1024 * 1024 * 1024;
pub(crate) const AES_KEY_EXP_SIZE: usize = 176;
pub(crate) const AES_IV_SIZE: usize = 16;
pub(crate) const AES_ROUND_KEY_SIZE: usize = AES_KEY_EXP_SIZE + AES_IV_SIZE;
pub(crate) const AES_BLOCK_LEN: usize = 16;
#[derive(Clone, Copy, Debug)]
pub(crate) struct DxHead {
    pub(crate) head: u16,
    pub(crate) version: u16,
    pub(crate) head_size: u32,
    pub(crate) data_start: u64,
    pub(crate) name_table_start: u64,
    pub(crate) file_table_start: u64,
    pub(crate) directory_table_start: u64,
    pub(crate) char_code_format: u32,
    pub(crate) flags: u32,
    pub(crate) huffman_encode_kb: u8,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct FileHead {
    pub(crate) name_addr: u64,
    pub(crate) attrs: u64,
    pub(crate) data_addr: u64,
    pub(crate) data_size: u64,
    pub(crate) press_size: u64,
    pub(crate) huff_size: u64,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct Directory {
    pub(crate) directory_addr: u64,
    pub(crate) parent_addr: u64,
    pub(crate) file_head_num: u64,
    pub(crate) file_head_addr: u64,
}

#[derive(Debug)]
pub(crate) struct Layout {
    pub(crate) table: Vec<u8>,
    pub(crate) data_start: u64,
    pub(crate) file_table_start: usize,
    pub(crate) directory_table_start: usize,
    pub(crate) huffman_encode_kb: u8,
    pub(crate) flags: u32,
    pub(crate) key_string: Vec<u8>,
    pub(crate) main_key_pos: usize,
    pub(crate) source: String,
    pub(crate) wolf: Option<WolfContext>,
    /// ChaCha20 (key, nonce) for "ChaCha2" archives (cryptVersion 0x64 / 0xC8).
    pub(crate) chacha: Option<([u8; 32], [u8; 12])>,
}

#[derive(Clone, Debug)]
pub(crate) struct WolfContext {
    pub(crate) crypt_version: u16,
    pub(crate) other_key: [u8; 768],
    pub(crate) special_key: [u8; 768],
    pub(crate) aes_round_key: [u8; AES_ROUND_KEY_SIZE],
    pub(crate) body_size: usize,
    pub(crate) name_table_start: usize,
}

/// `key_string` is the WolfPro key seed (use [`DEFAULT_WOLF_PRO_KEY`] when unknown).
pub fn extract_archive(data: &[u8], key_string: &[u8]) -> io::Result<Vec<(String, Vec<u8>)>> {
    let layout = match detect_layout(data, key_string) {
        Ok(l) => l,
        // Fall back to the old DXArchive VER5/VER6 format (Wolf 2.0x).
        Err(e) => return dxarc_v2::try_extract(data).ok_or(e),
    };
    let files = collect_files(&layout)?;
    let mut out = Vec::with_capacity(files.len());
    for entry in &files {
        let bytes = extract_file(data, &layout, entry)?;
        out.push((entry.path.clone(), bytes));
    }
    Ok(out)
}

/// List archive file paths. Decodes only the tables, not file contents, so it stays cheap
/// even for multi-GB archives.
pub fn list_archive(data: &[u8], key_string: &[u8]) -> io::Result<Vec<String>> {
    match detect_layout(data, key_string) {
        Ok(layout) => Ok(collect_files(&layout)?
            .into_iter()
            .map(|e| e.path)
            .collect()),
        Err(e) => dxarc_v2::try_extract(data)
            .map(|f| f.into_iter().map(|(p, _)| p).collect())
            .ok_or(e),
    }
}

/// Extract a single file by its `\\`-separated archive path, decoding only that file.
pub fn extract_one(data: &[u8], key_string: &[u8], path: &str) -> io::Result<Option<Vec<u8>>> {
    let layout = match detect_layout(data, key_string) {
        Ok(l) => l,
        Err(e) => {
            return match dxarc_v2::try_extract(data) {
                Some(files) => Ok(files.into_iter().find(|(p, _)| p == path).map(|(_, c)| c)),
                None => Err(e),
            }
        }
    };
    let files = collect_files(&layout)?;
    match files.iter().find(|e| e.path == path) {
        Some(e) => Ok(Some(extract_file(data, &layout, e)?)),
        None => Ok(None),
    }
}

/// CLI entry point: `wolf-unpack <Data.wolf> [output_dir] [key_string]`. Traces the head-table
/// decode with `key_string` and optionally extracts.
pub fn run(args: &[String]) -> io::Result<()> {
    if args.len() < 2 {
        eprintln!("usage: wolf-unpack <Data.wolf> [output_dir] [key_string]");
        std::process::exit(2);
    }

    let archive_path = PathBuf::from(&args[1]);
    let out_dir = args.get(2).map(PathBuf::from);
    let key_string = args
        .get(3)
        .map(|s| s.as_bytes().to_vec())
        .unwrap_or_else(|| DEFAULT_WOLF_PRO_KEY.to_vec());

    let mut data = Vec::new();
    fs::File::open(&archive_path)?.read_to_end(&mut data)?;

    let key = key_create(&key_string);
    println!("archive: {}", archive_path.display());
    println!("key: {}", hex(&key));

    let layout = detect_layout(&data, &key_string)?;
    println!("layout: {}", layout.source);
    println!(
        "table={} data_start={} file_table={} dir_table={} huff_kb={} flags=0x{:08x} key_pos={}",
        layout.table.len(),
        layout.data_start,
        layout.file_table_start,
        layout.directory_table_start,
        layout.huffman_encode_kb,
        layout.flags,
        layout.main_key_pos
    );

    let files = collect_files(&layout)?;
    println!("files: {}", files.len());
    for (i, entry) in files.iter().take(20).enumerate() {
        println!(
            "{:5} {:10} {:10} {:10} {}",
            i,
            entry.head.data_size,
            display_opt_size(entry.head.press_size),
            display_opt_size(entry.head.huff_size),
            entry.path
        );
    }

    if let Some(out_dir) = out_dir {
        extract_all(&data, &layout, &files, &out_dir)?;
        println!("extracted to {}", out_dir.display());
    }

    Ok(())
}
pub(crate) fn read_u16(b: &[u8]) -> u16 {
    u16::from_le_bytes([b[0], b[1]])
}

pub(crate) fn read_u32(b: &[u8]) -> u32 {
    u32::from_le_bytes([b[0], b[1], b[2], b[3]])
}

pub(crate) fn read_u64(b: &[u8]) -> u64 {
    u64::from_le_bytes([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]])
}

pub(crate) fn decode_filename(raw: &[u8]) -> String {
    // Archive filenames are ASCII/UTF-8 in newer (3.x) Wolf builds and Shift-JIS in older
    // Japanese ones. A lossy UTF-8 decode turns SJIS lead bytes into U+FFFD while leaving
    // their trailing bytes (e.g. 0x7C `|`, 0x3C `<`) as literal ASCII. Those are invalid in
    // Windows paths (ERROR_INVALID_NAME) and abort the unpack. Decode as Shift-JIS whenever
    // the bytes are not already valid UTF-8.
    let s = match std::str::from_utf8(raw) {
        Ok(s) => std::borrow::Cow::Borrowed(s),
        Err(_) => encoding_rs::SHIFT_JIS.decode(raw).0,
    };
    s.replace('/', "\\")
}

pub(crate) fn safe_relative_path(path: &str) -> PathBuf {
    let mut out = PathBuf::new();
    for part in path.split(['\\', '/']) {
        if part.is_empty() || part == "." || part == ".." {
            continue;
        }
        let cleaned: String = part
            .chars()
            .map(|c| match c {
                '<' | '>' | ':' | '"' | '|' | '?' | '*' => '_',
                _ => c,
            })
            .collect();
        out.push(cleaned);
    }
    out
}

pub(crate) fn display_opt_size(v: u64) -> String {
    if v == NONE {
        "-".to_string()
    } else {
        v.to_string()
    }
}

pub(crate) fn hex(bytes: &[u8]) -> String {
    bytes
        .iter()
        .map(|b| format!("{b:02X}"))
        .collect::<Vec<_>>()
        .join("")
}

pub(crate) fn invalid<E: std::fmt::Display>(msg: E) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, msg.to_string())
}
