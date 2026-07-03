//! DXArchive v8 (`Data.wolf`) container: header parsing, the key / crypt-version dispatch
//! and detection strategies, the directory walk, and per-file extraction.

use crate::chacha20;
use crate::codec::{dxa_decode, huffman_decode};
use crate::crypto::*;
use crate::*;
use std::fs;
use std::io;
use std::path::Path;

#[derive(Debug)]
pub(crate) struct Entry {
    pub(crate) path: String,
    pub(crate) head: FileHead,
    pub(crate) directory_addr: usize,
}

/// Map a DXArchive-Wolf cryptVersion (`Flags>>16`) to its table key. Returns `Some` only
/// for the plaintext-header, single-key "keyed decode" versions. New wolf-crypt (encrypted
/// header), ChaCha20, and the ambiguous version-0 string-keyed games are handled by the
/// strategy fallbacks.
pub(crate) fn table_key_for_version(crypt_version: u16) -> Option<Vec<u8>> {
    let key: &[u8] = match crypt_version {
        0x12C => DEFAULT_WOLF_V310_KEY,  // Wolf v3.00
        0x13A => DEFAULT_WOLF_V3173_KEY, // Wolf v3.14
        _ => return None,
    };
    Some(key.to_vec())
}

/// Build a layout for a "ChaCha2" (cryptVersion 0x64) archive: the header is plaintext, the
/// table and file data are ChaCha20-keyed with the fixed chacha2 key/nonce. This mirrors the
/// old-crypt path with ChaCha20 substituted for `key_conv`. Not yet verified against a real
/// ChaCha2 archive.
pub(crate) fn try_chacha_layout(data: &[u8], head: DxHead) -> Option<Layout> {
    let ck: [u8; 32] = DEFAULT_WOLF_CHACHA2_KEY[0..32].try_into().ok()?;
    let cn: [u8; 12] = DEFAULT_WOLF_CHACHA2_KEY[32..44].try_into().ok()?;
    let start = head.name_table_start as usize;
    let no_head_press = (head.flags & 2) != 0;
    let table = if no_head_press {
        let mut t = data
            .get(start..start.checked_add(head.head_size as usize)?)?
            .to_vec();
        chacha20::crypt(&mut t, &ck, &cn, 0);
        t
    } else {
        let mut huff = data.get(start..)?.to_vec();
        chacha20::crypt(&mut huff, &ck, &cn, 0);
        let lz = huffman_decode(&huff).ok()?;
        dxa_decode(&lz).ok()?
    };
    validate_table(
        &table,
        head.file_table_start as usize,
        head.directory_table_start as usize,
    )?;
    Some(Layout {
        table,
        data_start: head.data_start,
        file_table_start: head.file_table_start as usize,
        directory_table_start: head.directory_table_start as usize,
        huffman_encode_kb: head.huffman_encode_kb,
        flags: head.flags,
        key_string: DEFAULT_WOLF_CHACHA2_KEY.to_vec(),
        main_key_pos: 0,
        source: "deterministic chacha2 cv=0x64".to_string(),
        wolf: None,
        chacha: Some((ck, cn)),
    })
}

pub(crate) fn detect_layout(data: &[u8], requested_key_string: &[u8]) -> io::Result<Layout> {
    if data.len() < 8 {
        return Err(invalid("file is too small"));
    }

    // Use the full header (real table offsets and Flags). For an encrypted header the offsets
    // are garbage, but then `try_official_layout`/`plausible_head` reject it and we fall
    // through to the wolf-crypt strategies, so this is safe for all archives.
    let plain = parse_full_head(data).or_else(|_| parse_head_prefix(data))?;
    if plain.version != DX_VER_8 || plain.head != DX_HEAD {
        return Err(invalid("not a DX archive v8 header"));
    }

    // Deterministic dispatch: a plaintext header carries Flags, and cryptVersion = Flags>>16
    // selects the exact table key. No key guessing needed.
    if plausible_head(&plain, data.len()) {
        let crypt_version = (plain.flags >> 16) as u16;
        if let Some(key_string) = table_key_for_version(crypt_version) {
            let key = key_create(&key_string);
            if let Some(mut layout) =
                try_official_layout(data, key, key_string, plain, "deterministic")
            {
                layout.source = format!("deterministic cryptVersion={crypt_version:#x}");
                return Ok(layout);
            }
        }
        // cv 0x64: "ChaCha2" archive. Plaintext header, table and files ChaCha20-keyed.
        if crypt_version == 0x64 {
            if let Some(layout) = try_chacha_layout(data, plain) {
                return Ok(layout);
            }
        }
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

        if let Some(layout) = try_wolf_newcrypt_layout(data, key, key_string.clone(), plain, label)
        {
            return Ok(layout);
        }

        if let Some(layout) = try_official_layout(
            data,
            key,
            key_string.clone(),
            plain,
            "official-plain-header",
        ) {
            return Ok(layout);
        }

        if let Some(layout) =
            try_encrypted_v8_header_layout(data, key, key_string.clone(), plain, label)
        {
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

pub(crate) fn try_official_layout(
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

    validate_table(
        &table,
        head.file_table_start as usize,
        head.directory_table_start as usize,
    )?;
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
        chacha: None,
    })
}

pub(crate) fn try_encrypted_v8_header_layout(
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
            if let Some(layout) = try_official_layout(data, key, key_string.clone(), head, &source)
            {
                return Some(layout);
            }
        }
    }

    None
}

pub(crate) fn try_wolf_newcrypt_layout(
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
    let debug = std::env::var_os("WOLF_DEBUG").is_some();

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
                root.directory_addr, root.parent_addr, root.file_head_num, root.file_head_addr
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
    validate_table(
        &table,
        head.file_table_start as usize,
        head.directory_table_start as usize,
    )?;

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
        chacha: None,
    })
}

pub(crate) fn try_front_loaded_layout(
    data: &[u8],
    key: [u8; KEY_BYTES],
    key_string: Vec<u8>,
    head: DxHead,
) -> Option<Layout> {
    let block_size = head.head_size as usize;
    let block = data.get(8..8usize.checked_add(block_size)?)?;

    for pos in 0..KEY_BYTES {
        let mut decoded = block.to_vec();
        key_conv(&mut decoded, &key, pos);

        let candidates = front_table_candidates(&decoded);
        for (table, source_suffix) in candidates {
            if let Some(layout) = infer_front_layout(
                &table,
                data.len(),
                block_size,
                key_string.clone(),
                pos,
                &source_suffix,
            ) {
                return Some(layout);
            }
        }
    }

    None
}

pub(crate) fn front_table_candidates(decoded: &[u8]) -> Vec<(Vec<u8>, String)> {
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

pub(crate) fn infer_front_layout(
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
        if h.head == DX_HEAD
            && h.version == DX_VER_8
            && plausible_table_offsets(
                table,
                h.file_table_start as usize,
                h.directory_table_start as usize,
            )
        {
            offset_pairs.push((
                64,
                h.file_table_start as usize,
                h.directory_table_start as usize,
                h.huffman_encode_kb,
                h.flags,
                "embedded-head",
            ));
        }
    }

    for file_start in guess_file_table_starts(table) {
        for dir_start in guess_directory_table_starts(table, file_start) {
            offset_pairs.push((0, file_start, dir_start, 0xff, 0, "guessed"));
        }
    }

    for (base, file_table_start, directory_table_start, huff_kb, flags, kind) in offset_pairs {
        let logical_table = if base == 0 {
            table.to_vec()
        } else {
            table[base..].to_vec()
        };
        let file_start = file_table_start
            .checked_sub(base)
            .unwrap_or(file_table_start);
        let dir_start = directory_table_start
            .checked_sub(base)
            .unwrap_or(directory_table_start);
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
                    chacha: None,
                });
            }
        }
    }

    None
}

pub(crate) fn guess_file_table_starts(table: &[u8]) -> Vec<usize> {
    let mut guesses = Vec::new();
    let max = table.len().saturating_sub(72);
    let mut off = 0usize;
    while off <= max.min(0x20000) {
        if let Some(fh) = parse_file_head_at(table, off) {
            if fh.name_addr < table.len() as u64
                && fh.attrs & !0x37ff == 0
                && fh.data_size < 1u64 << 34
                && (fh.press_size == NONE || fh.press_size <= fh.data_size + (1u64 << 30))
                && (fh.huff_size == NONE
                    || fh.huff_size <= fh.press_size.max(fh.data_size) + (1u64 << 30))
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

pub(crate) fn guess_directory_table_starts(table: &[u8], file_start: usize) -> Vec<usize> {
    let mut guesses = Vec::new();
    let min = file_start.saturating_add(72);
    let max = table.len().saturating_sub(32);
    let mut off = min;
    while off <= max {
        if let Some(dir) = parse_directory_at(table, off) {
            if dir.parent_addr == NONE
                && dir.file_head_num > 0
                && dir.file_head_num < 500_000
                && (file_start as u64 + dir.file_head_addr) as usize
                    + (dir.file_head_num as usize).saturating_mul(72)
                    <= table.len()
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

pub(crate) fn validate_table(
    table: &[u8],
    file_table_start: usize,
    directory_table_start: usize,
) -> Option<()> {
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
    // Sanity-check the root's file headers. The root directory lives in the table's tail,
    // which (for an uncompressed/NO_HEAD_PRESS header) decodes plausibly even under a wrong
    // key because it sits past the stream-overlap range. The file headers do not. So a wrong
    // key leaves garbage `name_addr`s here, which we reject to keep the key dispatch from
    // latching onto a wrong candidate.
    for i in 0..root.file_head_num as usize {
        let fh = parse_file_head_at(table, first + i * 72)?;
        // `name_addr` outside the table is the strong wrong-key tell. Keep the press/huff
        // check only as a coarse garbage filter. A real compressed size is bounded by the
        // archive (well under 1 TB), while a wrong-key decode yields random ~1e19 values.
        if fh.name_addr as usize >= table.len() {
            return None;
        }
        let sane = |v: u64| v == NONE || v < (1u64 << 40);
        if !sane(fh.press_size) || !sane(fh.huff_size) {
            return None;
        }
    }
    Some(())
}

pub(crate) fn plausible_table_offsets(
    table: &[u8],
    file_table_start: usize,
    directory_table_start: usize,
) -> bool {
    file_table_start < table.len()
        && directory_table_start < table.len()
        && file_table_start % 4 == 0
        && directory_table_start % 4 == 0
        && file_table_start < directory_table_start
}

pub(crate) fn collect_files(layout: &Layout) -> io::Result<Vec<Entry>> {
    let mut out = Vec::new();
    let root = parse_directory_at(&layout.table, layout.directory_table_start)
        .ok_or_else(|| invalid("root directory is outside table"))?;
    collect_dir(
        layout,
        root,
        layout.directory_table_start,
        String::new(),
        &mut out,
    )?;
    Ok(out)
}

pub(crate) fn collect_dir(
    layout: &Layout,
    dir: Directory,
    dir_addr: usize,
    prefix: String,
    out: &mut Vec<Entry>,
) -> io::Result<()> {
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

pub(crate) fn name_for(layout: &Layout, name_addr: usize) -> io::Result<String> {
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

pub(crate) fn extract_all(
    data: &[u8],
    layout: &Layout,
    files: &[Entry],
    out_dir: &Path,
) -> io::Result<()> {
    fs::create_dir_all(out_dir)?;
    let mut failed = 0usize;
    for (idx, entry) in files.iter().enumerate() {
        // Extract resiliently. One unwritable entry (e.g. a reserved/over-long name) must not
        // abort the whole archive. Log it and keep going so the folder is as complete as possible.
        let res = (|| -> io::Result<()> {
            let bytes = extract_file(data, layout, entry)?;
            let target = out_dir.join(safe_relative_path(&entry.path));
            if let Some(parent) = target.parent() {
                fs::create_dir_all(parent)?;
            }
            fs::write(&target, bytes)
        })();
        if let Err(e) = res {
            eprintln!("warning: skipping {}: {e}", entry.path);
            failed += 1;
        }
        if idx % 100 == 0 {
            println!("extracted {:5}/{} {}", idx + 1, files.len(), entry.path);
        }
    }
    if failed > 0 {
        eprintln!("extract: {failed} file(s) could not be written (see warnings above)");
    }
    Ok(())
}

pub(crate) fn extract_file(data: &[u8], layout: &Layout, entry: &Entry) -> io::Result<Vec<u8>> {
    let fh = entry.head;
    // A NO_KEY archive (flags bit 0) stores file data unencrypted, with no per-file key.
    let no_key = (layout.flags & 1) != 0;
    let key = if layout.wolf.is_none() && layout.chacha.is_none() && !no_key {
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
            let huff = read_layout_slice(
                data,
                layout,
                start,
                fh.huff_size as usize,
                key.as_ref(),
                fh.data_size,
            )?;
            let mut lz = huffman_decode(&huff).map_err(invalid)?;
            if layout.huffman_encode_kb != 0xff
                && fh.press_size > (layout.huffman_encode_kb as u64) * 1024 * 2
            {
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
            read_layout_slice(
                data,
                layout,
                start,
                fh.press_size as usize,
                key.as_ref(),
                fh.data_size,
            )?
        };
        return dxa_decode(&press).map_err(invalid);
    }

    if fh.huff_size != NONE {
        let mut output = if layout.huffman_encode_kb != 0xff
            && fh.data_size > (layout.huffman_encode_kb as u64) * 1024 * 2
        {
            let kb = layout.huffman_encode_kb as usize * 1024;
            let huff = read_layout_slice(
                data,
                layout,
                start,
                fh.huff_size as usize,
                key.as_ref(),
                fh.data_size,
            )?;
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
            let huff = read_layout_slice(
                data,
                layout,
                start,
                fh.huff_size as usize,
                key.as_ref(),
                fh.data_size,
            )?;
            huffman_decode(&huff).map_err(invalid)?
        };
        output.truncate(fh.data_size as usize);
        return Ok(output);
    }

    read_layout_slice(
        data,
        layout,
        start,
        fh.data_size as usize,
        key.as_ref(),
        fh.data_size,
    )
}

pub(crate) fn read_layout_slice(
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
        read_wolf_archive_slice(data, start, len, wolf)
            .ok_or_else(|| invalid("file data outside archive"))?
    } else {
        data[start..end].to_vec()
    };

    if let Some(wolf) = &layout.wolf {
        if (layout.flags & 1) == 0 {
            wolf_crypt(
                &wolf.special_key,
                &mut out,
                pos as usize,
                wolf.crypt_version,
            );
        }
    } else if let Some((ck, cn)) = &layout.chacha {
        chacha20::crypt(&mut out, ck, cn, pos as u32);
    } else if let Some(key) = key {
        key_conv(&mut out, key, (pos as usize) % KEY_BYTES);
    }
    Ok(out)
}

pub(crate) fn file_key(layout: &Layout, entry: &Entry) -> io::Result<[u8; KEY_BYTES]> {
    let mut key_string = Vec::new();
    key_string.extend_from_slice(nul_terminated(&layout.key_string));

    let file_name = raw_search_name(layout, entry.head.name_addr as usize)?;
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
        key_string.extend_from_slice(raw_search_name(layout, dir_fh.name_addr as usize)?);
        let parent_addr = layout
            .directory_table_start
            .checked_add(dir.parent_addr as usize)
            .ok_or_else(|| invalid("parent directory overflow"))?;
        dir = parse_directory_at(&layout.table, parent_addr)
            .ok_or_else(|| invalid("parent directory outside table"))?;
    }

    Ok(key_create(&key_string))
}

/// The "search" name (uppercased, stored at `NameAddress + 4`). This is the form DXArchive's
/// `CreateKeyFileString` uses to build per-file keys. Distinct from the original display
/// name (at `+ 4 + packs*4`).
pub(crate) fn raw_search_name(layout: &Layout, name_addr: usize) -> io::Result<&[u8]> {
    let start = name_addr
        .checked_add(4)
        .ok_or_else(|| invalid("search name overflow"))?;
    if start > layout.table.len() {
        return Err(invalid("search name outside table"));
    }
    let end = layout.table[start..]
        .iter()
        .position(|&b| b == 0)
        .map(|p| start + p)
        .unwrap_or(layout.table.len());
    Ok(&layout.table[start..end])
}

pub(crate) fn parse_head_prefix(data: &[u8]) -> io::Result<DxHead> {
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

pub(crate) fn parse_full_head(data: &[u8]) -> io::Result<DxHead> {
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

pub(crate) fn parse_file_head_at(table: &[u8], off: usize) -> Option<FileHead> {
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

pub(crate) fn parse_directory_at(table: &[u8], off: usize) -> Option<Directory> {
    let b = table.get(off..off.checked_add(32)?)?;
    Some(Directory {
        directory_addr: read_u64(b),
        parent_addr: read_u64(&b[8..]),
        file_head_num: read_u64(&b[16..]),
        file_head_addr: read_u64(&b[24..]),
    })
}

pub(crate) fn plausible_head(head: &DxHead, file_len: usize) -> bool {
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
