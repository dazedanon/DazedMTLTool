//! Event command and move-route encoding, the core unit a decompiler operates on.
//!
//! Read order: `argCount = byte-1`, `cid` u32, `argCount` ints, `indent` byte,
//! `strCount` byte, `strCount` strings, `terminator` byte. Terminator `0x01` (or
//! cid==Move) is followed by a move-route block. Wolf Pro v3.5 appends a per-command
//! length-prefixed blob.

use crate::Ctx;
use wolf_core::{Error, Reader, Result, WStr, Writer};

/// On-disk command id for `Move` (201). The only cid whose `0x00`-terminated form
/// still carries a route block.
pub const CID_MOVE: u32 = 201;

/// A single event command, mirroring the on-disk bytes exactly. This is the round-trip
/// authority that the higher decompiler IR is derived from and lowered back to.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RawCommand {
    pub cid: u32,
    pub int_args: Vec<u32>,
    pub indent: u8,
    pub str_args: Vec<WStr>,
    /// Terminator byte as read (`0x00` normal, `0x01` move). Stored for faithfulness.
    pub term: u8,
    pub move_route: Option<MoveRoute>,
    /// Wolf Pro v3.5 trailing blob (length-prefixed by a single byte), if present.
    pub v35_blob: Option<Vec<u8>>,
}

impl RawCommand {
    pub fn read(r: &mut Reader, ctx: &Ctx) -> Result<Self> {
        let arg_count_byte = r.read_u8()?;
        let n = arg_count_byte
            .checked_sub(1)
            .ok_or_else(|| Error::invalid("command int-arg count byte was 0 (expected >= 1)"))?
            as usize;

        let cid = r.read_u32()?;
        let mut int_args = Vec::with_capacity(n);
        for _ in 0..n {
            int_args.push(r.read_u32()?);
        }

        let indent = r.read_u8()?;
        let str_count = r.read_u8()? as usize;
        let mut str_args = Vec::with_capacity(str_count);
        for _ in 0..str_count {
            str_args.push(r.read_string()?);
        }

        let term = r.read_u8()?;
        let move_route = match term {
            0x01 => Some(MoveRoute::read(r)?),
            0x00 => {
                if cid == CID_MOVE {
                    Some(MoveRoute::read(r)?)
                } else {
                    None
                }
            }
            other => {
                return Err(Error::invalid(format!(
                    "unexpected command terminator 0x{other:02x} (cid {cid})"
                )))
            }
        };

        let v35_blob = if ctx.v35 {
            let size = r.read_u8()? as usize;
            Some(r.read_bytes(size)?)
        } else {
            None
        };

        Ok(RawCommand {
            cid,
            int_args,
            indent,
            str_args,
            term,
            move_route,
            v35_blob,
        })
    }

    pub fn write(&self, w: &mut Writer, ctx: &Ctx) {
        w.write_u8((self.int_args.len() + 1) as u8);
        w.write_u32(self.cid);
        for &a in &self.int_args {
            w.write_u32(a);
        }
        w.write_u8(self.indent);
        w.write_u8(self.str_args.len() as u8);
        for s in &self.str_args {
            w.write_string(s);
        }
        w.write_u8(self.term);
        if let Some(mr) = &self.move_route {
            mr.write(w);
        }
        if ctx.v35 {
            let blob = self.v35_blob.as_deref().unwrap_or(&[]);
            w.write_u8(blob.len() as u8);
            w.write_bytes(blob);
        }
    }
}

/// The move-route block attached to a `Move` command: 5 opaque bytes, a flags byte,
/// and a length-prefixed list of [`RouteCommand`]s.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MoveRoute {
    pub unknown: [u8; 5],
    pub flags: u8,
    pub commands: Vec<RouteCommand>,
}

impl MoveRoute {
    pub fn read(r: &mut Reader) -> Result<Self> {
        let mut unknown = [0u8; 5];
        for b in &mut unknown {
            *b = r.read_u8()?;
        }
        let flags = r.read_u8()?;
        let count = r.read_u32()? as usize;
        let mut commands = Vec::with_capacity(count);
        for _ in 0..count {
            commands.push(RouteCommand::read(r)?);
        }
        Ok(MoveRoute {
            unknown,
            flags,
            commands,
        })
    }

    pub fn write(&self, w: &mut Writer) {
        w.write_bytes(&self.unknown);
        w.write_u8(self.flags);
        w.write_u32(self.commands.len() as u32);
        for c in &self.commands {
            c.write(w);
        }
    }
}

/// A single move-route sub-command: `id` byte, `argCount` byte, ints, then a fixed
/// `{01,00}` terminator. Used both inside [`MoveRoute`] and directly in a page's route list.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RouteCommand {
    pub id: u8,
    pub args: Vec<u32>,
    pub terminator: [u8; 2],
}

impl RouteCommand {
    pub fn read(r: &mut Reader) -> Result<Self> {
        let id = r.read_u8()?;
        let argc = r.read_u8()? as usize;
        let mut args = Vec::with_capacity(argc);
        for _ in 0..argc {
            args.push(r.read_u32()?);
        }
        let terminator = [r.read_u8()?, r.read_u8()?];
        if terminator != [0x01, 0x00] {
            return Err(Error::invalid(format!(
                "route command terminator was {:02x?}, expected [01, 00]",
                terminator
            )));
        }
        Ok(RouteCommand {
            id,
            args,
            terminator,
        })
    }

    pub fn write(&self, w: &mut Writer) {
        w.write_u8(self.id);
        w.write_u8(self.args.len() as u8);
        for &a in &self.args {
            w.write_u32(a);
        }
        w.write_bytes(&self.terminator);
    }
}

/// Read a length-prefixed (`u32` count) list of [`RouteCommand`]s. This is the form used
/// directly in a map page's route field (no 5-byte/flags header).
pub fn read_route_list(r: &mut Reader) -> Result<Vec<RouteCommand>> {
    let count = r.read_u32()? as usize;
    let mut out = Vec::with_capacity(count);
    for _ in 0..count {
        out.push(RouteCommand::read(r)?);
    }
    Ok(out)
}

pub fn write_route_list(w: &mut Writer, list: &[RouteCommand]) {
    w.write_u32(list.len() as u32);
    for c in list {
        c.write(w);
    }
}
