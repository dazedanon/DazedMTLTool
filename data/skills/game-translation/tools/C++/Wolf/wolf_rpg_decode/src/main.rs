use std::env;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

const MAP_PACK_VERSION: u8 = 0x65;

#[derive(Default)]
struct Stats {
    seen: usize,
    written: usize,
    unpacked: usize,
    copied_plain: usize,
    skipped: usize,
}

fn main() -> io::Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        eprintln!("usage: wolf_rpg_decode <input_dir> <output_dir>");
        std::process::exit(2);
    }

    let input = PathBuf::from(&args[1]);
    let output = PathBuf::from(&args[2]);
    fs::create_dir_all(&output)?;

    let mut stats = Stats::default();
    walk(&input, &input, &output, &mut stats)?;

    println!("seen: {}", stats.seen);
    println!("written: {}", stats.written);
    println!("unpacked_lz4: {}", stats.unpacked);
    println!("already_plain: {}", stats.copied_plain);
    println!("skipped: {}", stats.skipped);
    Ok(())
}

fn walk(root: &Path, dir: &Path, output_root: &Path, stats: &mut Stats) -> io::Result<()> {
    for item in fs::read_dir(dir)? {
        let item = item?;
        let path = item.path();
        if item.file_type()?.is_dir() {
            walk(root, &path, output_root, stats)?;
            continue;
        }

        let ext = path
            .extension()
            .and_then(|s| s.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase();
        if ext != "mps" && ext != "dat" {
            stats.skipped += 1;
            continue;
        }

        stats.seen += 1;
        let rel = path.strip_prefix(root).unwrap_or(&path);
        let out_path = output_root.join(rel);
        if let Some(parent) = out_path.parent() {
            fs::create_dir_all(parent)?;
        }

        let data = fs::read(&path)?;
        let decoded = if ext == "mps" {
            decode_map(&data)?
        } else {
            decode_dat(&data)?
        };

        if decoded.unpacked {
            stats.unpacked += 1;
        } else {
            stats.copied_plain += 1;
        }
        stats.written += 1;
        fs::write(&out_path, decoded.bytes)?;
    }
    Ok(())
}

struct Decoded {
    bytes: Vec<u8>,
    unpacked: bool,
}

fn decode_map(data: &[u8]) -> io::Result<Decoded> {
    if data.len() > 33 && data[20] >= MAP_PACK_VERSION && packed_block_bounds(data, 25).is_some() {
        let decoded = unpack_at(data, 25)?;
        return Ok(Decoded {
            bytes: decoded,
            unpacked: true,
        });
    }

    Ok(Decoded {
        bytes: data.to_vec(),
        unpacked: false,
    })
}

fn decode_dat(data: &[u8]) -> io::Result<Decoded> {
    if data.len() > 19 && matches!(data[10], 0x93 | 0xc4 | 0xcc) && packed_block_bounds(data, 11).is_some() {
        let decoded = unpack_at(data, 11)?;
        return Ok(Decoded {
            bytes: decoded,
            unpacked: true,
        });
    }

    Ok(Decoded {
        bytes: data.to_vec(),
        unpacked: false,
    })
}

fn packed_block_bounds(data: &[u8], start: usize) -> Option<(usize, usize)> {
    if start + 8 > data.len() {
        return None;
    }
    let encoded_size = read_u32(&data[start + 4..]) as usize;
    let encoded_start = start + 8;
    let encoded_end = encoded_start.checked_add(encoded_size)?;
    if encoded_end == data.len() {
        Some((encoded_start, encoded_end))
    } else {
        None
    }
}

fn unpack_at(data: &[u8], start: usize) -> io::Result<Vec<u8>> {
    if start + 8 > data.len() {
        return Err(invalid("packed block header is outside file"));
    }
    let decoded_size = read_u32(&data[start..]) as usize;
    let encoded_size = read_u32(&data[start + 4..]) as usize;
    let encoded_start = start + 8;
    let encoded_end = encoded_start
        .checked_add(encoded_size)
        .ok_or_else(|| invalid("packed block size overflow"))?;
    let encoded = data
        .get(encoded_start..encoded_end)
        .ok_or_else(|| invalid("packed block is truncated"))?;

    let payload = lz4_decompress_block(encoded, decoded_size)?;
    let mut out = Vec::with_capacity(start + payload.len());
    out.extend_from_slice(&data[..start]);
    out.extend_from_slice(&payload);
    Ok(out)
}

fn lz4_decompress_block(src: &[u8], decoded_size: usize) -> io::Result<Vec<u8>> {
    let mut out = Vec::with_capacity(decoded_size);
    let mut sp = 0usize;

    while sp < src.len() {
        let token = src[sp];
        sp += 1;

        let literal_len = read_lz4_len(src, &mut sp, (token >> 4) as usize)?;
        if sp + literal_len > src.len() {
            return Err(invalid("lz4 literal run exceeds source"));
        }
        out.extend_from_slice(&src[sp..sp + literal_len]);
        sp += literal_len;

        if sp >= src.len() {
            break;
        }
        if sp + 2 > src.len() {
            return Err(invalid("lz4 match offset is truncated"));
        }
        let offset = read_u16(&src[sp..]) as usize;
        sp += 2;
        if offset == 0 || offset > out.len() {
            return Err(invalid("lz4 match offset is invalid"));
        }

        let match_len = read_lz4_len(src, &mut sp, (token & 0x0f) as usize)? + 4;
        for _ in 0..match_len {
            let b = out[out.len() - offset];
            out.push(b);
        }
    }

    if out.len() != decoded_size {
        return Err(invalid(format!(
            "lz4 decoded {} bytes, expected {}",
            out.len(),
            decoded_size
        )));
    }

    Ok(out)
}

fn read_lz4_len(src: &[u8], sp: &mut usize, base: usize) -> io::Result<usize> {
    let mut len = base;
    if base != 15 {
        return Ok(len);
    }

    loop {
        let b = *src
            .get(*sp)
            .ok_or_else(|| invalid("lz4 length extension is truncated"))? as usize;
        *sp += 1;
        len = len
            .checked_add(b)
            .ok_or_else(|| invalid("lz4 length overflow"))?;
        if b != 255 {
            break;
        }
    }
    Ok(len)
}

fn read_u16(b: &[u8]) -> u16 {
    u16::from_le_bytes([b[0], b[1]])
}

fn read_u32(b: &[u8]) -> u32 {
    u32::from_le_bytes([b[0], b[1], b[2], b[3]])
}

fn invalid<E: std::fmt::Display>(msg: E) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, msg.to_string())
}
