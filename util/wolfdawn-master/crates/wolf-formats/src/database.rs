//! Database: the paired `.project` (schema: type/field/data names + field UI types)
//! and `.dat` (field index-info + actual int/string cell values) format. Used for the
//! User Database, System Database (`SysDatabase`) and Changeable Database (`CDatabase`).
//!
//! Handles the plaintext case (dat indicator 0, version != 0xC4, unencrypted project).
//! Pro/LZ4 variants error pending wolf-archive.

use crate::Ctx;
use wolf_core::codec::lz4;
use wolf_core::{Error, Reader, Result, WStr, Writer};

const MAGIC_LEN: usize = 9;
const UTF8_MARKER_INDEX: usize = 5;
const TYPE_SEPARATOR: [u8; 4] = [0xFE, 0xFF, 0xFF, 0xFF];
const STRING_INDICATOR: u32 = 0x0001_D4C0;
const STRING_START: u32 = 0x07D0;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Database {
    pub dat_indicator: u8,
    pub dat_magic: [u8; MAGIC_LEN],
    pub dat_version: u8,
    pub utf8: bool,
    pub types: Vec<DbType>,
    /// True when `dat_version == 0xC4` (Wolf Pro v3.5). The dat type/data section is
    /// LZ4-compressed. The `.project` schema is never compressed.
    pub v35: bool,
    /// For v3.5: the original framed LZ4 dat body `[decSize][encSize][block]`, kept so an
    /// unmodified database re-emits byte-exact.
    pub dat_packed: Option<Vec<u8>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DbType {
    // Project side.
    pub name: WStr,
    pub fields: Vec<DbField>,
    pub data: Vec<DbData>,
    pub description: WStr,
    pub field_type_list_size: u32,
    /// Padding bytes after the per-field type bytes (`field_type_list_size - fields.len()`).
    pub field_type_pad: Vec<u8>,
    // Dat side.
    pub dat_unknown1: u32,
    pub dat_fields_size: u32,
    /// Present only when `dat_unknown1 == STRING_INDICATOR`.
    pub dat_unknown2: Option<WStr>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DbField {
    // project side
    pub name: WStr,
    pub type_byte: u8,
    pub unknown1: WStr,
    pub string_args: Vec<WStr>,
    pub args: Vec<u32>,
    pub default_value: u32,
    // dat side
    pub index_info: u32,
}

impl DbField {
    /// True if this field stores a string value (its `index_info` is in the string range).
    /// Determines whether a data row reads from `string_values` or `int_values`.
    pub fn is_string(&self) -> bool {
        self.index_info >= STRING_START
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DbData {
    pub name: WStr,
    pub int_values: Vec<u32>,
    pub string_values: Vec<WStr>,
}

impl Database {
    pub fn read(project_bytes: &[u8], dat_bytes: &[u8]) -> Result<Self> {
        // --- dat header ---
        let mut rd = Reader::new(dat_bytes);
        let dat_indicator = rd.read_u8()?;
        if dat_indicator != 0 {
            return Err(Error::invalid(
                "database .dat is encrypted (indicator != 0); decrypt with wolf-archive first",
            ));
        }
        let magic_vec = rd.read_bytes(MAGIC_LEN)?;
        if magic_vec[0] != 0x57 || magic_vec[6] != 0x46 || magic_vec[7] != 0x4D {
            return Err(Error::invalid("not a database .dat (magic mismatch)"));
        }
        let mut dat_magic = [0u8; MAGIC_LEN];
        dat_magic.copy_from_slice(&magic_vec);
        let utf8 = dat_magic[UTF8_MARKER_INDEX] == b'U';
        let dat_version = rd.read_u8()?;
        let v35 = dat_version == 0xC4;
        let _ = Ctx { utf8, v35 };

        // For v3.5 the dat type/data section after the version byte is an LZ4 block.
        // Decompress it and read the values from the result. The `.project` is plain.
        let rem = rd.remaining();
        let (dat_packed, dat_body): (Option<Vec<u8>>, Vec<u8>) = if v35 {
            let framed = rd.read_bytes(rem)?;
            let body = lz4::unpack(&framed)?;
            (Some(framed), body)
        } else {
            (None, rd.read_bytes(rem)?)
        };
        let mut rd = Reader::new(&dat_body);

        // --- project (schema) ---
        let mut rp = Reader::new(project_bytes);
        let type_cnt = rp.read_u32()? as usize;
        let mut types = Vec::with_capacity(type_cnt);
        for _ in 0..type_cnt {
            types.push(DbType::read_project(&mut rp)?);
        }
        if !rp.is_eof() {
            return Err(Error::invalid("database .project has trailing data"));
        }

        // --- dat body (values) ---
        let dat_type_cnt = rd.read_u32()? as usize;
        if dat_type_cnt != types.len() {
            return Err(Error::invalid(format!(
                "database type count mismatch: project {} vs dat {}",
                types.len(),
                dat_type_cnt
            )));
        }
        for t in &mut types {
            t.read_dat(&mut rd)?;
        }
        let terminator = rd.read_u8()?;
        if terminator != dat_version {
            return Err(Error::invalid(format!(
                "database .dat terminator 0x{terminator:02x} != version 0x{dat_version:02x}"
            )));
        }
        if !rd.is_eof() {
            return Err(Error::invalid("database .dat has trailing data"));
        }

        Ok(Database {
            dat_indicator,
            dat_magic,
            dat_version,
            utf8,
            types,
            v35,
            dat_packed,
        })
    }

    /// Returns `(project_bytes, dat_bytes)`.
    pub fn write(&self) -> (Vec<u8>, Vec<u8>) {
        let mut wp = Writer::new();
        wp.write_u32(self.types.len() as u32);
        for t in &self.types {
            t.write_project(&mut wp);
        }

        let mut wd = Writer::new();
        wd.write_u8(self.dat_indicator);
        wd.write_bytes(&self.dat_magic);
        wd.write_u8(self.dat_version);

        // The compressible dat body: type count + per-type values + terminator.
        let mut body = Writer::new();
        body.write_u32(self.types.len() as u32);
        for t in &self.types {
            t.write_dat(&mut body);
        }
        body.write_u8(self.dat_version);
        let body = body.into_bytes();

        if self.v35 {
            // Re-emit original packed bytes verbatim when unchanged (byte-exact). Else
            // compress fresh (valid LZ4, content-exact).
            match &self.dat_packed {
                Some(orig) if lz4::unpack(orig).map(|b| b == body).unwrap_or(false) => {
                    wd.write_bytes(orig);
                }
                _ => wd.write_bytes(&lz4::pack(&body)),
            }
        } else {
            wd.write_bytes(&body);
        }

        (wp.into_bytes(), wd.into_bytes())
    }
}

/// True if a database `.dat` carries the `W..OL.FM` container magic (`indicator 0` + magic).
/// The legacy `SysDataBaseBasic.dat` (Wolf 2.x) does not. See [`BasicDatabase`].
pub fn dat_has_db_magic(dat_bytes: &[u8]) -> bool {
    dat_bytes.len() >= 9
        && dat_bytes[0] == 0
        && dat_bytes[1] == 0x57
        && dat_bytes[7] == 0x46
        && dat_bytes[8] == 0x4D
}

/// The legacy "basic system database" (`SysDataBaseBasic`, Wolf 2.x). Both halves predate the
/// modern serialization. The `.dat` has no `W..OL.FM` container magic, and the `.project` uses
/// an older field-metadata layout. It is an editor template, never referenced by command
/// operands (the real `SysDatabase` is the system DB), so reversing its older schema buys no
/// modding value. Both halves are carried verbatim. That keeps the pair byte-exact through a
/// repack and never errors, consistent with the toolchain's "unknown bytes preserved" contract.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BasicDatabase {
    pub project_raw: Vec<u8>,
    pub dat_raw: Vec<u8>,
}

impl BasicDatabase {
    pub fn read(project_bytes: &[u8], dat_bytes: &[u8]) -> Result<Self> {
        // A light sanity check so this isn't an accept-anything passthrough. The `.dat` must
        // lack the container magic (else it is a normal `Database`), and the `.project` must
        // start with a plausible type count.
        if dat_has_db_magic(dat_bytes) {
            return Err(Error::invalid(
                "SysDataBaseBasic .dat has DB magic; read it as a normal Database",
            ));
        }
        let type_cnt = Reader::new(project_bytes).read_u32()?;
        if type_cnt > 10_000 {
            return Err(Error::invalid(
                "basic database .project type count implausible",
            ));
        }
        Ok(BasicDatabase {
            project_raw: project_bytes.to_vec(),
            dat_raw: dat_bytes.to_vec(),
        })
    }

    /// Returns `(project_bytes, dat_bytes)`, both carried verbatim.
    pub fn write(&self) -> (Vec<u8>, Vec<u8>) {
        (self.project_raw.clone(), self.dat_raw.clone())
    }
}

impl DbType {
    fn read_project(r: &mut Reader) -> Result<Self> {
        let name = r.read_string()?;

        let field_cnt = r.read_u32()? as usize;
        let mut fields = Vec::with_capacity(field_cnt);
        for _ in 0..field_cnt {
            fields.push(DbField {
                name: r.read_string()?,
                type_byte: 0,
                unknown1: WStr::default(),
                string_args: Vec::new(),
                args: Vec::new(),
                default_value: 0,
                index_info: 0,
            });
        }

        let data_cnt = r.read_u32()? as usize;
        let mut data = Vec::with_capacity(data_cnt);
        for _ in 0..data_cnt {
            data.push(DbData {
                name: r.read_string()?,
                int_values: Vec::new(),
                string_values: Vec::new(),
            });
        }

        let description = r.read_string()?;

        let field_type_list_size = r.read_u32()?;
        for f in &mut fields {
            f.type_byte = r.read_u8()?;
        }
        let pad_len = (field_type_list_size as usize)
            .checked_sub(fields.len())
            .ok_or_else(|| Error::invalid("field_type_list_size smaller than field count"))?;
        let field_type_pad = r.read_bytes(pad_len)?;

        // Per-field metadata blocks. Each is preceded by a count that (for well-formed
        // databases) equals the field count.
        read_indexed(r, fields.len(), "unknown1", |r, i| {
            fields[i].unknown1 = r.read_string()?;
            Ok(())
        })?;
        read_indexed(r, fields.len(), "stringArgs", |r, i| {
            fields[i].string_args = r.read_string_array()?;
            Ok(())
        })?;
        read_indexed(r, fields.len(), "args", |r, i| {
            fields[i].args = r.read_int_array()?;
            Ok(())
        })?;
        read_indexed(r, fields.len(), "defaultValue", |r, i| {
            fields[i].default_value = r.read_u32()?;
            Ok(())
        })?;

        Ok(DbType {
            name,
            fields,
            data,
            description,
            field_type_list_size,
            field_type_pad,
            dat_unknown1: 0,
            dat_fields_size: 0,
            dat_unknown2: None,
        })
    }

    fn write_project(&self, w: &mut Writer) {
        w.write_string(&self.name);
        w.write_u32(self.fields.len() as u32);
        for f in &self.fields {
            w.write_string(&f.name);
        }
        w.write_u32(self.data.len() as u32);
        for d in &self.data {
            w.write_string(&d.name);
        }
        w.write_string(&self.description);

        w.write_u32(self.field_type_list_size);
        for f in &self.fields {
            w.write_u8(f.type_byte);
        }
        w.write_bytes(&self.field_type_pad);

        w.write_u32(self.fields.len() as u32);
        for f in &self.fields {
            w.write_string(&f.unknown1);
        }
        w.write_u32(self.fields.len() as u32);
        for f in &self.fields {
            w.write_string_array(&f.string_args);
        }
        w.write_u32(self.fields.len() as u32);
        for f in &self.fields {
            w.write_int_array(&f.args);
        }
        w.write_u32(self.fields.len() as u32);
        for f in &self.fields {
            w.write_u32(f.default_value);
        }
    }

    fn read_dat(&mut self, r: &mut Reader) -> Result<()> {
        r.verify(&TYPE_SEPARATOR, "database type separator")?;
        self.dat_unknown1 = r.read_u32()?;
        self.dat_fields_size = r.read_u32()?;
        if self.dat_unknown1 == STRING_INDICATOR {
            self.dat_unknown2 = Some(r.read_string()?);
        }

        let fields_size = self.dat_fields_size as usize;
        if fields_size > self.fields.len() {
            return Err(Error::invalid(format!(
                "dat fields_size {} exceeds project field count {}",
                fields_size,
                self.fields.len()
            )));
        }
        for f in self.fields.iter_mut().take(fields_size) {
            f.index_info = r.read_u32()?;
        }

        let data_size = r.read_u32()? as usize;
        if self.data.len() > data_size {
            self.data.truncate(data_size);
        }
        if data_size > self.data.len() {
            return Err(Error::invalid(format!(
                "dat data_size {} exceeds project data count {}",
                data_size,
                self.data.len()
            )));
        }

        let int_cnt = self
            .fields
            .iter()
            .take(fields_size)
            .filter(|f| !f.is_string())
            .count();
        let str_cnt = fields_size - int_cnt;

        for datum in &mut self.data {
            datum.int_values = Vec::with_capacity(int_cnt);
            for _ in 0..int_cnt {
                datum.int_values.push(r.read_u32()?);
            }
            datum.string_values = Vec::with_capacity(str_cnt);
            for _ in 0..str_cnt {
                datum.string_values.push(r.read_string()?);
            }
        }
        Ok(())
    }

    fn write_dat(&self, w: &mut Writer) {
        w.write_bytes(&TYPE_SEPARATOR);
        w.write_u32(self.dat_unknown1);
        w.write_u32(self.dat_fields_size);
        if self.dat_unknown1 == STRING_INDICATOR {
            // Always present in this branch. Default to an empty string if somehow missing.
            let s = self.dat_unknown2.clone().unwrap_or_default();
            w.write_string(&s);
        }
        let fields_size = self.dat_fields_size as usize;
        for f in self.fields.iter().take(fields_size) {
            w.write_u32(f.index_info);
        }
        w.write_u32(self.data.len() as u32);
        for datum in &self.data {
            for &v in &datum.int_values {
                w.write_u32(v);
            }
            for s in &datum.string_values {
                w.write_string(s);
            }
        }
    }
}

/// Read a `count`-prefixed metadata block. Reads the stored count and applies it to
/// `fields[0..count]`. Guards against the count exceeding the field vector.
fn read_indexed(
    r: &mut Reader,
    field_count: usize,
    label: &str,
    mut apply: impl FnMut(&mut Reader, usize) -> Result<()>,
) -> Result<()> {
    let n = r.read_u32()? as usize;
    if n > field_count {
        return Err(Error::invalid(format!(
            "database project '{label}' count {n} exceeds field count {field_count}"
        )));
    }
    for i in 0..n {
        apply(r, i)?;
    }
    Ok(())
}
