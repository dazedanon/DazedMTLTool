//! `wolf-formats`: byte-faithful, typed (de)serialization of Wolf RPG data files.
//!
//! Each format exposes `read(&[u8]) -> Result<T>` and `T::write(&self) -> Vec<u8>`.
//! The contract is round-trip fidelity. For an unmodified plaintext file,
//! `write(read(bytes)) == bytes`. Anything not yet understood is preserved verbatim
//! as opaque bytes rather than dropped, so recompiled files always remain loadable.

#![forbid(unsafe_code)]

pub mod command;
pub mod common_event;
pub mod database;
pub mod game_dat;
pub mod map;

pub use wolf_core::{Error, Reader, Result, WStr, Writer};

/// Context threaded through a load/dump so per-command behaviour matches the owning
/// file. Encoding and v3.5 mode are passed explicitly rather than via globals.
#[derive(Debug, Clone, Copy, Default)]
pub struct Ctx {
    /// File strings are UTF-8 (magic toggle byte == `'U'`), else Shift-JIS.
    pub utf8: bool,
    /// Wolf Pro v3.5 file: every command carries a trailing length-prefixed blob.
    pub v35: bool,
}
