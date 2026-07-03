//! Map file (`.mps`): `WOLFM` magic, tileset/size header, opaque tile grid, then a
//! list of events, each with pages that hold the event command program.
//!
//! The LZ4-compressed body of v3.5 maps (version >= 0x65) is not yet handled. The local
//! corpus is version 0x64 (plain).

use crate::command::{read_route_list, write_route_list, RawCommand, RouteCommand};
use crate::Ctx;
use wolf_core::codec::lz4;
use wolf_core::{Error, Reader, Result, WStr, Writer};

const MAGIC_LEN: usize = 20;
const WOLFM: &[u8] = b"WOLFM";
const UTF8_MARKER_INDEX: usize = 16;

const EVENT_INDICATOR: u8 = 0x6F;
const MAP_TERMINATOR: u8 = 0x66;
const PAGE_INDICATOR: u8 = 0x79;
const EVENT_TERMINATOR: u8 = 0x70;
const PAGE_TERMINATOR: u8 = 0x7A;

const EVENT_MAGIC1: [u8; 4] = [0x39, 0x30, 0x00, 0x00];
const EVENT_MAGIC2: [u8; 4] = [0x00, 0x00, 0x00, 0x00];

const LZ4_VERSION_GATE: u32 = 0x65;
const V35_VERSION_GATE: u32 = 0x67;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Map {
    /// The full 20-byte magic, kept verbatim (the byte at index 16 is `'U'` for UTF-8).
    pub magic: [u8; MAGIC_LEN],
    pub version: u32,
    pub unknown2: u8,
    pub unknown3: WStr,
    pub tileset_id: u32,
    pub width: u32,
    pub height: u32,
    /// Present only for version >= 0x67.
    pub unknown4: Option<u32>,
    /// Layer count (3 by default, explicit since v3.5). Used to size the tile grid.
    pub layer_count: u32,
    /// Raw tile grid bytes (`width * height * layer_count * 4`), opaque for now.
    pub tiles: Vec<u8>,
    /// UTF-8 maps may store a `0xFFFFFFFF` marker meaning "no tile grid".
    pub no_tiles_marker: bool,
    pub events: Vec<Event>,
    pub utf8: bool,
    /// For v3.5 maps (version >= 0x65): the original framed LZ4 body
    /// `[decSize][encSize][block]`, kept so an unmodified map re-emits byte-exact.
    pub packed: Option<Vec<u8>>,
}

impl Map {
    pub fn read(bytes: &[u8]) -> Result<Self> {
        let mut r = Reader::new(bytes);

        let magic_vec = r.read_bytes(MAGIC_LEN)?;
        if &magic_vec[10..15] != WOLFM {
            return Err(Error::invalid("not a WOLFM map (magic mismatch)"));
        }
        let mut magic = [0u8; MAGIC_LEN];
        magic.copy_from_slice(&magic_vec);
        let utf8 = magic[UTF8_MARKER_INDEX] == b'U';

        let version = r.read_u32()?;
        let unknown2 = r.read_u8()?;

        let ctx = Ctx {
            utf8,
            v35: version >= V35_VERSION_GATE,
        };

        // v3.5 maps (version >= 0x65) LZ4-compress everything after [magic][version][unknown2].
        let rem = r.remaining();
        let (packed, body): (Option<Vec<u8>>, Vec<u8>) = if version >= LZ4_VERSION_GATE {
            let framed = r.read_bytes(rem)?;
            let decompressed = lz4::unpack(&framed)?;
            (Some(framed), decompressed)
        } else {
            (None, r.read_bytes(rem)?)
        };
        let mut r = Reader::new(&body);

        let unknown3 = r.read_string()?;
        let tileset_id = r.read_u32()?;
        let width = r.read_u32()?;
        let height = r.read_u32()?;
        let event_count = r.read_u32()? as usize;

        let mut unknown4 = None;
        let mut layer_count = 3u32;
        if version >= V35_VERSION_GATE {
            unknown4 = Some(r.read_u32()?);
            layer_count = r.read_u32()?;
        }

        // UTF-8 maps may signal an absent tile grid with a 0xFFFFFFFF sentinel.
        let mut no_tiles_marker = false;
        let mut tiles = Vec::new();
        if utf8 && r.peek_u32()? == 0xFFFF_FFFF {
            r.read_u32()?;
            no_tiles_marker = true;
        }
        if !no_tiles_marker {
            let tile_bytes = (width as usize)
                .saturating_mul(height as usize)
                .saturating_mul(layer_count as usize)
                .saturating_mul(4);
            tiles = r.read_bytes(tile_bytes)?;
        }

        let mut events = Vec::with_capacity(event_count);
        loop {
            let indicator = r.read_u8()?;
            if indicator == MAP_TERMINATOR {
                break;
            }
            if indicator != EVENT_INDICATOR {
                return Err(Error::invalid(format!(
                    "unexpected map event indicator 0x{indicator:02x} (expected 0x6F or 0x66)"
                )));
            }
            events.push(Event::read(&mut r, &ctx)?);
        }

        if events.len() != event_count {
            return Err(Error::invalid(format!(
                "map declared {event_count} events but read {}",
                events.len()
            )));
        }
        if !r.is_eof() {
            return Err(Error::invalid("map has trailing data after terminator"));
        }

        Ok(Map {
            magic,
            version,
            unknown2,
            unknown3,
            tileset_id,
            width,
            height,
            unknown4,
            layer_count,
            tiles,
            no_tiles_marker,
            events,
            utf8,
            packed,
        })
    }

    pub fn write(&self) -> Vec<u8> {
        let ctx = Ctx {
            utf8: self.utf8,
            v35: self.version >= V35_VERSION_GATE,
        };
        let mut w = Writer::with_capacity(self.tiles.len() + 4096);

        // The fixed, never-compressed header.
        w.write_bytes(&self.magic);
        w.write_u32(self.version);
        w.write_u8(self.unknown2);

        // The compressible body: everything from unknown3 to the map terminator.
        let mut body = Writer::with_capacity(self.tiles.len() + 4096);
        body.write_string(&self.unknown3);
        body.write_u32(self.tileset_id);
        body.write_u32(self.width);
        body.write_u32(self.height);
        body.write_u32(self.events.len() as u32);

        if self.version >= V35_VERSION_GATE {
            body.write_u32(self.unknown4.unwrap_or(0));
            body.write_u32(self.layer_count);
        }

        if self.no_tiles_marker {
            body.write_u32(0xFFFF_FFFF);
        } else {
            body.write_bytes(&self.tiles);
        }

        for event in &self.events {
            body.write_u8(EVENT_INDICATOR);
            event.write(&mut body, &ctx);
        }
        body.write_u8(MAP_TERMINATOR);
        let body = body.into_bytes();

        if self.version >= LZ4_VERSION_GATE {
            // Re-emit original packed bytes verbatim when unchanged (byte-exact). Else
            // compress fresh (valid LZ4, content-exact).
            match &self.packed {
                Some(orig) if lz4::unpack(orig).map(|b| b == body).unwrap_or(false) => {
                    w.write_bytes(orig);
                }
                _ => w.write_bytes(&lz4::pack(&body)),
            }
        } else {
            w.write_bytes(&body);
        }

        w.into_bytes()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Event {
    pub id: u32,
    pub name: WStr,
    pub x: u32,
    pub y: u32,
    pub pages: Vec<Page>,
}

impl Event {
    fn read(r: &mut Reader, ctx: &Ctx) -> Result<Self> {
        r.verify(&EVENT_MAGIC1, "event magic1")?;
        let id = r.read_u32()?;
        let name = r.read_string()?;
        let x = r.read_u32()?;
        let y = r.read_u32()?;
        let page_count = r.read_u32()? as usize;
        r.verify(&EVENT_MAGIC2, "event magic2")?;

        let mut pages = Vec::with_capacity(page_count);
        loop {
            let indicator = r.read_u8()?;
            if indicator == EVENT_TERMINATOR {
                break;
            }
            if indicator != PAGE_INDICATOR {
                return Err(Error::invalid(format!(
                    "unexpected event page indicator 0x{indicator:02x} (expected 0x79 or 0x70)"
                )));
            }
            pages.push(Page::read(r, ctx)?);
        }

        if pages.len() != page_count {
            return Err(Error::invalid(format!(
                "event {id} declared {page_count} pages but read {}",
                pages.len()
            )));
        }

        Ok(Event {
            id,
            name,
            x,
            y,
            pages,
        })
    }

    fn write(&self, w: &mut Writer, ctx: &Ctx) {
        w.write_bytes(&EVENT_MAGIC1);
        w.write_u32(self.id);
        w.write_string(&self.name);
        w.write_u32(self.x);
        w.write_u32(self.y);
        w.write_u32(self.pages.len() as u32);
        w.write_bytes(&EVENT_MAGIC2);
        for page in &self.pages {
            w.write_u8(PAGE_INDICATOR);
            page.write(w, ctx);
        }
        w.write_u8(EVENT_TERMINATOR);
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Page {
    pub unknown1: u32,
    pub graphic_name: WStr,
    pub graphic_direction: u8,
    pub graphic_frame: u8,
    pub graphic_opacity: u8,
    pub graphic_render_mode: u8,
    /// 37 opaque condition bytes (1 + 4 + 16 + 16).
    pub conditions: Vec<u8>,
    /// 4 opaque movement bytes.
    pub movement: Vec<u8>,
    pub flags: u8,
    pub route_flags: u8,
    pub route: Vec<RouteCommand>,
    pub commands: Vec<RawCommand>,
    pub features: u32,
    pub shadow_graphic_num: u8,
    pub collision_width: u8,
    pub collision_height: u8,
    /// Present only when `features > 3`.
    pub page_transfer: Option<u8>,
}

impl Page {
    fn read(r: &mut Reader, ctx: &Ctx) -> Result<Self> {
        let unknown1 = r.read_u32()?;
        let graphic_name = r.read_string()?;
        let graphic_direction = r.read_u8()?;
        let graphic_frame = r.read_u8()?;
        let graphic_opacity = r.read_u8()?;
        let graphic_render_mode = r.read_u8()?;
        let conditions = r.read_bytes(37)?;
        let movement = r.read_bytes(4)?;
        let flags = r.read_u8()?;
        let route_flags = r.read_u8()?;
        let route = read_route_list(r)?;

        let command_count = r.read_u32()? as usize;
        let mut commands = Vec::with_capacity(command_count);
        for _ in 0..command_count {
            commands.push(RawCommand::read(r, ctx)?);
        }

        let features = r.read_u32()?;
        let shadow_graphic_num = r.read_u8()?;
        let collision_width = r.read_u8()?;
        let collision_height = r.read_u8()?;
        let page_transfer = if features > 3 {
            Some(r.read_u8()?)
        } else {
            None
        };

        let terminator = r.read_u8()?;
        if terminator != PAGE_TERMINATOR {
            return Err(Error::invalid(format!(
                "page terminator was 0x{terminator:02x}, expected 0x7A"
            )));
        }

        Ok(Page {
            unknown1,
            graphic_name,
            graphic_direction,
            graphic_frame,
            graphic_opacity,
            graphic_render_mode,
            conditions,
            movement,
            flags,
            route_flags,
            route,
            commands,
            features,
            shadow_graphic_num,
            collision_width,
            collision_height,
            page_transfer,
        })
    }

    fn write(&self, w: &mut Writer, ctx: &Ctx) {
        w.write_u32(self.unknown1);
        w.write_string(&self.graphic_name);
        w.write_u8(self.graphic_direction);
        w.write_u8(self.graphic_frame);
        w.write_u8(self.graphic_opacity);
        w.write_u8(self.graphic_render_mode);
        w.write_bytes(&self.conditions);
        w.write_bytes(&self.movement);
        w.write_u8(self.flags);
        w.write_u8(self.route_flags);
        write_route_list(w, &self.route);

        w.write_u32(self.commands.len() as u32);
        for c in &self.commands {
            c.write(w, ctx);
        }

        w.write_u32(self.features);
        w.write_u8(self.shadow_graphic_num);
        w.write_u8(self.collision_width);
        w.write_u8(self.collision_height);
        if let Some(pt) = self.page_transfer {
            w.write_u8(pt);
        }
        w.write_u8(PAGE_TERMINATOR);
    }
}
