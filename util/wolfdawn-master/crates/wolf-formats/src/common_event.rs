//! CommonEvent file (`CommonEvent.dat`): a flat list of shared event programs.
//! Each common event holds a command list (same encoding as map pages) plus a large
//! tail of editor metadata kept opaque for now.
//!
//! Layout on disk:
//! `[crypt-indicator u8=0][9-byte magic][version u8][eventCount u32][events][terminator u8]`.
//! The leading indicator and the v3.5 LZ4 body are crypto-layer concerns. This reader
//! handles the plaintext case (indicator 0, version != 0x93/0xCC) and errors otherwise.

use crate::command::RawCommand;
use crate::Ctx;
use wolf_core::codec::lz4;
use wolf_core::{Error, Reader, Result, WStr, Writer};

/// `{0x57,00,00,0x4F,0x4C,(00|'U'),0x46,0x43,00}`: "WOLFC" with a UTF-8 toggle at idx 5.
const MAGIC_LEN: usize = 9;
const UTF8_MARKER_INDEX: usize = 5;
const EVENT_INDICATOR: u8 = 0x8E;
const DATA_INDICATOR_8F: u8 = 0x8F;
const DATA_INDICATOR_91: u8 = 0x91;
const DATA_INDICATOR_92: u8 = 0x92;
const UNKNOWN8_COUNT: usize = 100;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommonEventsFile {
    /// Leading crypt-indicator byte (0 = plaintext).
    pub indicator: u8,
    pub magic: [u8; MAGIC_LEN],
    pub version: u8,
    pub events: Vec<CommonEvent>,
    pub terminator: u8,
    pub utf8: bool,
    /// True when version is `0x93`/`0xCC` (Wolf Pro v3.5). The body after the version byte
    /// is LZ4-compressed and every command carries a trailing blob.
    pub v35: bool,
    /// For v3.5 files: the original framed LZ4 body `[decSize][encSize][block]`, kept so an
    /// unmodified file re-emits byte-exact (LZ4 recompression isn't byte-stable).
    pub packed: Option<Vec<u8>>,
}

impl CommonEventsFile {
    pub fn read(bytes: &[u8]) -> Result<Self> {
        let mut r = Reader::new(bytes);

        let indicator = r.read_u8()?;
        if indicator != 0 {
            return Err(Error::invalid(
                "CommonEvent.dat is encrypted (indicator != 0); decrypt with wolf-archive first",
            ));
        }

        let magic_vec = r.read_bytes(MAGIC_LEN)?;
        if magic_vec[0] != 0x57 || magic_vec[6] != 0x46 || magic_vec[7] != 0x43 {
            return Err(Error::invalid("not a CommonEvent.dat (magic mismatch)"));
        }
        let mut magic = [0u8; MAGIC_LEN];
        magic.copy_from_slice(&magic_vec);
        let utf8 = magic[UTF8_MARKER_INDEX] == b'U';

        let version = r.read_u8()?;
        let v35 = version == 0x93 || version == 0xCC;
        let ctx = Ctx { utf8, v35 };

        // For v3.5 the body after the version byte is an LZ4 block. Decompress it and parse
        // the events from the decompressed bytes. Plain files just continue inline.
        let rem = r.remaining();
        let (packed, body): (Option<Vec<u8>>, Vec<u8>) = if v35 {
            let framed = r.read_bytes(rem)?;
            let body = lz4::unpack(&framed)?;
            (Some(framed), body)
        } else {
            (None, r.read_bytes(rem)?)
        };
        let mut r = Reader::new(&body);

        let event_count = r.read_u32()? as usize;
        let mut events = Vec::with_capacity(event_count);
        for _ in 0..event_count {
            events.push(CommonEvent::read(&mut r, &ctx)?);
        }

        let terminator = r.read_u8()?;
        if terminator < 0x89 {
            return Err(Error::invalid(format!(
                "CommonEvent terminator 0x{terminator:02x} < 0x89"
            )));
        }
        if !r.is_eof() {
            return Err(Error::invalid("CommonEvent.dat has trailing data"));
        }

        Ok(CommonEventsFile {
            indicator,
            magic,
            version,
            events,
            terminator,
            utf8,
            v35,
            packed,
        })
    }

    pub fn write(&self) -> Vec<u8> {
        let ctx = Ctx {
            utf8: self.utf8,
            v35: self.v35,
        };
        let mut w = Writer::new();
        w.write_u8(self.indicator);
        w.write_bytes(&self.magic);
        w.write_u8(self.version);

        // The compressible body: event count + events + terminator.
        let mut body = Writer::new();
        body.write_u32(self.events.len() as u32);
        for ev in &self.events {
            ev.write(&mut body, &ctx);
        }
        body.write_u8(self.terminator);
        let body = body.into_bytes();

        if self.v35 {
            // Re-emit the original packed bytes verbatim when the body is unchanged
            // (byte-exact). Otherwise compress fresh (valid LZ4, content-exact).
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
pub struct CommonEvent {
    pub int_id: u32,
    pub unknown1: u32,
    pub unknown2: [u8; 7],
    pub name: WStr,
    pub commands: Vec<RawCommand>,
    pub unknown11: WStr,
    pub description: WStr,
    pub unknown3: Vec<WStr>,
    pub unknown4: Vec<u8>,
    pub unknown5: Vec<Vec<WStr>>,
    pub unknown6: Vec<Vec<u32>>,
    pub unknown7: [u8; 0x1D],
    /// Exactly 100 strings (slot/argument names), no count prefix on disk.
    pub unknown8: Vec<WStr>,
    pub unknown9: WStr,
    /// Optional `0x92` tail: `(unknown10, unknown12)`.
    pub unknown10: Option<(WStr, u32)>,
}

impl CommonEvent {
    fn read(r: &mut Reader, ctx: &Ctx) -> Result<Self> {
        let ind = r.read_u8()?;
        if ind != EVENT_INDICATOR {
            return Err(Error::invalid(format!(
                "CommonEvent header indicator 0x{ind:02x} != 0x8E"
            )));
        }

        let int_id = r.read_u32()?;
        let unknown1 = r.read_u32()?;
        let unknown2 = read_fixed::<7>(r)?;
        let name = r.read_string()?;

        let command_count = r.read_u32()? as usize;
        let mut commands = Vec::with_capacity(command_count);
        for _ in 0..command_count {
            commands.push(RawCommand::read(r, ctx)?);
        }

        let unknown11 = r.read_string()?;
        let description = r.read_string()?;

        expect(r, DATA_INDICATOR_8F, "0x8F")?;

        let unknown3 = r.read_string_array()?;

        let unknown4 = r.read_byte_array()?;

        let n5 = r.read_u32()? as usize;
        let mut unknown5 = Vec::with_capacity(n5);
        for _ in 0..n5 {
            unknown5.push(r.read_string_array()?);
        }

        let n6 = r.read_u32()? as usize;
        let mut unknown6 = Vec::with_capacity(n6);
        for _ in 0..n6 {
            unknown6.push(r.read_int_array()?);
        }

        let unknown7 = read_fixed::<0x1D>(r)?;

        let mut unknown8 = Vec::with_capacity(UNKNOWN8_COUNT);
        for _ in 0..UNKNOWN8_COUNT {
            unknown8.push(r.read_string()?);
        }

        expect(r, DATA_INDICATOR_91, "0x91")?;
        let unknown9 = r.read_string()?;

        let next = r.read_u8()?;
        let unknown10 = match next {
            DATA_INDICATOR_91 => None,
            DATA_INDICATOR_92 => {
                let s = r.read_string()?;
                let n = r.read_u32()?;
                expect(r, DATA_INDICATOR_92, "0x92")?;
                Some((s, n))
            }
            other => {
                return Err(Error::invalid(format!(
                    "CommonEvent tail indicator 0x{other:02x} not 0x91/0x92"
                )))
            }
        };

        Ok(CommonEvent {
            int_id,
            unknown1,
            unknown2,
            name,
            commands,
            unknown11,
            description,
            unknown3,
            unknown4,
            unknown5,
            unknown6,
            unknown7,
            unknown8,
            unknown9,
            unknown10,
        })
    }

    fn write(&self, w: &mut Writer, ctx: &Ctx) {
        w.write_u8(EVENT_INDICATOR);
        w.write_u32(self.int_id);
        w.write_u32(self.unknown1);
        w.write_bytes(&self.unknown2);
        w.write_string(&self.name);
        w.write_u32(self.commands.len() as u32);
        for c in &self.commands {
            c.write(w, ctx);
        }
        w.write_string(&self.unknown11);
        w.write_string(&self.description);
        w.write_u8(DATA_INDICATOR_8F);

        w.write_string_array(&self.unknown3);
        w.write_byte_array(&self.unknown4);

        w.write_u32(self.unknown5.len() as u32);
        for strs in &self.unknown5 {
            w.write_string_array(strs);
        }

        w.write_u32(self.unknown6.len() as u32);
        for ints in &self.unknown6 {
            w.write_int_array(ints);
        }

        w.write_bytes(&self.unknown7);
        for s in &self.unknown8 {
            w.write_string(s);
        }

        w.write_u8(DATA_INDICATOR_91);
        w.write_string(&self.unknown9);

        match &self.unknown10 {
            Some((s, n)) => {
                w.write_u8(DATA_INDICATOR_92);
                w.write_string(s);
                w.write_u32(*n);
                w.write_u8(DATA_INDICATOR_92);
            }
            None => w.write_u8(DATA_INDICATOR_91),
        }
    }
}

fn read_fixed<const N: usize>(r: &mut Reader) -> Result<[u8; N]> {
    let v = r.read_bytes(N)?;
    let mut out = [0u8; N];
    out.copy_from_slice(&v);
    Ok(out)
}

fn expect(r: &mut Reader, byte: u8, label: &str) -> Result<()> {
    let got = r.read_u8()?;
    if got != byte {
        return Err(Error::invalid(format!(
            "CommonEvent expected indicator {label}, got 0x{got:02x}"
        )));
    }
    Ok(())
}
