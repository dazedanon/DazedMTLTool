//! Project-level name glossary. A cross-file, consistency-preserving translation of the database
//! names a Wolf game looks rows up by.
//!
//! A command like `UDB[Monster]["ブルノエール"].Graphic` resolves a row by its name, and that name
//! is mirrored in three or more independent places that must translate together or the lookup
//! breaks (returns -1 or hits the wrong row):
//!   1. The DB name/display field value (the row's `名前`, `表示名`, nickname, or element name).
//!   2. The stored row name ([`DbData::name`](wolf_formats::database::DbData), the `.project`
//!      half).
//!   3. Every command by-name reference: `cid250/252` dataName (str index 2), `cid251` dataName
//!      (str index 1), and `cid112` StringCondition comparison literals (any str).
//!
//! The per-file [`crate::strings`] extract/inject path translates each of these independently, so
//! a translator could rename a row's display field without the row name and by-name references
//! following, silently breaking the lookup. This module instead builds one `source -> text` map
//! from the whole data dir and applies it to all mirrors at once, keeping them consistent.
//!
//! Control-code preservation, drift guarding, and encoding checks reuse the existing
//! [`crate::strings::write_translation`] path.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::fmt::Write as _; // `write!`/`writeln!` into a String.

use serde_json::Value;
use wolf_formats::command::RawCommand;
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::database::{Database, DbType};
use wolf_formats::map::Map;
use wolf_formats::WStr;

use crate::json::value_slots;
use crate::strings::{
    db_field_role, has_translatable_text, value_is_asset_path, write_translation, InjectOptions,
    InjectStats, Role,
};
use crate::text::decode_wstr;

// ----------------------------------------------------------------------------
// Name / display field detection (general, not hardcoded per game)
// ----------------------------------------------------------------------------

/// A string field whose values are single-string names the game may look rows up by, so they must
/// stay consistent with the row name and every by-name reference. General, not a per-game
/// allowlist. It is exactly the cells the role classifier assigns [`Role::Name`].
///
/// This is the glossary's half of the disjoint split. It owns name cells, while the per-file
/// `db-strings` path owns description/dialogue content cells ([`Role::Content`]). Because
/// [`db_field_role`] assigns each cell exactly one role, no DB string cell is extracted by both
/// paths, which removes the hazard of a name being translated to two different values.
///
/// A cell is a name when [`db_field_role`] returns [`Role::Name`]: the type's first string field
/// (the canonical row-name column that `UDB[type][name]` reads, even with an empty or unrecognised
/// label), or a recognised name field or type (`名前`, `愛称`, `呼び方`, the `移動名`
/// location-banner key, and so on). A description/dialogue field is [`Role::Content`], owned by the
/// per-file path and independently translatable. An internal field is [`Role::Internal`]. Neither
/// is a name. The on-screen `移動名` location banner classifies as a name, since the consistency
/// machinery covers its by-name-key usage. A genuine internal field never does.
fn name_display_field(
    type_byte: u8,
    type_name: &str,
    field_jp: &str,
    field_en: &str,
    is_first_string: bool,
) -> bool {
    db_field_role(type_byte, type_name, field_jp, field_en, is_first_string) == Role::Name
}

/// The name/display fields of a type: `(field_idx, string_slot, type_byte, field_jp)` for each
/// field [`name_display_field`] keeps, in field order. `glossary` powers the EN field-name
/// matching.
fn name_fields(t: &DbType, utf8: bool, glossary: &HashMap<String, String>) -> Vec<(usize, usize, u8, String)> {
    let type_name = decode_wstr(&t.name, utf8);
    let fields_size = (t.dat_fields_size as usize).min(t.fields.len());
    let slots = value_slots(t, fields_size, utf8);
    let mut seen_string = false;
    let mut out = Vec::new();
    for (fi, (_, is_str, slot)) in slots.iter().enumerate() {
        if !is_str {
            continue;
        }
        let is_first_string = !seen_string;
        seen_string = true;
        let fjp = decode_wstr(&t.fields[fi].name, utf8);
        let fen = glossary.get(&fjp).map(String::as_str).unwrap_or(&fjp);
        let tb = t.fields[fi].type_byte;
        if name_display_field(tb, &type_name, &fjp, fen, is_first_string) {
            out.push((fi, *slot, tb, fjp));
        }
    }
    out
}

/// A single name/display cell value, with the per-cell asset-path exclusion applied. Returns the
/// decoded value only when it is a translatable name. Skips empty, pure-code, and folder-picker
/// paths.
fn name_cell_value(row: &wolf_formats::database::DbData, slot: usize, tb: u8, utf8: bool) -> Option<String> {
    let v = row.string_values.get(slot).map(|w| decode_wstr(w, utf8))?;
    if !has_translatable_text(&v) {
        return None;
    }
    if tb == 1 && value_is_asset_path(&v) {
        return None;
    }
    Some(v)
}

/// The glossary's per-cell name extraction of a database, as `(type_idx, row_idx, field_idx)` for
/// every string cell the glossary owns (a [`name_display_field`] cell with a translatable name
/// value). The stored row name (`DbData.name`) is not a field cell, so it carries no
/// `(type,row,field)` locator and is not in this set.
///
/// This is the glossary's side of the disjointness invariant. It must share no `(type,row,field)`
/// with [`crate::strings::extract_db_strings`]'s output, since every DB string cell has exactly
/// one [`crate::strings::Role`].
pub fn extract_db_name_cells(
    db: &Database,
    glossary: &HashMap<String, String>,
) -> Vec<(usize, usize, usize)> {
    let utf8 = db.utf8;
    let mut out = Vec::new();
    for (ti, t) in db.types.iter().enumerate() {
        let fields = name_fields(t, utf8, glossary);
        for (ri, row) in t.data.iter().enumerate() {
            for (fi, slot, tb, _) in &fields {
                if name_cell_value(row, *slot, *tb, utf8).is_some() {
                    out.push((ti, ri, *fi));
                }
            }
        }
    }
    out
}

// ----------------------------------------------------------------------------
// By-name command references (cid 250/252 str2, cid 251 str1, cid 112 any str)
// ----------------------------------------------------------------------------

/// The string-arg indices of a command that are DB by-name references: a data name a lookup
/// resolves, or a name compared in a StringCondition. Empty means none.
fn dbref_str_indices(cmd: &RawCommand) -> Vec<usize> {
    match cmd.cid {
        // DB read/write by name: str index 2 is the data (row) name operand.
        250 | 252 => vec![2],
        // DB-string read by name: str index 1 is the data (row) name operand.
        251 => vec![1],
        // StringCondition: any string operand may be a name compared against a row name.
        112 => (0..cmd.str_args.len()).collect(),
        _ => vec![],
    }
}

/// Visit every by-name reference string in a command list, calling `f(cmd_idx, str_idx, value)`.
fn for_each_dbref(cmds: &[RawCommand], utf8: bool, mut f: impl FnMut(usize, usize, &str)) {
    for (ci, cmd) in cmds.iter().enumerate() {
        for si in dbref_str_indices(cmd) {
            let Some(w) = cmd.str_args.get(si) else {
                continue;
            };
            let v = decode_wstr(w, utf8);
            if !v.is_empty() {
                f(ci, si, &v);
            }
        }
    }
}

// ----------------------------------------------------------------------------
// Extraction: collect the unique candidate name strings across the data dir
// ----------------------------------------------------------------------------

/// One candidate name in the glossary: the `source` string (its `text` starts equal, the
/// translator edits `text`), how many places it occurs across the corpus, and a short hint.
struct NameEntry {
    source: String,
    occurrences: usize,
    /// A short note: the originating DB type name (the first one observed), for context.
    note: String,
}

/// Accumulator. Per unique source string, its occurrence count and a note (the first type seen).
#[derive(Default)]
struct NameAcc {
    /// source -> occurrence count.
    counts: BTreeMap<String, usize>,
    /// source -> note (originating type name, kept from the first DB cell or row name seen).
    notes: BTreeMap<String, String>,
    /// Sources that qualified as a candidate (a DB name/display value or a stored row name). A
    /// by-name command reference only counts toward an existing candidate. It never introduces a
    /// new one. A reference to a name that exists in no DB is dead and untranslatable.
    candidates: BTreeSet<String>,
}

impl NameAcc {
    /// Register a DB-sourced candidate (row name or name/display cell value). It becomes a
    /// glossary entry and the occurrence is counted. `note` is the originating type name.
    fn add_candidate(&mut self, s: &str, note: &str) {
        self.candidates.insert(s.to_string());
        *self.counts.entry(s.to_string()).or_default() += 1;
        self.notes
            .entry(s.to_string())
            .or_insert_with(|| note.to_string());
    }

    /// Count a by-name reference occurrence. Does not introduce a new candidate.
    fn count_ref(&mut self, s: &str) {
        if self.candidates.contains(s) {
            *self.counts.entry(s.to_string()).or_default() += 1;
        }
    }
}

/// Collect candidate names from one database: every non-empty stored row name, and every
/// translatable name/display cell value.
fn collect_db_candidates(acc: &mut NameAcc, db: &Database, glossary: &HashMap<String, String>) {
    let utf8 = db.utf8;
    for t in &db.types {
        let type_name = decode_wstr(&t.name, utf8);
        let fields = name_fields(t, utf8, glossary);
        for row in &t.data {
            let row_name = decode_wstr(&row.name, utf8);
            if has_translatable_text(&row_name) {
                acc.add_candidate(&row_name, &type_name);
            }
            for (_, slot, tb, _) in &fields {
                if let Some(v) = name_cell_value(row, *slot, *tb, utf8) {
                    acc.add_candidate(&v, &type_name);
                }
            }
        }
    }
}

/// Build the project name glossary JSON over a whole data dir: the parsed databases, an optional
/// common-events file, and the parsed maps. `glossary` (JP to EN) powers EN field-name matching.
///
/// The result is a `{ "kind":"names", "names":[ {source,text,occurrences,note}, ... ] }` document
/// where `text == source` initially and the translator edits `text`. Sources are deduplicated by
/// exact value and sorted deterministically by source string, so re-running on the same corpus
/// yields byte-identical output.
pub fn extract_names(
    dbs: &[Database],
    ces: &[&CommonEventsFile],
    maps: &[Map],
    glossary: &HashMap<String, String>,
) -> String {
    let mut acc = NameAcc::default();
    // Pass 1: candidates from every DB (row names and name/display cell values).
    for db in dbs {
        collect_db_candidates(&mut acc, db, glossary);
    }
    // Pass 2: count by-name references in command streams against the candidate set.
    for ce in ces {
        for ev in &ce.events {
            for_each_dbref(&ev.commands, ce.utf8, |_, _, v| acc.count_ref(v));
        }
    }
    for map in maps {
        for ev in &map.events {
            for page in &ev.pages {
                for_each_dbref(&page.commands, map.utf8, |_, _, v| acc.count_ref(v));
            }
        }
    }

    // Materialise the sorted, deduped entry list. `candidates` is a BTreeSet so iteration is
    // already in deterministic source order. Skip anything that fails the translatable filter.
    // Candidates already passed it, but row names from a denylist-only path could slip a
    // pure-symbol value through.
    let mut entries: Vec<NameEntry> = Vec::with_capacity(acc.candidates.len());
    for source in &acc.candidates {
        if !has_translatable_text(source) {
            continue;
        }
        entries.push(NameEntry {
            source: source.clone(),
            occurrences: acc.counts.get(source).copied().unwrap_or(0),
            note: acc.notes.get(source).cloned().unwrap_or_default(),
        });
    }

    names_to_json(&entries)
}

/// Render the collected name entries as the names-glossary JSON. `text` starts equal to `source`.
fn names_to_json(entries: &[NameEntry]) -> String {
    let mut s = String::new();
    s.push_str("{\n");
    s.push_str("  \"kind\": \"names\",\n");
    let _ = writeln!(s, "  \"count\": {},", entries.len());
    s.push_str("  \"names\": [\n");
    for (i, e) in entries.iter().enumerate() {
        let _ = write!(
            s,
            "    {{\"source\": {}, \"text\": {}, \"occurrences\": {}, \"note\": {}}}",
            jstr(&e.source),
            jstr(&e.source),
            e.occurrences,
            jstr(&e.note),
        );
        s.push_str(if i + 1 == entries.len() { "\n" } else { ",\n" });
    }
    s.push_str("  ]\n}\n");
    s
}

// ----------------------------------------------------------------------------
// Injection: apply the glossary consistently across all name mirrors
// ----------------------------------------------------------------------------

/// Parse a names-glossary JSON into a `source -> text` map, keeping only entries whose `text`
/// actually differs from `source`. An untranslated entry is a no-op everywhere.
fn parse_name_map(json: &str) -> Result<HashMap<String, String>, String> {
    let root: Value = serde_json::from_str(json).map_err(|e| format!("invalid JSON: {e}"))?;
    let arr = root
        .get("names")
        .and_then(Value::as_array)
        .ok_or("names JSON has no `names` array")?;
    let mut map = HashMap::new();
    for e in arr {
        let source = e.get("source").and_then(Value::as_str).unwrap_or("");
        let text = e.get("text").and_then(Value::as_str).unwrap_or(source);
        if source.is_empty() || text == source {
            continue;
        }
        map.insert(source.to_string(), text.to_string());
    }
    Ok(map)
}

/// Apply a name translation to a single `WStr` cell when it currently equals a mapped source.
/// Reuses [`write_translation`] so the control-code, drift, and encoding guards are identical to
/// the player-text path. The cell's current decoded value is the drift base, so an
/// already-translated or unrelated cell is left byte-exact and counted as `drifted`.
fn apply_to_cell(
    cell: &mut WStr,
    map: &HashMap<String, String>,
    utf8: bool,
    opts: &InjectOptions,
    stats: &mut InjectStats,
    locator: &dyn Fn() -> String,
) {
    let cur = decode_wstr(cell, utf8);
    let Some(text) = map.get(&cur) else {
        return;
    };
    // `cur` is the source (it equals the map key) and `text` differs, since parse_name_map
    // dropped no-ops. This is always a real edit attempt. The guards decide if it lands.
    write_translation(cell, &cur, text, utf8, opts, stats, locator);
}

/// Apply the project name glossary across a whole data dir, consistently. The same `source ->
/// text` is written to (a) every stored row name, (b) every name/display cell value, and (c)
/// every by-name command reference (`cid250/252` str2, `cid251` str1, `cid112` strings) that
/// currently equals a source. Every write is drift, control-code, and encoding guarded via the
/// shared [`write_translation`]. Untouched cells keep their exact bytes, so each file
/// re-serializes byte-exact except for the translated names.
///
/// `dbs`, `ces`, and `maps` are the mutable parsed files of the dir, in any order. The caller
/// writes them back out and re-parses. Returns the aggregate [`InjectStats`].
pub fn inject_names(
    names_json: &str,
    dbs: &mut [Database],
    ces: &mut [&mut CommonEventsFile],
    maps: &mut [Map],
    opts: &InjectOptions,
    glossary: &HashMap<String, String>,
) -> Result<InjectStats, String> {
    let map = parse_name_map(names_json)?;
    let mut stats = InjectStats::default();
    if map.is_empty() {
        return Ok(stats);
    }

    // (a) and (b) Databases: stored row names and name/display cell values.
    for (di, db) in dbs.iter_mut().enumerate() {
        let utf8 = db.utf8;
        for (ti, t) in db.types.iter_mut().enumerate() {
            // Recompute the keep-set on an immutable borrow before mutating rows.
            let fields = name_fields(t, utf8, glossary);
            for (ri, row) in t.data.iter_mut().enumerate() {
                // (a) Row name.
                apply_to_cell(&mut row.name, &map, utf8, opts, &mut stats, &|| {
                    format!("db {di} type {ti} row {ri} name")
                });
                // (b) Name/display cell values.
                for (fi, slot, tb, _) in &fields {
                    // Re-apply the per-cell asset-path exclusion. A folder-picker path is never a
                    // name, even if its exact text somehow collided with a mapped source.
                    if *tb == 1 {
                        let cur = row
                            .string_values
                            .get(*slot)
                            .map(|w| decode_wstr(w, utf8))
                            .unwrap_or_default();
                        if value_is_asset_path(&cur) {
                            continue;
                        }
                    }
                    if let Some(cell) = row.string_values.get_mut(*slot) {
                        apply_to_cell(cell, &map, utf8, opts, &mut stats, &|| {
                            format!("db {di} type {ti} row {ri} field {fi}")
                        });
                    }
                }
            }
        }
    }

    // (c) By-name command references in common events.
    for (ei, ce) in ces.iter_mut().enumerate() {
        let utf8 = ce.utf8;
        for (evi, ev) in ce.events.iter_mut().enumerate() {
            apply_dbrefs(&mut ev.commands, &map, utf8, opts, &mut stats, &|ci, si| {
                format!("ce {ei} event {evi} cmd {ci} str {si}")
            });
        }
    }
    // (c) By-name command references in maps.
    for (mi, map_file) in maps.iter_mut().enumerate() {
        let utf8 = map_file.utf8;
        for (evi, ev) in map_file.events.iter_mut().enumerate() {
            for (pi, page) in ev.pages.iter_mut().enumerate() {
                apply_dbrefs(&mut page.commands, &map, utf8, opts, &mut stats, &|ci, si| {
                    format!("map {mi} event {evi} page {pi} cmd {ci} str {si}")
                });
            }
        }
    }

    Ok(stats)
}

/// Apply the name map to the by-name reference strings of a command list.
fn apply_dbrefs(
    cmds: &mut [RawCommand],
    map: &HashMap<String, String>,
    utf8: bool,
    opts: &InjectOptions,
    stats: &mut InjectStats,
    locator: &dyn Fn(usize, usize) -> String,
) {
    for (ci, cmd) in cmds.iter_mut().enumerate() {
        for si in dbref_str_indices(cmd) {
            if let Some(cell) = cmd.str_args.get_mut(si) {
                apply_to_cell(cell, map, utf8, opts, stats, &|| locator(ci, si));
            }
        }
    }
}

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

// ----------------------------------------------------------------------------
// Name-consistency conflict check (across translation JSONs)
// ----------------------------------------------------------------------------

/// One detected name-translation conflict: a single glossary name source that was given two or
/// more distinct non-identity translations across the loaded translation files. This is the exact
/// hazard the disjoint-ownership split prevents at extraction time. The check catches a residual
/// conflict that slipped in by hand, such as an old db-strings edit kept alongside the glossary.
pub struct Conflict {
    /// The source name string (an exact, full-string `names.json` entry).
    pub source: String,
    /// The divergent translations, each with the files that used it, sorted and deduped.
    pub variants: Vec<ConflictVariant>,
}

/// One divergent translation of a conflicting source, with where it came from.
pub struct ConflictVariant {
    pub text: String,
    /// Names of the files that translated the source to this `text`, sorted and deduped.
    pub files: Vec<String>,
}

/// Pull every `(source, text)` pair out of one parsed translation JSON, regardless of its shape.
/// The names, db, scenes, and gamedat documents all carry `source` and `text` leaves at various
/// depths. Recurse generically: any object that has both a string `source` and a string `text` is
/// a pair. This keeps the check robust to all the document kinds without re-encoding each schema.
fn collect_source_text_pairs(v: &Value, out: &mut Vec<(String, String)>) {
    match v {
        Value::Object(map) => {
            if let (Some(Value::String(s)), Some(Value::String(t))) =
                (map.get("source"), map.get("text"))
            {
                out.push((s.clone(), t.clone()));
            }
            for child in map.values() {
                collect_source_text_pairs(child, out);
            }
        }
        Value::Array(arr) => {
            for child in arr {
                collect_source_text_pairs(child, out);
            }
        }
        _ => {}
    }
}

/// The set of glossary name sources in one parsed JSON: every `source` of a `names.json` document
/// (`kind == "names"`, the `names` array). A non-names document contributes none. A db-strings
/// description source is content, never a name, so it can never define the glossary-name set.
fn collect_name_sources(v: &Value, out: &mut BTreeSet<String>) {
    if v.get("kind").and_then(Value::as_str) == Some("names") {
        if let Some(arr) = v.get("names").and_then(Value::as_array) {
            for e in arr {
                if let Some(s) = e.get("source").and_then(Value::as_str) {
                    if !s.is_empty() {
                        out.insert(s.to_string());
                    }
                }
            }
        }
    }
}

/// Check a set of loaded translation JSONs for name-translation conflicts: a glossary name (a
/// source that appears as a `names.json` entry) that is translated to two or more distinct
/// non-identity `text` values across the files.
///
/// Semantics, deliberately strict:
///   * The glossary-name set is the union of every `names.json`'s `source` values.
///   * Across all files (names, db-strings, scenes, gamedat), every `(source, text)` pair whose
///     `source` is an exact full-string match for a glossary name and whose `text != source` (a
///     real edit) is collected. No substring matching. A name appearing inside a dialogue
///     sentence is a different `source` string and is not a conflict.
///   * A source with two or more distinct `text` values is a conflict.
///
/// `files` is `(display-name, json-text)`. An unparseable file is skipped. Errors are ignored
/// here so one bad file cannot mask the rest. Returns the conflicts sorted by source for stable
/// output.
pub fn check_name_conflicts(files: &[(String, &str)]) -> Vec<Conflict> {
    // Parse once, keeping (name, value) for the parseable files.
    let parsed: Vec<(&str, Value)> = files
        .iter()
        .filter_map(|(name, json)| serde_json::from_str::<Value>(json).ok().map(|v| (name.as_str(), v)))
        .collect();

    // (1) The glossary-name set is every names.json source.
    let mut name_sources: BTreeSet<String> = BTreeSet::new();
    for (_, v) in &parsed {
        collect_name_sources(v, &mut name_sources);
    }

    // (2) source -> text -> set of files that used it. Only sources that are glossary names, only
    // non-identity edits. BTreeMap and BTreeSet keep the output deterministic.
    let mut by_source: BTreeMap<String, BTreeMap<String, BTreeSet<String>>> = BTreeMap::new();
    for (name, v) in &parsed {
        let mut pairs = Vec::new();
        collect_source_text_pairs(v, &mut pairs);
        for (source, text) in pairs {
            if source == text {
                continue; // identity is untranslated, not a divergence.
            }
            if !name_sources.contains(&source) {
                continue; // not a glossary name, or not an exact full-string match.
            }
            by_source
                .entry(source)
                .or_default()
                .entry(text)
                .or_default()
                .insert((*name).to_string());
        }
    }

    // (3) A source with two or more distinct translations is a conflict.
    let mut conflicts = Vec::new();
    for (source, variants) in by_source {
        if variants.len() < 2 {
            continue;
        }
        let variants = variants
            .into_iter()
            .map(|(text, files)| ConflictVariant {
                text,
                files: files.into_iter().collect(),
            })
            .collect();
        conflicts.push(Conflict { source, variants });
    }
    conflicts
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn name_display_field_is_name_role_only() {
        // The glossary owns name cells only (Role::Name), disjoint from the db-strings content path.
        // The first string field is always a name, even with an empty or unknown label.
        assert!(name_display_field(0, "Monster", "", "", true));
        assert!(name_display_field(0, "Item", "謎ラベル", "謎ラベル", true));
        // A recognised name field (not first) is kept: a 愛称 nickname or 呼び方 element name.
        assert!(name_display_field(0, "Trainer", "愛称", "愛称", false));
        assert!(name_display_field(0, "Element", "呼び方", "呼び方", false));
        // `移動名` is a displayed location-banner name, so the glossary keeps it and the
        // consistency machinery covers its by-name-key usage.
        assert!(name_display_field(0, "Map", "日本語移動名", "Move Name", false));
        // A description/dialogue field is content, not a name. The db-strings path owns it, not
        // the glossary, so descriptions stay independently translatable even on the first column.
        assert!(!name_display_field(0, "Skill", "説明", "Description", false));
        assert!(!name_display_field(0, "Help", "説明", "Description", true));
        // An unlabeled or unrecognised non-first field defaults to content, so the glossary drops
        // it. The per-file path owns it, which is safer than forcing glossary consistency on an
        // unknown label.
        assert!(!name_display_field(0, "Misc", "謎ラベル", "謎ラベル", false));
        // Genuinely-internal fields are never names.
        assert!(!name_display_field(0, "Monster", "ファイル", "File", true));
        assert!(!name_display_field(0, "Skill", "戦闘背景画像", "Graphic", false));
        // Non-string type_byte never holds a string cell.
        assert!(!name_display_field(2, "Monster", "名前", "Name", true));
    }

    #[test]
    fn dbref_indices_match_prototype() {
        let mk = |cid: u32, nstr: usize| RawCommand {
            cid,
            int_args: vec![],
            indent: 0,
            str_args: (0..nstr).map(|_| WStr::from("x")).collect(),
            term: 0,
            move_route: None,
            v35_blob: None,
        };
        assert_eq!(dbref_str_indices(&mk(250, 4)), vec![2]);
        assert_eq!(dbref_str_indices(&mk(252, 4)), vec![2]);
        assert_eq!(dbref_str_indices(&mk(251, 3)), vec![1]);
        assert_eq!(dbref_str_indices(&mk(112, 3)), vec![0, 1, 2]);
        assert!(dbref_str_indices(&mk(101, 2)).is_empty());
    }

    #[test]
    fn parse_name_map_drops_noops() {
        let json = r#"{"kind":"names","names":[
            {"source":"A","text":"Alpha","occurrences":3,"note":"T"},
            {"source":"B","text":"B","occurrences":1,"note":"T"},
            {"source":"","text":"x","occurrences":0,"note":""}
        ]}"#;
        let m = parse_name_map(json).unwrap();
        assert_eq!(m.get("A").map(String::as_str), Some("Alpha"));
        assert!(!m.contains_key("B")); // text equals source
        assert!(!m.contains_key("")); // empty source
        assert_eq!(m.len(), 1);
    }

    #[test]
    fn names_json_is_deterministic_and_sorted() {
        let entries = vec![
            NameEntry { source: "ゼニ".into(), occurrences: 2, note: "Item".into() },
            NameEntry { source: "あ".into(), occurrences: 5, note: "Monster".into() },
        ];
        let json = names_to_json(&entries);
        assert!(json.contains("\"kind\": \"names\""));
        assert!(json.contains("\"occurrences\": 2"));
        // Both sources present. Rendering is stable for a given input order.
        assert!(json.contains("ゼニ") && json.contains("あ"));
        assert_eq!(json, names_to_json(&entries));
    }

    #[test]
    fn conflict_check_flags_divergent_name_only() {
        // A glossary names.json defines the name set. A db-strings file and the names file each
        // translate the same exact name differently, giving one conflict. A description with two
        // values is not a conflict since it is not a glossary name. Identity (text==source) is ignored.
        let names = r#"{"kind":"names","names":[
            {"source":"ブルノエール","text":"Brunoir","occurrences":3,"note":"Monster"},
            {"source":"毒","text":"Poison","occurrences":1,"note":"Status"}
        ]}"#;
        let db = r#"{"kind":"db","groups":[{"type":0,"typeName":"Monster","lines":[
            {"row":0,"field":0,"rowName":"x","fieldName":"Name","source":"ブルノエール","text":"Brunoire"},
            {"row":1,"field":3,"rowName":"x","fieldName":"Description","source":"説明テキスト","text":"Desc A"}
        ]}]}"#;
        let scenes = r#"{"kind":"map","scenes":[{"event":1,"lines":[
            {"cmd":0,"str":0,"speaker":"NPC","speaker_src":"x","source":"説明テキスト","text":"Desc B"},
            {"cmd":1,"str":0,"speaker":"UI","speaker_src":"x","source":"毒","text":"Poison"}
        ]}]}"#;
        let files = vec![
            ("names.json".to_string(), names),
            ("DataBase.db.json".to_string(), db),
            ("map.scenes.json".to_string(), scenes),
        ];
        let conflicts = check_name_conflicts(&files);
        // Exactly one conflict: ブルノエール to {Brunoir, Brunoire}. 説明テキスト diverges too but is
        // not a glossary name, so it is ignored. 毒 to Poison is consistent, identical everywhere.
        assert_eq!(conflicts.len(), 1, "only the divergent NAME is a conflict");
        let c = &conflicts[0];
        assert_eq!(c.source, "ブルノエール");
        let texts: Vec<&str> = c.variants.iter().map(|v| v.text.as_str()).collect();
        assert!(texts.contains(&"Brunoir") && texts.contains(&"Brunoire"));
        assert_eq!(c.variants.len(), 2);
    }

    #[test]
    fn conflict_check_consistent_is_empty() {
        // Same name translated identically everywhere means no conflict.
        let names = r#"{"kind":"names","names":[{"source":"剣","text":"Sword","occurrences":2,"note":"Item"}]}"#;
        let db = r#"{"kind":"db","groups":[{"type":0,"typeName":"Item","lines":[
            {"row":0,"field":0,"rowName":"x","fieldName":"Name","source":"剣","text":"Sword"}
        ]}]}"#;
        let files = vec![
            ("names.json".to_string(), names),
            ("DataBase.db.json".to_string(), db),
        ];
        assert!(check_name_conflicts(&files).is_empty());
    }

    #[test]
    fn conflict_check_substring_is_not_a_conflict() {
        // A name appearing inside a dialogue sentence is a different full-string source, so two
        // different sentence translations are not a name conflict. No substring matching.
        let names = r#"{"kind":"names","names":[{"source":"剣","text":"Sword","occurrences":1,"note":"Item"}]}"#;
        let scenes = r#"{"kind":"map","scenes":[{"event":1,"lines":[
            {"cmd":0,"str":0,"speaker":"x","speaker_src":"x","source":"剣を手に入れた","text":"Got a sword"},
            {"cmd":1,"str":0,"speaker":"x","speaker_src":"x","source":"剣を装備した","text":"Equipped a blade"}
        ]}]}"#;
        let files = vec![
            ("names.json".to_string(), names),
            ("map.scenes.json".to_string(), scenes),
        ];
        assert!(
            check_name_conflicts(&files).is_empty(),
            "a name inside a sentence is not an exact full-string match"
        );
    }
}
