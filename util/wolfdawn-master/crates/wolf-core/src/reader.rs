use crate::error::{Error, Result};
use crate::wstr::WStr;

/// A cursor over an in-memory byte buffer that decodes the Wolf wire primitives.
///
/// `Int` = u32 little-endian, `Byte` = u8, `String` = u32 length prefix plus that many
/// raw bytes (kept undecoded, see [`WStr`]).
pub struct Reader<'a> {
    data: &'a [u8],
    pos: usize,
}

impl<'a> Reader<'a> {
    pub fn new(data: &'a [u8]) -> Self {
        Reader { data, pos: 0 }
    }

    pub fn pos(&self) -> usize {
        self.pos
    }

    pub fn len(&self) -> usize {
        self.data.len()
    }

    pub fn is_empty(&self) -> bool {
        self.data.is_empty()
    }

    pub fn remaining(&self) -> usize {
        self.data.len().saturating_sub(self.pos)
    }

    pub fn is_eof(&self) -> bool {
        self.pos >= self.data.len()
    }

    pub fn seek(&mut self, pos: usize) {
        self.pos = pos;
    }

    /// Absolute byte at `idx` without moving the cursor.
    pub fn at(&self, idx: usize) -> Option<u8> {
        self.data.get(idx).copied()
    }

    pub fn skip(&mut self, n: usize, context: &'static str) -> Result<()> {
        self.ensure(n, context)?;
        self.pos += n;
        Ok(())
    }

    fn ensure(&self, n: usize, context: &'static str) -> Result<()> {
        if self.pos + n > self.data.len() {
            return Err(Error::UnexpectedEof {
                context,
                needed: n,
                pos: self.pos,
                len: self.data.len(),
            });
        }
        Ok(())
    }

    pub fn read_u8(&mut self) -> Result<u8> {
        self.ensure(1, "u8")?;
        let v = self.data[self.pos];
        self.pos += 1;
        Ok(v)
    }

    pub fn read_u32(&mut self) -> Result<u32> {
        self.ensure(4, "u32")?;
        let b = &self.data[self.pos..self.pos + 4];
        self.pos += 4;
        Ok(u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
    }

    /// Peek the next u32 without advancing the cursor.
    pub fn peek_u32(&self) -> Result<u32> {
        self.ensure(4, "peek u32")?;
        let b = &self.data[self.pos..self.pos + 4];
        Ok(u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
    }

    pub fn read_bytes(&mut self, n: usize) -> Result<Vec<u8>> {
        self.ensure(n, "fixed bytes")?;
        let v = self.data[self.pos..self.pos + n].to_vec();
        self.pos += n;
        Ok(v)
    }

    /// `String`: u32 byte-length prefix + that many raw bytes.
    pub fn read_string(&mut self) -> Result<WStr> {
        let size = self.read_u32()? as usize;
        let bytes = self.read_bytes(size)?;
        Ok(WStr(bytes))
    }

    /// `ByteArray`: u32 count + that many bytes.
    pub fn read_byte_array(&mut self) -> Result<Vec<u8>> {
        let size = self.read_u32()? as usize;
        self.read_bytes(size)
    }

    /// `IntArray`: u32 count + that many u32s.
    pub fn read_int_array(&mut self) -> Result<Vec<u32>> {
        let size = self.read_u32()? as usize;
        let mut out = Vec::with_capacity(size.min(1 << 16));
        for _ in 0..size {
            out.push(self.read_u32()?);
        }
        Ok(out)
    }

    /// `StringArray`: u32 count + that many `String`s.
    pub fn read_string_array(&mut self) -> Result<Vec<WStr>> {
        let size = self.read_u32()? as usize;
        let mut out = Vec::with_capacity(size.min(1 << 16));
        for _ in 0..size {
            out.push(self.read_string()?);
        }
        Ok(out)
    }

    /// Verify a fixed marker/magic byte sequence and advance past it.
    pub fn verify(&mut self, expected: &[u8], context: &'static str) -> Result<()> {
        self.ensure(expected.len(), context)?;
        let found = &self.data[self.pos..self.pos + expected.len()];
        if found != expected {
            return Err(Error::BadMagic {
                context,
                expected: expected.to_vec(),
                found: found.to_vec(),
            });
        }
        self.pos += expected.len();
        Ok(())
    }
}
