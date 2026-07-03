//! DXArchive VER5 / VER6: the old Wolf RPG Editor 2.0x archive formats.
//!
//! The shared crypto and codec (12-byte key derivation and `KeyConv`, keycode-LZSS, name
//! extraction) live in [`common`]. Each version's distinct table/struct layout lives in its
//! own module ([`ver5`] = Wolf 2.01/2.10, [`ver6`] = Wolf 2.20). The newer v8 (Wolf 2.225+)
//! format is handled separately in the crate root.

mod common;
pub mod encode;
mod ver5;
mod ver6;

pub use encode::{pack_ver5, pack_ver6};

/// Try to decode `data` as a VER5 (Wolf 2.01/2.10) then VER6 (Wolf 2.20) archive, returning
/// `(path, contents)` pairs. `None` if it isn't one of these legacy formats.
pub fn try_extract(data: &[u8]) -> Option<Vec<(String, Vec<u8>)>> {
    ver5::try_extract(data).or_else(|| ver6::try_extract(data))
}
