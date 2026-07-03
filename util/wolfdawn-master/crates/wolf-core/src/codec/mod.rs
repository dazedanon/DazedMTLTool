//! Compression and encoding codecs shared across Wolf formats. The LZ4 block codec used by
//! v3.5 ("Pro") compressed file bodies, and the `.sav` outer XOR cipher ([`wolfsave`]).

pub mod lz4;
pub mod wolfsave;
