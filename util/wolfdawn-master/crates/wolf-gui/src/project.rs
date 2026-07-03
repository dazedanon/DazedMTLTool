//! The open game **project**: locating the game's files on disk and reading `Game.dat`.
//!
//! A project is opened from either a folder or a `Data.wolf` / `Game.dat` file. From whatever the
//! user picks we resolve the *game root* (the dir holding `Data.wolf` and/or an unpacked `Data/`),
//! then locate the three things every later section needs: the `Data.wolf` archive, the unpacked
//! `Data/` directory, and `Game.dat`. `Game.dat` is parsed with [`GameDat::read`] to surface the
//! title / encoding / font / version. A missing or unparseable `Game.dat` is non-fatal. The
//! project still opens with whatever was found, and the caller logs a warning.

use std::path::{Path, PathBuf};

use wolf_decompiler::extract_game_dat;
use wolf_decompiler::text::decode_wstr;
use wolf_formats::game_dat::GameDat;

/// An opened game, with the on-disk locations later sections operate on plus the human-readable
/// facts read out of `Game.dat`.
#[derive(Default, Clone)]
pub struct Project {
    /// The game root (the directory that holds `Data.wolf` and/or `Data/`).
    pub root: PathBuf,
    /// The packed `Data.wolf` archive, if present.
    pub data_wolf: Option<PathBuf>,
    /// The unpacked `Data/` directory, if present.
    pub data_dir: Option<PathBuf>,
    /// The `Game.dat` we parsed (root, `Data/`, or `Data/BasicData/`), if found.
    pub game_dat: Option<PathBuf>,

    // --- a cheap scanned index of the small relevant dirs (kept fresh by `rescan`) -------------
    /// Decompilable code files: `MapData/*.mps` + `BasicData/CommonEvent.dat` (sorted).
    pub code_files: Vec<PathBuf>,
    /// Editable databases: `BasicData/*.project` (sorted).
    pub databases: Vec<PathBuf>,
    /// `.sav` files found under the game's `Save/` dir (sorted).
    pub saves: Vec<PathBuf>,
    /// The `Save/` dir the saves were found under (the batch-update default), if any.
    pub save_dir: Option<PathBuf>,

    // --- facts read from Game.dat (empty / defaults when it was absent or unparseable) ---
    /// Window/game title (decoded for display).
    pub title: String,
    /// A short version/encoding descriptor (e.g. `UTF-8` vs `Shift-JIS`, plus title-suffix).
    pub version: String,
    /// True when `Game.dat` declared UTF-8 (vs Shift-JIS).
    pub utf8: bool,
    /// The editor's main font (decoded for display).
    pub font: String,
    /// True if `Game.dat` was found and parsed.
    pub game_dat_ok: bool,
}

impl Project {
    /// Re-walk the small relevant subdirs (`MapData/`, `BasicData/`, and `Save/`) and refresh the
    /// scanned file index ([`code_files`](Self::code_files) / [`databases`](Self::databases) /
    /// [`saves`](Self::saves) + [`save_dir`](Self::save_dir)). Returns `true` if any of those sets
    /// changed versus the previous scan, so the caller can log / repaint only on a real change.
    ///
    /// Cheap: it only `read_dir`s those specific folders (never the huge asset trees
    /// like Picture/ or Sound/), and only stats by extension/name. The lists are sorted so the
    /// dropdowns built from them have a stable order.
    pub fn rescan(&mut self) -> bool {
        let prev_code = self.code_files.clone();
        let prev_db = self.databases.clone();
        let prev_saves = self.saves.clone();
        let prev_save_dir = self.save_dir.clone();

        // The data dir is where MapData/ and BasicData/ live (it may be the root itself when the
        // project was opened on a folder that *is* a Data dir). Fall back to the root.
        let data_base = self.data_dir.clone().unwrap_or_else(|| self.root.clone());

        // Code: MapData/*.mps + BasicData/CommonEvent.dat.
        let mut code_files = list_with_ext(&data_base.join("MapData"), "mps");
        let common = data_base.join("BasicData").join("CommonEvent.dat");
        if common.is_file() {
            code_files.push(common);
        }
        code_files.sort();
        self.code_files = code_files;

        // Databases: BasicData/*.project (paired .dat is loaded by the section).
        let mut databases = list_with_ext(&data_base.join("BasicData"), "project");
        databases.sort();
        self.databases = databases;

        // Saves: *.sav under a Save/ dir at the game root (and/or next to Game.exe == the root).
        let (saves, save_dir) = scan_saves(&self.root);
        self.saves = saves;
        self.save_dir = save_dir;

        self.code_files != prev_code
            || self.databases != prev_db
            || self.saves != prev_saves
            || self.save_dir != prev_save_dir
    }
}

/// List the files directly in `dir` whose extension matches `ext` (case-insensitive). Empty when
/// `dir` is missing or unreadable. The scan is best-effort and never fails a project open.
fn list_with_ext(dir: &Path, ext: &str) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let Ok(entries) = std::fs::read_dir(dir) else {
        return out;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path
            .extension()
            .and_then(|s| s.to_str())
            .is_some_and(|e| e.eq_ignore_ascii_case(ext))
        {
            out.push(path);
        }
    }
    out
}

/// Locate the game's `Save/` dir (at the root) and list the `*.sav` files in it. Returns the sorted
/// save list plus the dir they came from (the batch-update default). Empty / `None` when there is no
/// `Save/` dir yet.
fn scan_saves(root: &Path) -> (Vec<PathBuf>, Option<PathBuf>) {
    let save_dir = root.join("Save");
    if !save_dir.is_dir() {
        return (Vec::new(), None);
    }
    let mut saves = list_with_ext(&save_dir, "sav");
    saves.sort();
    (saves, Some(save_dir))
}

/// The result of opening a project: the project itself plus any human-readable notes to log
/// (warnings for things that were missing or failed to parse, info for what was found).
pub struct OpenOutcome {
    pub project: Project,
    pub notes: Vec<(NoteLevel, String)>,
}

/// Severity for an [`OpenOutcome`] note, mapped onto the log by the caller.
#[derive(Clone, Copy)]
pub enum NoteLevel {
    Info,
    Warn,
}

/// Resolve the game root from whatever the user picked (a folder, a `Data.wolf`, or a `Game.dat`),
/// then locate `Data.wolf` / `Data/` / `Game.dat`, parse `Game.dat`, and build the [`Project`].
///
/// Never errors: a missing/garbled `Game.dat` produces a project with `game_dat_ok == false` and a
/// warning note. (The only "failure" worth refusing is a path that does not exist at all.)
pub fn open_project(picked: &Path) -> OpenOutcome {
    let mut notes: Vec<(NoteLevel, String)> = Vec::new();

    // Resolve the game root. If the user picked a file, the root is (heuristically) its parent, or
    // its grandparent when the file sits inside a `Data/` (or `Data/BasicData/`) subtree.
    let root = resolve_root(picked);

    // Locate Data.wolf (root or Data/) and the unpacked Data/ dir.
    let data_wolf = ["Data.wolf"]
        .iter()
        .map(|n| root.join(n))
        .find(|p| p.is_file());
    let data_dir = {
        let d = root.join("Data");
        if d.is_dir() {
            Some(d)
        } else {
            // A folder that *is* a Data dir (holds BasicData) counts too.
            root.join("BasicData").is_dir().then(|| root.clone())
        }
    };

    // Locate Game.dat. Try, in order: an explicitly-picked Game.dat, then the common spots.
    let game_dat = locate_game_dat(picked, &root, data_dir.as_deref());

    let mut project = Project {
        root: root.clone(),
        data_wolf: data_wolf.clone(),
        data_dir: data_dir.clone(),
        game_dat: game_dat.clone(),
        ..Default::default()
    };
    // Build the initial scanned index (code files / databases / saves) from the resolved dirs.
    project.rescan();

    // Log what we found, so the user sees the layout we resolved.
    notes.push((NoteLevel::Info, format!("game root: {}", root.display())));
    match &data_wolf {
        Some(p) => notes.push((NoteLevel::Info, format!("found Data.wolf: {}", p.display()))),
        None => notes.push((NoteLevel::Info, "no Data.wolf (will work from unpacked Data/)".into())),
    }
    match &data_dir {
        Some(p) => notes.push((NoteLevel::Info, format!("found unpacked data dir: {}", p.display()))),
        None => notes.push((NoteLevel::Info, "no unpacked Data/ dir yet (unpack Data.wolf to create one)".into())),
    }
    // Surface the scanned index counts so the user sees what the per-section dropdowns will offer.
    notes.push((
        NoteLevel::Info,
        format!(
            "indexed {} code file(s), {} database(s), {} save(s)",
            project.code_files.len(),
            project.databases.len(),
            project.saves.len(),
        ),
    ));

    // Parse Game.dat if we found one. Failure is non-fatal.
    match &game_dat {
        Some(path) => match read_game_facts(path) {
            Ok(facts) => {
                project.title = facts.title;
                project.version = facts.version;
                project.utf8 = facts.utf8;
                project.font = facts.font;
                project.game_dat_ok = true;
                notes.push((
                    NoteLevel::Info,
                    format!("parsed Game.dat: title={:?}, encoding={}", project.title, encoding_label(project.utf8)),
                ));
            }
            Err(e) => {
                notes.push((
                    NoteLevel::Warn,
                    format!("Game.dat found but could not be read ({e}); opening project without it"),
                ));
            }
        },
        None => notes.push((
            NoteLevel::Warn,
            "no Game.dat found (looked in the root, Data/, and Data/BasicData/)".into(),
        )),
    }

    OpenOutcome { project, notes }
}

/// Human label for the encoding flag.
pub fn encoding_label(utf8: bool) -> &'static str {
    if utf8 {
        "UTF-8"
    } else {
        "Shift-JIS"
    }
}

/// Resolve the game root from a picked path.
fn resolve_root(picked: &Path) -> PathBuf {
    if picked.is_dir() {
        // If they picked a `Data` dir, the game root is its parent. Otherwise it's the dir itself.
        if picked.file_name().and_then(|s| s.to_str()) == Some("Data") {
            if let Some(parent) = picked.parent() {
                return parent.to_path_buf();
            }
        }
        // If they picked a BasicData dir, climb to the game root (BasicData -> Data -> root).
        if picked.file_name().and_then(|s| s.to_str()) == Some("BasicData") {
            if let Some(root) = picked.parent().and_then(|p| p.parent()) {
                return root.to_path_buf();
            }
        }
        return picked.to_path_buf();
    }
    // A file: walk up out of a known `Data`/`BasicData` subtree to the game root.
    let parent = picked.parent().unwrap_or(Path::new("."));
    let parent_name = parent.file_name().and_then(|s| s.to_str());
    match parent_name {
        Some("BasicData") => parent
            .parent()
            .and_then(|p| p.parent())
            .unwrap_or(parent)
            .to_path_buf(),
        Some("Data") => parent.parent().unwrap_or(parent).to_path_buf(),
        _ => parent.to_path_buf(),
    }
}

/// Locate `Game.dat`, trying (in order): an explicitly-picked `Game.dat`, the game root,
/// `Data/`, and `Data/BasicData/`.
fn locate_game_dat(picked: &Path, root: &Path, data_dir: Option<&Path>) -> Option<PathBuf> {
    if picked.is_file() && picked.file_name().and_then(|s| s.to_str()) == Some("Game.dat") {
        return Some(picked.to_path_buf());
    }
    let mut candidates = vec![
        root.join("Game.dat"),
        root.join("Data").join("Game.dat"),
        root.join("Data").join("BasicData").join("Game.dat"),
    ];
    if let Some(d) = data_dir {
        candidates.push(d.join("Game.dat"));
        candidates.push(d.join("BasicData").join("Game.dat"));
    }
    candidates.into_iter().find(|p| p.is_file())
}

/// The subset of `Game.dat` facts we display.
struct GameFacts {
    title: String,
    version: String,
    utf8: bool,
    font: String,
}

/// Read and decode the display facts from a `Game.dat` file.
fn read_game_facts(path: &Path) -> Result<GameFacts, String> {
    let bytes = std::fs::read(path).map_err(|e| e.to_string())?;
    let gd = GameDat::read(&bytes).map_err(|e| e.to_string())?;
    let utf8 = gd.utf8;
    let title = decode_wstr(&gd.title, utf8);
    let font = decode_wstr(&gd.font, utf8);

    // "version" is a soft concept in Game.dat: surface the encoding plus the title-suffix string
    // (string 8, e.g. a "Ver1.02" the author bakes in), which is the closest user-visible version.
    let suffix = gd
        .title_plus
        .as_ref()
        .map(|w| decode_wstr(w, utf8))
        .filter(|s| !s.trim().is_empty());
    let version = match suffix {
        Some(s) => format!("{} · {}", encoding_label(utf8), s.trim()),
        None => encoding_label(utf8).to_string(),
    };

    // Sanity-cross-check against extract_game_dat: it always emits Title first, decoded in-encoding.
    // If our direct decode somehow disagrees (it shouldn't), prefer the extractor's value so the UI
    // matches the translation tooling exactly. Cheap and keeps the two paths from ever drifting.
    let title = title_from_extract(&gd).unwrap_or(title);

    Ok(GameFacts {
        title,
        version,
        utf8,
        font,
    })
}

/// Pull the Title `source` out of `extract_game_dat`'s JSON (the same value the translation
/// pipeline sees), so the GUI's title display can never disagree with the tooling.
fn title_from_extract(gd: &GameDat) -> Option<String> {
    let json = extract_game_dat(gd);
    // Fixed machine shape: `{"key": "Title", "source": "...", "text": "..."}`. Scan for it without
    // pulling in a JSON dep (mirrors wolf-cli's own minimal scan in save-update).
    let marker = json.find("\"key\": \"Title\"")?;
    let after = &json[marker..];
    let src_at = after.find("\"source\":")?;
    let after = &after[src_at + "\"source\":".len()..];
    let open = after.find('"')? + 1;
    let rest = &after[open..];
    let mut out = String::new();
    let mut chars = rest.chars();
    while let Some(c) = chars.next() {
        match c {
            '"' => return Some(out),
            '\\' => match chars.next()? {
                'n' => out.push('\n'),
                'r' => out.push('\r'),
                't' => out.push('\t'),
                '"' => out.push('"'),
                '\\' => out.push('\\'),
                '/' => out.push('/'),
                'u' => {
                    let hex: String = chars.by_ref().take(4).collect();
                    let code = u32::from_str_radix(&hex, 16).ok()?;
                    out.push(char::from_u32(code)?);
                }
                other => out.push(other),
            },
            _ => out.push(c),
        }
    }
    None
}
