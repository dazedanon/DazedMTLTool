//! DXArchive VER5 / VER6 writers: the inverse of [`super::ver5`] / [`super::ver6`].
//!
//! Produce the old Wolf 2.0x containers, storing files uncompressed so no keycode-LZSS encoder
//! is needed (the reader reads `press_size == 0xFFFF…` verbatim). Both ciphers are a symmetric
//! `key_conv` XOR, so encryption is the reader's decrypt applied to the plaintext container.
//! Header layouts mirror the real sample archives exactly. VER5 is version 3 with a 24-byte
//! header and whole-archive XOR by file offset. VER6 is version 6 with a 48-byte header, tables
//! keyed at position 0, and each file's data at position `data_size`. The shared tree walk and
//! name-table encoder come from [`crate::pack`].

use super::common::{key_conv, key_create, KEYLEN};
use crate::pack::{add_filename, Node};

const DX_HEAD: u16 = 0x5844;
const ATTR_DIRECTORY: u64 = 0x10;
const ATTR_ARCHIVE: u64 = 0x20;

/// VER5 v2.01 / VER6 v2.20 table keys. The reader tries these, so the output decodes through
/// our own dispatch and the real engine.
const KEY_V201: &[u8] = &[
    0x0f, 0x53, 0xe1, 0x3e, 0x04, 0x37, 0x12, 0x17, 0x60, 0x0f, 0x53, 0xe1,
];
const KEY_V220: &[u8] = &[
    0x38, 0x50, 0x40, 0x28, 0x72, 0x4f, 0x21, 0x70, 0x3b, 0x73, 0x35, 0x38,
];

/// Per-version struct geometry. Field offsets within a file head: `name_addr@0`, `attr@ptr`,
/// time block, `data_addr@data_addr_off`, `data_size@+ptr`, `press@+2*ptr`.
struct Spec {
    ptr: usize,
    fh_size: usize,
    data_addr_off: usize,
}
const V5: Spec = Spec {
    ptr: 4,
    fh_size: 44,
    data_addr_off: 32,
};
const V6: Spec = Spec {
    ptr: 8,
    fh_size: 64,
    data_addr_off: 40,
};

impl Spec {
    fn none(&self) -> u64 {
        if self.ptr == 4 {
            0xFFFF_FFFF
        } else {
            u64::MAX
        }
    }
    fn dir_size(&self) -> usize {
        self.ptr * 4
    }
}

fn put(buf: &mut [u8], off: usize, val: u64, ptr: usize) {
    buf[off..off + ptr].copy_from_slice(&val.to_le_bytes()[..ptr]);
}

fn get(buf: &[u8], off: usize, ptr: usize) -> u64 {
    let mut b = [0u8; 8];
    b[..ptr].copy_from_slice(&buf[off..off + ptr]);
    u64::from_le_bytes(b)
}

#[derive(Default)]
struct Build {
    name: Vec<u8>,
    file: Vec<u8>,
    dir: Vec<u8>,
    data: Vec<u8>,
    /// `(data_addr, data_size)` per leaf file. VER6 keys each region at `pos = data_size`.
    file_regions: Vec<(u64, u64)>,
}

/// Build the name/file/dir/data buffers for `root` using `spec`'s geometry (mirrors the v8
/// `DirectoryEncode`: root self-filehead, per-directory contiguous file runs).
fn build_tables(spec: &Spec, root: &Node) -> Build {
    let mut b = Build::default();
    add_filename(&mut b.name, ""); // root name (address 0)
    b.file.resize(spec.fh_size, 0);
    write_filehead(spec, &mut b.file, 0, 0, ATTR_DIRECTORY, 0, 0);

    let root_num = root.entry_count() as u64;
    let root_fha = b.file.len() as u64; // = fh_size
    append_dir(spec, &mut b.dir, 0, spec.none(), root_num, root_fha);
    b.file
        .resize(b.file.len() + spec.fh_size * root_num as usize, 0);

    encode_children(spec, &mut b, root, root_fha, 0);
    b
}

fn encode_children(spec: &Spec, b: &mut Build, node: &Node, fha: u64, this_dir_addr: u64) {
    let mut i = 0u64;
    for (name, child) in &node.dirs {
        directory_encode(spec, b, child, name, fha, this_dir_addr, i);
        i += 1;
    }
    for (name, data) in &node.files {
        write_file_entry(spec, b, name, data, fha, i);
        i += 1;
    }
}

fn directory_encode(
    spec: &Spec,
    b: &mut Build,
    node: &Node,
    name: &str,
    parent_fha: u64,
    parent_dir_addr: u64,
    data_number: u64,
) {
    let name_addr = b.name.len() as u64;
    let this_dir_offset = b.dir.len() as u64;
    add_filename(&mut b.name, name);
    let self_off = (parent_fha + data_number * spec.fh_size as u64) as usize;
    write_filehead(
        spec,
        &mut b.file,
        self_off,
        name_addr,
        ATTR_DIRECTORY,
        this_dir_offset,
        0,
    );

    let this_fha = b.file.len() as u64;
    let parent_directory_address = if parent_dir_addr != spec.none() && parent_dir_addr != 0 {
        get(
            &b.file,
            parent_dir_addr as usize + spec.data_addr_off,
            spec.ptr,
        )
    } else {
        0
    };
    let num = node.entry_count() as u64;
    append_dir(
        spec,
        &mut b.dir,
        self_off as u64,
        parent_directory_address,
        num,
        this_fha,
    );
    b.file.resize(b.file.len() + spec.fh_size * num as usize, 0);

    encode_children(spec, b, node, this_fha, self_off as u64);
}

fn write_file_entry(
    spec: &Spec,
    b: &mut Build,
    name: &str,
    data: &[u8],
    fha: u64,
    data_number: u64,
) {
    let name_addr = b.name.len() as u64;
    add_filename(&mut b.name, name);
    let data_addr = b.data.len() as u64;
    let off = (fha + data_number * spec.fh_size as u64) as usize;
    write_filehead(
        spec,
        &mut b.file,
        off,
        name_addr,
        ATTR_ARCHIVE,
        data_addr,
        data.len() as u64,
    );
    b.file_regions.push((data_addr, data.len() as u64));
    b.data.extend_from_slice(data);
    while b.data.len() % 4 != 0 {
        b.data.push(0);
    }
}

fn write_filehead(
    spec: &Spec,
    file: &mut [u8],
    off: usize,
    name_addr: u64,
    attr: u64,
    data_addr: u64,
    data_size: u64,
) {
    put(file, off, name_addr, spec.ptr);
    put(file, off + spec.ptr, attr, spec.ptr);
    // time block [2*ptr .. data_addr_off] stays zero
    put(file, off + spec.data_addr_off, data_addr, spec.ptr);
    put(
        file,
        off + spec.data_addr_off + spec.ptr,
        data_size,
        spec.ptr,
    );
    put(
        file,
        off + spec.data_addr_off + 2 * spec.ptr,
        spec.none(),
        spec.ptr,
    ); // press = uncompressed
}

fn append_dir(spec: &Spec, dir: &mut Vec<u8>, dir_addr: u64, parent: u64, fhn: u64, fha: u64) {
    let base = dir.len();
    dir.resize(base + spec.dir_size(), 0);
    put(dir, base, dir_addr, spec.ptr);
    put(dir, base + spec.ptr, parent, spec.ptr);
    put(dir, base + 2 * spec.ptr, fhn, spec.ptr);
    put(dir, base + 3 * spec.ptr, fha, spec.ptr);
}

fn build_tree<'a>(files: &'a [(String, Vec<u8>)]) -> Result<Node<'a>, String> {
    if files.is_empty() {
        return Err("cannot pack an empty file list".to_string());
    }
    let mut root = Node::default();
    for (path, data) in files {
        let parts: Vec<&str> = path.split(['\\', '/']).filter(|s| !s.is_empty()).collect();
        if parts.is_empty() {
            return Err(format!("invalid (empty) path: {path:?}"));
        }
        root.insert(&parts, data);
    }
    Ok(root)
}

/// Pack into a Wolf 2.01/2.10 (VER5, version 3) archive. Build the plaintext container, then
/// XOR the whole file by offset with the version key, which is the reader's exact inverse.
pub fn pack_ver5(files: &[(String, Vec<u8>)]) -> Result<Vec<u8>, String> {
    let root = build_tree(files)?;
    let b = build_tables(&V5, &root);
    let head_size = b.name.len() + b.file.len() + b.dir.len();
    let data_start = 24usize; // version-3 header has no CodePage field
    let name_tbl = data_start + b.data.len();

    let mut out = vec![0u8; data_start];
    out[0..2].copy_from_slice(&DX_HEAD.to_le_bytes());
    out[2..4].copy_from_slice(&3u16.to_le_bytes()); // version 3 (Wolf 2.01/2.10)
    put(&mut out, 4, head_size as u64, 4);
    put(&mut out, 8, data_start as u64, 4);
    put(&mut out, 12, name_tbl as u64, 4);
    put(&mut out, 16, b.name.len() as u64, 4); // FileTableStart (rel to name table)
    put(&mut out, 20, (b.name.len() + b.file.len()) as u64, 4); // DirectoryTableStart (rel)
    out.extend_from_slice(&b.data);
    out.extend_from_slice(&b.name);
    out.extend_from_slice(&b.file);
    out.extend_from_slice(&b.dir);

    let key = key_create(KEY_V201);
    for (i, byte) in out.iter_mut().enumerate() {
        *byte ^= key[i % KEYLEN];
    }
    Ok(out)
}

/// Pack into a Wolf 2.20 (VER6, version 6) archive: header + tables keyed at position 0, each
/// file's data keyed at position `data_size`. Mirrors the reader's decrypt.
pub fn pack_ver6(files: &[(String, Vec<u8>)]) -> Result<Vec<u8>, String> {
    let root = build_tree(files)?;
    let b = build_tables(&V6, &root);
    let head_size = b.name.len() + b.file.len() + b.dir.len();
    let data_start = 48usize;
    let name_tbl = data_start + b.data.len();

    let mut head = vec![0u8; 48];
    head[0..2].copy_from_slice(&DX_HEAD.to_le_bytes());
    head[2..4].copy_from_slice(&6u16.to_le_bytes()); // version 6 (Wolf 2.20)
    put(&mut head, 4, head_size as u64, 4); // HeadSize is u32 even in VER6
    put(&mut head, 8, data_start as u64, 8);
    put(&mut head, 16, name_tbl as u64, 8);
    put(&mut head, 24, b.name.len() as u64, 8); // FileTableStart (rel)
    put(&mut head, 32, (b.name.len() + b.file.len()) as u64, 8); // DirectoryTableStart (rel)
    put(&mut head, 40, 1252, 8); // CodePage (matches the real 2.20 sample archive)

    let key = key_create(KEY_V220);

    // File data: key each region at pos = its data_size (padding between files stays
    // plaintext, exactly as the reader ignores it).
    let mut data = b.data.clone();
    for &(addr, size) in &b.file_regions {
        let (a, s) = (addr as usize, size as usize);
        let keyed = key_conv(&key, &data[a..a + s], s);
        data[a..a + s].copy_from_slice(&keyed);
    }

    let mut table = Vec::with_capacity(head_size);
    table.extend_from_slice(&b.name);
    table.extend_from_slice(&b.file);
    table.extend_from_slice(&b.dir);

    let mut out = Vec::with_capacity(data_start + data.len() + head_size);
    out.extend_from_slice(&key_conv(&key, &head, 0)); // header keyed at 0
    out.extend_from_slice(&data);
    out.extend_from_slice(&key_conv(&key, &table, 0)); // tables keyed at 0
    Ok(out)
}
