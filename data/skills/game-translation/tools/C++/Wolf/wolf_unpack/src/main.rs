use std::env;
use std::fs;
use std::io::{self, Read};
use std::path::{Path, PathBuf};

const DX_HEAD: u16 = 0x5844;
const DX_VER_8: u16 = 0x0008;
const KEY_BYTES: usize = 7;
const NONE: u64 = u64::MAX;
const FILE_ATTRIBUTE_DIRECTORY: u64 = 0x10;
const DEFAULT_WOLF_PRO_KEY: &[u8] = b"WLFRPrO!p(;s5((8P@((UFWlu$#5(=";
const DEFAULT_DXLIB_KEY: &[u8] = b"DXBDXARC";
const DEFAULT_OLD_WOLF_KEY: &[u8] = b"8P@(rO!p;s5";
const DEFAULT_WOLF_V310_KEY: &[u8] = &[
    0x0f, 0x53, 0xe1, 0x3e, 0x8e, 0xb5, 0x41, 0x91, 0x52, 0x16, 0x55, 0xae, 0x34, 0xc9, 0x8f,
    0x79, 0x59, 0x2f, 0x59, 0x6b, 0x95, 0x19, 0x9b, 0x1b, 0x35, 0x9a, 0x2f, 0xde, 0xc9, 0x7c,
    0x12, 0x96, 0xc3, 0x14, 0xb5, 0x0f, 0x53, 0xe1, 0x3e, 0x8e, 0x00,
];
const DEFAULT_WOLF_V3173_KEY: &[u8] = &[
    0x31, 0xf9, 0x01, 0x36, 0xa3, 0xe3, 0x8d, 0x3c, 0x7b, 0xc3, 0x7d, 0x25, 0xad, 0x63, 0x28,
    0x19, 0x1b, 0xf7, 0x8e, 0x6c, 0xc4, 0xe5, 0xe2, 0x76, 0x82, 0xea, 0x4f, 0xed, 0x61, 0xda,
    0xe0, 0x44, 0x5b, 0xb6, 0x46, 0x3b, 0x06, 0xd5, 0xce, 0xb6, 0x78, 0x58, 0xd0, 0x7c, 0x82,
    0x00,
];
const DEFAULT_WOLF_V331_KEY: &[u8] = &[
    0xca, 0x08, 0x4c, 0x5d, 0x17, 0x0d, 0xda, 0xa1, 0xd7, 0x27, 0xc8, 0x41, 0x54, 0x38, 0x82,
    0x32, 0x54, 0xb7, 0xf9, 0x46, 0x8e, 0x13, 0x6b, 0xca, 0xd0, 0x5c, 0x95, 0x95, 0xe2, 0xdc,
    0x03, 0x53, 0x60, 0x9b, 0x4a, 0x38, 0x17, 0xf3, 0x69, 0x59, 0xa4, 0xc7, 0x9a, 0x43, 0x63,
    0xe6, 0x54, 0xaf, 0xdb, 0xbb, 0x43, 0x58, 0x00,
];
const DEFAULT_WOLF_V350_KEY: &[u8] = &[
    0xd2, 0x84, 0xce, 0x28, 0xce, 0x88, 0x82, 0xe4, 0x2a, 0x18, 0x2e, 0x4c, 0x06, 0xb4, 0xea,
    0x84, 0x06, 0xb8, 0xc6, 0x88, 0x5a, 0xa0, 0x9e, 0x7c, 0x56, 0x40, 0xba, 0x34, 0x52, 0xcc,
    0xc6, 0x7c, 0x2e, 0x14, 0x12, 0x68, 0xfe, 0x5c, 0x76, 0x94, 0x86, 0x78, 0x8e, 0x4c, 0xbe,
    0x88, 0x66, 0x9c, 0x1e, 0xe0, 0x8e, 0x6c, 0x00,
];
const DEFAULT_WOLF_CHACHA2_KEY: &[u8] = &[
    0xc9, 0x82, 0xf8, 0xb4, 0x2c, 0x93, 0x9e, 0x83, 0x0e, 0xbc, 0xbc, 0x92, 0x68, 0x8d, 0x59,
    0xa1, 0x4a, 0x9e, 0x7f, 0xb0, 0xac, 0xaf, 0x1d, 0x8f, 0x8e, 0xb8, 0x3b, 0x9e, 0xe8, 0x89,
    0xd9, 0xad, 0xff, 0xbc, 0x2d, 0xab, 0x9d, 0x8b, 0x0f, 0xb4, 0xbb, 0x9a, 0x69, 0x85, 0x00,
];
const DEFAULT_ONE_WAY_KEY: &[u8] = b"nGui9('&1=@3#a";
const DEFAULT_ONE_WAY_FULL_KEY: &[u8] = b"Ph=X3^]o2A(,1=@3#a";
const MAX_DECODE_SIZE: usize = 2 * 1024 * 1024 * 1024;
const AES_KEY_EXP_SIZE: usize = 176;
const AES_IV_SIZE: usize = 16;
const AES_ROUND_KEY_SIZE: usize = AES_KEY_EXP_SIZE + AES_IV_SIZE;
const AES_BLOCK_LEN: usize = 16;

#[derive(Clone, Copy, Debug)]
struct DxHead {
    head: u16,
    version: u16,
    head_size: u32,
    data_start: u64,
    name_table_start: u64,
    file_table_start: u64,
    directory_table_start: u64,
    char_code_format: u32,
    flags: u32,
    huffman_encode_kb: u8,
}

#[derive(Clone, Copy, Debug)]
struct FileHead {
    name_addr: u64,
    attrs: u64,
    data_addr: u64,
    data_size: u64,
    press_size: u64,
    huff_size: u64,
}

#[derive(Clone, Copy, Debug)]
struct Directory {
    directory_addr: u64,
    parent_addr: u64,
    file_head_num: u64,
    file_head_addr: u64,
}

#[derive(Debug)]
struct Layout {
    table: Vec<u8>,
    data_start: u64,
    file_table_start: usize,
    directory_table_start: usize,
    huffman_encode_kb: u8,
    flags: u32,
    key_string: Vec<u8>,
    main_key_pos: usize,
    source: String,
    wolf: Option<WolfContext>,
}

#[derive(Clone, Debug)]
struct WolfContext {
    crypt_version: u16,
    other_key: [u8; 768],
    special_key: [u8; 768],
    aes_round_key: [u8; AES_ROUND_KEY_SIZE],
    body_size: usize,
    name_table_start: usize,
}

#[derive(Clone, Copy)]
struct HuffNode {
    weight: u32,
    child: [i32; 2],
    parent: i32,
    index: u8,
    bit_num: u8,
    bit_array: [u8; 32],
}

fn main() -> io::Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: wolf_unpack <Data.wolf> [output_dir] [key_string]");
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

#[derive(Debug)]
struct Entry {
    path: String,
    head: FileHead,
    directory_addr: usize,
}

fn detect_layout(data: &[u8], requested_key_string: &[u8]) -> io::Result<Layout> {
    if data.len() < 8 {
        return Err(invalid("file is too small"));
    }

    let plain = parse_head_prefix(data)?;
    if plain.version != DX_VER_8 || plain.head != DX_HEAD {
        return Err(invalid("not a DX archive v8 header"));
    }

    let mut tried = Vec::new();

    let mut candidates: Vec<(&str, Vec<u8>)> = vec![
        ("requested", requested_key_string.to_vec()),
        ("wolf-pro", DEFAULT_WOLF_PRO_KEY.to_vec()),
        ("wolf-v3.10", DEFAULT_WOLF_V310_KEY.to_vec()),
        ("wolf-v3.173", DEFAULT_WOLF_V3173_KEY.to_vec()),
        ("wolf-v3.31", DEFAULT_WOLF_V331_KEY.to_vec()),
        ("wolf-v3.50", DEFAULT_WOLF_V350_KEY.to_vec()),
        ("wolf-chacha2", DEFAULT_WOLF_CHACHA2_KEY.to_vec()),
        ("one-way", DEFAULT_ONE_WAY_KEY.to_vec()),
        ("one-way-full", DEFAULT_ONE_WAY_FULL_KEY.to_vec()),
        ("dxlib", DEFAULT_DXLIB_KEY.to_vec()),
        ("old-wolf", DEFAULT_OLD_WOLF_KEY.to_vec()),
    ];
    candidates.dedup_by(|a, b| nul_terminated(&a.1) == nul_terminated(&b.1));

    for (label, key_string) in candidates {
        let key = key_create(&key_string);
        if tried.iter().any(|prev| prev == &hex(&key)) {
            continue;
        }
        tried.push(hex(&key));

        if let Some(layout) = try_wolf_newcrypt_layout(data, key, key_string.clone(), plain, label) {
            return Ok(layout);
        }

        if let Some(layout) = try_official_layout(data, key, key_string.clone(), plain, "official-plain-header") {
            return Ok(layout);
        }

        if let Some(layout) = try_encrypted_v8_header_layout(data, key, key_string.clone(), plain, label) {
            return Ok(layout);
        }

        if let Some(layout) = try_front_loaded_layout(data, key, key_string, plain) {
            return Ok(layout);
        }
    }

    Err(invalid(format!(
        "could not decode archive tables; alternate keys tried: {}",
        tried.join(", ")
    )))
}

fn try_official_layout(
    data: &[u8],
    key: [u8; KEY_BYTES],
    key_string: Vec<u8>,
    head: DxHead,
    source: &str,
) -> Option<Layout> {
    if !plausible_head(&head, data.len()) {
        return None;
    }

    let start = head.name_table_start as usize;
    let head_size = head.head_size as usize;
    let no_key = (head.flags & 1) != 0;
    let no_head_press = (head.flags & 2) != 0;

    let table = if no_head_press {
        let mut table = data.get(start..start.checked_add(head_size)?)?.to_vec();
        if !no_key {
            key_conv(&mut table, &key, 0);
        }
        table
    } else {
        let mut huff = data.get(start..)?.to_vec();
        if !no_key {
            key_conv(&mut huff, &key, 0);
        }
        let lz = huffman_decode(&huff).ok()?;
        dxa_decode(&lz).ok()?
    };

    validate_table(&table, head.file_table_start as usize, head.directory_table_start as usize)?;
    Some(Layout {
        table,
        data_start: head.data_start,
        file_table_start: head.file_table_start as usize,
        directory_table_start: head.directory_table_start as usize,
        huffman_encode_kb: head.huffman_encode_kb,
        flags: head.flags,
        key_string,
        main_key_pos: 0,
        source: source.to_string(),
        wolf: None,
    })
}

fn try_encrypted_v8_header_layout(
    data: &[u8],
    key: [u8; KEY_BYTES],
    key_string: Vec<u8>,
    plain: DxHead,
    label: &str,
) -> Option<Layout> {
    if data.len() < 64 {
        return None;
    }

    for pos in 0..KEY_BYTES {
        let mut head_buf = data[..64].to_vec();
        key_conv(&mut head_buf[8..64], &key, pos);
        let head = parse_full_head(&head_buf).ok()?;
        if head.head == plain.head
            && head.version == plain.version
            && head.head_size == plain.head_size
            && plausible_head(&head, data.len())
        {
            let source = format!("encrypted-v8-header-{label}-pos{pos}");
            if let Some(layout) = try_official_layout(data, key, key_string.clone(), head, &source) {
                return Some(layout);
            }
        }
    }

    None
}

fn try_wolf_newcrypt_layout(
    data: &[u8],
    _key: [u8; KEY_BYTES],
    key_string: Vec<u8>,
    plain: DxHead,
    label: &str,
) -> Option<Layout> {
    if data.len() < 64 {
        return None;
    }

    let raw_head = parse_full_head(data).ok()?;
    let crypt_version = (raw_head.flags >> 16) as u16;
    if !is_new_wolf_crypt(crypt_version) || !candidate_matches_wolf_version(label, crypt_version) {
        return None;
    }
    let debug = env::var_os("WOLF_DEBUG").is_some();

    let mut pwd = [0u8; 15];
    pwd.copy_from_slice(data.get(49..64)?);

    let mut head_buf = data[..64].to_vec();
    wolf_crypt_addresses(&mut head_buf, &pwd, crypt_version);
    let head = parse_full_head(&head_buf).ok()?;
    if debug {
        eprintln!(
            "newcrypt {label}: raw_cv=0x{crypt_version:04x} head_size={} data_start={} name_start={} file_start={} dir_start={} flags=0x{:08x} huff_kb={}",
            head.head_size,
            head.data_start,
            head.name_table_start,
            head.file_table_start,
            head.directory_table_start,
            head.flags,
            head.huffman_encode_kb
        );
    }
    if head.head != plain.head
        || head.version != plain.version
        || head.head_size != plain.head_size
        || !plausible_head(&head, data.len())
    {
        return None;
    }

    let ctx = WolfContext {
        crypt_version,
        other_key: wolf_init_key(crypt_version, &pwd, None, true, &key_string),
        special_key: wolf_init_key(crypt_version, &pwd, None, false, &key_string),
        aes_round_key: wolf_aes_init_round_key(&pwd, None, crypt_version),
        body_size: wolf_aes_body_size(data.len(), crypt_version, &pwd, None),
        name_table_start: head.name_table_start as usize,
    };

    let table = read_wolf_table(data, &head, &ctx)?;
    if debug {
        eprintln!(
            "newcrypt {label}: table len={} first={}",
            table.len(),
            hex(&table[..table.len().min(16)])
        );
        if let Some(root) = parse_directory_at(&table, head.directory_table_start as usize) {
            eprintln!(
                "newcrypt {label}: root dir_addr={} parent={:016x} file_num={} file_addr={}",
                root.directory_addr,
                root.parent_addr,
                root.file_head_num,
                root.file_head_addr
            );
        }
        if let Some(first_file) = parse_file_head_at(&table, head.file_table_start as usize) {
            eprintln!(
                "newcrypt {label}: first file name={} attrs={:x} data={} size={} press={} huff={}",
                first_file.name_addr,
                first_file.attrs,
                first_file.data_addr,
                first_file.data_size,
                first_file.press_size,
                first_file.huff_size
            );
        }
    }
    validate_table(&table, head.file_table_start as usize, head.directory_table_start as usize)?;

    Some(Layout {
        table,
        data_start: head.data_start,
        file_table_start: head.file_table_start as usize,
        directory_table_start: head.directory_table_start as usize,
        huffman_encode_kb: head.huffman_encode_kb,
        flags: head.flags,
        key_string,
        main_key_pos: 0,
        source: format!("wolf-newcrypt-v{crypt_version:x}-{label}"),
        wolf: Some(ctx),
    })
}

fn try_front_loaded_layout(data: &[u8], key: [u8; KEY_BYTES], key_string: Vec<u8>, head: DxHead) -> Option<Layout> {
    let block_size = head.head_size as usize;
    let block = data.get(8..8usize.checked_add(block_size)?)?;

    for pos in 0..KEY_BYTES {
        let mut decoded = block.to_vec();
        key_conv(&mut decoded, &key, pos);

        let candidates = front_table_candidates(&decoded);
        for (table, source_suffix) in candidates {
            if let Some(layout) = infer_front_layout(&table, data.len(), block_size, key_string.clone(), pos, &source_suffix) {
                return Some(layout);
            }
        }
    }

    None
}

fn front_table_candidates(decoded: &[u8]) -> Vec<(Vec<u8>, String)> {
    let mut out = Vec::new();

    out.push((decoded.to_vec(), "xor-direct".to_string()));

    if let Ok(lz) = dxa_decode(decoded) {
        out.push((lz, "xor-lz".to_string()));
    }

    if let Ok(huff) = huffman_decode(decoded) {
        out.push((huff.clone(), "xor-huff".to_string()));
        if let Ok(lz) = dxa_decode(&huff) {
            out.push((lz, "xor-huff-lz".to_string()));
        }
    }

    out
}

fn infer_front_layout(
    table: &[u8],
    archive_len: usize,
    block_size: usize,
    key_string: Vec<u8>,
    pos: usize,
    suffix: &str,
) -> Option<Layout> {
    if table.len() < 32 {
        return None;
    }

    let data_start = 8u64 + block_size as u64;

    let mut offset_pairs = Vec::new();

    if table.len() >= 64 {
        let h = parse_full_head(table).ok()?;
        if h.head == DX_HEAD && h.version == DX_VER_8 && plausible_table_offsets(table, h.file_table_start as usize, h.directory_table_start as usize) {
            offset_pairs.push((64, h.file_table_start as usize, h.directory_table_start as usize, h.huffman_encode_kb, h.flags, "embedded-head"));
        }
    }

    for file_start in guess_file_table_starts(table) {
        for dir_start in guess_directory_table_starts(table, file_start) {
            offset_pairs.push((0, file_start, dir_start, 0xff, 0, "guessed"));
        }
    }

    for (base, file_table_start, directory_table_start, huff_kb, flags, kind) in offset_pairs {
        let logical_table = if base == 0 { table.to_vec() } else { table[base..].to_vec() };
        let file_start = file_table_start.checked_sub(base).unwrap_or(file_table_start);
        let dir_start = directory_table_start.checked_sub(base).unwrap_or(directory_table_start);
        if validate_table(&logical_table, file_start, dir_start).is_some() {
            if data_start as usize <= archive_len {
                return Some(Layout {
                    table: logical_table,
                    data_start,
                    file_table_start: file_start,
                    directory_table_start: dir_start,
                    huffman_encode_kb: huff_kb,
                    flags,
                    key_string,
                    main_key_pos: pos,
                    source: format!("front-loaded-{suffix}-{kind}"),
                    wolf: None,
                });
            }
        }
    }

    None
}

fn guess_file_table_starts(table: &[u8]) -> Vec<usize> {
    let mut guesses = Vec::new();
    let max = table.len().saturating_sub(72);
    let mut off = 0usize;
    while off <= max.min(0x20000) {
        if let Some(fh) = parse_file_head_at(table, off) {
            if fh.name_addr < table.len() as u64
                && fh.attrs & !0x37ff == 0
                && fh.data_size < 1u64 << 34
                && (fh.press_size == NONE || fh.press_size <= fh.data_size + (1u64 << 30))
                && (fh.huff_size == NONE || fh.huff_size <= fh.press_size.max(fh.data_size) + (1u64 << 30))
            {
                guesses.push(off);
            }
        }
        off += 8;
    }
    guesses.sort_unstable();
    guesses.dedup();
    guesses
}

fn guess_directory_table_starts(table: &[u8], file_start: usize) -> Vec<usize> {
    let mut guesses = Vec::new();
    let min = file_start.saturating_add(72);
    let max = table.len().saturating_sub(32);
    let mut off = min;
    while off <= max {
        if let Some(dir) = parse_directory_at(table, off) {
            if dir.parent_addr == NONE
                && dir.file_head_num > 0
                && dir.file_head_num < 500_000
                && (file_start as u64 + dir.file_head_addr) as usize + (dir.file_head_num as usize).saturating_mul(72) <= table.len()
            {
                guesses.push(off);
            }
        }
        off += 8;
    }
    guesses.sort_unstable();
    guesses.dedup();
    guesses
}

fn validate_table(table: &[u8], file_table_start: usize, directory_table_start: usize) -> Option<()> {
    if !plausible_table_offsets(table, file_table_start, directory_table_start) {
        return None;
    }
    let root = parse_directory_at(table, directory_table_start)?;
    if root.parent_addr != NONE {
        return None;
    }
    if root.file_head_num == 0 || root.file_head_num > 500_000 {
        return None;
    }
    let first = file_table_start.checked_add(root.file_head_addr as usize)?;
    let bytes = (root.file_head_num as usize).checked_mul(72)?;
    if first.checked_add(bytes)? > table.len() {
        return None;
    }
    Some(())
}

fn plausible_table_offsets(table: &[u8], file_table_start: usize, directory_table_start: usize) -> bool {
    file_table_start < table.len()
        && directory_table_start < table.len()
        && file_table_start % 4 == 0
        && directory_table_start % 4 == 0
        && file_table_start < directory_table_start
}

fn collect_files(layout: &Layout) -> io::Result<Vec<Entry>> {
    let mut out = Vec::new();
    let root = parse_directory_at(&layout.table, layout.directory_table_start)
        .ok_or_else(|| invalid("root directory is outside table"))?;
    collect_dir(layout, root, layout.directory_table_start, String::new(), &mut out)?;
    Ok(out)
}

fn collect_dir(layout: &Layout, dir: Directory, dir_addr: usize, prefix: String, out: &mut Vec<Entry>) -> io::Result<()> {
    let start = layout
        .file_table_start
        .checked_add(dir.file_head_addr as usize)
        .ok_or_else(|| invalid("file table address overflow"))?;
    for i in 0..dir.file_head_num as usize {
        let off = start + i * 72;
        let fh = parse_file_head_at(&layout.table, off)
            .ok_or_else(|| invalid(format!("bad file header at 0x{off:x}")))?;
        let name = name_for(layout, fh.name_addr as usize)?;
        if fh.attrs & FILE_ATTRIBUTE_DIRECTORY != 0 {
            let child_addr = layout
                .directory_table_start
                .checked_add(fh.data_addr as usize)
                .ok_or_else(|| invalid("directory address overflow"))?;
            let child = parse_directory_at(&layout.table, child_addr)
                .ok_or_else(|| invalid(format!("bad directory at 0x{child_addr:x}")))?;
            let child_prefix = if prefix.is_empty() {
                name
            } else {
                format!("{prefix}\\{name}")
            };
            collect_dir(layout, child, child_addr, child_prefix, out)?;
        } else {
            let path = if prefix.is_empty() {
                name
            } else {
                format!("{prefix}\\{name}")
            };
            out.push(Entry {
                path,
                head: fh,
                directory_addr: dir_addr,
            });
        }
    }
    Ok(())
}

fn name_for(layout: &Layout, name_addr: usize) -> io::Result<String> {
    if name_addr + 4 > layout.table.len() {
        return Err(invalid("name address outside table"));
    }
    let packs = read_u16(&layout.table[name_addr..]) as usize;
    let original_start = name_addr + 4 + packs * 4;
    if original_start >= layout.table.len() {
        return Err(invalid("name original string outside table"));
    }
    let end = layout.table[original_start..]
        .iter()
        .position(|&b| b == 0)
        .map(|p| original_start + p)
        .unwrap_or(layout.table.len());
    let raw = &layout.table[original_start..end];
    Ok(decode_filename(raw))
}

fn extract_all(data: &[u8], layout: &Layout, files: &[Entry], out_dir: &Path) -> io::Result<()> {
    fs::create_dir_all(out_dir)?;
    for (idx, entry) in files.iter().enumerate() {
        let bytes = extract_file(data, layout, entry)?;
        let safe_path = safe_relative_path(&entry.path);
        let target = out_dir.join(safe_path);
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(&target, bytes)?;
        if idx % 100 == 0 {
            println!("extracted {:5}/{} {}", idx + 1, files.len(), entry.path);
        }
    }
    Ok(())
}

fn extract_file(data: &[u8], layout: &Layout, entry: &Entry) -> io::Result<Vec<u8>> {
    let fh = entry.head;
    let key = if layout.wolf.is_none() {
        Some(file_key(layout, entry)?)
    } else {
        None
    };
    let start = layout
        .data_start
        .checked_add(fh.data_addr)
        .ok_or_else(|| invalid("data address overflow"))? as usize;

    if fh.press_size != NONE {
        let press = if fh.huff_size != NONE {
            let huff = read_layout_slice(data, layout, start, fh.huff_size as usize, key.as_ref(), fh.data_size)?;
            let mut lz = huffman_decode(&huff).map_err(invalid)?;
            if layout.huffman_encode_kb != 0xff && fh.press_size > (layout.huffman_encode_kb as u64) * 1024 * 2 {
                let kb = layout.huffman_encode_kb as usize * 1024;
                let middle_len = fh.press_size as usize - kb * 2;
                let middle_start = start + fh.huff_size as usize;
                let mut middle = read_layout_slice(
                    data,
                    layout,
                    middle_start,
                    middle_len,
                    key.as_ref(),
                    fh.data_size + fh.huff_size,
                )?;
                let tail = lz[kb..kb * 2].to_vec();
                lz.truncate(kb);
                lz.append(&mut middle);
                lz.extend_from_slice(&tail);
            }
            lz
        } else {
            read_layout_slice(data, layout, start, fh.press_size as usize, key.as_ref(), fh.data_size)?
        };
        return dxa_decode(&press).map_err(invalid);
    }

    if fh.huff_size != NONE {
        let mut output = if layout.huffman_encode_kb != 0xff && fh.data_size > (layout.huffman_encode_kb as u64) * 1024 * 2 {
            let kb = layout.huffman_encode_kb as usize * 1024;
            let huff = read_layout_slice(data, layout, start, fh.huff_size as usize, key.as_ref(), fh.data_size)?;
            let mut decoded = huffman_decode(&huff).map_err(invalid)?;
            let middle_len = fh.data_size as usize - kb * 2;
            let middle_start = start + fh.huff_size as usize;
            let mut middle = read_layout_slice(
                data,
                layout,
                middle_start,
                middle_len,
                key.as_ref(),
                fh.data_size + fh.huff_size,
            )?;
            let tail = decoded[kb..kb * 2].to_vec();
            decoded.truncate(kb);
            decoded.append(&mut middle);
            decoded.extend_from_slice(&tail);
            decoded
        } else {
            let huff = read_layout_slice(data, layout, start, fh.huff_size as usize, key.as_ref(), fh.data_size)?;
            huffman_decode(&huff).map_err(invalid)?
        };
        output.truncate(fh.data_size as usize);
        return Ok(output);
    }

    read_layout_slice(data, layout, start, fh.data_size as usize, key.as_ref(), fh.data_size)
}

fn read_layout_slice(
    data: &[u8],
    layout: &Layout,
    start: usize,
    len: usize,
    key: Option<&[u8; KEY_BYTES]>,
    pos: u64,
) -> io::Result<Vec<u8>> {
    let end = start
        .checked_add(len)
        .ok_or_else(|| invalid("slice address overflow"))?;
    if end > data.len() {
        return Err(invalid("file data outside archive"));
    }

    let mut out = if let Some(wolf) = &layout.wolf {
        read_wolf_archive_slice(data, start, len, wolf).ok_or_else(|| invalid("file data outside archive"))?
    } else {
        data[start..end].to_vec()
    };

    if let Some(wolf) = &layout.wolf {
        if (layout.flags & 1) == 0 {
            wolf_crypt(&wolf.special_key, &mut out, pos as usize, wolf.crypt_version);
        }
    } else if let Some(key) = key {
        key_conv(&mut out, key, (pos as usize) % KEY_BYTES);
    }
    Ok(out)
}

fn file_key(layout: &Layout, entry: &Entry) -> io::Result<[u8; KEY_BYTES]> {
    let mut key_string = Vec::new();
    key_string.extend_from_slice(nul_terminated(&layout.key_string));

    let file_name = raw_original_name(layout, entry.head.name_addr as usize)?;
    key_string.extend_from_slice(file_name);

    let mut dir = parse_directory_at(&layout.table, entry.directory_addr)
        .ok_or_else(|| invalid("entry directory is outside table"))?;
    while dir.parent_addr != NONE {
        let dir_fh_addr = layout
            .file_table_start
            .checked_add(dir.directory_addr as usize)
            .ok_or_else(|| invalid("directory file header overflow"))?;
        let dir_fh = parse_file_head_at(&layout.table, dir_fh_addr)
            .ok_or_else(|| invalid("directory file header outside table"))?;
        key_string.extend_from_slice(raw_original_name(layout, dir_fh.name_addr as usize)?);
        let parent_addr = layout
            .directory_table_start
            .checked_add(dir.parent_addr as usize)
            .ok_or_else(|| invalid("parent directory overflow"))?;
        dir = parse_directory_at(&layout.table, parent_addr)
            .ok_or_else(|| invalid("parent directory outside table"))?;
    }

    Ok(key_create(&key_string))
}

fn raw_original_name(layout: &Layout, name_addr: usize) -> io::Result<&[u8]> {
    if name_addr + 4 > layout.table.len() {
        return Err(invalid("name address outside table"));
    }
    let packs = read_u16(&layout.table[name_addr..]) as usize;
    let original_start = name_addr + 4 + packs * 4;
    if original_start >= layout.table.len() {
        return Err(invalid("name original string outside table"));
    }
    let end = layout.table[original_start..]
        .iter()
        .position(|&b| b == 0)
        .map(|p| original_start + p)
        .unwrap_or(layout.table.len());
    Ok(&layout.table[original_start..end])
}

fn parse_head_prefix(data: &[u8]) -> io::Result<DxHead> {
    if data.len() < 8 {
        return Err(invalid("missing header"));
    }
    Ok(DxHead {
        head: read_u16(data),
        version: read_u16(&data[2..]),
        head_size: read_u32(&data[4..]),
        data_start: 0,
        name_table_start: 0,
        file_table_start: 0,
        directory_table_start: 0,
        char_code_format: 0,
        flags: 0,
        huffman_encode_kb: 0xff,
    })
}

fn parse_full_head(data: &[u8]) -> io::Result<DxHead> {
    if data.len() < 64 {
        return Err(invalid("missing full header"));
    }
    Ok(DxHead {
        head: read_u16(data),
        version: read_u16(&data[2..]),
        head_size: read_u32(&data[4..]),
        data_start: read_u64(&data[8..]),
        name_table_start: read_u64(&data[16..]),
        file_table_start: read_u64(&data[24..]),
        directory_table_start: read_u64(&data[32..]),
        char_code_format: read_u32(&data[40..]),
        flags: read_u32(&data[44..]),
        huffman_encode_kb: data[48],
    })
}

fn parse_file_head_at(table: &[u8], off: usize) -> Option<FileHead> {
    let b = table.get(off..off.checked_add(72)?)?;
    Some(FileHead {
        name_addr: read_u64(b),
        attrs: read_u64(&b[8..]),
        data_addr: read_u64(&b[40..]),
        data_size: read_u64(&b[48..]),
        press_size: read_u64(&b[56..]),
        huff_size: read_u64(&b[64..]),
    })
}

fn parse_directory_at(table: &[u8], off: usize) -> Option<Directory> {
    let b = table.get(off..off.checked_add(32)?)?;
    Some(Directory {
        directory_addr: read_u64(b),
        parent_addr: read_u64(&b[8..]),
        file_head_num: read_u64(&b[16..]),
        file_head_addr: read_u64(&b[24..]),
    })
}

fn plausible_head(head: &DxHead, file_len: usize) -> bool {
    head.head == DX_HEAD
        && head.version == DX_VER_8
        && head.head_size > 0
        && head.head_size as usize <= file_len
        && head.data_start < file_len as u64
        && head.name_table_start < file_len as u64
        && head.file_table_start < head.head_size as u64
        && head.directory_table_start < head.head_size as u64
        && head.file_table_start < head.directory_table_start
        && head.char_code_format < 100_000
}

fn key_create(source: &[u8]) -> [u8; KEY_BYTES] {
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

fn nul_terminated(source: &[u8]) -> &[u8] {
    source
        .iter()
        .position(|&b| b == 0)
        .map(|end| &source[..end])
        .unwrap_or(source)
}

fn crc32(data: &[u8]) -> u32 {
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

fn key_conv(data: &mut [u8], key: &[u8; KEY_BYTES], pos: usize) {
    for (i, byte) in data.iter_mut().enumerate() {
        *byte ^= key[(pos + i) % KEY_BYTES];
    }
}

fn is_new_wolf_crypt(crypt_version: u16) -> bool {
    (crypt_version >= 331 && crypt_version < 1000) || crypt_version >= 1010
}

fn is_wolf_v35(crypt_version: u16) -> bool {
    (crypt_version >= 0x15e && crypt_version < 0x3e8) || crypt_version >= 0x3fc
}

fn candidate_matches_wolf_version(label: &str, crypt_version: u16) -> bool {
    label == "requested"
        || matches!(
            (crypt_version, label),
            (0x14b, "wolf-v3.31") | (0x15e, "wolf-v3.50") | (0x64, "wolf-chacha2") | (0xc8, "wolf-chacha2")
        )
}

#[derive(Clone, Copy)]
struct MsvcRand {
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

fn wolf_init_key(
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

fn calc_wolf_salt(source: &[u8], salt: &mut [u8; 128]) {
    let source = if source.is_empty() { DEFAULT_DXLIB_KEY } else { source };
    for i in 0..128 {
        salt[i] = (i / source.len()) as u8 + source[i % source.len()];
    }
}

fn wolf_crypt(key: &[u8; 768], data: &mut [u8], start: usize, crypt_version: u16) {
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

fn wolf_crypt_addresses(data: &mut [u8], pwd: &[u8; 15], crypt_version: u16) {
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

fn xor_u16_at(data: &mut [u8], off: usize, value: u16) {
    if off + 2 <= data.len() {
        let v = read_u16(&data[off..]) ^ value;
        data[off..off + 2].copy_from_slice(&v.to_le_bytes());
    }
}

fn xor_u32_at(data: &mut [u8], off: usize, value: u32) {
    if off + 4 <= data.len() {
        let v = read_u32(&data[off..]) ^ value;
        data[off..off + 4].copy_from_slice(&v.to_le_bytes());
    }
}

fn wolf_aes_body_size(file_size: usize, crypt_version: u16, pwd: &[u8; 15], key2: Option<&[u8]>) -> usize {
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

struct XorShift32 {
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

fn read_wolf_table(data: &[u8], head: &DxHead, wolf: &WolfContext) -> Option<Vec<u8>> {
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

fn read_wolf_archive_slice(data: &[u8], start: usize, len: usize, wolf: &WolfContext) -> Option<Vec<u8>> {
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

fn apply_wolf_stream_overlap(
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
    wolf_crypt(key, &mut out[local..local + (end - begin)], begin, crypt_version);
}

fn apply_aes_overlap(
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

const AES_SBOX: [u8; 256] = [
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab,
    0x76, 0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4,
    0x72, 0xc0, 0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71,
    0xd8, 0x31, 0x15, 0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2,
    0xeb, 0x27, 0xb2, 0x75, 0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6,
    0xb3, 0x29, 0xe3, 0x2f, 0x84, 0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb,
    0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf, 0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45,
    0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8, 0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5,
    0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2, 0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44,
    0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73, 0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a,
    0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb, 0xe0, 0x32, 0x3a, 0x0a, 0x49,
    0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79, 0xe7, 0xc8, 0x37, 0x6d,
    0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08, 0xba, 0x78, 0x25,
    0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a, 0x70, 0x3e,
    0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e, 0xe1,
    0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb,
    0x16,
];
const AES_RCON: [u8; 11] = [0x8d, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36];

fn wolf_aes_init_round_key(pwd: &[u8; 15], pro_key: Option<&[u8]>, crypt_version: u16) -> [u8; AES_ROUND_KEY_SIZE] {
    let zero = [0u8; 4];
    let pro = pro_key.unwrap_or(&zero);
    let mut key = [0u8; AES_BLOCK_LEN];
    let mut iv = [0u8; AES_BLOCK_LEN];

    if is_wolf_v35(crypt_version) {
        for i in 0..15usize {
            let pro_elem = pro[i % 4];
            let key_idx = ((i * (pro_elem as usize % 5 + 7)) ^ (3 * pwd[i] as usize)) % 15;
            let iv_idx = (i * (pro[(i + 1) % 4] as usize % 7 + 0x0b) ^ (5 * pwd[(i + 3) % 15] as usize)) % 15;

            key[i] ^= ((i as u8 ^ pro_elem).wrapping_add(pwd[key_idx].wrapping_shl((i % 3) as u32))) % 0xfb;
            iv[i] ^= (pwd[iv_idx].wrapping_shr((i % 2) as u32).wrapping_add((i * i) as u8 ^ pro[(i + 2) % 4])) % 0xf6;
            key[15] ^= (7u16 * (pwd[i].wrapping_add((i as u8 + 1) ^ pro_elem)) as u16 % 0xfd) as u8;
            iv[15] ^= (11u16 * (pwd[i].wrapping_sub((i as u8 * 2) ^ pro[(i + 2) % 4])) as u16 % 0x100) as u8;
        }
    } else if crypt_version == 0x3f2 {
        for i in 0..15usize {
            key[i] ^= pwd[(i * 7) % 15].wrapping_add(pro[i & 3]).wrapping_mul((i * i) as u8);
            iv[i] ^= pwd[(i * 11) % 15].wrapping_add(pro[(i + 2) % 4]).wrapping_sub((i * i) as u8);
            key[15] ^= (i as u8).wrapping_mul(3).wrapping_add(pwd[i]).wrapping_add(pro[i & 3]);
            iv[15] ^= (i as u8).wrapping_mul(5).wrapping_add(pwd[i]).wrapping_add(pro[(i + 2) % 4]);
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

fn aes_key_expansion(round_key: &mut [u8], key: &[u8; AES_BLOCK_LEN]) {
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

fn aes_ctr_xcrypt_at(
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

fn aes_next_ctr_block(round_key: &mut [u8; AES_ROUND_KEY_SIZE], state: &mut [u8; AES_BLOCK_LEN]) {
    state.copy_from_slice(&round_key[AES_KEY_EXP_SIZE..]);
    aes_cipher(state, &round_key[..AES_KEY_EXP_SIZE]);
    aes_increment_iv(&mut round_key[AES_KEY_EXP_SIZE..]);
}

fn aes_advance_iv(iv: &mut [u8], blocks: usize) {
    for _ in 0..blocks {
        aes_increment_iv(iv);
    }
}

fn aes_increment_iv(iv: &mut [u8]) {
    for byte in iv.iter_mut().rev() {
        if *byte == 0xff {
            *byte = 0;
        } else {
            *byte = byte.wrapping_add(1);
            break;
        }
    }
}

fn aes_cipher(state: &mut [u8; AES_BLOCK_LEN], round_key: &[u8]) {
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

fn aes_add_round_key(state: &mut [u8; AES_BLOCK_LEN], round: u8, round_key: &[u8]) {
    let start = round as usize * AES_BLOCK_LEN;
    for i in 0..AES_BLOCK_LEN {
        state[i] ^= round_key[start + i];
    }
}

fn aes_sub_bytes(state: &mut [u8; AES_BLOCK_LEN]) {
    for byte in state {
        *byte = AES_SBOX[*byte as usize];
    }
}

fn aes_shift_rows(state: &mut [u8; AES_BLOCK_LEN]) {
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

fn aes_xtime(x: u8) -> u8 {
    (x << 1) ^ (((x >> 7) & 1) * 0x1b)
}

fn aes_mix_columns(state: &mut [u8; AES_BLOCK_LEN]) {
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

struct BitReader<'a> {
    data: &'a [u8],
    byte: usize,
    bit: u8,
}

impl<'a> BitReader<'a> {
    fn new(data: &'a [u8]) -> Self {
        Self { data, byte: 0, bit: 0 }
    }

    fn read(&mut self, bits: u8) -> io::Result<u64> {
        let mut out = 0u64;
        for i in 0..bits {
            let b = *self
                .data
                .get(self.byte)
                .ok_or_else(|| invalid("huffman bitstream ended early"))?;
            out |= (((b >> (7 - self.bit)) & 1) as u64) << (bits - 1 - i);
            self.bit += 1;
            if self.bit == 8 {
                self.byte += 1;
                self.bit = 0;
            }
        }
        Ok(out)
    }

    fn bytes(&self) -> usize {
        self.byte + usize::from(self.bit != 0)
    }
}

fn huffman_decode(src: &[u8]) -> io::Result<Vec<u8>> {
    let mut br = BitReader::new(src);
    let original_bits = br.read(6)? as u8 + 1;
    let original_size = br.read(original_bits)? as usize;
    if original_size > MAX_DECODE_SIZE {
        return Err(invalid(format!("huffman output is implausibly large: {original_size}")));
    }
    let press_bits = br.read(6)? as u8 + 1;
    let _press_size = br.read(press_bits)?;

    let mut weight = [0u16; 256];
    let mut bit_num = (br.read(3)? as u8 + 1) * 2;
    let _ = br.read(1)?;
    let mut save = br.read(bit_num)? as u16;
    weight[0] = save;
    for i in 1..256 {
        bit_num = (br.read(3)? as u8 + 1) * 2;
        let minus = br.read(1)?;
        save = br.read(bit_num)? as u16;
        weight[i] = if minus == 1 {
            weight[i - 1].wrapping_sub(save)
        } else {
            weight[i - 1].wrapping_add(save)
        };
    }

    let head_size = br.bytes();
    if head_size >= src.len() {
        return Err(invalid("huffman body missing"));
    }

    let mut nodes = vec![
        HuffNode {
            weight: 0,
            child: [-1, -1],
            parent: -1,
            index: 0,
            bit_num: 0,
            bit_array: [0; 32],
        };
        511
    ];
    for i in 0..511 {
        nodes[i].weight = if i < 256 { weight[i] as u32 } else { 0 };
    }

    let mut data_num = 256usize;
    let mut node_num = 256usize;
    while data_num > 1 {
        let mut min1: i32 = -1;
        let mut min2: i32 = -1;
        let mut valid = 0usize;
        let mut node_index = 0usize;
        while valid < data_num {
            if nodes[node_index].parent != -1 {
                node_index += 1;
                continue;
            }
            valid += 1;
            if min1 == -1 || nodes[min1 as usize].weight > nodes[node_index].weight {
                min2 = min1;
                min1 = node_index as i32;
            } else if min2 == -1 || nodes[min2 as usize].weight > nodes[node_index].weight {
                min2 = node_index as i32;
            }
            node_index += 1;
        }

        let a = min1 as usize;
        let b = min2 as usize;
        nodes[node_num].weight = nodes[a].weight + nodes[b].weight;
        nodes[node_num].child = [min1, min2];
        nodes[a].index = 0;
        nodes[b].index = 1;
        nodes[a].parent = node_num as i32;
        nodes[b].parent = node_num as i32;
        node_num += 1;
        data_num -= 1;
    }

    for i in 0..510 {
        let mut temp = [0u8; 32];
        let mut temp_index = 0usize;
        let mut temp_count = 0u8;
        let mut n = i;
        while nodes[n].parent != -1 {
            if temp_count == 8 {
                temp_count = 0;
                temp_index += 1;
            }
            temp[temp_index] <<= 1;
            temp[temp_index] |= nodes[n].index;
            temp_count += 1;
            nodes[i].bit_num += 1;
            n = nodes[n].parent as usize;
        }

        let mut bit_count = 0u8;
        let mut bit_index = 0usize;
        while temp_index < temp.len() {
            if bit_count == 8 {
                bit_count = 0;
                bit_index += 1;
            }
            nodes[i].bit_array[bit_index] |= (temp[temp_index] & 1) << bit_count;
            temp[temp_index] >>= 1;
            temp_count = temp_count.wrapping_sub(1);
            if temp_count == 0 {
                if temp_index == 0 {
                    break;
                }
                temp_index -= 1;
                temp_count = 8;
            }
            bit_count += 1;
        }
    }

    let mut bitmask = [0u16; 9];
    for i in 0..9 {
        bitmask[i] = (1u16 << (i + 1)) - 1;
    }
    let mut node_index_table = [-1i32; 512];
    for i in 0..512usize {
        for j in 0..510usize {
            let bn = nodes[j].bit_num;
            if bn == 0 || bn > 9 {
                continue;
            }
            let bit_array_01 = nodes[j].bit_array[0] as u16 | ((nodes[j].bit_array[1] as u16) << 8);
            if (i as u16 & bitmask[bn as usize - 1]) == (bit_array_01 & bitmask[bn as usize - 1]) {
                node_index_table[i] = j as i32;
                break;
            }
        }
    }

    let press = &src[head_size..];
    let mut out = vec![0u8; original_size];
    let mut press_counter = 0usize;
    let mut press_bit_counter = 0u8;
    let mut press_bit_data = *press.first().ok_or_else(|| invalid("empty huffman body"))? as u16;

    for dest_counter in 0..original_size {
        let mut node_index: i32;
        if dest_counter >= original_size.saturating_sub(17) {
            node_index = 510;
        } else {
            if press_bit_counter == 8 {
                press_counter += 1;
                press_bit_data = *press
                    .get(press_counter)
                    .ok_or_else(|| invalid("huffman body ended early"))? as u16;
                press_bit_counter = 0;
            }
            let next = *press.get(press_counter + 1).unwrap_or(&0) as u16;
            press_bit_data = (press_bit_data | (next << (8 - press_bit_counter))) & 0x1ff;
            node_index = node_index_table[press_bit_data as usize];
            if node_index < 0 {
                return Err(invalid("bad huffman lookup"));
            }
            press_bit_counter += nodes[node_index as usize].bit_num;
            if press_bit_counter >= 16 {
                press_counter += 2;
                press_bit_counter -= 16;
                press_bit_data = (*press.get(press_counter).unwrap_or(&0) as u16) >> press_bit_counter;
            } else if press_bit_counter >= 8 {
                press_counter += 1;
                press_bit_counter -= 8;
                press_bit_data = (*press.get(press_counter).unwrap_or(&0) as u16) >> press_bit_counter;
            } else {
                press_bit_data >>= nodes[node_index as usize].bit_num;
            }
        }

        while node_index > 255 {
            if press_bit_counter == 8 {
                press_counter += 1;
                press_bit_data = *press
                    .get(press_counter)
                    .ok_or_else(|| invalid("huffman body ended early"))? as u16;
                press_bit_counter = 0;
            }
            let index = (press_bit_data & 1) as usize;
            press_bit_data >>= 1;
            press_bit_counter += 1;
            node_index = nodes[node_index as usize].child[index];
        }
        out[dest_counter] = node_index as u8;
    }

    Ok(out)
}

fn dxa_decode(src: &[u8]) -> io::Result<Vec<u8>> {
    if src.len() < 9 {
        return Err(invalid("lz source too small"));
    }
    let dest_size = read_u32(src) as usize;
    if dest_size > MAX_DECODE_SIZE {
        return Err(invalid(format!("lz output is implausibly large: {dest_size}")));
    }
    let packed_total = read_u32(&src[4..]) as usize;
    if packed_total < 9 || packed_total > src.len() {
        return Err(invalid("lz packed size is invalid"));
    }
    let mut src_left = packed_total - 9;
    let key_code = src[8];
    let mut sp = 9usize;
    let mut out = Vec::with_capacity(dest_size);

    while src_left > 0 {
        let b = *src.get(sp).ok_or_else(|| invalid("lz source ended early"))?;
        if b != key_code {
            out.push(b);
            sp += 1;
            src_left -= 1;
            continue;
        }

        let b1 = *src.get(sp + 1).ok_or_else(|| invalid("lz source ended early"))?;
        if b1 == key_code {
            out.push(key_code);
            sp += 2;
            src_left = src_left.saturating_sub(2);
            continue;
        }

        let mut code = b1;
        if code > key_code {
            code -= 1;
        }
        sp += 2;
        src_left = src_left.saturating_sub(2);

        let mut conbo = (code >> 3) as usize;
        if (code & 4) != 0 {
            conbo |= (*src.get(sp).ok_or_else(|| invalid("lz source ended early"))? as usize) << 5;
            sp += 1;
            src_left = src_left.saturating_sub(1);
        }
        conbo += 4;

        let index_size = code & 3;
        let mut index = match index_size {
            0 => {
                let v = *src.get(sp).ok_or_else(|| invalid("lz source ended early"))? as usize;
                sp += 1;
                src_left = src_left.saturating_sub(1);
                v
            }
            1 => {
                if sp + 2 > src.len() {
                    return Err(invalid("lz source ended early"));
                }
                let v = read_u16(&src[sp..]) as usize;
                sp += 2;
                src_left = src_left.saturating_sub(2);
                v
            }
            2 => {
                if sp + 3 > src.len() {
                    return Err(invalid("lz source ended early"));
                }
                let v = read_u16(&src[sp..]) as usize | ((src[sp + 2] as usize) << 16);
                sp += 3;
                src_left = src_left.saturating_sub(3);
                v
            }
            _ => return Err(invalid("unsupported lz index size")),
        };
        index += 1;
        if index > out.len() {
            return Err(invalid("lz back-reference before output start"));
        }
        for _ in 0..conbo {
            let v = out[out.len() - index];
            out.push(v);
        }
    }

    if out.len() != dest_size {
        return Err(invalid(format!("lz decoded {} bytes, expected {}", out.len(), dest_size)));
    }
    Ok(out)
}

fn read_u16(b: &[u8]) -> u16 {
    u16::from_le_bytes([b[0], b[1]])
}

fn read_u32(b: &[u8]) -> u32 {
    u32::from_le_bytes([b[0], b[1], b[2], b[3]])
}

fn read_u64(b: &[u8]) -> u64 {
    u64::from_le_bytes([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]])
}

fn decode_filename(raw: &[u8]) -> String {
    String::from_utf8_lossy(raw).replace('/', "\\")
}

fn safe_relative_path(path: &str) -> PathBuf {
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

fn display_opt_size(v: u64) -> String {
    if v == NONE {
        "-".to_string()
    } else {
        v.to_string()
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02X}")).collect::<Vec<_>>().join("")
}

fn invalid<E: std::fmt::Display>(msg: E) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, msg.to_string())
}
