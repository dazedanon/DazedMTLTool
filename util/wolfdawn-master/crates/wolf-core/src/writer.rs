use crate::wstr::WStr;

/// Accumulates the Wolf wire primitives into a byte buffer. The exact inverse of
/// [`crate::reader::Reader`]. Writing back everything that was read reproduces the
/// original bytes, which is the round-trip contract for the format layer.
#[derive(Default)]
pub struct Writer {
    buf: Vec<u8>,
}

impl Writer {
    pub fn new() -> Self {
        Writer { buf: Vec::new() }
    }

    pub fn with_capacity(cap: usize) -> Self {
        Writer {
            buf: Vec::with_capacity(cap),
        }
    }

    pub fn len(&self) -> usize {
        self.buf.len()
    }

    pub fn is_empty(&self) -> bool {
        self.buf.is_empty()
    }

    pub fn as_slice(&self) -> &[u8] {
        &self.buf
    }

    pub fn into_bytes(self) -> Vec<u8> {
        self.buf
    }

    pub fn write_u8(&mut self, v: u8) {
        self.buf.push(v);
    }

    pub fn write_u32(&mut self, v: u32) {
        self.buf.extend_from_slice(&v.to_le_bytes());
    }

    pub fn write_bytes(&mut self, b: &[u8]) {
        self.buf.extend_from_slice(b);
    }

    pub fn write_string(&mut self, s: &WStr) {
        self.write_u32(s.len() as u32);
        self.buf.extend_from_slice(s.as_bytes());
    }

    pub fn write_byte_array(&mut self, b: &[u8]) {
        self.write_u32(b.len() as u32);
        self.buf.extend_from_slice(b);
    }

    pub fn write_int_array(&mut self, a: &[u32]) {
        self.write_u32(a.len() as u32);
        for &v in a {
            self.write_u32(v);
        }
    }

    pub fn write_string_array(&mut self, a: &[WStr]) {
        self.write_u32(a.len() as u32);
        for s in a {
            self.write_string(s);
        }
    }
}
