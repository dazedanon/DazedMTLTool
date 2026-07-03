//! The Game.dat section's data model and headless logic.
//!
//! A friendly form over *every* editable `Game.dat` string field, so a non-coder can change the
//! window title or the editor font without touching JSON. This mirrors the CLI's `gamedat-json`
//! (`dump_game_dat`) + `gamedat-apply` (`apply_game_dat`) pair, calling the same `wolf_decompiler`
//! library functions directly (no shelling out), so the GUI and CLI agree on the field set and the
//! byte-exact apply.
//!
//! The module owns everything except the egui rendering (which lives in `app.rs`), so the whole
//! workflow can be exercised headlessly:
//!
//!   * [`load`] reads a `Game.dat` with [`GameDat::read`], dumps every editable field to JSON with
//!     [`dump_game_dat`], and parses it into typed [`Field`]s. **Only the fields actually present**
//!     for this file's `string_count` (no phantom keys), plus the read-only `encoding` badge.
//!   * [`save`] builds a JSON object of *only the changed fields*, applies it with [`apply_game_dat`]
//!     onto a freshly-read base, re-parses the [`GameDat::write`] output to verify it round-trips
//!     (exactly as `cmd_gamedat_apply` does), and writes it, optionally backing up the original
//!     first. Untouched fields re-serialize byte-exact (guaranteed by `apply_game_dat` + the
//!     `GameDat::write` housekeeping anchor), so a no-change save reproduces the file byte-for-byte.

use std::path::{Path, PathBuf};

use serde_json::{Map, Value};
use wolf_decompiler::{apply_game_dat, dump_game_dat};
use wolf_formats::game_dat::GameDat;

/// Which group a field belongs to, so the form can render sensible section headers.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Group {
    /// Window title + splash/title-screen messages.
    Titles,
    /// The editor font + fallback sub-fonts.
    Fonts,
    /// Image / graphic path fields.
    Graphics,
    /// The opaque trailing string.
    Other,
}

/// One editable scalar field of a loaded Game.dat: its JSON key, an editable value (seeded from the
/// original), the read-only original (for "changed?" detection), and which form group it belongs to.
pub struct Field {
    /// The JSON key (`"Title"`, `"Font"`, …), the same key `apply_game_dat` recognizes.
    pub key: &'static str,
    /// A friendly label for the form.
    pub label: &'static str,
    /// The editable value (starts equal to `original`).
    pub value: String,
    /// The value as loaded (read-only reference, for change detection).
    pub original: String,
    /// Which form section this field is shown under.
    pub group: Group,
}

impl Field {
    /// True when the user changed this field's value.
    pub fn is_changed(&self) -> bool {
        self.value != self.original
    }
}

/// The loaded, editable view of a Game.dat: where it came from, the read-only encoding badge, the
/// present scalar fields (in form order), and the present `SubFonts` (0..=3, as the file carries).
pub struct LoadedGameDat {
    /// The on-disk `Game.dat` this was loaded from (the [`save`] in-place target).
    pub path: PathBuf,
    /// The encoding badge (`"utf8"` / `"shiftjis"`), read-only.
    pub encoding: String,
    /// The present scalar fields, in display order.
    pub fields: Vec<Field>,
    /// The present sub-font values (editable), in order. Empty when the file carries none.
    pub sub_fonts: Vec<SubFont>,
}

/// One editable sub-font slot (a `SubFonts` array entry).
pub struct SubFont {
    pub value: String,
    pub original: String,
}

impl SubFont {
    pub fn is_changed(&self) -> bool {
        self.value != self.original
    }
}

/// The form-order + group + label for each scalar key. Only keys actually present in the dumped JSON
/// become [`Field`]s, so an absent optional never shows (and is never materialized on save).
const SCALAR_FORM: &[(&str, &str, Group)] = &[
    ("Title", "Title", Group::Titles),
    ("TitlePlus", "Title plus", Group::Titles),
    ("StartUpMsg", "Start-up message", Group::Titles),
    ("TitleMsg", "Title message", Group::Titles),
    ("Font", "Font", Group::Fonts),
    ("DefaultPcGraphic", "Default PC graphic", Group::Graphics),
    ("RoadImg", "Road image", Group::Graphics),
    ("GaugeImg", "Gauge image", Group::Graphics),
    ("UnknownString14", "Unknown string 14", Group::Other),
];

impl LoadedGameDat {
    /// How many fields (scalars + sub-fonts) the user has changed.
    pub fn changed_count(&self) -> usize {
        self.fields.iter().filter(|f| f.is_changed()).count()
            + self.sub_fonts.iter().filter(|s| s.is_changed()).count()
    }

    /// True when anything was edited (so the Save button can gate on it).
    pub fn dirty(&self) -> bool {
        self.changed_count() > 0
    }

    /// Build the minimal `apply_game_dat` JSON: an object holding only the *changed* fields (each
    /// already proven present at load time, so `apply_game_dat` only edits existing cells). Including
    /// just the changes keeps unchanged cells untouched, which is what makes a no-change save
    /// byte-exact. `SubFonts` must be passed whole (the array is replaced atomically) whenever any
    /// entry changed, so the unchanged entries carry their current value through.
    fn edits_json(&self) -> String {
        let mut obj = Map::new();
        for f in &self.fields {
            if f.is_changed() {
                obj.insert(f.key.to_string(), Value::String(f.value.clone()));
            }
        }
        if self.sub_fonts.iter().any(SubFont::is_changed) {
            let arr: Vec<Value> =
                self.sub_fonts.iter().map(|s| Value::String(s.value.clone())).collect();
            obj.insert("SubFonts".to_string(), Value::Array(arr));
        }
        Value::Object(obj).to_string()
    }
}

/// Read and parse a `Game.dat` into the editable form model, reusing [`GameDat::read`] +
/// [`dump_game_dat`] (the CLI's `gamedat-json` path). Only the fields the file actually carries
/// appear (the dump omits absent optionals). The `encoding` badge is read-only.
pub fn load(path: &Path) -> Result<LoadedGameDat, String> {
    let bytes = std::fs::read(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    let gd = GameDat::read(&bytes).map_err(|e| format!("Game.dat parse failed: {e}"))?;
    let json = dump_game_dat(&gd);
    let root: Value = serde_json::from_str(&json).map_err(|e| format!("invalid dump JSON: {e}"))?;
    let obj = root.as_object().ok_or("Game.dat dump must be a JSON object")?;

    let encoding = obj
        .get("encoding")
        .and_then(Value::as_str)
        .unwrap_or("utf8")
        .to_string();

    // Present scalars, in form order (skip any the dump omitted for this file's string_count).
    let mut fields = Vec::new();
    for (key, label, group) in SCALAR_FORM {
        if let Some(v) = obj.get(*key).and_then(Value::as_str) {
            fields.push(Field {
                key,
                label,
                value: v.to_string(),
                original: v.to_string(),
                group: *group,
            });
        }
    }

    // SubFonts: a present array (0..=3 entries). Each becomes an editable slot.
    let sub_fonts = obj
        .get("SubFonts")
        .and_then(Value::as_array)
        .map(|arr| {
            arr.iter()
                .filter_map(Value::as_str)
                .map(|s| SubFont { value: s.to_string(), original: s.to_string() })
                .collect()
        })
        .unwrap_or_default();

    Ok(LoadedGameDat {
        path: path.to_path_buf(),
        encoding,
        fields,
        sub_fonts,
    })
}

/// Where a backup goes for an in-place save.
fn backup_path(file: &Path) -> PathBuf {
    let mut name = file.file_name().map(|s| s.to_os_string()).unwrap_or_default();
    name.push(".bak");
    file.with_file_name(name)
}

/// The outcome of a [`save`] run, for the log.
pub struct SaveOutcome {
    /// How many fields `apply_game_dat` actually changed.
    pub changed: usize,
    /// True when the output is byte-identical to the base (an unchanged save, or edits that net to
    /// the original values).
    pub byte_identical: bool,
    /// Where the result was written.
    pub out: PathBuf,
    /// The backup path, if one was made.
    pub backup: Option<PathBuf>,
}

/// Apply the form's edits onto the base `Game.dat` and write the result to `output`, mirroring the
/// CLI's `gamedat-apply`: build a minimal JSON of the changed fields, [`apply_game_dat`] it onto a
/// freshly-read base, **re-parse the [`GameDat::write`] output to verify it round-trips** before
/// writing, and report the change count + byte-identity. When `backup` is set and the output already
/// exists, the original is copied to `<output>.bak` first.
///
/// Byte-exactness: `apply_game_dat` only rewrites cells whose value changed and `GameDat::write`
/// anchors its size/offset housekeeping on the read-time body size, so untouched fields re-serialize
/// verbatim and a no-change save reproduces the base byte-for-byte.
pub fn save(loaded: &LoadedGameDat, output: &Path, backup: bool) -> Result<SaveOutcome, String> {
    // Always read the base fresh from disk (the load-time bytes), so the apply is onto a pristine
    // base and the byte-identity check is honest.
    let base_bytes = std::fs::read(&loaded.path)
        .map_err(|e| format!("cannot read base {}: {e}", loaded.path.display()))?;
    let mut gd = GameDat::read(&base_bytes).map_err(|e| format!("base parse failed: {e}"))?;

    let edits = loaded.edits_json();
    let changed = apply_game_dat(&mut gd, &edits).map_err(|e| format!("apply failed: {e}"))?;

    let out_bytes = gd.write();
    // Re-parse the output to verify it still round-trips before committing it to disk (the guard
    // `cmd_gamedat_apply` runs).
    GameDat::read(&out_bytes)
        .map_err(|e| format!("internal error: edited Game.dat no longer parses ({e})"))?;
    let byte_identical = out_bytes == base_bytes;

    // Back up the original (only when overwriting an existing target).
    let backup_made = if backup && output.exists() {
        let bak = backup_path(output);
        std::fs::copy(output, &bak)
            .map_err(|e| format!("backup failed ({}): {e}", bak.display()))?;
        Some(bak)
    } else {
        None
    };

    if let Some(parent) = output.parent() {
        if !parent.as_os_str().is_empty() {
            let _ = std::fs::create_dir_all(parent);
        }
    }
    std::fs::write(output, &out_bytes)
        .map_err(|e| format!("write failed ({}): {e}", output.display()))?;

    Ok(SaveOutcome {
        changed,
        byte_identical,
        out: output.to_path_buf(),
        backup: backup_made,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A unique temp dir for scratch output (never a game folder or the fixtures root).
    fn tmp_dir(tag: &str) -> PathBuf {
        let p = std::env::temp_dir().join(format!(
            "wolfdawn_gamedat_{tag}_{}_{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        ));
        let _ = std::fs::create_dir_all(&p);
        p
    }

    /// Resolve a fixture by its clean relative path under `WOLFDAWN_TEST_DATA`. Returns `None` when
    /// the var is unset or the file is missing, so the data-dependent tests skip gracefully.
    fn test_data(rel: &str) -> Option<PathBuf> {
        let base = std::env::var_os("WOLFDAWN_TEST_DATA")?;
        let p = std::path::Path::new(&base).join(rel);
        p.exists().then_some(p)
    }

    /// The first present Game.dat fixture from the fixtures root (read-only).
    fn fixture() -> Option<PathBuf> {
        ["chamber/Data/BasicData/Game.dat"]
            .into_iter()
            .find_map(test_data)
    }

    /// Helper: find a field by key in a loaded model.
    fn field<'a>(g: &'a LoadedGameDat, key: &str) -> Option<&'a Field> {
        g.fields.iter().find(|f| f.key == key)
    }

    /// Load a real Game.dat, change the Font field through this module's code, save to a temp output,
    /// then reload. Font is the new value and Title etc. unchanged. Then a no-change save reproduces
    /// the file byte-for-byte. Never touches the fixtures root (reads the fixture, writes only temp).
    #[test]
    fn load_edit_font_save_reload_round_trip() {
        let Some(input) = fixture() else {
            eprintln!("skip load_edit_font_save_reload_round_trip: no Game.dat fixture present");
            return;
        };
        // Work on a COPY so the base path is in a temp dir (we never write into the fixtures root).
        let work = tmp_dir("rt");
        let copy = work.join("Game.dat");
        std::fs::copy(&input, &copy).expect("copy fixture");

        let mut g = load(&copy).expect("load");
        assert!(field(&g, "Title").is_some(), "Title should always be present");
        assert!(field(&g, "Font").is_some(), "Font should always be present");
        let original_title = field(&g, "Title").unwrap().value.clone();
        let original_font = field(&g, "Font").unwrap().value.clone();

        // Change the Font field.
        let new_font = format!("{original_font}_X");
        g.fields.iter_mut().find(|f| f.key == "Font").unwrap().value = new_font.clone();
        assert_eq!(g.changed_count(), 1, "exactly one field changed");

        let out = work.join("edited.dat");
        let outcome = save(&g, &out, false).expect("save");
        assert_eq!(outcome.changed, 1, "apply should report one field changed");
        assert!(!outcome.byte_identical, "an edited save differs from base");

        // Reload the edited file: Font is the new value, Title unchanged.
        let re = load(&out).expect("reload");
        assert_eq!(field(&re, "Font").unwrap().value, new_font, "Font should be the new value");
        assert_eq!(
            field(&re, "Title").unwrap().value,
            original_title,
            "Title must be unchanged"
        );
        assert_eq!(re.encoding, g.encoding, "encoding preserved");

        // A no-change save reproduces the (original) file byte-for-byte.
        let pristine = load(&copy).expect("reload pristine");
        let noop_out = work.join("noop.dat");
        let noop = save(&pristine, &noop_out, false).expect("no-op save");
        assert_eq!(noop.changed, 0, "no fields changed");
        assert!(noop.byte_identical, "a no-change save must be byte-identical to base");
        assert_eq!(
            std::fs::read(&noop_out).unwrap(),
            std::fs::read(&copy).unwrap(),
            "no-op output equals the original bytes"
        );

        let _ = std::fs::remove_dir_all(&work);
    }

    /// In-place save with a backup writes a `.bak` holding the original bytes, then overwrites.
    #[test]
    fn in_place_save_backs_up_original() {
        let Some(input) = fixture() else {
            eprintln!("skip in_place_save_backs_up_original: no Game.dat fixture present");
            return;
        };
        let work = tmp_dir("bak");
        let copy = work.join("Game.dat");
        std::fs::copy(&input, &copy).expect("copy fixture");
        let original_bytes = std::fs::read(&copy).unwrap();

        let mut g = load(&copy).expect("load");
        let title = g.fields.iter_mut().find(|f| f.key == "Title").unwrap();
        title.value = format!("{} [GUI]", title.value);

        // Save in place (output == loaded.path) with backup ON.
        let outcome = save(&g, &copy, true).expect("save in place");
        assert!(outcome.backup.is_some(), "a backup should have been made");
        let bak = outcome.backup.unwrap();
        assert_eq!(std::fs::read(&bak).unwrap(), original_bytes, "backup holds the original bytes");
        // The in-place file is now the edited one (reloads to the new title).
        let re = load(&copy).expect("reload");
        assert!(field(&re, "Title").unwrap().value.ends_with("[GUI]"), "title was rewritten");

        let _ = std::fs::remove_dir_all(&work);
    }
}
