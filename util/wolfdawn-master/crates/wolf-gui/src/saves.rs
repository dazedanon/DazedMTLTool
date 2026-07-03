//! The Saves section's data model and the headless logic behind it.
//!
//! A `.sav` bakes in the game *title* and player-facing *strings* (item / skill / mode names shown
//! on the save-load screen). After a fan translation those go stale: the translated build rejects a
//! save whose baked title does not match its own `Game.dat` title ("trying to load from another
//! game"), and the baked strings still read in the original language. This section refreshes both,
//! exactly as the CLI's `save-update` does, over either a single `.sav` or a whole save folder.
//!
//! This module owns everything *except* the egui rendering (which lives in `app.rs`), so the whole
//! workflow can be exercised headlessly in tests:
//!
//!   * [`inspect`] reads a `.sav` and calls the library's [`inspect_save`] to surface the format,
//!     encoding, baked title, and the editable baked-string list, the same records `update_save`
//!     can rewrite.
//!   * [`save_changes`] turns the user's edits (a possibly-changed title + the rows the user
//!     actually changed) into a `new_title` + `source->target` map, optionally backs up the
//!     original, then calls the library's [`update_save`] and writes the result.
//!   * [`batch_update`] mirrors the CLI's `cmd_save_update`: a new title (typed or read from a
//!     translated `Game.dat`) and/or a translation file/dir (turned into a `source->target` map via
//!     [`build_memory`], like the CLI), applied with `update_save` over every `*.sav` in a folder.
//!
//! Every codec is handled by `wolf_decompiler` (standard and GamePro Pro). An unsupported buffer is
//! reported and skipped, never written.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use wolf_decompiler::{
    build_memory, extract_game_dat, inspect_save, update_save, SaveFormat, SaveInfo,
    SaveUpdateStats,
};
use wolf_formats::game_dat::GameDat;

/// One editable baked string: the read-only `original` (used as the `update_save` map key) and the
/// editable `edited` value (starts equal to `original`).
#[derive(Clone)]
pub struct StringRow {
    pub original: String,
    pub edited: String,
}

impl StringRow {
    /// True when the user actually changed this string (so only real edits go into the map).
    pub fn is_changed(&self) -> bool {
        self.edited != self.original
    }
}

/// The loaded-and-editable view of a single inspected `.sav`: where it came from, its detected
/// format/encoding, the editable title (seeded from the baked title), and the editable string rows.
pub struct LoadedSave {
    /// The on-disk `.sav` this was inspected from (the [`save_changes`] write target).
    pub path: PathBuf,
    pub format: SaveFormat,
    pub encoding: &'static str,
    /// The baked title as read (read-only reference, for "changed?" detection and the dim original).
    pub original_title: String,
    /// The editable title field (starts equal to `original_title`).
    pub title: String,
    /// The editable baked strings (deduplicated, in first-seen order).
    pub strings: Vec<StringRow>,
}

impl LoadedSave {
    /// True when the save's format is one we can edit/write.
    pub fn editable(&self) -> bool {
        self.format != SaveFormat::Unsupported
    }

    /// True when the title field differs from the baked title.
    pub fn title_changed(&self) -> bool {
        self.title != self.original_title
    }

    /// How many string rows the user has changed.
    pub fn changed_count(&self) -> usize {
        self.strings.iter().filter(|r| r.is_changed()).count()
    }

    /// Build the `new_title` + `source->target` map that [`save_changes`] hands to `update_save`,
    /// from only what the user actually changed.
    fn build_edits(&self) -> (Option<String>, HashMap<String, String>) {
        let new_title = self.title_changed().then(|| self.title.clone());
        let mut map = HashMap::new();
        for r in &self.strings {
            if r.is_changed() && !r.original.is_empty() {
                // Last write wins if the same original appears twice with different edits. The rows
                // are deduplicated on load so that should not happen in practice.
                map.insert(r.original.clone(), r.edited.clone());
            }
        }
        (new_title, map)
    }
}

/// Read and inspect a `.sav`, building the editable [`LoadedSave`]. The baked-string list is
/// deduplicated (keeping first-seen order) so the same item/skill name shows once. Editing it
/// rewrites *every* occurrence on save (that is how `update_save`'s map works). An `Unsupported`
/// save still loads (so the UI can show the not-supported note), just with editing disabled.
pub fn inspect(path: &Path) -> Result<LoadedSave, String> {
    let raw = std::fs::read(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    let info: SaveInfo = inspect_save(&raw)?;

    // Deduplicate the strings, preserving first-seen order, so each unique baked string is one row.
    let mut seen: std::collections::HashSet<&str> = std::collections::HashSet::new();
    let mut strings = Vec::new();
    for s in &info.strings {
        if seen.insert(s.as_str()) {
            strings.push(StringRow {
                original: s.clone(),
                edited: s.clone(),
            });
        }
    }

    Ok(LoadedSave {
        path: path.to_path_buf(),
        format: info.format,
        encoding: info.encoding,
        original_title: info.title.clone(),
        title: info.title,
        strings,
    })
}

/// Where a backup goes for a single-file save change.
fn backup_path(save: &Path) -> PathBuf {
    let mut name = save.file_name().map(|s| s.to_os_string()).unwrap_or_default();
    name.push(".bak");
    save.with_file_name(name)
}

/// Apply the user's edits (title + changed strings) to the loaded save and write it back, optionally
/// backing up the original to `*.bak` first. Returns the [`SaveUpdateStats`] from `update_save`.
/// Refuses to write an unsupported save. Mirrors the single-file path of the CLI's `cmd_save_update`.
pub fn save_changes(loaded: &LoadedSave, backup: bool) -> Result<SaveUpdateStats, String> {
    if !loaded.editable() {
        return Err("this save's format is not supported; nothing was written".to_string());
    }
    let (new_title, map) = loaded.build_edits();
    if new_title.is_none() && map.is_empty() {
        return Err("no changes to save (edit the title or a baked string first)".to_string());
    }

    let raw = std::fs::read(&loaded.path)
        .map_err(|e| format!("cannot read {}: {e}", loaded.path.display()))?;
    let (out, stats) = update_save(&raw, new_title.as_deref(), &map)?;

    if backup {
        let bak = backup_path(&loaded.path);
        std::fs::copy(&loaded.path, &bak)
            .map_err(|e| format!("backup failed ({}): {e}", bak.display()))?;
    }
    std::fs::write(&loaded.path, &out)
        .map_err(|e| format!("write failed ({}): {e}", loaded.path.display()))?;
    Ok(stats)
}

/// Read the baked title out of a (translated) `Game.dat`, the same way the CLI's `--game` does:
/// parse it and pull the Title `source` from `extract_game_dat`'s fixed JSON shape.
pub fn title_from_game_dat(path: &Path) -> Result<String, String> {
    let bytes = std::fs::read(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    let gd = GameDat::read(&bytes).map_err(|e| format!("Game.dat parse failed: {e}"))?;
    let json = extract_game_dat(&gd);
    let value: serde_json::Value = serde_json::from_str(&json).map_err(|e| e.to_string())?;
    value
        .get("lines")
        .and_then(serde_json::Value::as_array)
        .into_iter()
        .flatten()
        .find(|l| l.get("key").and_then(serde_json::Value::as_str) == Some("Title"))
        .and_then(|l| l.get("source").and_then(serde_json::Value::as_str))
        .map(str::to_owned)
        .ok_or_else(|| format!("{} has no Title entry", path.display()))
}

/// Collect every `*.json` under each path (recursively for dirs, the file itself if it is `.json`).
fn collect_json_files(paths: &[PathBuf]) -> Vec<PathBuf> {
    fn walk(path: &Path, out: &mut Vec<PathBuf>) {
        if path.is_dir() {
            if let Ok(rd) = std::fs::read_dir(path) {
                for e in rd.flatten() {
                    walk(&e.path(), out);
                }
            }
        } else if path.extension().and_then(|s| s.to_str()) == Some("json") {
            out.push(path.to_path_buf());
        }
    }
    let mut out = Vec::new();
    for p in paths {
        walk(p, &mut out);
    }
    out.sort();
    out.dedup();
    out
}

/// Build the `source->target` baked-string map from translation JSON file(s)/dir(s), reusing the
/// library's [`build_memory`] exactly as the CLI's `build_save_string_map` does. Returns the map and
/// the count of sources that had divergent translations across files (the first value is kept).
pub fn build_string_map(paths: &[PathBuf]) -> Result<(HashMap<String, String>, usize), String> {
    let files = collect_json_files(paths);
    if files.is_empty() {
        return Err("no *.json found under the chosen translation path(s)".to_string());
    }
    let mut texts: Vec<String> = Vec::with_capacity(files.len());
    for p in &files {
        texts.push(std::fs::read_to_string(p).map_err(|e| format!("{}: {e}", p.display()))?);
    }
    let refs: Vec<&str> = texts.iter().map(String::as_str).collect();
    let (memory, conflicts) = build_memory(&refs);
    Ok((memory, conflicts.len()))
}

/// One save's outcome in a [`batch_update`] run, for the log.
pub enum BatchEntry {
    /// Updated: `(file name, stats)`.
    Updated(String, SaveUpdateStats),
    /// Skipped because its format is unsupported: `file name`.
    Skipped(String),
    /// An I/O error on this file: `(file name, message)`.
    Failed(String, String),
}

/// The summary of a whole batch run.
pub struct BatchOutcome {
    pub entries: Vec<BatchEntry>,
    pub backup_dir: Option<PathBuf>,
}

impl BatchOutcome {
    pub fn updated(&self) -> usize {
        self.entries.iter().filter(|e| matches!(e, BatchEntry::Updated(..))).count()
    }
    pub fn skipped(&self) -> usize {
        self.entries.iter().filter(|e| matches!(e, BatchEntry::Skipped(..))).count()
    }
    pub fn failed(&self) -> usize {
        self.entries.iter().filter(|e| matches!(e, BatchEntry::Failed(..))).count()
    }
}

/// List every `*.sav` directly under `dir`, sorted (mirrors the CLI's discovery).
fn list_saves(dir: &Path) -> Vec<PathBuf> {
    let mut v: Vec<PathBuf> = std::fs::read_dir(dir)
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.is_file() && p.extension().and_then(|s| s.to_str()) == Some("sav"))
        .collect();
    v.sort();
    v
}

/// A short timestamp (`YYYYmmdd_HHMMSS`) for a backup dir name, like the CLI's `backup_stamp`.
pub fn backup_stamp() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let days = secs / 86_400;
    let tod = secs % 86_400;
    let (hh, mm, ss) = (tod / 3600, (tod % 3600) / 60, tod % 60);
    // Civil-from-days (Howard Hinnant's algorithm).
    let z = days as i64 + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if m <= 2 { y + 1 } else { y };
    format!("{year:04}{m:02}{d:02}_{hh:02}{mm:02}{ss:02}")
}

/// Apply a `new_title` and/or a `source->target` string `map` over every `*.sav` in `dir`, in place,
/// mirroring the CLI's `cmd_save_update`. When `backup` is set, the originals are copied into a
/// `save_backup_<stamp>/` under `dir` first. Each file's outcome (updated / skipped-unsupported /
/// failed) is recorded for the log. `report` drives a progress bar. Pass a no-op in tests.
///
/// Errors only when there is nothing to do (no title and an empty map) or no `*.sav` is found.
pub fn batch_update(
    dir: &Path,
    new_title: Option<&str>,
    map: &HashMap<String, String>,
    backup: bool,
    mut report: impl FnMut(f32, String),
) -> Result<BatchOutcome, String> {
    if new_title.is_none() && map.is_empty() {
        return Err("nothing to do (give a new title and/or a translations file)".to_string());
    }
    let saves = list_saves(dir);
    if saves.is_empty() {
        return Err(format!("no *.sav files found under {}", dir.display()));
    }

    // Back up the originals into a stamped dir before overwriting (mirrors the CLI).
    let backup_dir = if backup {
        let root = dir.join(format!("save_backup_{}", backup_stamp()));
        std::fs::create_dir_all(&root)
            .map_err(|e| format!("cannot create backup dir {}: {e}", root.display()))?;
        for src in &saves {
            let name = src.file_name().unwrap_or_default();
            std::fs::copy(src, root.join(name))
                .map_err(|e| format!("backup failed for {}: {e}", src.display()))?;
        }
        Some(root)
    } else {
        None
    };

    let total = saves.len();
    let mut entries = Vec::with_capacity(total);
    for (i, src) in saves.iter().enumerate() {
        let name = src
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("?")
            .to_string();
        report((i as f32) / (total as f32), format!("update {name}"));
        let raw = match std::fs::read(src) {
            Ok(b) => b,
            Err(e) => {
                entries.push(BatchEntry::Failed(name, format!("read failed: {e}")));
                continue;
            }
        };
        match update_save(&raw, new_title, map) {
            Ok((out, stats)) => match std::fs::write(src, &out) {
                Ok(()) => entries.push(BatchEntry::Updated(name, stats)),
                Err(e) => entries.push(BatchEntry::Failed(name, format!("write failed: {e}"))),
            },
            // Err means the buffer is neither a standard nor a detectable Pro save: skip, never write.
            Err(_) => entries.push(BatchEntry::Skipped(name)),
        }
    }
    report(1.0, "done".to_string());
    Ok(BatchOutcome { entries, backup_dir })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Resolve a fixture by its clean relative path under `WOLFDAWN_TEST_DATA`. Returns `None` when
    /// the var is unset or the file is missing, so the data-dependent tests skip gracefully.
    fn test_data(rel: &str) -> Option<PathBuf> {
        let base = std::env::var_os("WOLFDAWN_TEST_DATA")?;
        let p = std::path::Path::new(&base).join(rel);
        p.exists().then_some(p)
    }

    /// The two real save fixtures. Tests skip gracefully when neither is present.
    fn fixtures() -> Vec<PathBuf> {
        ["chamber/SaveData01.sav", "pachimon/SaveData01.sav"]
            .into_iter()
            .filter_map(test_data)
            .collect()
    }

    fn tmp_dir(tag: &str) -> PathBuf {
        let p = std::env::temp_dir().join(format!(
            "wolfdawn_saves_{tag}_{}_{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        ));
        let _ = std::fs::create_dir_all(&p);
        p
    }

    /// Inspect a real save (on a COPY), change the title + one baked string through this module's
    /// own code path, write it, re-inspect from the written bytes, and assert the title + string
    /// changed and the format is preserved. The game folders are never touched.
    #[test]
    fn inspect_edit_save_reinspect_round_trip() {
        let fixtures = fixtures();
        if fixtures.is_empty() {
            eprintln!("skip inspect_edit_save_reinspect_round_trip: no save fixture present");
            return;
        }
        for fixture in fixtures {
            let work = tmp_dir("rt");
            let copy = work.join("SaveData01.sav");
            std::fs::copy(&fixture, &copy).expect("copy fixture");

            let mut loaded = inspect(&copy).expect("inspect");
            assert!(loaded.editable(), "{fixture:?}: real save should be editable");
            assert!(!loaded.original_title.is_empty(), "title should be non-empty");
            let original_format = loaded.format;

            // Change the title.
            let new_title = format!("{} [GUI]", loaded.original_title);
            loaded.title = new_title.clone();

            // Change the first baked string that can re-encode in this save's encoding.
            let utf8 = loaded.encoding == "utf8";
            let mut edited_marker: Option<String> = None;
            for r in &mut loaded.strings {
                if r.original.is_empty() {
                    continue;
                }
                let candidate = format!("{} X", r.original);
                // Shift-JIS saves: only edit a string whose new value is representable.
                let representable = utf8 || {
                    let (_, _, had_err) = encoding_rs::SHIFT_JIS.encode(&candidate);
                    !had_err
                };
                if representable {
                    r.edited = candidate.clone();
                    edited_marker = Some(candidate);
                    break;
                }
            }

            let stats = save_changes(&loaded, true).expect("save changes");
            assert!(stats.title_changed);
            assert_eq!(stats.encoding, loaded.encoding);
            // The backup must exist and still hold the original bytes.
            let bak = copy.with_file_name("SaveData01.sav.bak");
            assert!(bak.exists(), "backup should have been written");
            assert_eq!(
                std::fs::read(&bak).unwrap(),
                std::fs::read(&fixture).unwrap(),
                "backup should equal the original fixture"
            );

            // Re-inspect from the written file: title + string changed, format preserved.
            let re = inspect(&copy).expect("re-inspect");
            assert_eq!(re.format, original_format, "format must be preserved");
            assert_eq!(re.title, new_title, "new title should re-inspect");
            if let Some(marker) = edited_marker {
                assert!(
                    re.strings.iter().any(|r| r.original == marker),
                    "the edited baked string should re-inspect"
                );
            }

            let _ = std::fs::remove_dir_all(&work);
        }
    }

    /// Batch update over a folder of save copies: applies a new title and reports per-file outcomes,
    /// with the originals backed up to a stamped dir first.
    #[test]
    fn batch_update_folder_titles() {
        let fixtures = fixtures();
        if fixtures.is_empty() {
            eprintln!("skip batch_update_folder_titles: no save fixture present");
            return;
        }
        let fixture = &fixtures[0];
        let work = tmp_dir("batch");
        // Two copies so the batch has more than one file to walk.
        for n in ["SaveData01.sav", "SaveData02.sav"] {
            std::fs::copy(fixture, work.join(n)).expect("copy");
        }

        let new_title = "Batched Title";
        let outcome =
            batch_update(&work, Some(new_title), &HashMap::new(), true, |_, _| {}).expect("batch");
        assert!(outcome.updated() >= 1, "at least one save should update");
        assert_eq!(outcome.failed(), 0, "no I/O failures expected");
        assert!(outcome.backup_dir.is_some(), "a backup dir should have been made");
        let backup_dir = outcome.backup_dir.unwrap();
        assert!(backup_dir.join("SaveData01.sav").exists(), "original backed up");

        // Every updated file re-inspects to the new title.
        for n in ["SaveData01.sav", "SaveData02.sav"] {
            let re = inspect(&work.join(n)).expect("re-inspect");
            if re.editable() {
                assert_eq!(re.title, new_title);
            }
        }

        let _ = std::fs::remove_dir_all(&work);
    }

    /// `save_changes` refuses a no-op (nothing edited) and never writes.
    #[test]
    fn save_changes_rejects_no_op() {
        let fixtures = fixtures();
        if fixtures.is_empty() {
            eprintln!("skip save_changes_rejects_no_op: no save fixture present");
            return;
        }
        let work = tmp_dir("noop");
        let copy = work.join("SaveData01.sav");
        std::fs::copy(&fixtures[0], &copy).expect("copy");
        let loaded = inspect(&copy).expect("inspect");
        let err = save_changes(&loaded, true).unwrap_err();
        assert!(err.contains("no changes"), "got: {err}");
        let _ = std::fs::remove_dir_all(&work);
    }
}
