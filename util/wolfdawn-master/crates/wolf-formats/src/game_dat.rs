//! Game.dat: the per-game settings/title record. Carries the window title, the
//! splash/title-screen messages, the editor font list and a handful of opaque size/offset
//! housekeeping fields the engine uses internally.
//!
//! Layout on disk (plaintext case):
//! `[crypt-indicator u8=0][9-byte magic][unknown1 byteArray][stringCount u32][strings...]
//!  [fileSize u32][unknownSize u32][unknownWordSize u32][wordData][intOffset1 u32]
//!  [intOffset2 u32][unknown2 tail]`.
//!
//! The leading indicator and any encrypted body are crypto-layer concerns. This reader handles
//! the plaintext case (indicator 0) and errors otherwise.
//!
//! Write quirk: the engine recomputes `fileSize` and shifts `intOffset1`/`intOffset2` by the
//! size delta on dump. To keep an unmodified file byte-exact, anchor the delta on the body size
//! as read. An unchanged file yields `sizeDiff == 0`, so the three fields re-emit verbatim. An
//! edited title shifts them by the exact byte delta.

use crate::Ctx;
use wolf_core::{Error, Reader, Result, WStr, Writer};

/// `{0x57,00,00,0x4F,0x4C,00,0x46,0x4D,(00|'U')}`: "WOLFM" with a UTF-8 toggle at idx 8.
const MAGIC_LEN: usize = 9;
const UTF8_MARKER_INDEX: usize = 8;
/// The fixed `magicString` (string index 1) every Game.dat carries.
const MAGIC_STRING: &[u8] = b"0000-0000";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GameDat {
    /// Leading crypt-indicator byte (0 = plaintext).
    pub indicator: u8,
    pub magic: [u8; MAGIC_LEN],
    pub utf8: bool,

    /// Opaque header byte-array preceding the string table.
    pub unknown1: Vec<u8>,
    /// The on-disk string count. Gates which optional strings are present (see [`GameDat::read`]).
    pub string_count: u32,

    // The string table. Player-facing strings are kept as byte-preserving `WStr`.
    /// String 0: the window/game title.
    pub title: WStr,
    /// String 1: the fixed `0000-0000` marker, preserved verbatim.
    pub magic_string: WStr,
    /// String 2: the decrypt key, stored as a raw byte-array (not a length-prefixed string).
    pub decrypt_key: Vec<u8>,
    /// String 3: the main editor font.
    pub font: WStr,
    /// Strings 4 to 6: the three fallback sub-fonts.
    pub sub_fonts: Vec<WStr>,
    /// String 7: the default protagonist graphic.
    pub default_pc_graphic: WStr,
    /// String 8 (present when `string_count >= 9`): the title-suffix or version string.
    pub title_plus: Option<WStr>,
    /// Strings 9 to 12 (present when `string_count > 9`): road image, gauge image, the start-up
    /// message and the title message.
    pub road_img: Option<WStr>,
    pub gauge_img: Option<WStr>,
    pub start_up_msg: Option<WStr>,
    pub title_msg: Option<WStr>,
    /// String 14 (present when `string_count > 13`): an opaque trailing string.
    pub unknown_string14: Option<WStr>,

    // Size/offset housekeeping (recomputed on write, see module docs).
    pub file_size: u32,
    pub unknown_size: u32,
    pub unknown_word_size: u32,
    /// `unknown_word_size * 2` opaque bytes.
    pub unknown_word_data: Vec<u8>,
    pub int_offset1: u32,
    pub int_offset2: u32,
    /// Everything after `int_offset2` until EOF (opaque editor tail).
    pub unknown2: Vec<u8>,

    /// The body size (everything after the indicator byte) as computed from the data at read
    /// time. The write-time `sizeDiff` is `calc_body_size() - body_size_at_read`, so an
    /// unmodified file re-serializes byte-exact (delta 0) while an edit shifts the offsets by the
    /// exact byte delta.
    body_size_at_read: u32,
}

impl GameDat {
    pub fn read(bytes: &[u8]) -> Result<Self> {
        let mut r = Reader::new(bytes);

        let indicator = r.read_u8()?;
        if indicator != 0 {
            return Err(Error::invalid(
                "Game.dat is encrypted (indicator != 0); decrypt with wolf-archive first",
            ));
        }

        let magic_vec = r.read_bytes(MAGIC_LEN)?;
        if magic_vec[0] != 0x57 || magic_vec[6] != 0x46 || magic_vec[7] != 0x4D {
            return Err(Error::invalid("not a Game.dat (magic mismatch)"));
        }
        let mut magic = [0u8; MAGIC_LEN];
        magic.copy_from_slice(&magic_vec);
        let utf8 = magic[UTF8_MARKER_INDEX] == b'U';
        let _ = Ctx { utf8, v35: false };

        let unknown1 = r.read_byte_array()?;
        let string_count = r.read_u32()?;

        // String 0
        let title = r.read_string()?;
        // String 1 (the fixed marker)
        let magic_string = r.read_string()?;
        if magic_string.as_bytes().strip_suffix(&[0u8]).unwrap_or(magic_string.as_bytes())
            != MAGIC_STRING
        {
            return Err(Error::invalid(format!(
                "Game.dat invalid magic string: {:?}",
                magic_string.to_lossy()
            )));
        }
        // String 2 (a byte-array, not a string)
        let decrypt_key = r.read_byte_array()?;
        // String 3
        let font = r.read_string()?;
        // Strings 4-6
        let mut sub_fonts = Vec::with_capacity(3);
        for _ in 0..3 {
            sub_fonts.push(r.read_string()?);
        }
        // String 7
        let default_pc_graphic = r.read_string()?;

        // String 8
        let title_plus = if string_count >= 9 {
            Some(r.read_string()?)
        } else {
            None
        };

        // Strings 9-12
        let (road_img, gauge_img, start_up_msg, title_msg) = if string_count > 9 {
            (
                Some(r.read_string()?),
                Some(r.read_string()?),
                Some(r.read_string()?),
                Some(r.read_string()?),
            )
        } else {
            (None, None, None, None)
        };

        // String 14
        let unknown_string14 = if string_count > 13 {
            Some(r.read_string()?)
        } else {
            None
        };

        let file_size = r.read_u32()?;
        let unknown_size = r.read_u32()?;
        let unknown_word_size = r.read_u32()?;
        let unknown_word_data = r.read_bytes(unknown_word_size as usize * 2)?;
        let int_offset1 = r.read_u32()?;
        let int_offset2 = r.read_u32()?;
        let unknown2 = r.read_bytes(r.remaining())?;

        if !r.is_eof() {
            return Err(Error::invalid("Game.dat has trailing data"));
        }

        let mut gd = GameDat {
            indicator,
            magic,
            utf8,
            unknown1,
            string_count,
            title,
            magic_string,
            decrypt_key,
            font,
            sub_fonts,
            default_pc_graphic,
            title_plus,
            road_img,
            gauge_img,
            start_up_msg,
            title_msg,
            unknown_string14,
            file_size,
            unknown_size,
            unknown_word_size,
            unknown_word_data,
            int_offset1,
            int_offset2,
            unknown2,
            body_size_at_read: 0,
        };
        gd.body_size_at_read = gd.calc_body_size();
        Ok(gd)
    }

    pub fn write(&self) -> Vec<u8> {
        // The size delta vs. the data as read. It is 0 for an unmodified file (byte-exact), else
        // the exact byte difference, applied to the three housekeeping fields.
        let new_size = self.calc_body_size();
        let size_diff = new_size as i64 - self.body_size_at_read as i64;
        let shift = |v: u32| -> u32 { (v as i64 + size_diff) as u32 };

        let mut w = Writer::new();
        w.write_u8(self.indicator);
        w.write_bytes(&self.magic);

        w.write_byte_array(&self.unknown1);
        w.write_u32(self.string_count);

        w.write_string(&self.title);
        w.write_string(&self.magic_string);
        w.write_byte_array(&self.decrypt_key);
        w.write_string(&self.font);
        for f in &self.sub_fonts {
            w.write_string(f);
        }
        w.write_string(&self.default_pc_graphic);
        if let Some(s) = &self.title_plus {
            w.write_string(s);
        }
        if let (Some(r), Some(g), Some(s), Some(t)) =
            (&self.road_img, &self.gauge_img, &self.start_up_msg, &self.title_msg)
        {
            w.write_string(r);
            w.write_string(g);
            w.write_string(s);
            w.write_string(t);
        }
        if let Some(s) = &self.unknown_string14 {
            w.write_string(s);
        }

        w.write_u32(shift(self.file_size));
        w.write_u32(self.unknown_size);
        w.write_u32(self.unknown_word_size);
        w.write_bytes(&self.unknown_word_data);
        w.write_u32(shift(self.int_offset1));
        w.write_u32(shift(self.int_offset2));
        w.write_bytes(&self.unknown2);

        w.into_bytes()
    }

    /// The body size everything after the indicator byte serializes to (magic + string table +
    /// housekeeping fields + tail). Excludes the leading crypt indicator. Used to anchor the
    /// write-time `sizeDiff`.
    fn calc_body_size(&self) -> u32 {
        let str_size = |s: &WStr| s.len() + 4; // u32 length prefix + bytes
        let mut size = MAGIC_LEN;
        size += self.unknown1.len() + 4;
        size += 4; // string_count
        size += str_size(&self.title);
        size += str_size(&self.magic_string);
        size += self.decrypt_key.len() + 4;
        size += str_size(&self.font);
        for f in &self.sub_fonts {
            size += str_size(f);
        }
        size += str_size(&self.default_pc_graphic);
        if let Some(s) = &self.title_plus {
            size += str_size(s);
        }
        for s in [&self.road_img, &self.gauge_img, &self.start_up_msg, &self.title_msg]
            .into_iter()
            .flatten()
        {
            size += str_size(s);
        }
        if let Some(s) = &self.unknown_string14 {
            size += str_size(s);
        }
        size += 4; // file_size
        size += 4; // unknown_size
        size += 4; // unknown_word_size
        size += self.unknown_word_data.len();
        size += 4; // int_offset1
        size += 4; // int_offset2
        size += self.unknown2.len();
        size as u32
    }
}
