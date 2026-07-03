use std::fmt;

pub type Result<T> = std::result::Result<T, Error>;

/// Errors raised by the low-level wire layer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    /// Tried to read past the end of the buffer.
    UnexpectedEof {
        context: &'static str,
        needed: usize,
        pos: usize,
        len: usize,
    },
    /// A fixed magic/marker byte sequence did not match.
    BadMagic {
        context: &'static str,
        expected: Vec<u8>,
        found: Vec<u8>,
    },
    /// A structural invariant was violated.
    Invalid(String),
}

impl Error {
    pub fn invalid(msg: impl Into<String>) -> Self {
        Error::Invalid(msg.into())
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::UnexpectedEof {
                context,
                needed,
                pos,
                len,
            } => write!(
                f,
                "unexpected EOF while reading {context}: need {needed} byte(s) at offset {pos}, buffer is {len} byte(s)"
            ),
            Error::BadMagic {
                context,
                expected,
                found,
            } => write!(
                f,
                "bad magic for {context}: expected {}, found {}",
                hex(expected),
                hex(found)
            ),
            Error::Invalid(msg) => write!(f, "{msg}"),
        }
    }
}

impl std::error::Error for Error {}

fn hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 3);
    for (i, b) in bytes.iter().enumerate() {
        if i > 0 {
            s.push(' ');
        }
        s.push_str(&format!("{b:02x}"));
    }
    s
}
