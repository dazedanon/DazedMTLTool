//! Apply edits from a [`database_to_json`](crate::database_to_json) export back onto a
//! [`Database`], byte-exact. Only values (cell ints and strings) and row names are editable. The
//! schema (types, fields, kinds, counts, structure) is fixed and any change to it is rejected.
//! Unchanged cells are never re-encoded, so untouched rows re-serialize byte-identical via
//! [`Database::write`](wolf_formats::database::Database::write). Only the cells you actually
//! changed differ.

use std::collections::HashMap;

use serde_json::Value;
use wolf_formats::database::Database;

use crate::json::value_slots;
use crate::text::{decode_wstr, text_to_wstr};

/// Apply the edited JSON onto `db` in place. Returns the number of changed cells and names.
/// Errors on any schema or structure mismatch, an out-of-range id, an ambiguous field name, or a
/// value that cannot be encoded in the database's text encoding. On error, any edits committed
/// before the failure point remain applied.
pub fn apply_database_edit(json: &str, db: &mut Database) -> Result<usize, String> {
    let root: Value = serde_json::from_str(json).map_err(|e| format!("invalid JSON: {e}"))?;
    let utf8 = db.utf8;
    let types = root
        .get("types")
        .and_then(Value::as_array)
        .ok_or("edited JSON has no `types` array")?;

    let type_count = db.types.len();
    let mut changed = 0usize;
    for tj in types {
        let ti = json_id(tj, "type")?;
        let dt = db
            .types
            .get_mut(ti)
            .ok_or_else(|| format!("type id {ti} is out of range (base has {type_count} types)"))?;

        // Schema-integrity guard, only when the doc carries a `fields` array (a full export).
        // Edits are patch-style: a `rows` array may include just the rows you touched. Others are
        // left as-is, never deleted, and an out-of-range row id is rejected below.
        if let Some(fields) = tj.get("fields").and_then(Value::as_array) {
            if fields.len() != dt.fields.len() {
                return Err(format!(
                    "type {ti}: field count changed ({} edited vs {} base) - schema edits are not allowed",
                    fields.len(),
                    dt.fields.len()
                ));
            }
        }

        // Map each value key to (is_string, value-slot index), derived identically to the JSON
        // export (unique field name, else `#<fieldId>`), so the keys always match.
        let fields_size = (dt.dat_fields_size as usize).min(dt.fields.len());
        let by_key: HashMap<String, (bool, usize)> = value_slots(dt, fields_size, utf8)
            .into_iter()
            .map(|(k, is_str, slot)| (k, (is_str, slot)))
            .collect();

        let Some(rows) = tj.get("rows").and_then(Value::as_array) else {
            continue;
        };
        for rj in rows {
            let ri = json_id(rj, "row")?;
            let row = dt
                .data
                .get_mut(ri)
                .ok_or_else(|| format!("type {ti}: row id {ri} is out of range"))?;

            // Row display name lives in the .project half.
            if let Some(nm) = rj.get("name").and_then(Value::as_str) {
                if decode_wstr(&row.name, utf8) != nm {
                    row.name = text_to_wstr(nm, utf8)
                        .map_err(|e| format!("type {ti} row {ri} name: {e}"))?;
                    changed += 1;
                }
            }

            let Some(values) = rj.get("values").and_then(Value::as_object) else {
                continue;
            };
            for (key, val) in values {
                let &(is_str, slot) = by_key.get(key).ok_or_else(|| {
                    format!("type {ti} row {ri}: unknown/schema-only field {key:?}")
                })?;
                if is_str {
                    let new = val.as_str().ok_or_else(|| {
                        format!("type {ti} row {ri} field {key:?}: expected a string")
                    })?;
                    let cur = row
                        .string_values
                        .get(slot)
                        .map(|w| decode_wstr(w, utf8))
                        .unwrap_or_default();
                    // Skip unchanged cells to preserve the original bytes exactly. This avoids the
                    // empty-string and trailing-NUL re-encode ambiguity.
                    if cur != new {
                        let w = text_to_wstr(new, utf8)
                            .map_err(|e| format!("type {ti} row {ri} field {key:?}: {e}"))?;
                        *row.string_values.get_mut(slot).ok_or_else(|| {
                            format!("type {ti} row {ri} field {key:?}: value slot missing")
                        })? = w;
                        changed += 1;
                    }
                } else {
                    let new = val.as_i64().ok_or_else(|| {
                        format!("type {ti} row {ri} field {key:?}: expected a number")
                    })?;
                    let nv = new as u32;
                    let cell = row.int_values.get_mut(slot).ok_or_else(|| {
                        format!("type {ti} row {ri} field {key:?}: value slot missing")
                    })?;
                    if *cell != nv {
                        *cell = nv;
                        changed += 1;
                    }
                }
            }
        }
    }
    Ok(changed)
}

fn json_id(v: &Value, what: &str) -> Result<usize, String> {
    v.get("id")
        .and_then(Value::as_u64)
        .map(|n| n as usize)
        .ok_or_else(|| format!("{what} entry is missing its numeric `id`"))
}
