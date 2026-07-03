//! Human-readable JSON export of a [`Database`] (the tabular `.project` plus `.dat` data).
//!
//! Databases do not fit the WolfScript code view, so they export to JSON for inspection: each
//! type's schema (fields and kind) and its data rows, with each row's values mapped back to field
//! names. The byte-faithful [`wolf_formats::database::Database`] stays the round-trip authority.
//! This is a read-only projection for readability, with values shown as signed ints or decoded
//! strings.

use std::collections::HashMap;
use std::fmt::Write;

use wolf_formats::database::{Database, DbData, DbType};

use crate::text::decode_wstr;

/// Render a database as pretty-printed JSON. `kind` is a label such as `"UDB"`, `"CDB"`, or
/// `"SDB"`. `glossary` is the engine-text map (JP to EN). Every structural name it covers (a type
/// or field, and the variable-name rows of the System DB) gets a `"name_en"` field next to its
/// Japanese `"name"`, so a modder reading the English code can look the entry up in either
/// language. Player-facing content such as item and skill row names is absent from the glossary
/// and stays Japanese-only, which matches how it reads in the code.
pub fn database_to_json(db: &Database, kind: &str, glossary: &HashMap<String, String>) -> String {
    let utf8 = db.utf8;
    let mut s = String::new();
    s.push_str("{\n");
    s.push_str(&format!("  \"kind\": {},\n", jstr(kind)));
    s.push_str(&format!("  \"version\": \"0x{:02x}\",\n", db.dat_version));
    let enc = if utf8 { "UTF-8" } else { "Shift-JIS" };
    s.push_str(&format!("  \"encoding\": {},\n", jstr(enc)));
    s.push_str(&format!("  \"typeCount\": {},\n", db.types.len()));
    s.push_str("  \"types\": [\n");

    for (ti, t) in db.types.iter().enumerate() {
        type_to_json(&mut s, ti, t, utf8, glossary);
        s.push_str(if ti + 1 == db.types.len() {
            "\n"
        } else {
            ",\n"
        });
    }
    s.push_str("  ]\n}\n");
    s
}

/// Render `"name": "<jp>"`, plus `, "name_en": "<en>"` when the glossary translates it. Used for
/// every name field so the JSON is searchable in either language.
fn name_pair(jp: &str, glossary: &HashMap<String, String>) -> String {
    match glossary.get(jp) {
        Some(en) if en != jp => format!("{}, \"name_en\": {}", jstr(jp), jstr(en)),
        _ => jstr(jp),
    }
}

fn type_to_json(
    s: &mut String,
    id: usize,
    t: &DbType,
    utf8: bool,
    glossary: &HashMap<String, String>,
) {
    let fields_size = (t.dat_fields_size as usize).min(t.fields.len());
    s.push_str("    {\n");
    let _ = write!(s, "      \"id\": {id},\n");
    let _ = write!(
        s,
        "      \"name\": {},\n",
        name_pair(&decode_wstr(&t.name, utf8), glossary)
    );
    let _ = write!(
        s,
        "      \"description\": {},\n",
        jstr(&decode_wstr(&t.description, utf8))
    );

    // Schema fields: name (plus name_en) and kind. Only the first `fields_size` carry row data.
    s.push_str("      \"fields\": [");
    for (fi, f) in t.fields.iter().enumerate() {
        let kind = if f.is_string() { "string" } else { "int" };
        let has_data = fi < fields_size;
        let _ = write!(
            s,
            "{}{{\"id\": {fi}, \"name\": {}, \"kind\": {}{}}}",
            if fi == 0 { "" } else { ", " },
            name_pair(&decode_wstr(&f.name, utf8), glossary),
            jstr(kind),
            if has_data {
                ""
            } else {
                ", \"schemaOnly\": true"
            }
        );
    }
    s.push_str("],\n");

    // Data rows: id, name (plus name_en), and values mapped to field names.
    let _ = write!(s, "      \"rowCount\": {},\n", t.data.len());
    s.push_str("      \"rows\": [\n");
    for (di, d) in t.data.iter().enumerate() {
        row_to_json(s, di, t, d, fields_size, utf8, glossary);
        s.push_str(if di + 1 == t.data.len() { "\n" } else { ",\n" });
    }
    s.push_str("      ]\n    }");
}

/// The per-row value slots of a type, in on-disk order: `(jsonKey, is_string, slot_index)` for
/// each of the first `fields_size` fields. The key is the field's decoded name when that name is
/// unique within the type, else a stable `#<fieldId>`. That covers empty and duplicated names
/// such as formula columns. The slot index points into the row's `int_values` or `string_values`
/// (all int fields first, then all string fields). Shared by the JSON export and
/// [`crate::db_edit`] so the keys match exactly. `slot` indexes `string_values` when `is_string`,
/// otherwise `int_values`.
pub fn value_slots(t: &DbType, fields_size: usize, utf8: bool) -> Vec<(String, bool, usize)> {
    let mut counts: HashMap<String, u32> = HashMap::new();
    for fi in 0..fields_size {
        let n = decode_wstr(&t.fields[fi].name, utf8);
        if !n.is_empty() {
            *counts.entry(n).or_default() += 1;
        }
    }
    let (mut int_i, mut str_i) = (0usize, 0usize);
    let mut out = Vec::with_capacity(fields_size);
    for fi in 0..fields_size {
        let f = &t.fields[fi];
        let n = decode_wstr(&f.name, utf8);
        let key = if n.is_empty() || counts.get(&n).copied().unwrap_or(0) > 1 {
            format!("#{fi}")
        } else {
            n
        };
        let is_str = f.is_string();
        let slot = if is_str {
            let s = str_i;
            str_i += 1;
            s
        } else {
            let s = int_i;
            int_i += 1;
            s
        };
        out.push((key, is_str, slot));
    }
    out
}

fn row_to_json(
    s: &mut String,
    id: usize,
    t: &DbType,
    d: &DbData,
    fields_size: usize,
    utf8: bool,
    glossary: &HashMap<String, String>,
) {
    let _ = write!(
        s,
        "        {{\"id\": {id}, \"name\": {}",
        name_pair(&decode_wstr(&d.name, utf8), glossary)
    );
    s.push_str(", \"values\": {");
    let mut first = true;
    for (key, is_str, slot) in value_slots(t, fields_size, utf8) {
        if !first {
            s.push_str(", ");
        }
        first = false;
        if is_str {
            let v = d
                .string_values
                .get(slot)
                .map(|w| decode_wstr(w, utf8))
                .unwrap_or_default();
            let _ = write!(s, "{}: {}", jstr(&key), jstr(&v));
        } else {
            let v = d.int_values.get(slot).copied().unwrap_or(0) as i32;
            let _ = write!(s, "{}: {}", jstr(&key), v);
        }
    }
    s.push_str("}}");
}

/// JSON string literal with escaping.
fn jstr(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}
