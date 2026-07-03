//! DXArchive (VER8) writer: the inverse of [`crate::dxarchive`].
//!
//! Produces a `.wolf` the engine loads (DXLib's `NO_HEAD_PRESS` mode, plus `NO_KEY` for the
//! plaintext variant) that our own extractor round-trips byte-for-byte. Follows DXLib's
//! `EncodeArchive`/`DirectoryEncode` address semantics (root self-filehead, per-directory
//! contiguous file runs, name-table parity), so the container is a real DXArchive. Re-encryption
//! per `cryptVersion` layers on top of the plaintext build, reusing the reader's symmetric
//! decrypt as the encrypt.
//!
//! ## Known deviations from an editor-produced archive (do not affect loading)
//! * Filenames are stored as UTF-8 bytes with the header declaring codepage 932. For the
//!   all-ASCII paths Wolf uses internally (`Game.dat`, `MapData/Map001.mps`, …) UTF-8 == SJIS,
//!   so this is exact. A non-ASCII filename would need Shift-JIS encoding to match the
//!   engine's `packNum`/parity file search, which is not yet done (this crate is
//!   zero-dependency).
//! * Inter-file 4-byte alignment padding is written as plaintext zeros (the reader reads
//!   exactly `data_size` and ignores it). DXLib keys the padded length. So the archive
//!   round-trips through our reader and loads, but is not byte-identical to the editor's.

use std::collections::BTreeMap;

use crate::crypto::{
    key_conv, key_create, read_wolf_archive_slice, wolf_aes_body_size, wolf_aes_init_round_key,
    wolf_crypt, wolf_crypt_addresses, wolf_init_key,
};
use crate::dxarchive::{collect_files, file_key, parse_full_head};
use crate::{
    Layout, WolfContext, DEFAULT_WOLF_V310_KEY, DEFAULT_WOLF_V3173_KEY, DEFAULT_WOLF_V331_KEY,
    DEFAULT_WOLF_V350_KEY, KEY_BYTES,
};

const HEADER_SIZE: usize = 64;
const FILEHEAD_SIZE: usize = 72;
const NONE: u64 = u64::MAX;

const DX_HEAD: u16 = 0x5844; // *(u16*)"DX"
const DX_VER_8: u16 = 0x0008;
const FLAG_NO_KEY: u32 = 0x01;
const FLAG_NO_HEAD_PRESS: u32 = 0x02;
const CHAR_CODE_SJIS: u32 = 0x3A4; // codepage 932
const ATTR_DIRECTORY: u64 = 0x10;
const ATTR_ARCHIVE: u64 = 0x20;

/// A directory node built from the flat path list (references the caller's file bytes).
/// Shared with the VER5/VER6 encoder ([`crate::dxarc_v2::encode`]).
#[derive(Default)]
pub(crate) struct Node<'a> {
    pub(crate) dirs: BTreeMap<String, Node<'a>>,
    pub(crate) files: BTreeMap<String, &'a [u8]>,
}

impl<'a> Node<'a> {
    pub(crate) fn entry_count(&self) -> usize {
        self.dirs.len() + self.files.len()
    }

    pub(crate) fn insert(&mut self, parts: &[&str], data: &'a [u8]) {
        match parts {
            [] => {}
            [name] => {
                self.files.insert((*name).to_string(), data);
            }
            [dir, rest @ ..] => {
                self.dirs
                    .entry((*dir).to_string())
                    .or_default()
                    .insert(rest, data);
            }
        }
    }
}

/// The four growing sections of a DXArchive (mirrors DXLib's `SIZESAVE` + buffers).
#[derive(Default)]
struct Build {
    name: Vec<u8>,
    file: Vec<u8>,
    dir: Vec<u8>,
    data: Vec<u8>,
}

/// Pack a flat `(path, bytes)` list into an unencrypted, uncompressed `.wolf` archive.
/// Paths may use `/` or `\` separators. Returns the archive bytes. Errors only if the list
/// is empty (DXArchive requires at least one entry under the root).
pub fn pack_plaintext(files: &[(String, Vec<u8>)]) -> Result<Vec<u8>, String> {
    if files.is_empty() {
        return Err("cannot pack an empty file list".to_string());
    }

    let mut root = Node::default();
    for (path, data) in files {
        let parts: Vec<&str> = path.split(['\\', '/']).filter(|s| !s.is_empty()).collect();
        if parts.is_empty() {
            return Err(format!("invalid (empty) path in file list: {path:?}"));
        }
        root.insert(&parts, data);
    }

    let mut b = Build::default();

    // Root self-filehead (empty name) at file-table offset 0, root DARC_DIRECTORY at dir
    // offset 0 (parent = NONE). Mirrors DXLib's EncodeArchive root setup.
    add_filename(&mut b.name, ""); // name_address 0
    b.file.resize(FILEHEAD_SIZE, 0);
    write_filehead(&mut b.file, 0, 0, ATTR_DIRECTORY, 0, 0);

    let root_num = root.entry_count() as u64;
    let root_fha = b.file.len() as u64; // = 72
    append_directory(&mut b.dir, 0, NONE, root_num, root_fha);
    b.file
        .resize(b.file.len() + FILEHEAD_SIZE * root_num as usize, 0);

    encode_children(&mut b, &root, root_fha, 0);

    // Assemble: HEADER | file data | name table | file table | directory table.
    let head_size = b.name.len() + b.file.len() + b.dir.len();
    let mut out = Vec::with_capacity(HEADER_SIZE + b.data.len() + head_size);
    write_header(
        &mut out,
        head_size as u32,
        (HEADER_SIZE + b.data.len()) as u64,  // name_table_start
        b.name.len() as u64,                  // file_table_start (rel to name table)
        (b.name.len() + b.file.len()) as u64, // directory_table_start (rel)
    );
    out.extend_from_slice(&b.data);
    out.extend_from_slice(&b.name);
    out.extend_from_slice(&b.file);
    out.extend_from_slice(&b.dir);
    Ok(out)
}

/// Re-encrypt a directory into a keyed VER8 archive for a known cryptVersion (v3.00 = `0x12C`,
/// v3.14 = `0x13A`). Every Wolf cipher is symmetric (XOR-stream), so we build the plaintext
/// container then apply the same `key_conv` the reader undoes. The 64-byte header stays
/// plaintext (only `Flags` is patched), the table block and each file's data are keyed, and
/// `NO_HEAD_PRESS` keeps the header uncompressed so no Huffman encoder is needed. The output
/// decodes through our own deterministic dispatch (see the module-level note for the minor
/// deviations from an editor-produced archive).
pub fn pack_encrypted(files: &[(String, Vec<u8>)], crypt_version: u16) -> Result<Vec<u8>, String> {
    let key_string: &[u8] = match crypt_version {
        0x12C => DEFAULT_WOLF_V310_KEY,  // Wolf v3.00
        0x13A => DEFAULT_WOLF_V3173_KEY, // Wolf v3.14
        _ => {
            return Err(format!(
                "unsupported encrypt cryptVersion {crypt_version:#x} \
                 (supported: 0x12c=v3.00, 0x13a=v3.14)"
            ))
        }
    };

    let mut out = pack_plaintext(files)?;
    let head = parse_full_head(&out).map_err(|e| e.to_string())?;
    let name_start = head.name_table_start as usize;
    let head_size = head.head_size as usize;
    let data_start = head.data_start;

    // A reader Layout over the RAW (still-plaintext) table, so per-file keys are computed
    // from the same name table the reader will see after it decrypts.
    let layout = Layout {
        table: out[name_start..name_start + head_size].to_vec(),
        data_start,
        file_table_start: head.file_table_start as usize,
        directory_table_start: head.directory_table_start as usize,
        huffman_encode_kb: head.huffman_encode_kb,
        flags: head.flags,
        key_string: key_string.to_vec(),
        main_key_pos: 0,
        source: "encrypt".to_string(),
        wolf: None,
        chacha: None,
    };
    let entries = collect_files(&layout).map_err(|e| e.to_string())?;

    // Encrypt each file's data with its per-file key, at the same start offset the reader
    // uses (`data_size % KEY_BYTES`).
    for entry in &entries {
        let key = file_key(&layout, entry).map_err(|e| e.to_string())?;
        let start = (data_start + entry.head.data_addr) as usize;
        let len = entry.head.data_size as usize;
        key_conv(&mut out[start..start + len], &key, len % KEY_BYTES);
    }

    // Encrypt the table block (header stays plaintext) and patch Flags (clears NO_KEY).
    key_conv(
        &mut out[name_start..name_start + head_size],
        &key_create(key_string),
        0,
    );
    let flags = ((crypt_version as u32) << 16) | FLAG_NO_HEAD_PRESS;
    out[44..48].copy_from_slice(&flags.to_le_bytes());

    Ok(out)
}

/// Re-encrypt into a "ChaCha2" archive (cryptVersion `0x64`). The header stays plaintext, the
/// table and each file's data are ChaCha20-keyed with the fixed chacha2 key/nonce (position 0
/// for the table, `data_size` for each file, matching our decoder). ChaCha20 is symmetric, so
/// this is again the reader's decode applied to plaintext. Self-consistent with our extractor.
/// The ChaCha2 decode path itself is unverified against a real ChaCha2 game (none in the
/// corpus).
pub fn pack_chacha(files: &[(String, Vec<u8>)]) -> Result<Vec<u8>, String> {
    let mut out = pack_plaintext(files)?;
    let head = parse_full_head(&out).map_err(|e| e.to_string())?;
    let name_start = head.name_table_start as usize;
    let head_size = head.head_size as usize;
    let data_start = head.data_start;

    let ck: [u8; 32] = crate::DEFAULT_WOLF_CHACHA2_KEY[0..32]
        .try_into()
        .map_err(|_| "chacha key")?;
    let cn: [u8; 12] = crate::DEFAULT_WOLF_CHACHA2_KEY[32..44]
        .try_into()
        .map_err(|_| "chacha nonce")?;

    // Enumerate files from the plaintext table.
    let layout = Layout {
        table: out[name_start..name_start + head_size].to_vec(),
        data_start,
        file_table_start: head.file_table_start as usize,
        directory_table_start: head.directory_table_start as usize,
        huffman_encode_kb: head.huffman_encode_kb,
        flags: head.flags,
        key_string: Vec::new(),
        main_key_pos: 0,
        source: "chacha-encode".to_string(),
        wolf: None,
        chacha: Some((ck, cn)),
    };
    let entries = collect_files(&layout).map_err(|e| e.to_string())?;
    for entry in &entries {
        let start = (data_start + entry.head.data_addr) as usize;
        let len = entry.head.data_size as usize;
        crate::chacha20::crypt(&mut out[start..start + len], &ck, &cn, len as u32);
    }
    // Table at position 0.
    crate::chacha20::crypt(&mut out[name_start..name_start + head_size], &ck, &cn, 0);

    let flags = (0x64u32 << 16) | FLAG_NO_HEAD_PRESS;
    out[44..48].copy_from_slice(&flags.to_le_bytes());
    Ok(out)
}

/// Read the cryptVersion (`Flags>>16`) and the embedded 15-byte password from an existing
/// archive header (both live plaintext in the header). Feed these to [`pack_newcrypt`] to
/// repack a directory under the same encryption an original `Data.wolf` uses.
pub fn archive_crypt_params(data: &[u8]) -> Option<(u16, [u8; 15])> {
    if data.len() < 64 {
        return None;
    }
    let flags = u32::from_le_bytes(data[44..48].try_into().ok()?);
    let mut pwd = [0u8; 15];
    pwd.copy_from_slice(&data[49..64]);
    Some(((flags >> 16) as u16, pwd))
}

/// Re-encrypt into a WolfPro "new-crypt" archive (v3.31 = `0x14B`, v3.50 / v3.5 = `0x15E`).
/// The whole new-crypt transform (768-byte stream, AES-CTR, header address scramble) is
/// XOR-based, hence an involution, so encryption is exactly the reader's decrypt applied to
/// the plaintext container, reusing the tested primitives. The 15-byte `pwd` is embedded in the
/// header (bytes 49..64) just as the engine stores it. Re-encrypting GamePro with its own
/// embedded password yields a game-loadable archive (the Game.dat hash still validates).
/// `NO_HEAD_PRESS` keeps the header uncompressed (no Huffman encoder needed).
pub fn pack_newcrypt(
    files: &[(String, Vec<u8>)],
    crypt_version: u16,
    pwd: &[u8; 15],
) -> Result<Vec<u8>, String> {
    let key_string: &[u8] = match crypt_version {
        0x14B => DEFAULT_WOLF_V331_KEY, // Wolf Pro v3.31
        0x15E => DEFAULT_WOLF_V350_KEY, // Wolf Pro v3.50 / v3.5
        _ => {
            return Err(format!(
                "unsupported new-crypt cryptVersion {crypt_version:#x} \
                 (supported: 0x14b=v3.31, 0x15e=v3.50)"
            ))
        }
    };

    let mut out = pack_plaintext(files)?;
    let head = parse_full_head(&out).map_err(|e| e.to_string())?;
    let name_start = head.name_table_start as usize;
    let head_size = head.head_size as usize;
    let data_start = head.data_start;

    // Patch the header: embed the password, set new-crypt flags (cv<<16 | NO_HEAD_PRESS).
    out[49..64].copy_from_slice(pwd);
    let flags = ((crypt_version as u32) << 16) | FLAG_NO_HEAD_PRESS;
    out[44..48].copy_from_slice(&flags.to_le_bytes());

    // Build the context exactly as the reader will recompute it (file_size + embedded pwd).
    let file_size = out.len();
    let ctx = WolfContext {
        crypt_version,
        other_key: wolf_init_key(crypt_version, pwd, None, true, key_string),
        special_key: wolf_init_key(crypt_version, pwd, None, false, key_string),
        aes_round_key: wolf_aes_init_round_key(pwd, None, crypt_version),
        body_size: wolf_aes_body_size(file_size, crypt_version, pwd, None),
        name_table_start: name_start,
    };

    // Enumerate files from the still-plaintext table (collect_files only walks the table).
    let layout = Layout {
        table: out[name_start..name_start + head_size].to_vec(),
        data_start,
        file_table_start: head.file_table_start as usize,
        directory_table_start: head.directory_table_start as usize,
        huffman_encode_kb: head.huffman_encode_kb,
        flags,
        key_string: key_string.to_vec(),
        main_key_pos: 0,
        source: "newcrypt-encode".to_string(),
        wolf: Some(ctx.clone()),
        chacha: None,
    };
    let entries = collect_files(&layout).map_err(|e| e.to_string())?;

    // Encrypt each file's data: ciphertext = wolf_crypt_special(S(plaintext)), i.e. the
    // reader's decrypt path, which is its own inverse. File regions are disjoint, so order
    // is irrelevant and reading one never depends on another.
    for entry in &entries {
        let start = (data_start + entry.head.data_addr) as usize;
        let len = entry.head.data_size as usize;
        let mut slice = read_wolf_archive_slice(&out, start, len, &ctx)
            .ok_or("file data slice out of range")?;
        wolf_crypt(&ctx.special_key, &mut slice, len, crypt_version);
        out[start..start + len].copy_from_slice(&slice);
    }

    // Encrypt the table block (still plaintext at this point).
    let mut table = read_wolf_archive_slice(&out, name_start, head_size, &ctx)
        .ok_or("table slice out of range")?;
    wolf_crypt(&ctx.special_key, &mut table, 0, crypt_version);
    out[name_start..name_start + head_size].copy_from_slice(&table);

    // Encrypt the header address fields (bytes 8..40). The password at 49..64 stays plaintext.
    let mut header = out[..64].to_vec();
    wolf_crypt_addresses(&mut header, pwd, crypt_version);
    out[..64].copy_from_slice(&header);

    Ok(out)
}

/// Write the `data_number`-th entry slots of a directory whose children block starts at
/// `fha`. Subdirectories recurse (each writes its own self-filehead into this block). Files
/// write a leaf filehead and append their (4-aligned) data. `this_dir_addr` is this
/// directory's own DirectoryAddress (used by children for ParentDirectoryAddress).
fn encode_children(b: &mut Build, node: &Node, fha: u64, this_dir_addr: u64) {
    let mut i = 0u64;
    for (name, child) in &node.dirs {
        directory_encode(b, child, name, fha, this_dir_addr, i);
        i += 1;
    }
    for (name, data) in &node.files {
        write_file_entry(b, name, data, fha, i);
        i += 1;
    }
}

/// Encode one subdirectory: its self-filehead goes into the parent's reserved slot
/// (`parent_fha + data_number*72`). Its own DARC_DIRECTORY and children block follow.
fn directory_encode(
    b: &mut Build,
    node: &Node,
    name: &str,
    parent_fha: u64,
    parent_dir_addr: u64,
    data_number: u64,
) {
    // This dir's self-filehead (written into the parent's file run).
    let name_addr = b.name.len() as u64;
    let this_dir_offset = b.dir.len() as u64;
    add_filename(&mut b.name, name);
    let self_fh_off = (parent_fha + data_number * FILEHEAD_SIZE as u64) as usize;
    write_filehead(
        &mut b.file,
        self_fh_off,
        name_addr,
        ATTR_DIRECTORY,
        this_dir_offset,
        0,
    );

    let this_fha = b.file.len() as u64;
    // ParentDirectoryAddress = DataAddress field of the parent's self-filehead (= parent's
    // dir-table offset), or 0 for children of the root (whose DirectoryAddress is 0).
    let parent_directory_address = if parent_dir_addr != NONE && parent_dir_addr != 0 {
        read_u64(&b.file, parent_dir_addr as usize + 40)
    } else {
        0
    };
    let num = node.entry_count() as u64;
    append_directory(
        &mut b.dir,
        self_fh_off as u64,
        parent_directory_address,
        num,
        this_fha,
    );
    b.file
        .resize(b.file.len() + FILEHEAD_SIZE * num as usize, 0);

    encode_children(b, node, this_fha, self_fh_off as u64);
}

/// Write a leaf file: its filehead into slot `data_number` of the run at `fha`, its bytes
/// (4-aligned) into the data section.
fn write_file_entry(b: &mut Build, name: &str, data: &[u8], fha: u64, data_number: u64) {
    let name_addr = b.name.len() as u64;
    add_filename(&mut b.name, name);
    let data_addr = b.data.len() as u64;
    let off = (fha + data_number * FILEHEAD_SIZE as u64) as usize;
    write_filehead(
        &mut b.file,
        off,
        name_addr,
        ATTR_ARCHIVE,
        data_addr,
        data.len() as u64,
    );
    b.data.extend_from_slice(data);
    while b.data.len() % 4 != 0 {
        b.data.push(0);
    }
}

/// Append a DXArchive name-table entry: `[u16 packNum][u16 parity][UPPER name][original name]`.
/// `packNum = ceil((len+1)/4)` and parity = sum of the uppercased name bytes. The engine's file
/// search matches on packNum and parity, so both must be exact. The name-table format is
/// identical across v8 and VER5/VER6, so the VER5/VER6 encoder ([`crate::dxarc_v2::encode`])
/// reuses this.
pub(crate) fn add_filename(buf: &mut Vec<u8>, name: &str) {
    let s = name.as_bytes();
    if s.is_empty() {
        buf.extend_from_slice(&[0, 0, 0, 0]); // packNum 0, parity 0
        return;
    }
    let length = s.len() + 1; // include the trailing NUL
    let pack_num = (length + 3) / 4;
    let entry_size = pack_num * 4 * 2 + 4;
    let start = buf.len();
    buf.resize(start + entry_size, 0);

    let upper_off = start + 4;
    let orig_off = start + 4 + pack_num * 4;
    buf[orig_off..orig_off + s.len()].copy_from_slice(s); // original name (NUL already 0)

    let mut parity: u32 = 0;
    let mut i = 0;
    while i < s.len() {
        let lead = s[i];
        // Shift-JIS lead bytes carry a 2-byte char copied verbatim (no upper-casing).
        if (0x81..=0x9F).contains(&lead) || (0xE0..=0xFC).contains(&lead) {
            if i + 1 < s.len() {
                buf[upper_off + i] = s[i];
                buf[upper_off + i + 1] = s[i + 1];
                parity += s[i] as u32 + s[i + 1] as u32;
                i += 2;
                continue;
            }
        }
        let up = if lead.is_ascii_lowercase() {
            lead - b'a' + b'A'
        } else {
            lead
        };
        buf[upper_off + i] = up;
        parity += up as u32;
        i += 1;
    }
    buf[start + 2..start + 4].copy_from_slice(&(parity as u16).to_le_bytes());
    buf[start..start + 2].copy_from_slice(&(pack_num as u16).to_le_bytes());
}

fn write_filehead(
    file: &mut [u8],
    off: usize,
    name_addr: u64,
    attrs: u64,
    data_addr: u64,
    data_size: u64,
) {
    let b = &mut file[off..off + FILEHEAD_SIZE];
    b[0..8].copy_from_slice(&name_addr.to_le_bytes());
    b[8..16].copy_from_slice(&attrs.to_le_bytes());
    // Time (create / last-access / last-write) left zero.
    b[40..48].copy_from_slice(&data_addr.to_le_bytes());
    b[48..56].copy_from_slice(&data_size.to_le_bytes());
    b[56..64].copy_from_slice(&NONE.to_le_bytes()); // PressDataSize: not compressed
    b[64..72].copy_from_slice(&NONE.to_le_bytes()); // HuffPressDataSize: not compressed
}

fn append_directory(
    dir: &mut Vec<u8>,
    directory_addr: u64,
    parent_addr: u64,
    file_head_num: u64,
    file_head_addr: u64,
) {
    dir.extend_from_slice(&directory_addr.to_le_bytes());
    dir.extend_from_slice(&parent_addr.to_le_bytes());
    dir.extend_from_slice(&file_head_num.to_le_bytes());
    dir.extend_from_slice(&file_head_addr.to_le_bytes());
}

fn write_header(
    out: &mut Vec<u8>,
    head_size: u32,
    name_table_start: u64,
    file_table_start: u64,
    directory_table_start: u64,
) {
    out.extend_from_slice(&DX_HEAD.to_le_bytes());
    out.extend_from_slice(&DX_VER_8.to_le_bytes());
    out.extend_from_slice(&head_size.to_le_bytes());
    out.extend_from_slice(&(HEADER_SIZE as u64).to_le_bytes()); // DataStartAddress
    out.extend_from_slice(&name_table_start.to_le_bytes());
    out.extend_from_slice(&file_table_start.to_le_bytes());
    out.extend_from_slice(&directory_table_start.to_le_bytes());
    out.extend_from_slice(&CHAR_CODE_SJIS.to_le_bytes());
    out.extend_from_slice(&(FLAG_NO_KEY | FLAG_NO_HEAD_PRESS).to_le_bytes()); // cryptVersion 0
    out.push(0); // HuffmanEncodeKB (unused: nothing is compressed)
    out.extend_from_slice(&[0u8; 15]); // Reserve
}

fn read_u64(b: &[u8], off: usize) -> u64 {
    u64::from_le_bytes(b[off..off + 8].try_into().unwrap())
}
