//! `wolf-core`: the low-level Wolf RPG wire layer.
//!
//! Provides the byte [`Reader`]/[`Writer`] and the length-prefixed [`WStr`] string
//! primitive shared by every Wolf file format. This layer carries no Wolf domain
//! semantics (no maps, databases or commands) and decodes nothing it cannot reproduce
//! byte-for-byte. Strings are kept as raw bytes so read/write is exact regardless of
//! Shift-JIS vs UTF-8 encoding.

#![forbid(unsafe_code)]

pub mod codec;
pub mod error;
pub mod reader;
pub mod writer;
pub mod wstr;

pub use error::{Error, Result};
pub use reader::Reader;
pub use writer::Writer;
pub use wstr::WStr;
