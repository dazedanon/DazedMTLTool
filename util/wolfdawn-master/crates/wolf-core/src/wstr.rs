use std::fmt;

/// A Wolf length-prefixed string, stored as its raw on-disk bytes (no length prefix
/// included). Encoding is either Shift-JIS (CP932) or UTF-8 depending on the owning
/// file's magic. The low-level layer does not decode it, so read/write stays byte-exact
/// regardless of encoding. Decoding to UTF-8 for human display happens in the decompiler
/// layer.
#[derive(Clone, Default, PartialEq, Eq, Hash)]
pub struct WStr(pub Vec<u8>);

impl WStr {
    pub fn new(bytes: Vec<u8>) -> Self {
        WStr(bytes)
    }

    pub fn as_bytes(&self) -> &[u8] {
        &self.0
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    /// Lossy UTF-8 view, for diagnostics/display only. Not used on the round-trip path.
    pub fn to_lossy(&self) -> String {
        String::from_utf8_lossy(&self.0).into_owned()
    }
}

impl fmt::Debug for WStr {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:?}", self.to_lossy())
    }
}

impl From<&str> for WStr {
    fn from(s: &str) -> Self {
        WStr(s.as_bytes().to_vec())
    }
}
