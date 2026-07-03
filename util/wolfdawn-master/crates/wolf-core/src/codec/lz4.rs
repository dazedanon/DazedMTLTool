//! LZ4 block format codec (not the LZ4 frame format). This is the exact variant Wolf RPG
//! Editor v3.5 ("Pro") uses for compressed file bodies via `LZ4_decompress_safe` and
//! `LZ4_compress_default`.
//!
//! Wolf wraps a block as `[decompressedSize: u32][compressedSize: u32][block bytes]`.
//! [`unpack`]/[`pack`] handle that framing, [`decompress_block`]/[`compress_block`] the
//! raw block.
//!
//! The encoder is a greedy single-pass LZ4 compressor with a 4-byte hash table match finder.
//! It emits a valid compressed block honouring the constraints `LZ4_decompress_safe` requires.
//! The last 5 bytes are literals, no match starts within the last 12 bytes, min match is 4,
//! and offsets are 1..=65535. Byte-exact round-trip of unmodified files is achieved at the
//! format layer by re-emitting the original packed bytes verbatim. Fresh compression is used
//! for edited bodies, where what matters is validity and a reasonable size, not byte-identity
//! with the editor's own LZ4.

use crate::error::{Error, Result};

/// Decompress a raw LZ4 block of known output size.
pub fn decompress_block(src: &[u8], decoded_size: usize) -> Result<Vec<u8>> {
    let mut out = Vec::with_capacity(decoded_size);
    let mut sp = 0usize;

    while sp < src.len() {
        let token = src[sp];
        sp += 1;

        // Literal run.
        let literal_len = read_len(src, &mut sp, (token >> 4) as usize)?;
        if sp + literal_len > src.len() {
            return Err(Error::invalid("lz4: literal run exceeds source"));
        }
        out.extend_from_slice(&src[sp..sp + literal_len]);
        sp += literal_len;

        // A block legitimately ends right after a literal run (the last sequence).
        if sp >= src.len() {
            break;
        }
        if sp + 2 > src.len() {
            return Err(Error::invalid("lz4: match offset is truncated"));
        }
        let offset = u16::from_le_bytes([src[sp], src[sp + 1]]) as usize;
        sp += 2;
        if offset == 0 || offset > out.len() {
            return Err(Error::invalid("lz4: match offset is invalid"));
        }

        // Match copy (min length 4, byte-by-byte to allow overlap).
        let match_len = read_len(src, &mut sp, (token & 0x0F) as usize)? + 4;
        for _ in 0..match_len {
            let b = out[out.len() - offset];
            out.push(b);
        }
    }

    if out.len() != decoded_size {
        return Err(Error::invalid(format!(
            "lz4: decoded {} bytes, expected {decoded_size}",
            out.len()
        )));
    }
    Ok(out)
}

/// Read an LZ4 length (the `0xF`/`0xFF`-extension scheme) given the 4-bit token nibble.
fn read_len(src: &[u8], sp: &mut usize, base: usize) -> Result<usize> {
    let mut len = base;
    if base != 15 {
        return Ok(len);
    }
    loop {
        let b = *src
            .get(*sp)
            .ok_or_else(|| Error::invalid("lz4: length extension truncated"))?
            as usize;
        *sp += 1;
        len = len
            .checked_add(b)
            .ok_or_else(|| Error::invalid("lz4: length overflow"))?;
        if b != 255 {
            break;
        }
    }
    Ok(len)
}

// LZ4 block constraints (so `LZ4_decompress_safe` accepts the output).
const MIN_MATCH: usize = 4;
/// No match may *start* within the last 12 bytes of the block.
const MFLIMIT: usize = 12;
/// The last 5 bytes of the block are always literals.
const LAST_LITERALS: usize = 5;
const HASH_BITS: u32 = 16;

fn read_u32(s: &[u8], i: usize) -> u32 {
    u32::from_le_bytes([s[i], s[i + 1], s[i + 2], s[i + 3]])
}

fn hash4(v: u32) -> usize {
    (v.wrapping_mul(2_654_435_761) >> (32 - HASH_BITS)) as usize
}

/// Append an LZ4 length extension (the value beyond the 15 already encoded in the token nibble).
fn write_len_ext(out: &mut Vec<u8>, mut rem: usize) {
    while rem >= 255 {
        out.push(255);
        rem -= 255;
    }
    out.push(rem as u8);
}

/// Emit the trailing literals-only sequence (no match), terminating the block.
fn emit_last_literals(out: &mut Vec<u8>, lits: &[u8]) {
    let n = lits.len();
    out.push(((n.min(15)) as u8) << 4);
    if n >= 15 {
        write_len_ext(out, n - 15);
    }
    out.extend_from_slice(lits);
}

/// Compress to a valid LZ4 block with a greedy 4-byte-hash match finder. Used for
/// freshly-serialized (edited) bodies. Unmodified bodies are re-emitted verbatim by the format
/// layer. Round-trips through [`decompress_block`] and respects the engine's block constraints.
pub fn compress_block(src: &[u8]) -> Vec<u8> {
    let n = src.len();
    let mut out = Vec::with_capacity(n / 2 + 16);

    // Too short to hold a match plus the mandatory trailing literals: emit all literals.
    if n < MFLIMIT + MIN_MATCH {
        emit_last_literals(&mut out, src);
        return out;
    }
    let match_limit = n - MFLIMIT; // a match may only start at ip < match_limit
    let match_end = n - LAST_LITERALS; // a match may not cover bytes at/after this

    let mut table = vec![usize::MAX; 1 << HASH_BITS];
    let mut anchor = 0usize; // start of the pending literal run
    let mut ip = 0usize;
    table[hash4(read_u32(src, ip))] = ip;
    ip += 1;

    while ip < match_limit {
        let h = hash4(read_u32(src, ip));
        let cand = table[h];
        table[h] = ip;

        let is_match =
            cand != usize::MAX && ip - cand <= 0xFFFF && read_u32(src, cand) == read_u32(src, ip);
        if !is_match {
            ip += 1;
            continue;
        }

        // Extend the match (stops before the mandatory last-literals tail).
        let offset = ip - cand;
        let mut mlen = MIN_MATCH;
        while ip + mlen < match_end && src[cand + mlen] == src[ip + mlen] {
            mlen += 1;
        }

        // Emit: pending literals, then the match.
        let lits = &src[anchor..ip];
        let lit_len = lits.len();
        let match_tok = (mlen - MIN_MATCH).min(15);
        out.push(((lit_len.min(15) as u8) << 4) | match_tok as u8);
        if lit_len >= 15 {
            write_len_ext(&mut out, lit_len - 15);
        }
        out.extend_from_slice(lits);
        out.extend_from_slice(&(offset as u16).to_le_bytes());
        if mlen - MIN_MATCH >= 15 {
            write_len_ext(&mut out, mlen - MIN_MATCH - 15);
        }

        ip += mlen;
        anchor = ip;
    }

    // Trailing literals (always at least LAST_LITERALS bytes).
    emit_last_literals(&mut out, &src[anchor..]);
    out
}

/// Decompress Wolf's framed form `[decSize u32][encSize u32][block]` (the bytes that
/// follow a v3.5 file header). Trailing bytes beyond `encSize` are ignored.
pub fn unpack(framed: &[u8]) -> Result<Vec<u8>> {
    if framed.len() < 8 {
        return Err(Error::invalid(
            "lz4: framed body shorter than 8-byte header",
        ));
    }
    let dec_size = u32::from_le_bytes([framed[0], framed[1], framed[2], framed[3]]) as usize;
    let enc_size = u32::from_le_bytes([framed[4], framed[5], framed[6], framed[7]]) as usize;
    let block = framed
        .get(8..8 + enc_size)
        .ok_or_else(|| Error::invalid("lz4: framed body shorter than declared compressed size"))?;
    decompress_block(block, dec_size)
}

/// Produce Wolf's framed form `[decSize u32][encSize u32][block]` for a body.
pub fn pack(body: &[u8]) -> Vec<u8> {
    let block = compress_block(body);
    let mut out = Vec::with_capacity(block.len() + 8);
    out.extend_from_slice(&(body.len() as u32).to_le_bytes());
    out.extend_from_slice(&(block.len() as u32).to_le_bytes());
    out.extend_from_slice(&block);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn roundtrip(data: &[u8]) {
        let packed = pack(data);
        let back = unpack(&packed).expect("unpack");
        assert_eq!(back, data, "lz4 pack/unpack round-trip mismatch");
    }

    #[test]
    fn pack_unpack_roundtrips() {
        roundtrip(b"");
        roundtrip(b"a");
        roundtrip(b"hello world");
        roundtrip(&[0u8; 1000]);
        // 14, 15, 16 bytes straddle the literal-length extension boundary.
        for n in [14usize, 15, 16, 270, 271, 600] {
            roundtrip(&(0..n).map(|i| (i * 31 % 256) as u8).collect::<Vec<_>>());
        }
    }

    #[test]
    fn compresses_and_roundtrips() {
        // Highly repetitive -> should compress hard and still round-trip.
        let zeros = vec![0u8; 10_000];
        let p = pack(&zeros);
        assert_eq!(unpack(&p).unwrap(), zeros);
        assert!(
            p.len() < zeros.len() / 20,
            "zeros packed to {} bytes",
            p.len()
        );

        // Repeating phrase.
        let mut text = Vec::new();
        for _ in 0..2000 {
            text.extend_from_slice(b"the quick brown fox jumps. ");
        }
        let p = pack(&text);
        assert_eq!(unpack(&p).unwrap(), text);
        assert!(p.len() < text.len() / 3, "text packed to {} bytes", p.len());

        // Varied sizes / patterns straddling the match + last-literal boundaries.
        for n in [0usize, 1, 4, 11, 12, 13, 16, 17, 64, 255, 256, 4096, 12345] {
            let data: Vec<u8> = (0..n).map(|i| ((i * 7 + i / 13) % 256) as u8).collect();
            let p = pack(&data);
            assert_eq!(unpack(&p).unwrap(), data, "roundtrip failed at n={n}");
        }
    }

    #[test]
    fn decodes_a_match_bearing_block() {
        // "abcabcabc": emit literals "abc" then a match (offset 3, len 6).
        // token: litlen=3 (hi), matchlen-4=2 (lo) => 0x32, then "abc", then offset=3, no ext.
        let block = [0x32u8, b'a', b'b', b'c', 0x03, 0x00];
        let out = decompress_block(&block, 9).expect("decode");
        assert_eq!(&out, b"abcabcabc");
    }
}
