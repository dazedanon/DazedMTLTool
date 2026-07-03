//! `WolfDawnApp`, the application shell: state, the top/side/bottom/central panel layout, and
//! the per-section dispatch. Phase 0 ships the Project section (which reads real `Game.dat`) and
//! stubs every later section so the full navigation shape is visible from day one.

use std::path::{Path, PathBuf};
use std::sync::mpsc::{Receiver, Sender};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::archive::{self, CryptSource, PackFormat, PackOptions};
use crate::database::{self, DbModel};
use crate::decompile;
use crate::gamedat::{self, Group, LoadedGameDat};
use crate::log::Log;
use crate::project::{self, NoteLevel, Project};
use crate::saves::{self, LoadedSave};
use crate::task::JobManager;
use crate::translation::{
    self, Conflict, FileKind, InjectTarget, TranslationModel,
};
use crate::verify::{self, CorpusOutcome, Verdict};
use crate::widgets;
use wolf_decompiler::{InjectOptions, SaveFormat};

/// The top-level navigation sections. Each later section plugs its real UI in where the stub is.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Section {
    Project,
    Archive,
    Decompile,
    Database,
    GameDat,
    Translation,
    Saves,
    Verify,
    Settings,
}

impl Section {
    /// Every section, in sidebar order. Tests iterate this to exercise the dispatch exhaustively.
    pub const ALL: [Section; 9] = [
        Section::Project,
        Section::Archive,
        Section::Decompile,
        Section::Database,
        Section::GameDat,
        Section::Translation,
        Section::Saves,
        Section::Verify,
        Section::Settings,
    ];

    /// The text label.
    pub fn name(self) -> &'static str {
        match self {
            Section::Project => "Project",
            Section::Archive => "Archive",
            Section::Decompile => "Decompile",
            Section::Database => "Database",
            Section::GameDat => "Game.dat",
            Section::Translation => "Translation",
            Section::Saves => "Saves",
            Section::Verify => "Verify",
            Section::Settings => "Settings",
        }
    }
}

/// Per-section UI state. Phase 0 only needs the Project section's. The rest are stubbed so the
/// fields exist for later phases to fill in (each section owns its inputs/options here).
#[derive(Default)]
struct SectionState {
    archive: ArchiveState,
    database: DatabaseState,
    decompile: DecompileState,
    gamedat: GameDatState,
    translation: TranslationState,
    saves: SavesState,
    verify: VerifyState,
    // Settings live on the app (`WolfDawnApp::settings`), not here, since they persist across runs
    // and other sections read their defaults. The rest of `SectionState` is per-session scratch.
}

/// Persisted user preferences (the Settings section). Serde-derived so the whole struct round-trips
/// through eframe's on-disk storage (see [`WolfDawnApp::new`] / [`eframe::App::save`]). Defaults
/// match the sections' historical defaults so a fresh install behaves exactly as before.
#[derive(Clone, PartialEq, Eq, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    /// Dark vs light theme (applied via `ctx.set_visuals` on startup + when toggled).
    pub dark_mode: bool,
    /// Default for the Translation section's `--en-punct` flag.
    pub default_en_punct: bool,
    /// Default for the Translation section's `--allow-code-drift` flag.
    pub default_allow_code_drift: bool,
    /// Default for the "back up originals" toggles (Saves / Database / Game.dat).
    pub default_backup: bool,
    /// Gate for the periodic auto-detect rescan while a project is open.
    pub auto_detect: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            // egui's own default visuals are dark, so default to dark to match the unchanged look.
            dark_mode: true,
            default_en_punct: false,
            default_allow_code_drift: false,
            // Every section historically defaulted its backup toggle ON. Preserve that.
            default_backup: true,
            // Live auto-detect on by default. The Settings toggle gates it.
            auto_detect: true,
        }
    }
}

/// Which Archive sub-panel is active.
#[derive(Clone, Copy, PartialEq, Eq)]
enum ArchiveMode {
    Unpack,
    UnpackAll,
    Repack,
}

/// Archive section scratch state: the Unpack inputs (archive + output folder) and the Repack inputs
/// (folder + output `.wolf` + the encrypt/version/like/format options that mirror the CLI `pack`
/// flags).
struct ArchiveState {
    /// Which sub-panel is shown (Unpack / Repack).
    mode: ArchiveMode,

    // --- Unpack ---
    /// The `.wolf` archive to extract.
    unpack_archive: Option<PathBuf>,
    /// Where to extract it (defaults to `<archive_dir>/Data`).
    unpack_out: Option<PathBuf>,

    // --- Unpack all (a per-category game's whole set of .wolf files) ---
    /// The folder holding the `.wolf` archives (a game's `Data` folder).
    unpack_all_dir: Option<PathBuf>,
    /// Where to write the per-archive folders (defaults to the archive folder itself, in place).
    unpack_all_out: Option<PathBuf>,

    // --- Repack ---
    /// The folder to pack.
    repack_in: Option<PathBuf>,
    /// The output `.wolf`.
    repack_out: Option<PathBuf>,
    /// Encrypt the output (`--encrypt`).
    repack_encrypt: bool,
    /// Where the crypt params come from when encrypting (default / typed version / like an archive).
    repack_crypt: RepackCryptMode,
    /// The typed cryptVersion text (parsed to a `u16`, accepts `0x14b` or decimal).
    repack_version_text: String,
    /// The existing `.wolf` to inherit crypto from (for the "like existing" mode).
    repack_like: Option<PathBuf>,
    /// The container format (`auto` / `ver5` / `ver6`).
    repack_format: PackFormat,
}

/// Where the encrypt-repack crypto parameters come from (the small radio in the Repack panel).
#[derive(Clone, Copy, PartialEq, Eq)]
enum RepackCryptMode {
    /// The CLI default cryptVersion.
    Default,
    /// A manually-typed cryptVersion.
    Version,
    /// Inherit cryptVersion + password from an existing `.wolf` (`--like`).
    Like,
}

impl Default for ArchiveState {
    fn default() -> Self {
        Self {
            mode: ArchiveMode::Unpack,
            unpack_archive: None,
            unpack_out: None,
            unpack_all_dir: None,
            unpack_all_out: None,
            repack_in: None,
            repack_out: None,
            repack_encrypt: false,
            repack_crypt: RepackCryptMode::Default,
            repack_version_text: format!("{:#x}", archive::DEFAULT_CRYPT_VERSION),
            repack_like: None,
            repack_format: PackFormat::Auto,
        }
    }
}

/// The heavy result a background Database job hands back to the UI thread (mirrors [`GameDatResult`]):
/// the freshly-loaded (or reloaded-after-save) grid model, over the per-section side-channel.
enum DbResult {
    /// A freshly loaded model replaces the current one.
    Loaded(Box<DbModel>),
}

/// The Database section's scratch state: the `.project` path, the loaded editable grid model, the
/// selected type + a row-name filter, the in-place-vs-output choice + a backup toggle, and the
/// side-channel a background Load/Save job hands the model back on.
struct DatabaseState {
    /// The `.project` to load (its sibling `.dat` is paired by extension).
    path: Option<PathBuf>,
    /// The loaded, editable grid model (None until Load runs / after Reload-clears).
    loaded: Option<DbModel>,
    /// Which type (table) is shown on the right.
    selected_type: usize,
    /// The row-name filter (matches the row name, case-insensitive).
    filter: String,
    /// Output target: in-place (`None`) or a chosen output `.project`.
    out_project: Option<PathBuf>,
    /// Back up the originals before an in-place overwrite (default ON).
    backup: bool,
    /// Receiver for a running Load/Save job's heavy result (the loaded/reloaded model).
    result_rx: Option<Receiver<DbResult>>,
}

impl Default for DatabaseState {
    fn default() -> Self {
        Self {
            path: None,
            loaded: None,
            selected_type: 0,
            filter: String::new(),
            out_project: None,
            backup: true,
            result_rx: None,
        }
    }
}

/// The heavy result a background Decompile job hands back to the UI thread (mirrors [`VerifyResult`]
/// / [`SaveResult`]): the freshly-decompiled WolfScript text for the chosen input, carried over the
/// per-section side-channel since the shared [`JobManager`] only carries progress/log/summary.
enum DecompileResult {
    /// Decompiled WolfScript text for `input` (the path it came from, kept as the compile `--base`).
    Text(PathBuf, String),
}

/// The Decompile section's scratch state: the input `.mps`/`CommonEvent.dat`, the editable WolfScript
/// buffer + the base it was decompiled from (needed as the compile `--base` so unknown bytes are
/// preserved), the chosen compile output, and the side-channel a background job hands its text back on.
struct DecompileState {
    /// The binary event file to decompile (a `.mps` map or `CommonEvent.dat`).
    input: Option<PathBuf>,
    /// The editable WolfScript document (empty until Decompile / Open .wscript runs).
    script: String,
    /// The original file the current script was decompiled from, the compile `--base`. Set on a
    /// successful Decompile. Required before Compile (Open .wscript leaves it as the picked input).
    base: Option<PathBuf>,
    /// Where Compile writes the recompiled file (defaults to `<input>.out`).
    out: Option<PathBuf>,
    /// Receiver for a running Decompile job's heavy result (the WolfScript text).
    result_rx: Option<Receiver<DecompileResult>>,
    /// The find-in-editor (Ctrl+F) bar's state.
    find: FindState,
}

impl Default for DecompileState {
    fn default() -> Self {
        Self {
            input: None,
            script: String::new(),
            base: None,
            out: None,
            result_rx: None,
            find: FindState::default(),
        }
    }
}

/// The Decompile editor's find-in-text (Ctrl+F) state: whether the bar is open, the query text, the
/// case toggle, and the index of the currently-selected match (so Next/Prev step through). The match
/// list itself is recomputed each frame from the script + query (`find_matches` is linear and cheap),
/// so it never goes stale against an edited script.
#[derive(Default)]
struct FindState {
    /// Whether the find bar is shown (toggled by Ctrl+F / the Find button / the close button).
    open: bool,
    /// The search query.
    query: String,
    /// Case-sensitive matching (off = case-insensitive, the default).
    case_sensitive: bool,
    /// Which match is "current" (0-based) for the counter + scroll-to. Clamped to the match count.
    current: usize,
    /// Set when the bar was just opened, so the query field grabs focus for one frame.
    focus_query: bool,
    /// A pending match (char range) to select + scroll the editor to on this frame's `TextEdit`.
    pending_select: Option<(usize, usize)>,
}

/// The heavy result a background Game.dat job hands back to the UI thread: the freshly-loaded (or
/// reloaded-after-save) editable model, over the per-section side-channel.
enum GameDatResult {
    /// A freshly loaded model replaces the current one.
    Loaded(Box<LoadedGameDat>),
}

/// The Game.dat section's scratch state: the `Game.dat` path, the loaded editable form model, the
/// in-place backup toggle, and the side-channel a background Load/Save job hands the model back on.
struct GameDatState {
    /// The `Game.dat` to load (defaults to the open project's `game_dat`).
    path: Option<PathBuf>,
    /// The loaded, editable form model (None until Load runs / after Reload-clears).
    loaded: Option<LoadedGameDat>,
    /// Back up the original before an in-place overwrite (default ON).
    backup: bool,
    /// Receiver for a running Load/Save job's heavy result (the loaded/reloaded model).
    result_rx: Option<Receiver<GameDatResult>>,
}

impl Default for GameDatState {
    fn default() -> Self {
        Self {
            path: None,
            loaded: None,
            backup: true,
            result_rx: None,
        }
    }
}

/// The Verify section's scratch state: the single-file pick + its last verdict, and the corpus
/// folder + its last per-file results. A background job hands results back via `result_rx`.
struct VerifyState {
    /// The single data file to round-trip.
    file: Option<PathBuf>,
    /// The last single-file verdict (shown in the result panel until re-run/cleared).
    file_verdict: Option<(PathBuf, Verdict)>,
    /// The folder to verify as a corpus.
    corpus_dir: Option<PathBuf>,
    /// The last corpus run's per-file rows + summary.
    corpus: Option<CorpusOutcome>,
    /// Receiver for a running job's heavy result (a single verdict or a whole corpus outcome).
    result_rx: Option<Receiver<VerifyResult>>,
}

impl Default for VerifyState {
    fn default() -> Self {
        Self {
            file: None,
            file_verdict: None,
            corpus_dir: None,
            corpus: None,
            result_rx: None,
        }
    }
}

/// The heavy result a background Verify job hands back to the UI thread (mirrors [`TrResult`] /
/// [`SaveResult`]): a single file's verdict, or a whole corpus outcome.
enum VerifyResult {
    /// A single file's round-trip verdict, with the file it was run on.
    Single(PathBuf, Box<Verdict>),
    /// A whole corpus run's outcome.
    Corpus(Box<CorpusOutcome>),
}

/// A heavy result a background translation job hands back to the UI thread. The shared
/// [`JobManager`] only carries progress/log/summary. This side-channel carries the actual model the
/// job built so the UI can swap it in once the job lands.
enum TrResult {
    /// A freshly extracted (or merged-into) model replaces the current one.
    Model(Box<TranslationModel>),
    /// The name-conflict check's findings, to render in the conflicts panel.
    Conflicts(Vec<Conflict>),
}

/// The Translation section's scratch state: the source folder, the loaded editable model, the grid
/// controls (selection / filter / counters), the inject options + output choice, and the
/// side-channel a background job uses to hand a rebuilt model back to the UI.
struct TranslationState {
    /// The data dir to extract from (defaults to the open project's `data_dir`).
    source_dir: Option<PathBuf>,
    /// The loaded editable model (None until Extract / Load runs).
    model: Option<TranslationModel>,
    /// Which left-list entry is selected: `None` = the names glossary, `Some(i)` = files\[i\].
    selected: SelectedEntry,
    /// The grid's text filter (matches source or translation, case-insensitive).
    filter: String,
    /// Show only rows that are still untranslated.
    untranslated_only: bool,
    /// `--en-punct`: normalize Japanese punctuation to ASCII on inject.
    en_punct: bool,
    /// `--allow-code-drift`: relax the inline-code preservation guard on inject.
    allow_code_drift: bool,
    /// Output target: in-place when `None`, else a chosen output dir.
    out_dir: Option<PathBuf>,
    /// The last name-conflict check's findings (shown in a small panel until re-run/cleared).
    conflicts: Vec<Conflict>,
    /// Receiver for a running job's heavy result (the rebuilt model / conflicts).
    result_rx: Option<Receiver<TrResult>>,
}

/// Which left-list entry the grid is showing.
#[derive(Clone, Copy, PartialEq, Eq)]
enum SelectedEntry {
    Names,
    File(usize),
}

impl Default for TranslationState {
    fn default() -> Self {
        Self {
            source_dir: None,
            model: None,
            selected: SelectedEntry::Names,
            filter: String::new(),
            untranslated_only: false,
            en_punct: false,
            allow_code_drift: false,
            out_dir: None,
            conflicts: Vec::new(),
            result_rx: None,
        }
    }
}

/// The heavy result a background Saves job hands back to the UI thread, mirroring [`TrResult`]: the
/// shared [`JobManager`] only carries progress/log/summary, so the freshly-inspected save (or the
/// re-inspect after a write) comes back over this per-section side-channel.
enum SaveResult {
    /// A freshly inspected (or re-inspected) save replaces the loaded one.
    Loaded(Box<LoadedSave>),
}

/// Which source the batch title comes from.
#[derive(Clone, Copy, PartialEq, Eq)]
enum BatchTitleMode {
    /// No title change in the batch (only refresh strings).
    None,
    /// A literally-typed title.
    Typed,
    /// The title read from a chosen (translated) `Game.dat`.
    FromGameDat,
}

/// The Saves section's scratch state: the single-file open inputs + the loaded/editable save, and
/// the batch-update inputs. A background job hands a (re-)inspected save back via `result_rx`.
struct SavesState {
    /// The `.sav` the user picked to inspect (single-file flow).
    sav_path: Option<PathBuf>,
    /// The loaded, editable save (None until Inspect runs / after a clear).
    loaded: Option<LoadedSave>,
    /// The string-table filter (matches original or edited, case-insensitive).
    filter: String,
    /// Back up the original before writing (default ON), for both single + batch flows.
    backup: bool,
    /// Receiver for a running single-file job's heavy result (the inspected save).
    result_rx: Option<Receiver<SaveResult>>,

    // --- batch flow ---
    /// The save folder to batch-update.
    batch_dir: Option<PathBuf>,
    /// Where the batch title comes from.
    batch_title_mode: BatchTitleMode,
    /// The typed batch title (used when `batch_title_mode == Typed`).
    batch_title: String,
    /// The translated `Game.dat` to read a title from (used when `batch_title_mode == FromGameDat`).
    batch_game_dat: Option<PathBuf>,
    /// Optional translation file/dir(s) to refresh baked strings from in the batch.
    batch_translations: Option<PathBuf>,
}

impl Default for SavesState {
    fn default() -> Self {
        Self {
            sav_path: None,
            loaded: None,
            filter: String::new(),
            backup: true,
            result_rx: None,
            batch_dir: None,
            batch_title_mode: BatchTitleMode::None,
            batch_title: String::new(),
            batch_game_dat: None,
            batch_translations: None,
        }
    }
}

/// The application. `eframe` calls [`eframe::App::update`] each frame.
pub struct WolfDawnApp {
    /// The active navigation section.
    section: Section,
    /// The open game, if any.
    project: Option<Project>,
    /// The scrolling activity log (bottom panel).
    log: Log,
    /// Background-job manager (progress bar + worker threads).
    jobs: JobManager,
    /// Per-section UI state.
    state: SectionState,
    /// Persisted user preferences (theme + section defaults + auto-detect gate).
    settings: Settings,
    /// When the open project's file index was last re-walked, for throttling the live auto-detect
    /// in [`render_frame`](Self::render_frame). `None` until the first tick (or while no project).
    last_scan: Option<Instant>,
    /// The output dir of an in-flight Unpack job, if any. Set when an Unpack starts. Consumed when
    /// it finishes to immediately rescan the index (and adopt the dir as `data_dir` when it sits
    /// under the project root) so the freshly-extracted files show in the dropdowns at once.
    pending_unpack_out: Option<PathBuf>,
    /// Whether a job was running on the previous frame, so the per-frame tick can detect the
    /// running→idle transition (job-just-finished) without a completion callback in `JobManager`.
    job_was_running: bool,
}

impl Default for WolfDawnApp {
    fn default() -> Self {
        let mut log = Log::new();
        log.info("WolfDawn Studio ready. Open a game from the Project section to begin.");
        Self {
            section: Section::Project,
            project: None,
            log,
            jobs: JobManager::new(),
            state: SectionState::default(),
            settings: Settings::default(),
            last_scan: None,
            pending_unpack_out: None,
            job_was_running: false,
        }
    }
}

impl WolfDawnApp {
    /// The eframe storage key the persisted [`Settings`] live under.
    const SETTINGS_KEY: &'static str = "settings";

    /// Construct the app for an eframe creation context. Installs a Japanese fallback font so CJK
    /// text renders instead of tofu, loads the persisted [`Settings`]
    /// (theme + defaults) from eframe storage, applies the theme, and seeds the sections' option
    /// flags from the saved defaults so a returning user gets their preferences on startup.
    pub fn new(cc: &eframe::CreationContext<'_>) -> Self {
        install_cjk_font(&cc.egui_ctx);
        let mut app = Self::default();
        // Restore the saved settings (falls back to defaults the first run / if storage is empty).
        if let Some(storage) = cc.storage {
            if let Some(saved) = eframe::get_value::<Settings>(storage, Self::SETTINGS_KEY) {
                app.settings = saved;
            }
        }
        app.apply_theme(&cc.egui_ctx);
        app.seed_section_defaults();
        app
    }

    /// Apply the current theme preference to the egui context (called on startup + on every toggle).
    fn apply_theme(&self, ctx: &egui::Context) {
        ctx.set_visuals(if self.settings.dark_mode {
            egui::Visuals::dark()
        } else {
            egui::Visuals::light()
        });
    }

    /// Seed the sections' option flags from the persisted [`Settings`] defaults. Called once on
    /// startup (and after a "reset" could be added later); sections then own those flags for the
    /// session, so toggling a section checkbox is never clobbered by the settings default.
    fn seed_section_defaults(&mut self) {
        self.state.translation.en_punct = self.settings.default_en_punct;
        self.state.translation.allow_code_drift = self.settings.default_allow_code_drift;
        self.state.saves.backup = self.settings.default_backup;
        self.state.database.backup = self.settings.default_backup;
        self.state.gamedat.backup = self.settings.default_backup;
    }

    // --- the section dispatch -------------------------------------------------------------

    /// Render the body of the currently-selected section into `ui`. Public so the headless smoke
    /// test can drive each section without a window.
    pub fn render_current_section(&mut self, ui: &mut egui::Ui) {
        match self.section {
            Section::Project => self.ui_project(ui),
            Section::Archive => self.ui_archive(ui),
            Section::Decompile => self.ui_decompile(ui),
            Section::Database => self.ui_database(ui),
            Section::GameDat => self.ui_gamedat(ui),
            Section::Translation => self.ui_translation(ui),
            Section::Saves => self.ui_saves(ui),
            Section::Verify => self.ui_verify(ui),
            Section::Settings => self.ui_settings(ui),
        }
    }

    /// Switch the active section. The sidebar sets it inline. This is the programmatic entry the
    /// smoke tests use to walk every section.
    #[allow(dead_code)]
    pub fn set_section(&mut self, section: Section) {
        self.section = section;
    }

    /// Install a translation model into the Translation section (test-only entry so the headless
    /// render smoke test can exercise the grid with a loaded model, not just the empty state).
    #[cfg(test)]
    pub fn set_translation_model(&mut self, model: TranslationModel) {
        self.state.translation.selected = if model.files.is_empty() {
            SelectedEntry::Names
        } else {
            SelectedEntry::File(0)
        };
        self.state.translation.model = Some(model);
    }

    /// Install a loaded save into the Saves section (test-only entry so the headless render smoke
    /// test can exercise the save editor + string table with a real loaded save).
    #[cfg(test)]
    pub fn set_loaded_save(&mut self, loaded: LoadedSave) {
        self.state.saves.loaded = Some(loaded);
    }

    /// Install WolfScript + its base into the Decompile section (test-only entry so the headless
    /// render smoke test can exercise the code editor + Compile controls with real content).
    #[cfg(test)]
    pub fn set_decompile_script(&mut self, input: PathBuf, script: String) {
        self.state.decompile.base = Some(input.clone());
        self.state.decompile.input = Some(input);
        self.state.decompile.script = script;
    }

    /// Open the Decompile find bar with `query` (test-only entry so the headless render smoke test
    /// can exercise the find bar + a query on a loaded script without panicking).
    #[cfg(test)]
    pub fn open_decompile_find(&mut self, query: &str) {
        self.state.decompile.find.open = true;
        self.state.decompile.find.query = query.to_string();
        // Trigger an initial jump-to-first-match, the way a fresh query would.
        let matches = decompile::find_matches(
            &self.state.decompile.script,
            query,
            self.state.decompile.find.case_sensitive,
        );
        if let Some(m) = matches.first() {
            self.state.decompile.find.pending_select = Some((m.start, m.end));
        }
    }

    /// Install a loaded Game.dat model into the Game.dat section (test-only entry so the headless
    /// render smoke test can exercise the field form with a real loaded file).
    #[cfg(test)]
    pub fn set_gamedat_loaded(&mut self, loaded: LoadedGameDat) {
        self.state.gamedat.loaded = Some(loaded);
    }

    /// Install a loaded database model into the Database section (test-only entry so the headless
    /// render smoke test can exercise the grid with a real loaded DB).
    #[cfg(test)]
    pub fn set_database_loaded(&mut self, loaded: DbModel) {
        self.state.database.loaded = Some(loaded);
    }

    // --- Unload / clear (free a section's loaded data so the RAM returns to the OS) -------------
    // Dropping the model frees its memory; with the mimalloc allocator that memory is handed back to
    // the OS, so unloading a file you are done with actually lowers the process footprint. Paths are
    // kept so the file can be reloaded with one click.

    /// Drop the loaded database grid (its rows/cells). Discards unsaved edits.
    fn unload_database(&mut self) {
        self.state.database.loaded = None;
        self.state.database.selected_type = 0;
        self.state.database.filter.clear();
    }

    /// Drop the decompiled script (and its editor layout). Discards unsaved edits.
    fn clear_decompile(&mut self) {
        self.state.decompile.script = String::new();
        self.state.decompile.find = FindState::default();
    }

    /// Drop the loaded translation model (every file's rows + docs + the glossary). Discards unsaved
    /// edits. The source folder is kept so Extract can rebuild it.
    fn unload_translation(&mut self) {
        self.state.translation.model = None;
        self.state.translation.conflicts.clear();
        self.state.translation.selected = SelectedEntry::Names;
        self.state.translation.filter.clear();
    }

    /// Drop the loaded Game.dat model. Discards unsaved edits.
    fn unload_gamedat(&mut self) {
        self.state.gamedat.loaded = None;
    }

    /// Drop the loaded save. Discards unsaved edits.
    fn unload_save(&mut self) {
        self.state.saves.loaded = None;
    }

    /// Install an open project (test-only entry so the headless render smoke test can exercise the
    /// per-section dropdowns + the Settings section with a project loaded).
    #[cfg(test)]
    pub fn set_project(&mut self, project: Project) {
        self.project = Some(project);
    }

    // --- Project section ------------------------------------------------------------------

    fn ui_project(&mut self, ui: &mut egui::Ui) {
        ui.heading("Project");
        widgets::caption(
            ui,
            "Open a Wolf RPG game to read its Game.dat and locate Data.wolf / the unpacked Data folder.",
        );
        ui.add_space(8.0);

        ui.horizontal(|ui| {
            if ui
                .button("Open Game…")
                .on_hover_text("Pick the game folder, or a Data.wolf / Game.dat file.")
                .clicked()
            {
                if let Some(picked) = widgets::pick_folder() {
                    self.open_from(picked);
                }
            }
            if ui
                .button("Open File…")
                .on_hover_text("Pick a Data.wolf archive or a Game.dat directly.")
                .clicked()
            {
                if let Some(picked) = widgets::pick_file(&[
                    ("Wolf archive / Game data", &["wolf", "dat"]),
                    ("All files", &["*"]),
                ]) {
                    self.open_from(picked);
                }
            }
            if self.project.is_some() {
                if ui
                    .button("Refresh")
                    .on_hover_text("Re-scan the game's folders now for newly-added maps / databases / saves.")
                    .clicked()
                {
                    self.refresh_project_index();
                }
                if ui.button("Close").on_hover_text("Close the open game.").clicked() {
                    self.project = None;
                    self.last_scan = None;
                    self.log.info("closed project");
                }
            }
        });

        ui.add_space(12.0);
        ui.separator();
        ui.add_space(8.0);

        match &self.project {
            None => {
                widgets::caption(ui, "No project open.");
            }
            Some(p) => project_details(ui, p),
        }
    }

    /// Open a project from a picked path (synchronous, Game.dat parsing is fast). Routes the
    /// outcome notes into the log.
    fn open_from(&mut self, picked: PathBuf) {
        self.log.info(format!("opening {}…", picked.display()));
        let outcome = project::open_project(&picked);
        for (level, msg) in outcome.notes {
            match level {
                NoteLevel::Info => self.log.info(msg),
                NoteLevel::Warn => self.log.warn(msg),
            }
        }
        self.project = Some(outcome.project);
        // A fresh open resets the auto-detect clock so the next tick rescans promptly.
        self.last_scan = None;
    }

    /// Manually re-scan the open project's index now (the Project section's Refresh button),
    /// logging whether anything changed.
    fn refresh_project_index(&mut self) {
        let Some(project) = self.project.as_mut() else {
            return;
        };
        if project.rescan() {
            self.log.info(format!(
                "refreshed: {} code file(s), {} database(s), {} save(s)",
                project.code_files.len(),
                project.databases.len(),
                project.saves.len(),
            ));
        } else {
            self.log.info("refreshed: no changes");
        }
        self.last_scan = Some(Instant::now());
    }

    // --- Archive section: unpack a .wolf / repack a folder ---------------------------------

    fn ui_archive(&mut self, ui: &mut egui::Ui) {
        ui.heading("Archive");
        widgets::caption(
            ui,
            "Unpack Data.wolf to an editable folder, or repack a folder back into a Data.wolf.",
        );
        widgets::caption(
            ui,
            "Most workflows run on the loose, unpacked Data folder; encryption/version only matter \
             if you are shipping an encrypted archive.",
        );
        ui.add_space(6.0);

        // Seed the unpack archive + the repack folder from the open project the first time we show.
        self.archive_default_paths();

        // Sub-panel selector (Unpack / Unpack all / Repack).
        ui.horizontal(|ui| {
            ui.selectable_value(&mut self.state.archive.mode, ArchiveMode::Unpack, "Unpack")
                .on_hover_text("Extract one Data.wolf to an editable folder.");
            ui.selectable_value(&mut self.state.archive.mode, ArchiveMode::UnpackAll, "Unpack all")
                .on_hover_text(
                    "Some games split their data across many .wolf files (BasicData.wolf, \
                     MapData.wolf, Evtext.wolf, ...). This unpacks every archive in a folder at once.",
                );
            ui.selectable_value(&mut self.state.archive.mode, ArchiveMode::Repack, "Repack")
                .on_hover_text("Rebuild Data.wolf from a folder.");
        });
        ui.add_space(6.0);
        ui.separator();
        ui.add_space(6.0);

        match self.state.archive.mode {
            ArchiveMode::Unpack => self.archive_unpack_pane(ui),
            ArchiveMode::UnpackAll => self.archive_unpack_all_pane(ui),
            ArchiveMode::Repack => self.archive_repack_pane(ui),
        }
    }

    /// Seed the unpack archive + the repack input folder from the open project (its `data_wolf` /
    /// `root`), once, so a project user has sensible defaults.
    fn archive_default_paths(&mut self) {
        if self.state.archive.unpack_archive.is_none() {
            if let Some(p) = self.project.as_ref().and_then(|p| p.data_wolf.clone()) {
                self.state.archive.unpack_archive = Some(p);
            }
        }
        if self.state.archive.repack_in.is_none() {
            if let Some(d) = self.project.as_ref().and_then(|p| p.data_dir.clone()) {
                self.state.archive.repack_in = Some(d);
            }
        }
        // Unpack-all defaults to the folder holding the archives: the project data dir, else the
        // folder the single Data.wolf sits in.
        if self.state.archive.unpack_all_dir.is_none() {
            let guess = self
                .project
                .as_ref()
                .and_then(|p| p.data_dir.clone())
                .or_else(|| {
                    self.project
                        .as_ref()
                        .and_then(|p| p.data_wolf.as_ref())
                        .and_then(|w| w.parent().map(std::path::Path::to_path_buf))
                });
            if let Some(d) = guess {
                self.state.archive.unpack_all_dir = Some(d);
            }
        }
    }

    /// The Unpack pane: pick a `.wolf` + an output folder (default `<archive_dir>/Data`), then Unpack.
    fn archive_unpack_pane(&mut self, ui: &mut egui::Ui) {
        let mut archive = self.state.archive.unpack_archive.clone();
        let changed = widgets::path_field(
            ui,
            "Archive",
            &mut archive,
            "Unpack = extract Data.wolf to an editable folder. Pick the .wolf to extract.",
            || widgets::pick_file(&[("Wolf archive", &["wolf"]), ("All files", &["*"])]),
        );
        self.state.archive.unpack_archive = archive;
        // Default the output folder to <archive_dir>/Data when a fresh archive is picked (or first show).
        if (changed || self.state.archive.unpack_out.is_none())
            && self.state.archive.unpack_archive.is_some()
        {
            if let Some(arc) = &self.state.archive.unpack_archive {
                let default_out = arc.parent().map(|d| d.join("Data"));
                if self.state.archive.unpack_out.is_none() || changed {
                    self.state.archive.unpack_out = default_out;
                }
            }
        }

        let start = self.state.archive.unpack_out.clone();
        let mut out = self.state.archive.unpack_out.clone();
        widgets::path_field(
            ui,
            "Output folder",
            &mut out,
            "Where to extract the archive's files (its inner folder tree is preserved).",
            move || widgets::pick_folder_in(start.as_deref()),
        );
        self.state.archive.unpack_out = out;

        ui.add_space(8.0);
        let running = self.jobs.is_running();
        let ready = self.state.archive.unpack_archive.is_some()
            && self.state.archive.unpack_out.is_some();
        ui.add_enabled_ui(ready && !running, |ui| {
            if ui
                .button("Unpack ▶")
                .on_hover_text("Extract every file from the archive into the output folder on a background thread.")
                .clicked()
            {
                self.start_unpack_job();
            }
        });
        if !ready {
            widgets::caption(ui, "Pick a .wolf archive and an output folder to enable Unpack.");
        }
    }

    /// The Unpack-all pane: pick the folder of `.wolf` archives and an output root, then unpack
    /// every archive at once. Each `Name.wolf` becomes a `Name/` folder under the output, the loose
    /// per-category tree the game loads and the Translation section can read.
    fn archive_unpack_all_pane(&mut self, ui: &mut egui::Ui) {
        let start_dir = self.state.archive.unpack_all_dir.clone();
        let mut dir = self.state.archive.unpack_all_dir.clone();
        let changed = widgets::path_field(
            ui,
            "Archives folder",
            &mut dir,
            "The folder holding the game's .wolf archives (its Data folder). Every .wolf in it is unpacked.",
            move || widgets::pick_folder_in(start_dir.as_deref()),
        );
        self.state.archive.unpack_all_dir = dir;
        // Default the output root to the archives folder itself (unpack in place, the layout the
        // game loads), refreshed when a new folder is picked.
        if (changed || self.state.archive.unpack_all_out.is_none())
            && self.state.archive.unpack_all_dir.is_some()
        {
            self.state.archive.unpack_all_out = self.state.archive.unpack_all_dir.clone();
        }

        let start_out = self.state.archive.unpack_all_out.clone();
        let mut out = self.state.archive.unpack_all_out.clone();
        widgets::path_field(
            ui,
            "Output root",
            &mut out,
            "Where the per-archive folders are written. Defaults to the archives folder, so the \
             loose files sit beside the .wolf and the game loads them.",
            move || widgets::pick_folder_in(start_out.as_deref()),
        );
        self.state.archive.unpack_all_out = out;

        ui.add_space(8.0);
        let running = self.jobs.is_running();
        let ready = self.state.archive.unpack_all_dir.is_some()
            && self.state.archive.unpack_all_out.is_some();
        ui.add_enabled_ui(ready && !running, |ui| {
            if ui
                .button("Unpack all ▶")
                .on_hover_text("Unpack every .wolf in the folder, each into its own subfolder, on a background thread.")
                .clicked()
            {
                self.start_unpack_all_job();
            }
        });
        if !ready {
            widgets::caption(ui, "Pick the folder of .wolf archives and an output root to enable Unpack all.");
        }
    }

    /// The Repack pane: pick a folder + output `.wolf`, set the encrypt/version/like/format options
    /// (mirroring the CLI `pack` flags), then Repack.
    fn archive_repack_pane(&mut self, ui: &mut egui::Ui) {
        let start_in = self.state.archive.repack_in.clone();
        let mut input = self.state.archive.repack_in.clone();
        widgets::path_field(
            ui,
            "Input folder",
            &mut input,
            "Repack = rebuild Data.wolf from a folder. Pick the folder of loose game files to pack.",
            move || widgets::pick_folder_in(start_in.as_deref()),
        );
        self.state.archive.repack_in = input;

        let mut out = self.state.archive.repack_out.clone();
        widgets::path_field(
            ui,
            "Output .wolf",
            &mut out,
            "Where to write the rebuilt archive.",
            || widgets::save_file("Data.wolf", &[("Wolf archive", &["wolf"])]),
        );
        self.state.archive.repack_out = out;

        ui.add_space(8.0);
        // Format dropdown (auto / ver5 / ver6) in a shared form row so its label lines up with
        // the path rows above.
        widgets::form_row(
            ui,
            "Format",
            "auto = the modern Data.wolf container. ver5/ver6 are legacy DXArchive containers for \
             old Wolf 2.0x games - leave on auto unless you specifically need them.",
            |ui| {
                egui::ComboBox::from_id_salt("repack_format")
                    .selected_text(self.state.archive.repack_format.label())
                    .show_ui(ui, |ui| {
                        for f in [PackFormat::Auto, PackFormat::Ver5, PackFormat::Ver6] {
                            ui.selectable_value(&mut self.state.archive.repack_format, f, f.label());
                        }
                    });
            },
        );

        // Encryption is only meaningful for the modern (auto) container.
        let auto = self.state.archive.repack_format == PackFormat::Auto;
        ui.add_enabled_ui(auto, |ui| {
            widgets::labeled_checkbox(
                ui,
                &mut self.state.archive.repack_encrypt,
                "Encrypt",
                "Encrypt the output archive. Usually only needed when shipping an encrypted \
                 Data.wolf; most workflows leave this off and run the game on a loose Data folder.",
            );
        });

        // The crypt-source radio + its inputs, shown only when encrypting an auto archive.
        if auto && self.state.archive.repack_encrypt {
            ui.add_space(2.0);
            ui.horizontal(|ui| {
                ui.radio_value(
                    &mut self.state.archive.repack_crypt,
                    RepackCryptMode::Default,
                    "default version",
                )
                .on_hover_text("Use the standard default cryptVersion.");
                ui.radio_value(
                    &mut self.state.archive.repack_crypt,
                    RepackCryptMode::Version,
                    "match version",
                )
                .on_hover_text("Type a specific cryptVersion (e.g. 0x14b).");
                ui.radio_value(
                    &mut self.state.archive.repack_crypt,
                    RepackCryptMode::Like,
                    "like existing .wolf",
                )
                .on_hover_text("Inherit the cryptVersion + embedded password from an original archive (turnkey repack).");
            });
            match self.state.archive.repack_crypt {
                RepackCryptMode::Default => {}
                RepackCryptMode::Version => {
                    widgets::form_row(ui, "Version", "", |ui| {
                        ui.add(
                            egui::TextEdit::singleline(&mut self.state.archive.repack_version_text)
                                .hint_text("0x14b")
                                .desired_width(120.0),
                        )
                        .on_hover_text("A cryptVersion as hex (0x14b) or decimal.");
                    });
                    if parse_crypt_version(&self.state.archive.repack_version_text).is_none() {
                        ui.colored_label(
                            egui::Color32::from_rgb(0xE0, 0xB0, 0x40),
                            "Warning: not a valid version number",
                        );
                    }
                }
                RepackCryptMode::Like => {
                    let mut like = self.state.archive.repack_like.clone();
                    widgets::path_field(
                        ui,
                        "Original .wolf",
                        &mut like,
                        "An existing encrypted archive to copy the crypto from.",
                        || widgets::pick_file(&[("Wolf archive", &["wolf"]), ("All files", &["*"])]),
                    );
                    self.state.archive.repack_like = like;
                }
            }
        }

        ui.add_space(8.0);
        let running = self.jobs.is_running();
        let ready = self.repack_ready();
        ui.add_enabled_ui(ready && !running, |ui| {
            if ui
                .button("Repack ▶")
                .on_hover_text("Rebuild the archive from the folder on a background thread.")
                .clicked()
            {
                self.start_repack_job();
            }
        });
        if !ready {
            widgets::caption(
                ui,
                "Pick an input folder and an output .wolf (and, for \"like\"/\"match\", a valid \
                 source/version) to enable Repack.",
            );
        }
    }

    /// True when the Repack inputs are complete enough to run (folder + output, and a resolvable
    /// crypt source when encrypting).
    fn repack_ready(&self) -> bool {
        let a = &self.state.archive;
        if a.repack_in.is_none() || a.repack_out.is_none() {
            return false;
        }
        if a.repack_format == PackFormat::Auto && a.repack_encrypt {
            return match a.repack_crypt {
                RepackCryptMode::Default => true,
                RepackCryptMode::Version => parse_crypt_version(&a.repack_version_text).is_some(),
                RepackCryptMode::Like => a.repack_like.is_some(),
            };
        }
        true
    }

    /// Spawn the Unpack job: extract the archive into the output folder on a worker thread, reusing
    /// the library's `extract_archive` via [`archive::unpack`]. Bad/odd filenames are sanitised and
    /// reported, never written outside the output folder.
    fn start_unpack_job(&mut self) {
        let Some(arc) = self.state.archive.unpack_archive.clone() else {
            return;
        };
        let Some(out) = self.state.archive.unpack_out.clone() else {
            return;
        };
        // Remember the output dir so the running→idle transition can rescan it (and adopt it as the
        // project's data_dir when it sits under the project root) the moment the job finishes.
        self.pending_unpack_out = Some(out.clone());
        self.jobs.run(format!("Unpack {}", arc.display()), &mut self.log, move |rep| {
            let outcome = archive::unpack(&arc, &out, |frac, msg| rep.progress(frac, msg))?;
            for (orig, safe) in &outcome.sanitised {
                if safe.is_empty() {
                    rep.warn(format!("skipped odd archive entry {orig:?} (no safe path)"));
                } else {
                    rep.warn(format!("sanitised archive path {orig:?} → {safe:?}"));
                }
            }
            rep.info(format!("{} file(s) → {}", outcome.written, outcome.out_dir.display()));
            Ok(format!("{} file(s) → {}", outcome.written, outcome.out_dir.display()))
        });
    }

    /// Spawn the Unpack-all job: unpack every `.wolf` in the chosen folder into per-archive
    /// subfolders on a worker thread, reusing [`archive::unpack_all`]. Each archive's result is
    /// logged, and the output root is rescanned when the job finishes (so new files show up).
    fn start_unpack_all_job(&mut self) {
        let Some(dir) = self.state.archive.unpack_all_dir.clone() else {
            return;
        };
        let Some(out) = self.state.archive.unpack_all_out.clone() else {
            return;
        };
        self.pending_unpack_out = Some(out.clone());
        self.jobs.run(format!("Unpack all in {}", dir.display()), &mut self.log, move |rep| {
            let outcome = archive::unpack_all(&dir, &out, |frac, msg| rep.progress(frac, msg))?;
            for (name, res) in &outcome.details {
                match res {
                    Ok(n) => rep.info(format!("{name} → {n} file(s)")),
                    Err(e) => rep.warn(format!("{name} failed: {e}")),
                }
            }
            let summary = if outcome.failed > 0 {
                format!(
                    "{} archive(s), {} file(s) → {} ({} failed)",
                    outcome.ok,
                    outcome.files,
                    outcome.out_root.display(),
                    outcome.failed
                )
            } else {
                format!(
                    "{} archive(s), {} file(s) → {}",
                    outcome.ok,
                    outcome.files,
                    outcome.out_root.display()
                )
            };
            Ok(summary)
        });
    }

    /// Spawn the Repack job: gather the folder + pack it with the chosen options on a worker thread,
    /// reusing the library `pack_*` paths via [`archive::repack`].
    fn start_repack_job(&mut self) {
        let a = &self.state.archive;
        let Some(input) = a.repack_in.clone() else {
            return;
        };
        let Some(out) = a.repack_out.clone() else {
            return;
        };
        // Assemble the PackOptions from the UI (resolve the crypt source).
        let crypt = match a.repack_crypt {
            RepackCryptMode::Default => CryptSource::Default,
            RepackCryptMode::Version => match parse_crypt_version(&a.repack_version_text) {
                Some(v) => CryptSource::Version(v),
                None => {
                    self.log.error("repack: invalid cryptVersion");
                    return;
                }
            },
            RepackCryptMode::Like => match a.repack_like.clone() {
                Some(p) => CryptSource::Like(p),
                None => {
                    self.log.error("repack: pick an original .wolf for \"like existing\"");
                    return;
                }
            },
        };
        let opts = PackOptions {
            encrypt: a.repack_encrypt,
            crypt,
            format: a.repack_format,
        };
        self.jobs.run(format!("Repack → {}", out.display()), &mut self.log, move |rep| {
            let outcome = archive::repack(&input, &out, &opts, |frac, msg| rep.progress(frac, msg))?;
            Ok(format!(
                "{} file(s) → {} ({} bytes, {})",
                outcome.files,
                outcome.out.display(),
                outcome.bytes,
                outcome.mode
            ))
        });
    }

    // --- stubbed sections -----------------------------------------------------------------

    fn ui_decompile(&mut self, ui: &mut egui::Ui) {
        // Pump any background result (the freshly-decompiled WolfScript) into section state first, so
        // the rest of this frame renders what the just-finished job produced.
        self.poll_decompile_result();

        ui.heading("Decompile");
        widgets::caption(ui, "Render maps and common events to readable, editable WolfScript - and recompile byte-exact.");
        ui.add_space(6.0);

        // Ctrl+F toggles the find bar (only meaningful once a script is loaded). Consuming the
        // shortcut here keeps it working from anywhere in the section.
        let have_script = !self.state.decompile.script.is_empty();
        if have_script
            && ui.input_mut(|i| i.consume_key(egui::Modifiers::COMMAND, egui::Key::F))
        {
            let f = &mut self.state.decompile.find;
            f.open = true;
            f.focus_query = true; // grab the query field next frame so the user can type at once.
        }

        // Default the input to the open project's data dir (no file pre-selected) the first time.
        self.decompile_input_row(ui);
        ui.add_space(6.0);
        self.decompile_action_row(ui);
        ui.add_space(6.0);
        ui.separator();
        ui.add_space(6.0);
        self.decompile_editor(ui);
    }

    /// The input field + the Decompile button.
    fn decompile_input_row(&mut self, ui: &mut egui::Ui) {
        // A project dropdown of the scanned code files (MapData/*.mps + CommonEvent.dat), above the
        // Browse field for files outside the project.
        if let Some(code) = self.project.as_ref().map(|p| p.code_files.clone()) {
            let mut input = self.state.decompile.input.clone();
            if project_combo(
                ui,
                "decompile_combo",
                "Project file",
                &code,
                &mut input,
                "Pick a map / CommonEvent from the open game (or use Browse below for a file outside it).",
            ) {
                self.state.decompile.input = input;
            }
        }

        // Seed the picker's start dir from the open project's data dir. Don't auto-pick a file,
        // since there are many candidate .mps maps and the user chooses.
        let start = self
            .project
            .as_ref()
            .and_then(|p| p.data_dir.clone());
        let mut input = self.state.decompile.input.clone();
        widgets::path_field(
            ui,
            "Input",
            &mut input,
            "Decompile = turn a map/common-event into readable WolfScript you can edit. Pick a .mps \
             map or CommonEvent.dat.",
            move || {
                widgets::pick_file_in(
                    start.as_deref(),
                    &[("Wolf event file", &["mps", "dat"]), ("All files", &["*"])],
                )
            },
        );
        self.state.decompile.input = input;

        // Warn early if the pick isn't a code-bearing file. Decompile still runs and gives a clear error.
        if let Some(f) = &self.state.decompile.input {
            if !decompile::is_supported(f) {
                ui.colored_label(
                    egui::Color32::from_rgb(0xE0, 0xB0, 0x40),
                    "Warning: not a decompilable file (decompile supports .mps maps and CommonEvent.dat).",
                );
            }
        }
    }

    /// The action row: Decompile, plus Open/Save .wscript and the Compile controls.
    fn decompile_action_row(&mut self, ui: &mut egui::Ui) {
        let running = self.jobs.is_running();
        let have_input = self.state.decompile.input.is_some();
        ui.horizontal(|ui| {
            ui.add_enabled_ui(have_input && !running, |ui| {
                if ui
                    .button("Decompile ▶")
                    .on_hover_text("Decompile the input to editable WolfScript on a background thread.")
                    .clicked()
                {
                    self.start_decompile_job();
                }
            });
            ui.add_enabled_ui(!running, |ui| {
                if ui
                    .button("Open .wscript…")
                    .on_hover_text("Load an existing WolfScript document to compile (its base is the Input above).")
                    .clicked()
                {
                    self.decompile_open_script();
                }
                if !self.state.decompile.script.is_empty()
                    && ui
                        .button("Save .wscript…")
                        .on_hover_text("Export the current WolfScript text to a .wscript file.")
                        .clicked()
                {
                    self.decompile_save_script();
                }
                if !self.state.decompile.script.is_empty()
                    && ui
                        .button("Clear")
                        .on_hover_text("Close the script and free its memory (a large file's editor layout is the heaviest thing the GUI holds). Discards unsaved edits.")
                        .clicked()
                {
                    self.clear_decompile();
                }
            });
        });

        // The Compile row: output target + the Compile button (needs a script + a base).
        let mut out = self.state.decompile.out.clone();
        let start = out.clone().or_else(|| self.state.decompile.input.clone());
        widgets::path_field(
            ui,
            "Compile to",
            &mut out,
            "Where Compile writes the recompiled file (defaults to <input>.out).",
            move || widgets::save_file(
                &start
                    .as_ref()
                    .and_then(|p| p.file_name().and_then(|s| s.to_str()))
                    .map(|n| format!("{n}.out"))
                    .unwrap_or_else(|| "compiled.out".to_string()),
                &[("Wolf event file", &["mps", "dat", "out"]), ("All files", &["*"])],
            ),
        );
        self.state.decompile.out = out;

        let have_script = !self.state.decompile.script.is_empty();
        let have_base = self.state.decompile.base.is_some() || self.state.decompile.input.is_some();
        ui.add_enabled_ui(have_script && have_base && !running, |ui| {
            if ui
                .button("Compile ▶")
                .on_hover_text("Compile needs the original file as a base so unknown bytes are preserved. Recompiles the edited WolfScript onto the base.")
                .clicked()
            {
                self.start_compile_job();
            }
        });
        if !have_script {
            widgets::caption(ui, "Decompile a file (or Open a .wscript) to enable Compile.");
        } else if !have_base {
            widgets::caption(ui, "Pick the original Input file (the compile base) to enable Compile.");
        }
    }

    /// The WolfScript editor: a large monospace code editor inside a scroll area, with a line count.
    ///
    /// Perf: egui re-lays-out the whole `TextEdit` buffer every frame, and word-wrapping is the
    /// dominant cost. Wrapping forces per-glyph width measurement of every line against the viewport
    /// width on each layout pass. Giving the editor an infinite desired width inside a **both-axis**
    /// `ScrollArea` disables wrapping, so each line lays out at its natural width with no wrap-point
    /// search (horizontal scrolling instead). For code this is also the correct behaviour (lines
    /// shouldn't reflow). On a big CommonEvent (thousands of lines) this is much cheaper than a
    /// vertical-only scroll that clamps the editor to the viewport width and wraps every line each
    /// frame. No re-decompile or buffer re-allocation happens per frame. Only the TextEdit's own
    /// galley layout runs.
    fn decompile_editor(&mut self, ui: &mut egui::Ui) {
        /// Scripts at/above this size get a "large file" notice (in-app edits still work).
        const LARGE_BYTES: usize = 200 * 1024;
        /// …or at/above this many lines.
        const LARGE_LINES: usize = 5000;

        if self.state.decompile.script.is_empty() {
            widgets::caption(
                ui,
                "No WolfScript loaded. Pick a .mps map or CommonEvent.dat and press Decompile, or \
                 Open an existing .wscript.",
            );
            return;
        }
        let lines = self.state.decompile.script.lines().count();
        let chars = self.state.decompile.script.len();
        ui.horizontal(|ui| {
            ui.label(egui::RichText::new(format!("{lines} line(s) · {chars} bytes")).strong());
            if let Some(base) = &self.state.decompile.base {
                ui.separator();
                ui.label(
                    egui::RichText::new(format!("base: {}", base.display())).weak(),
                );
            }
        });

        // For very large scripts, surface the "edit externally" escape hatch. In-app edits still
        // work. Save .wscript, edit in your editor, then Open .wscript to bring it back.
        if chars >= LARGE_BYTES || lines >= LARGE_LINES {
            ui.colored_label(
                egui::Color32::from_rgb(0xE0, 0xB0, 0x40),
                "Warning: large script — editing stays responsive (lines don't wrap; scroll horizontally). \
                 For heavy edits you can Save .wscript, edit it externally, then Open .wscript.",
            );
        }
        // The find-in-editor (Ctrl+F) bar sits just above the editor. It also returns the pending
        // match (a char range) to select + scroll to in this frame's TextEdit.
        self.decompile_find_bar(ui);

        ui.add_space(4.0);
        // A generous, responsive code editor for potentially large CommonEvents. Both-axis scroll
        // plus an infinite desired width disable word-wrap (the big per-frame layout cost). See the
        // method doc. The CJK fallback is installed on the Monospace family (see `install_cjk_font`),
        // so `.code_editor()` (which uses Monospace) renders Japanese here instead of tofu.
        let pending = self.state.decompile.find.pending_select.take();
        egui::ScrollArea::both()
            .auto_shrink([false, false])
            .show(ui, |ui| {
                let mut output = egui::TextEdit::multiline(&mut self.state.decompile.script)
                    .code_editor()
                    .desired_rows(28)
                    // Infinite width means no wrap-point search. Lines lay out at natural width and
                    // the horizontal ScrollArea handles overflow.
                    .desired_width(f32::INFINITY)
                    .show(ui);

                // If the find bar asked to jump to a match, set the editor's selection to that char
                // range and scroll it into view. We set the selection on the stored state (so egui
                // shows it next frame) AND scroll directly via the galley this frame (so the jump is
                // immediate and reliable regardless of focus timing). egui's own cursor-scroll only
                // fires when the editor is focused and the selection changed.
                if let Some((start, end)) = pending {
                    use egui::text::{CCursor, CCursorRange};
                    let range = CCursorRange::two(CCursor::new(start), CCursor::new(end));
                    output.state.cursor.set_char_range(Some(range));
                    output.state.clone().store(ui.ctx(), output.response.id);
                    // Scroll the inner ScrollArea to the match's rect (galley-local to screen coords).
                    let cursor_rect = output
                        .galley
                        .pos_from_ccursor(CCursor::new(start))
                        .translate(output.galley_pos.to_vec2());
                    ui.scroll_to_rect(cursor_rect, Some(egui::Align::Center));
                    // Focus the editor so the selection highlight is visible.
                    output.response.request_focus();
                }
            });
    }

    /// The find-in-editor (Ctrl+F) bar: a query field, Prev/Next, a match counter, an optional
    /// case toggle, and a close (×). Recomputes the match list each frame from the script + query, and
    /// (on a navigation) stashes the current match's char range in `find.pending_select` for the
    /// editor to select + scroll to. Renders nothing when the bar is closed.
    fn decompile_find_bar(&mut self, ui: &mut egui::Ui) {
        if !self.state.decompile.find.open {
            return;
        }
        // Compute matches up front (immutable borrow of the script), then mutate find state.
        let matches = decompile::find_matches(
            &self.state.decompile.script,
            &self.state.decompile.find.query,
            self.state.decompile.find.case_sensitive,
        );
        let count = matches.len();

        let f = &mut self.state.decompile.find;
        // Keep `current` in range as matches change.
        if count == 0 {
            f.current = 0;
        } else if f.current >= count {
            f.current = count - 1;
        }

        // `go` is set when the user navigates this frame: +1 next, -1 prev, 0 = jump to current
        // (e.g. just after typing). We resolve it to a concrete match index at the end.
        let mut nav: Option<isize> = None;

        ui.horizontal(|ui| {
            ui.label("Find");
            // Enter = next, Shift+Enter = prev, handled via the response below.
            let resp = ui.add(
                egui::TextEdit::singleline(&mut f.query)
                    .hint_text("find in script")
                    .desired_width(220.0),
            );
            if f.focus_query {
                resp.request_focus();
                f.focus_query = false;
            }
            // On a query change, jump to the first match from the top.
            if resp.changed() {
                f.current = 0;
                nav = Some(0);
            }
            if resp.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter)) {
                let shift = ui.input(|i| i.modifiers.shift);
                nav = Some(if shift { -1 } else { 1 });
                // Keep typing/searching: re-focus the query field after an Enter.
                f.focus_query = true;
            }

            ui.add_enabled_ui(count > 0, |ui| {
                if ui.button("◀ Prev").on_hover_text("Previous match (Shift+Enter).").clicked() {
                    nav = Some(-1);
                }
                if ui.button("Next ▶").on_hover_text("Next match (Enter).").clicked() {
                    nav = Some(1);
                }
            });

            // The match counter ("3 / 17", or "0 / 0" / "no matches").
            let counter = if f.query.is_empty() {
                String::new()
            } else if count == 0 {
                "no matches".to_string()
            } else {
                format!("{} / {}", f.current + 1, count)
            };
            if !counter.is_empty() {
                ui.label(egui::RichText::new(counter).weak());
            }

            ui.checkbox(&mut f.case_sensitive, "Aa")
                .on_hover_text("Case-sensitive matching (off = case-insensitive).");

            if ui.button("×").on_hover_text("Close find (Esc).").clicked() {
                f.open = false;
            }
        });

        // Esc closes the bar.
        if ui.input(|i| i.key_pressed(egui::Key::Escape)) {
            f.open = false;
        }

        // Resolve a navigation request to a concrete match and stash its range for the editor.
        if let Some(delta) = nav {
            if count > 0 {
                let cur = f.current as isize;
                let next = (cur + delta).rem_euclid(count as isize) as usize;
                f.current = next;
                let m = matches[next];
                f.pending_select = Some((m.start, m.end));
            }
        }
    }

    // --- Decompile background jobs + sync helpers -----------------------------------------

    /// Drain the heavy-result side-channel: a finished Decompile job hands its WolfScript here.
    fn poll_decompile_result(&mut self) {
        let Some(rx) = &self.state.decompile.result_rx else {
            return;
        };
        let mut disconnected = false;
        loop {
            match rx.try_recv() {
                Ok(DecompileResult::Text(input, text)) => {
                    self.state.decompile.script = text;
                    // The decompiled input is the compile base (so unknown bytes are preserved).
                    self.state.decompile.base = Some(input.clone());
                    // Default the compile output to <input>.out the first time (or when unset).
                    if self.state.decompile.out.is_none() {
                        let mut name = input.file_name().map(|s| s.to_os_string()).unwrap_or_default();
                        name.push(".out");
                        self.state.decompile.out = Some(input.with_file_name(name));
                    }
                }
                Err(std::sync::mpsc::TryRecvError::Empty) => break,
                Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                    disconnected = true;
                    break;
                }
            }
        }
        if disconnected && !self.jobs.is_running() {
            self.state.decompile.result_rx = None;
        }
    }

    /// Spawn the Decompile job: render the input to editable WolfScript off the worker thread, hand
    /// the text back via the side-channel (mirrors the CLI's `decompile --mode edit`).
    fn start_decompile_job(&mut self) {
        let Some(input) = self.state.decompile.input.clone() else {
            return;
        };
        let (tx, rx) = std::sync::mpsc::channel();
        self.state.decompile.result_rx = Some(rx);
        self.jobs.run(format!("Decompile {}", input.display()), &mut self.log, move |rep| {
            rep.progress(0.2, "decompiling…");
            let text = decompile::decompile_edit(&input)?;
            let lines = text.lines().count();
            let _ = tx.send(DecompileResult::Text(input.clone(), text));
            rep.progress(1.0, "done");
            Ok(format!("decompiled {} ({lines} line(s) of WolfScript)", input.display()))
        });
    }

    /// Spawn the Compile job: recompile the edited WolfScript onto the stored base (the original
    /// input, so unknown bytes are preserved) and write to the chosen output (mirrors the CLI's
    /// `compile`). The compiled bytes are re-parsed before the write is reported.
    fn start_compile_job(&mut self) {
        let text = self.state.decompile.script.clone();
        let Some(base) = self
            .state
            .decompile
            .base
            .clone()
            .or_else(|| self.state.decompile.input.clone())
        else {
            self.log.error("compile: no base file (Decompile a file or pick the Input first)");
            return;
        };
        // Default the output to <base>.out when none was chosen.
        let out = self.state.decompile.out.clone().unwrap_or_else(|| {
            let mut name = base.file_name().map(|s| s.to_os_string()).unwrap_or_default();
            name.push(".out");
            base.with_file_name(name)
        });
        self.jobs.run(format!("Compile → {}", out.display()), &mut self.log, move |rep| {
            rep.progress(0.3, "compiling…");
            let outcome = decompile::compile_to(&text, &base, &out)?;
            rep.progress(1.0, "done");
            Ok(format!(
                "wrote {} ({} bytes{})",
                outcome.out.display(),
                outcome.bytes,
                if outcome.byte_identical { ", byte-identical to base" } else { "" }
            ))
        });
    }

    /// Save the current WolfScript buffer to a chosen `.wscript` file (synchronous text write).
    fn decompile_save_script(&mut self) {
        let default = self
            .state
            .decompile
            .base
            .as_ref()
            .or(self.state.decompile.input.as_ref())
            .and_then(|p| p.file_stem().and_then(|s| s.to_str()))
            .map(|s| format!("{s}.wscript"))
            .unwrap_or_else(|| "script.wscript".to_string());
        let Some(path) = widgets::save_file(&default, &[("WolfScript", &["wscript", "txt"])]) else {
            return;
        };
        match std::fs::write(&path, &self.state.decompile.script) {
            Ok(()) => self.log.info(format!("saved WolfScript → {}", path.display())),
            Err(e) => self.log.error(format!("save .wscript failed: {e}")),
        }
    }

    /// Load an existing `.wscript` into the editor (synchronous). The compile base stays the Input
    /// file the user picked above (compile needs the matching original).
    fn decompile_open_script(&mut self) {
        let Some(path) = widgets::pick_file(&[("WolfScript", &["wscript", "txt"]), ("All files", &["*"])])
        else {
            return;
        };
        match std::fs::read_to_string(&path) {
            Ok(text) => {
                let lines = text.lines().count();
                self.state.decompile.script = text;
                self.log.info(format!(
                    "loaded WolfScript ({lines} line(s)) from {} — set the Input above to its original file before Compile",
                    path.display()
                ));
            }
            Err(e) => self.log.error(format!("open .wscript failed: {e}")),
        }
    }

    fn ui_database(&mut self, ui: &mut egui::Ui) {
        // Pump any background result (a freshly loaded / reloaded grid model) into section state first.
        self.poll_database_result();

        // Default the path to the open project's main DataBase.project the first time we're shown.
        if self.state.database.path.is_none() {
            if let Some(p) = self.database_default_project() {
                self.state.database.path = Some(p);
            }
        }

        // Layout: the heading + path row sit in a fixed top region, the Save controls in a fixed
        // bottom region, and the (independently scrolling) grid fills the space between them. Using
        // nested panels keeps each region in its own rectangle so the grid never draws over the
        // controls (the old single-`ui` flow let the grid's inner CentralPanel claim all remaining
        // height and paint on top of the Save row).
        egui::TopBottomPanel::top("db_top")
            .resizable(false)
            .show_inside(ui, |ui| {
                ui.heading("Database");
                widgets::caption(
                    ui,
                    "Database = items, skills, enemies, etc. — edit values in the grid (no JSON needed).",
                );
                ui.add_space(6.0);
                self.database_path_row(ui);
                ui.add_space(4.0);
            });

        if self.state.database.loaded.is_none() {
            egui::CentralPanel::default().show_inside(ui, |ui| {
                widgets::caption(
                    ui,
                    "No database loaded. Pick a .project (a game has several: DataBase / CDataBase / \
                     SysDatabase) and press Load.",
                );
            });
            return;
        }

        // Save controls pinned to the bottom (drawn before the central grid so the grid gets the
        // remaining height and the two regions never overlap).
        egui::TopBottomPanel::bottom("db_save")
            .resizable(false)
            .show_inside(ui, |ui| {
                ui.add_space(4.0);
                self.database_save_row(ui);
            });

        // The grid fills the remaining space and scrolls independently below the controls.
        egui::CentralPanel::default().show_inside(ui, |ui| {
            self.database_grid(ui);
        });
    }

    /// The open project's `DataBase.project`, if its data dir holds one (the sensible default).
    fn database_default_project(&self) -> Option<PathBuf> {
        let data_dir = self.project.as_ref().and_then(|p| p.data_dir.clone())?;
        // The DB pairs live under the data dir or its BasicData/ subfolder.
        for cand in [data_dir.join("DataBase.project"), data_dir.join("BasicData").join("DataBase.project")] {
            if cand.exists() {
                return Some(cand);
            }
        }
        None
    }

    /// The `.project` path field + Load/Reload buttons + the kind/encoding badges.
    fn database_path_row(&mut self, ui: &mut egui::Ui) {
        let mut path_changed = false;
        // A project dropdown of the scanned databases (BasicData/*.project), above the Browse field.
        if let Some(dbs) = self.project.as_ref().map(|p| p.databases.clone()) {
            let mut path = self.state.database.path.clone();
            if project_combo(
                ui,
                "database_combo",
                "Project DB",
                &dbs,
                &mut path,
                "Pick a database (.project) from the open game: DataBase / CDataBase / SysDatabase.",
            ) {
                self.state.database.path = path;
                self.state.database.out_project = None;
                path_changed = true;
            }
        }

        let start = self.state.database.path.clone();
        let mut path = self.state.database.path.clone();
        let changed = widgets::path_field(
            ui,
            "Database",
            &mut path,
            "A database .project (its sibling .dat is loaded automatically). A game has several: \
             DataBase (items/skills/enemies), CDataBase (system config), SysDatabase.",
            move || {
                let start_dir = start.as_ref().and_then(|p| p.parent());
                widgets::pick_file_in(start_dir, &[("Database project", &["project"]), ("All files", &["*"])])
            },
        );
        self.state.database.path = path;
        // Picking a fresh .project clears the previous output choice (it pointed at the old DB).
        if changed {
            self.state.database.out_project = None;
            path_changed = true;
        }

        // Auto-load the moment the selection or path changes, so switching databases does not need a
        // manual Load click. Discards unsaved edits to the previous DB (it was a different table).
        if path_changed && self.state.database.path.is_some() && !self.jobs.is_running() {
            self.start_database_load_job();
        }

        ui.add_space(4.0);
        let running = self.jobs.is_running();
        let have = self.state.database.path.is_some();
        ui.horizontal(|ui| {
            ui.add_enabled_ui(have && !running, |ui| {
                if ui
                    .button("Load")
                    .on_hover_text("Read the .project + .dat pair and fill the grid with its current values.")
                    .clicked()
                {
                    self.start_database_load_job();
                }
            });
            if self.state.database.loaded.is_some()
                && ui
                    .button("Reload")
                    .on_hover_text("Discard edits and reload the values from disk.")
                    .clicked()
            {
                self.start_database_load_job();
            }
            if self.state.database.loaded.is_some()
                && ui
                    .button("Unload")
                    .on_hover_text("Close the database and free its memory (discards unsaved edits).")
                    .clicked()
            {
                self.unload_database();
            }
            // Export the whole database to a JSON file (full structure, all rows/fields/numbers) so it
            // can be edited outside the GUI, and import an edited JSON back. Exports the ON-DISK state,
            // so Save first if you want grid edits included.
            ui.add_enabled_ui(have && !running, |ui| {
                if ui
                    .button("Export JSON…")
                    .on_hover_text("Write the full database to a .json file you can edit in any editor (Save first to include grid edits).")
                    .clicked()
                {
                    if let Some(out) = widgets::save_file("database.json", &[("JSON", &["json"])]) {
                        self.start_database_export_job(out);
                    }
                }
                if ui
                    .button("Import JSON…")
                    .on_hover_text("Apply an edited database .json back onto the .project + .dat (the originals are backed up first), then reload.")
                    .clicked()
                {
                    if let Some(json) = widgets::pick_file(&[("JSON", &["json"]), ("All files", &["*"])]) {
                        self.start_database_import_job(json);
                    }
                }
            });
            // The kind + encoding badges (read-only), shown once a model is loaded.
            if let Some(m) = &self.state.database.loaded {
                ui.separator();
                ui.label(
                    egui::RichText::new(format!(" {} ", m.kind))
                        .strong()
                        .background_color(egui::Color32::from_rgb(0x40, 0x80, 0xE0))
                        .color(egui::Color32::BLACK),
                )
                .on_hover_text("UDB = the main user database (items/skills/enemies); CDB = system config; SDB = engine system.");
                ui.separator();
                ui.label(egui::RichText::new(format!(" {} ", m.encoding)).strong())
                    .on_hover_text("How the strings are stored. A Shift-JIS database can only hold characters representable in Shift-JIS.");
            }
        });
    }

    /// The two-pane grid: the type (table) selector on the left, the selected type's rows as an
    /// editable table on the right.
    fn database_grid(&mut self, ui: &mut egui::Ui) {
        // Left: a selectable list of types with their row counts.
        egui::SidePanel::left("db_types")
            .resizable(true)
            .default_width(240.0)
            .show_inside(ui, |ui| {
                ui.label(egui::RichText::new("Types (tables)").strong())
                    .on_hover_text("Each type is a table: Skill, Item, Enemy, … Pick one to edit its rows.");
                ui.add_space(2.0);
                egui::ScrollArea::vertical().auto_shrink([false, false]).show(ui, |ui| {
                    let db = &mut self.state.database;
                    let Some(model) = &db.loaded else { return };
                    if db.selected_type >= model.types.len() {
                        db.selected_type = 0;
                    }
                    for (i, t) in model.types.iter().enumerate() {
                        let edited = t.changed_count();
                        let mut label = format!("{}  ({} rows)", t.name, t.rows.len());
                        if edited > 0 {
                            // The edit badge stays on the row (it wraps with the rest of the text).
                            label.push_str(&format!("  ● {edited}"));
                        }
                        // A custom full-width row that allocates at the wrapped text height and paints
                        // a rounded, padded highlight, so a two-line type name is fully contained.
                        if selectable_row(ui, db.selected_type == i, &label).clicked() {
                            db.selected_type = i;
                            db.filter.clear();
                        }
                    }
                });
            });

        // Right: the selected type's filter/counter bar + the editable rows table.
        egui::CentralPanel::default().show_inside(ui, |ui| {
            self.database_rows_pane(ui);
        });
    }

    /// The right pane: a filter box over row names, a row counter, and the editable rows table
    /// (first column = the row name, then one column per data field).
    fn database_rows_pane(&mut self, ui: &mut egui::Ui) {
        use egui_extras::{Column, TableBuilder};

        let db = &mut self.state.database;
        let Some(model) = &mut db.loaded else { return };
        let Some(t) = model.types.get_mut(db.selected_type) else {
            widgets::caption(ui, "Select a type on the left.");
            return;
        };

        // Filter/counter bar.
        let total = t.rows.len();
        ui.horizontal(|ui| {
            ui.label(egui::RichText::new(&t.name).strong());
            ui.separator();
            ui.label("Filter:");
            ui.add(
                egui::TextEdit::singleline(&mut db.filter)
                    .hint_text("search row names")
                    .desired_width(200.0),
            );
            ui.separator();
            ui.label(egui::RichText::new(format!("{total} row(s)")).strong());
        });
        ui.add_space(4.0);

        if t.fields.is_empty() {
            widgets::caption(ui, "This type has no editable data fields.");
            return;
        }

        // Which row indices pass the (row-name) filter. When no filter is active we skip building an
        // index Vec entirely and address rows directly, so the common case has no per-frame O(rows)
        // allocation or scan on top of the now-virtualized body.
        let needle = db.filter.to_lowercase();
        let filtered: Option<Vec<usize>> = if needle.is_empty() {
            None
        } else {
            Some(
                t.rows
                    .iter()
                    .enumerate()
                    .filter(|(_, r)| r.name.to_lowercase().contains(&needle))
                    .map(|(i, _)| i)
                    .collect(),
            )
        };
        let count = filtered.as_ref().map_or(t.rows.len(), Vec::len);
        if count == 0 {
            widgets::caption(ui, "No rows match the current filter.");
            return;
        }

        let text_h = egui::TextStyle::Body.resolve(ui.style()).size;
        let field_labels = t.fields.clone();
        // The egui_extras Table only scrolls vertically. A type with many fields is wider than the
        // pane, so wrap the whole table in a horizontal ScrollArea: the outer area pans sideways
        // while the Table's own vertical scroll keeps the rows virtualized. Bound the table height to
        // the space left so the inner vertical scroll has a viewport to virtualize against.
        let avail_h = ui.available_height();
        egui::ScrollArea::horizontal()
            .auto_shrink([false, false])
            .show(ui, |ui| {
                let mut builder = TableBuilder::new(ui)
                    .striped(true)
                    .resizable(true)
                    .max_scroll_height(avail_h)
                    .cell_layout(egui::Layout::left_to_right(egui::Align::TOP))
                    .column(Column::auto().at_least(40.0)) // id
                    .column(Column::initial(160.0).at_least(90.0)); // name
                for _ in &field_labels {
                    builder = builder.column(Column::initial(130.0).at_least(70.0));
                }
                builder
                    .header(text_h + 6.0, |mut header| {
                        header.col(|ui| {
                            ui.strong("id");
                        });
                        header.col(|ui| {
                            ui.strong("name").on_hover_text(
                                "The row's display name. Tip: translating names is best done in the \
                                 Translation section's glossary so by-name lookups stay consistent.",
                            );
                        });
                        for label in &field_labels {
                            header.col(|ui| {
                                ui.strong(label.as_str()).on_hover_text(label.as_str());
                            });
                        }
                    })
                    // Virtualized body: egui_extras only builds widgets for the rows actually on
                    // screen, so a type with thousands of rows no longer lays out thousands of
                    // TextEdits every frame. `r.index()` indexes into the filtered set.
                    .body(|body| {
                        body.rows(text_h * 2.0, count, |mut r| {
                            let ri = filtered.as_ref().map_or(r.index(), |v| v[r.index()]);
                            let row = &mut t.rows[ri];
                            r.col(|ui| {
                                ui.add(
                                    egui::Label::new(
                                        egui::RichText::new(row.id.to_string()).weak().small(),
                                    )
                                    .wrap(),
                                );
                            });
                            r.col(|ui| {
                                ui.add(
                                    egui::TextEdit::singleline(&mut row.name)
                                        .desired_width(f32::INFINITY),
                                );
                            });
                            for cell in row.cells.iter_mut() {
                                r.col(|ui| {
                                    let hint = if cell.is_string { "" } else { "(number)" };
                                    ui.add(
                                        egui::TextEdit::singleline(&mut cell.value)
                                            .hint_text(hint)
                                            .desired_width(f32::INFINITY),
                                    );
                                });
                            }
                        });
                    });
            });
    }

    /// The Options + Save row: output choice (in place vs an output `.project`), backup toggle,
    /// change counter, and Save.
    fn database_save_row(&mut self, ui: &mut egui::Ui) {
        let running = self.jobs.is_running();

        // Output choice: in place (default) vs a Browse'd output .project.
        let mut out = self.state.database.out_project.clone();
        let mut in_place = out.is_none();
        ui.horizontal(|ui| {
            if ui
                .radio(in_place, "Save in place")
                .on_hover_text("Overwrite the loaded .project + .dat (backing up the originals first if the box is checked).")
                .clicked()
            {
                in_place = true;
                out = None;
            }
            let pick = ui
                .radio(!in_place, "Save to a new .project")
                .on_hover_text("Write the result to a chosen .project (its sibling .dat is written next to it); the originals are left untouched.")
                .clicked();
            if pick {
                in_place = false;
                if out.is_none() {
                    out = widgets::save_file("DataBase.project", &[("Database project", &["project"])]);
                }
            }
        });
        if !in_place {
            let mut o = out.clone();
            widgets::path_field(
                ui,
                "Output .project",
                &mut o,
                "Where to write the edited database (the sibling .dat is written alongside it).",
                || widgets::save_file("DataBase.project", &[("Database project", &["project"])]),
            );
            out = o;
        }
        self.state.database.out_project = out;

        ui.add_space(4.0);
        widgets::labeled_checkbox(
            ui,
            &mut self.state.database.backup,
            "Back up originals",
            "Copy the .project + .dat to *.bak before overwriting them in place. Leave ON unless you \
             have your own backups (ignored when saving to a new file).",
        );

        let model = self.state.database.loaded.as_ref().expect("loaded checked by caller");
        let changed = model.changed_count();
        ui.horizontal(|ui| {
            ui.label(egui::RichText::new(format!("{changed} cell(s)/name(s) edited")).strong());
        });
        ui.add_space(4.0);

        let dirty = model.dirty();
        let in_place_now = self.state.database.out_project.is_none();
        ui.add_enabled_ui(dirty && !running, |ui| {
            if ui
                .button("Save ▶")
                .on_hover_text(if in_place_now {
                    "Apply the edits and write the .project + .dat back in place, byte-exact for untouched data."
                } else {
                    "Apply the edits and write the .project + .dat to the chosen output, byte-exact for untouched data."
                })
                .clicked()
            {
                self.start_database_save_job();
            }
        });
        if !dirty {
            widgets::caption(ui, "Edit a cell or row name to enable Save.");
        }
    }

    // --- Database background jobs + sync helpers -------------------------------------------

    /// Drain the heavy-result side-channel: a finished Load/Save job hands its (re)loaded model here.
    fn poll_database_result(&mut self) {
        let Some(rx) = &self.state.database.result_rx else {
            return;
        };
        let mut disconnected = false;
        loop {
            match rx.try_recv() {
                Ok(DbResult::Loaded(m)) => {
                    let ntypes = m.types.len();
                    self.state.database.loaded = Some(*m);
                    if self.state.database.selected_type >= ntypes {
                        self.state.database.selected_type = 0;
                    }
                }
                Err(std::sync::mpsc::TryRecvError::Empty) => break,
                Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                    disconnected = true;
                    break;
                }
            }
        }
        if disconnected && !self.jobs.is_running() {
            self.state.database.result_rx = None;
        }
    }

    /// Spawn the Load job: read + render the `.project`+`.dat` pair into the grid model off the worker
    /// thread, hand it back via the side-channel, and report type/row counts (mirrors `db-json`).
    fn start_database_load_job(&mut self) {
        let Some(path) = self.state.database.path.clone() else {
            return;
        };
        let (tx, rx) = std::sync::mpsc::channel();
        self.state.database.result_rx = Some(rx);
        self.jobs.run(format!("Load {}", path.display()), &mut self.log, move |rep| {
            rep.progress(0.3, "reading database…");
            let model = database::load(&path)?;
            let summary = format!(
                "{} type(s), {} data row(s), {} encoding",
                model.types.len(),
                model.total_rows(),
                model.encoding
            );
            let _ = tx.send(DbResult::Loaded(Box::new(model)));
            rep.progress(1.0, "done");
            Ok(summary)
        });
    }

    /// Spawn the Save job: apply the grid edits onto a freshly-read base, re-parse the written pair to
    /// verify it round-trips, and write both halves (in place when no output is chosen), then reload
    /// from the written `.project` so the grid shows the persisted state. Mirrors the CLI's `db-apply`.
    fn start_database_save_job(&mut self) {
        // Move the loaded model onto the worker. It comes back (reloaded) via the side-channel.
        let Some(model) = self.state.database.loaded.take() else {
            return;
        };
        let backup = self.state.database.backup;
        let output = self.state.database.out_project.clone().unwrap_or_else(|| model.project.clone());
        let in_place = output == model.project;
        let (tx, rx) = std::sync::mpsc::channel();
        self.state.database.result_rx = Some(rx);
        self.jobs.run(format!("Save database → {}", output.display()), &mut self.log, move |rep| {
            rep.progress(0.3, "applying edits…");
            match database::save(&model, &output, backup && in_place) {
                Ok(outcome) => {
                    for bak in &outcome.backups {
                        rep.info(format!("backed up original → {}", bak.display()));
                    }
                    // Reload from the written .project so the grid reflects the persisted state.
                    match database::load(&outcome.out_project) {
                        Ok(fresh) => {
                            let _ = tx.send(DbResult::Loaded(Box::new(fresh)));
                        }
                        Err(e) => {
                            rep.warn(format!("reload after save failed: {e}"));
                            let _ = tx.send(DbResult::Loaded(Box::new(model)));
                        }
                    }
                    rep.progress(1.0, "done");
                    Ok(format!(
                        "{} cell(s)/name(s) changed → {} + {}{}",
                        outcome.changed,
                        outcome.out_project.display(),
                        outcome.out_dat.display(),
                        if outcome.byte_identical { " (byte-identical to base)" } else { "" }
                    ))
                }
                Err(e) => {
                    // Put the model back unchanged so the user's edits aren't lost.
                    let _ = tx.send(DbResult::Loaded(Box::new(model)));
                    rep.progress(1.0, "done");
                    Err(e)
                }
            }
        });
    }

    /// Spawn the DB export job: write the on-disk database to a `.json` file on a worker thread
    /// (reads only the base path, so the live grid is untouched).
    fn start_database_export_job(&mut self, out: PathBuf) {
        let Some(base) = self.state.database.path.clone() else {
            return;
        };
        self.jobs.run(format!("Export DB → {}", out.display()), &mut self.log, move |rep| {
            rep.progress(0.4, "reading database…");
            database::export_json(&base, &out)?;
            rep.progress(1.0, "done");
            Ok(format!("exported → {}", out.display()))
        });
    }

    /// Spawn the DB import job: apply an edited `.json` onto the loaded database in place (backing up
    /// the originals first), then reload the grid from the written result.
    fn start_database_import_job(&mut self, json: PathBuf) {
        let Some(base) = self.state.database.path.clone() else {
            return;
        };
        let backup = self.state.database.backup;
        let (tx, rx) = std::sync::mpsc::channel();
        self.state.database.result_rx = Some(rx);
        self.jobs.run(format!("Import DB ← {}", json.display()), &mut self.log, move |rep| {
            rep.progress(0.3, "applying JSON…");
            let outcome = database::import_json(&base, &json, &base, backup)?;
            for bak in &outcome.backups {
                rep.info(format!("backed up original → {}", bak.display()));
            }
            // Reload the grid from the written .project so it reflects the imported state.
            match database::load(&outcome.out_project) {
                Ok(fresh) => {
                    let _ = tx.send(DbResult::Loaded(Box::new(fresh)));
                }
                Err(e) => rep.warn(format!("reload after import failed: {e}")),
            }
            rep.progress(1.0, "done");
            Ok(format!(
                "{} cell(s)/name(s) changed{}",
                outcome.changed,
                if outcome.byte_identical { " (no change)" } else { "" }
            ))
        });
    }

    fn ui_gamedat(&mut self, ui: &mut egui::Ui) {
        // Pump any background result (a freshly loaded / reloaded model) into section state first.
        self.poll_gamedat_result();

        ui.heading("Game.dat");
        widgets::caption(ui, "Edit every Game.dat field: title, fonts, splash/title messages, image paths.");
        ui.add_space(6.0);

        // Default the path to the open project's Game.dat the first time we're shown.
        if self.state.gamedat.path.is_none() {
            if let Some(p) = self.project.as_ref().and_then(|p| p.game_dat.clone()) {
                self.state.gamedat.path = Some(p);
            }
        }

        self.gamedat_path_row(ui);
        ui.add_space(8.0);
        ui.separator();
        ui.add_space(6.0);

        if self.state.gamedat.loaded.is_none() {
            widgets::caption(ui, "No Game.dat loaded. Pick a Game.dat and press Load.");
            return;
        }
        self.gamedat_form(ui);
    }

    /// The Game.dat path field + Load button + the encoding badge.
    fn gamedat_path_row(&mut self, ui: &mut egui::Ui) {
        let start = self.state.gamedat.path.clone();
        let mut path = self.state.gamedat.path.clone();
        widgets::path_field(
            ui,
            "Game.dat",
            &mut path,
            "The game's Game.dat (holds the window title, fonts, splash/title messages and image paths).",
            move || {
                let start_dir = start.as_ref().and_then(|p| p.parent());
                widgets::pick_file_in(start_dir, &[("Game data", &["dat"]), ("All files", &["*"])])
            },
        );
        self.state.gamedat.path = path;

        ui.add_space(4.0);
        let running = self.jobs.is_running();
        let have = self.state.gamedat.path.is_some();
        ui.horizontal(|ui| {
            ui.add_enabled_ui(have && !running, |ui| {
                if ui
                    .button("Load")
                    .on_hover_text("Read the Game.dat and fill the form with its current field values.")
                    .clicked()
                {
                    self.start_gamedat_load_job();
                }
            });
            if self.state.gamedat.loaded.is_some()
                && ui
                    .button("Reload")
                    .on_hover_text("Discard edits and reload the field values from disk.")
                    .clicked()
            {
                self.start_gamedat_load_job();
            }
            if self.state.gamedat.loaded.is_some()
                && ui
                    .button("Unload")
                    .on_hover_text("Close Game.dat and free its memory (discards unsaved edits).")
                    .clicked()
            {
                self.unload_gamedat();
            }
            // The encoding badge (read-only), shown once a model is loaded.
            if let Some(g) = &self.state.gamedat.loaded {
                ui.separator();
                ui.label(
                    egui::RichText::new(format!(" {} ", g.encoding))
                        .strong()
                        .background_color(egui::Color32::from_rgb(0x40, 0x80, 0xE0))
                        .color(egui::Color32::BLACK),
                )
                .on_hover_text("How the strings are stored (utf8 or shiftjis). A Shift-JIS file can only hold characters representable in Shift-JIS.");
            }
        });
    }

    /// The grouped field form + the Save controls.
    fn gamedat_form(&mut self, ui: &mut egui::Ui) {
        let running = self.jobs.is_running();
        // Render the grouped fields inside a scroll area (a file can carry many).
        egui::ScrollArea::vertical()
            .auto_shrink([false, false])
            .max_height(360.0)
            .show(ui, |ui| {
                let g = self.state.gamedat.loaded.as_mut().expect("loaded checked by caller");
                Self::gamedat_group(ui, "Titles & messages", g, Group::Titles, false);
                Self::gamedat_group(ui, "Fonts", g, Group::Fonts, true);
                Self::gamedat_group(ui, "Graphics", g, Group::Graphics, false);
                Self::gamedat_group(ui, "Other", g, Group::Other, false);
            });

        ui.add_space(8.0);
        ui.separator();
        ui.add_space(4.0);

        // Backup toggle + change counter + Save.
        widgets::labeled_checkbox(
            ui,
            &mut self.state.gamedat.backup,
            "Back up original",
            "Copy the file to a *.bak before overwriting it in place. Leave ON unless you have your \
             own backups (ignored when saving to a new file).",
        );
        let g = self.state.gamedat.loaded.as_ref().expect("loaded");
        let changed = g.changed_count();
        ui.horizontal(|ui| {
            ui.label(egui::RichText::new(format!("{changed} field(s) edited")).strong());
        });
        ui.add_space(4.0);
        let dirty = g.dirty();
        ui.horizontal(|ui| {
            ui.add_enabled_ui(dirty && !running, |ui| {
                if ui
                    .button("Save (in place) ▶")
                    .on_hover_text("Apply the edits and write the Game.dat back in place (backing up the original first if the box is checked).")
                    .clicked()
                {
                    self.start_gamedat_save_job(None);
                }
            });
            ui.add_enabled_ui(dirty && !running, |ui| {
                if ui
                    .button("Save as…")
                    .on_hover_text("Apply the edits and write the result to a chosen file (the original is left untouched).")
                    .clicked()
                {
                    if let Some(out) =
                        widgets::save_file("Game.dat", &[("Game data", &["dat"]), ("All files", &["*"])])
                    {
                        self.start_gamedat_save_job(Some(out));
                    }
                }
            });
        });
        if !dirty {
            widgets::caption(ui, "Edit a field to enable Save.");
        }
    }

    /// Render the fields of one group as a labelled form section, plus (when `with_subfonts`) the
    /// SubFonts array under the same header. Skips the section entirely when it has no fields.
    ///
    /// Every row goes through the shared [`widgets::text_row`], so every input fills the row to the
    /// same width and starts at the same x (the fixed [`widgets::LABEL_COL_W`] left column). The
    /// inputs line up on both edges across all groups, and the whole Game.dat form matches the path
    /// rows of the other sections.
    fn gamedat_group(
        ui: &mut egui::Ui,
        header: &str,
        g: &mut LoadedGameDat,
        group: Group,
        with_subfonts: bool,
    ) {
        let any_fields = g.fields.iter().any(|f| f.group == group);
        let any_subfonts = with_subfonts && !g.sub_fonts.is_empty();
        if !any_fields && !any_subfonts {
            return;
        }
        ui.add_space(4.0);
        ui.label(egui::RichText::new(header).strong());
        ui.add_space(2.0);
        for f in g.fields.iter_mut().filter(|f| f.group == group) {
            // The Font field's label gets a tofu-busting tooltip (the non-coder rescue).
            let label_tip = if f.key == "Font" {
                "the game's font; if text shows as boxes/tofu on your system, try another installed \
                 Japanese font here"
            } else {
                ""
            };
            widgets::text_row(ui, f.label, &mut f.value, label_tip, "(empty)");
        }
        if any_subfonts {
            for (i, s) in g.sub_fonts.iter_mut().enumerate() {
                widgets::text_row(
                    ui,
                    &format!("Sub-font {}", i + 1),
                    &mut s.value,
                    "A fallback font the engine uses when the main font lacks a glyph.",
                    "(empty)",
                );
            }
        }
    }

    // --- Game.dat background jobs + sync helpers -------------------------------------------

    /// Drain the heavy-result side-channel: a finished Load/Save job hands its (re)loaded model here.
    fn poll_gamedat_result(&mut self) {
        let Some(rx) = &self.state.gamedat.result_rx else {
            return;
        };
        let mut disconnected = false;
        loop {
            match rx.try_recv() {
                Ok(GameDatResult::Loaded(g)) => self.state.gamedat.loaded = Some(*g),
                Err(std::sync::mpsc::TryRecvError::Empty) => break,
                Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                    disconnected = true;
                    break;
                }
            }
        }
        if disconnected && !self.jobs.is_running() {
            self.state.gamedat.result_rx = None;
        }
    }

    /// Spawn the Load job: read + parse the Game.dat into the form model off the worker thread, hand
    /// it back via the side-channel, and report the field/encoding counts (mirrors `gamedat-json`).
    fn start_gamedat_load_job(&mut self) {
        let Some(path) = self.state.gamedat.path.clone() else {
            return;
        };
        let (tx, rx) = std::sync::mpsc::channel();
        self.state.gamedat.result_rx = Some(rx);
        self.jobs.run(format!("Load {}", path.display()), &mut self.log, move |rep| {
            rep.progress(0.3, "reading Game.dat…");
            let g = gamedat::load(&path)?;
            let summary = format!(
                "{} field(s) + {} sub-font(s), {} encoding",
                g.fields.len(),
                g.sub_fonts.len(),
                g.encoding
            );
            let _ = tx.send(GameDatResult::Loaded(Box::new(g)));
            rep.progress(1.0, "done");
            Ok(summary)
        });
    }

    /// Spawn the Save job: apply the form edits onto a fresh base, re-parse to verify the round-trip,
    /// and write to `out` (in place when `None`), then reload from the written bytes so the form shows
    /// the persisted state. Mirrors the CLI's `gamedat-apply` guard.
    fn start_gamedat_save_job(&mut self, out: Option<PathBuf>) {
        // Move the loaded model onto the worker. It comes back (reloaded) via the side-channel.
        let Some(loaded) = self.state.gamedat.loaded.take() else {
            return;
        };
        let backup = self.state.gamedat.backup;
        let output = out.unwrap_or_else(|| loaded.path.clone());
        let in_place = output == loaded.path;
        let (tx, rx) = std::sync::mpsc::channel();
        self.state.gamedat.result_rx = Some(rx);
        self.jobs.run(format!("Save Game.dat → {}", output.display()), &mut self.log, move |rep| {
            rep.progress(0.3, "applying edits…");
            let result = gamedat::save(&loaded, &output, backup && in_place);
            match result {
                Ok(outcome) => {
                    if let Some(bak) = &outcome.backup {
                        rep.info(format!("backed up original → {}", bak.display()));
                    }
                    // Reload from the written file so the form reflects the persisted state.
                    match gamedat::load(&outcome.out) {
                        Ok(fresh) => {
                            let _ = tx.send(GameDatResult::Loaded(Box::new(fresh)));
                        }
                        Err(e) => {
                            rep.warn(format!("reload after save failed: {e}"));
                            let _ = tx.send(GameDatResult::Loaded(Box::new(loaded)));
                        }
                    }
                    rep.progress(1.0, "done");
                    Ok(format!(
                        "{} field(s) changed → {}{}",
                        outcome.changed,
                        outcome.out.display(),
                        if outcome.byte_identical { " (byte-identical to base)" } else { "" }
                    ))
                }
                Err(e) => {
                    // Put the model back unchanged so the user's edits aren't lost.
                    let _ = tx.send(GameDatResult::Loaded(Box::new(loaded)));
                    rep.progress(1.0, "done");
                    Err(e)
                }
            }
        });
    }

    fn ui_translation(&mut self, ui: &mut egui::Ui) {
        // Pump any background result (a rebuilt model / conflict list) into the section state first,
        // so the rest of this frame renders what the just-finished job produced.
        self.poll_translation_result();

        ui.heading("Translation");
        widgets::caption(ui, "Extract player-facing text, edit translations, inject them back, and carry them across game updates.");
        ui.add_space(6.0);

        // Default the source folder to the open project's data dir the first time we're shown.
        if self.state.translation.source_dir.is_none() {
            if let Some(d) = self.project.as_ref().and_then(|p| p.data_dir.clone()) {
                self.state.translation.source_dir = Some(d);
            }
        }

        self.translation_source_row(ui);
        ui.add_space(6.0);
        self.translation_action_row(ui);
        ui.add_space(8.0);
        ui.separator();

        if self.state.translation.model.is_none() {
            ui.add_space(8.0);
            widgets::caption(
                ui,
                "No translation loaded. Pick a game's unpacked Data folder and press Extract, \
                 or Load a saved translation project.",
            );
            return;
        }

        if let Some(model) = &self.state.translation.model {
            widgets::caption(
                ui,
                &format!(
                    "{} file(s) · {} / {} lines translated overall",
                    model.files.len(),
                    model.translated_rows(),
                    model.total_rows(),
                ),
            );
        }
        ui.add_space(4.0);
        self.translation_options_row(ui);
        ui.add_space(6.0);
        ui.separator();
        ui.add_space(6.0);
        self.translation_grid(ui);
        self.translation_conflicts_panel(ui);
    }

    /// The source-folder field + Extract button.
    fn translation_source_row(&mut self, ui: &mut egui::Ui) {
        let mut dir = self.state.translation.source_dir.clone();
        let start = dir.clone();
        widgets::path_field(
            ui,
            "Source folder",
            &mut dir,
            "The game's unpacked Data folder (holds BasicData/ and MapData/). Extract reads every \
             text file under it.",
            move || widgets::pick_folder_in(start.as_deref()),
        );
        self.state.translation.source_dir = dir;

        ui.add_space(6.0);
        let running = self.jobs.is_running();
        let have_dir = self.state.translation.source_dir.is_some();
        ui.horizontal(|ui| {
            ui.add_enabled_ui(have_dir && !running, |ui| {
                if ui
                    .button("Extract")
                    .on_hover_text("Read every map, CommonEvent, database and Game.dat under the folder into an editable grid.")
                    .clicked()
                {
                    self.start_extract_job();
                }
            });
            ui.add_enabled_ui(!running, |ui| {
                if ui
                    .button("Load project…")
                    .on_hover_text("Restore a translation you saved earlier (a .wdtr.json file).")
                    .clicked()
                {
                    self.translation_load_project();
                }
                if self.state.translation.model.is_some()
                    && ui
                        .button("Save project…")
                        .on_hover_text("Save the whole translation (all edits) to a single JSON so it persists across sessions.")
                        .clicked()
                {
                    self.translation_save_project();
                }
            });
        });
    }

    /// The Merge / Check-names action row (only useful once a model is loaded).
    fn translation_action_row(&mut self, ui: &mut egui::Ui) {
        let running = self.jobs.is_running();
        let have_model = self.state.translation.model.is_some();
        ui.horizontal(|ui| {
            ui.add_enabled_ui(have_model && !running, |ui| {
                if ui
                    .button("Merge older translation…")
                    .on_hover_text("Carry translations from a previous version's exported JSON(s) into this model, matched by source text.")
                    .clicked()
                {
                    self.start_merge_job();
                }
                if ui
                    .button("Check names")
                    .on_hover_text("Check that each glossary name is translated to ONE value everywhere (inconsistent names break by-name lookups).")
                    .clicked()
                {
                    self.start_check_job();
                }
            });
            if have_model
                && ui
                    .button("Unload")
                    .on_hover_text("Close the translation and free its memory (discards unsaved edits; Save or Inject first to keep them).")
                    .clicked()
            {
                self.unload_translation();
            }
        });
    }

    /// The inject options (en-punct / allow-code-drift), the output choice, and the Inject button.
    fn translation_options_row(&mut self, ui: &mut egui::Ui) {
        let tr = &mut self.state.translation;
        ui.horizontal(|ui| {
            widgets::labeled_checkbox(
                ui,
                &mut tr.en_punct,
                "--en-punct",
                "Convert Japanese punctuation 「」～。 to ASCII for English (applied to your translations on inject).",
            );
            widgets::labeled_checkbox(
                ui,
                &mut tr.allow_code_drift,
                "--allow-code-drift",
                "Allow dropping/altering \\codes — risky. Off keeps the strict control-code guard that protects byte-exactness.",
            );
        });

        // Output choice: in place (default, with a note) vs a Browse'd output dir.
        let mut out = tr.out_dir.clone();
        let mut in_place = out.is_none();
        ui.horizontal(|ui| {
            if ui
                .radio(in_place, "Write in place")
                .on_hover_text("Overwrite the files in the source folder (make a backup of your game first).")
                .clicked()
            {
                in_place = true;
                out = None;
            }
            let pick_out = ui
                .radio(!in_place, "Write to output folder")
                .on_hover_text("Write the translated files into a separate folder, mirroring the source layout.")
                .clicked();
            if pick_out {
                in_place = false;
                if out.is_none() {
                    out = widgets::pick_folder();
                }
            }
        });
        if !in_place {
            let start = out.clone();
            widgets::path_field(
                ui,
                "Output folder",
                &mut out,
                "Where to write the translated files (mirrors the source folder's layout).",
                move || widgets::pick_folder_in(start.as_deref()),
            );
        }
        self.state.translation.out_dir = out;

        ui.add_space(6.0);
        let running = self.jobs.is_running();
        let in_place_now = self.state.translation.out_dir.is_none();
        ui.add_enabled_ui(!running, |ui| {
            let btn = ui.button("Inject ▶").on_hover_text(if in_place_now {
                "Apply your translations back into the game files IN PLACE (overwrites the source folder)."
            } else {
                "Apply your translations into the chosen output folder, byte-exact."
            });
            if btn.clicked() {
                self.start_inject_job();
            }
        });
    }

    /// The two-pane grid: the file/names list on the left, the selected entry's rows on the right.
    fn translation_grid(&mut self, ui: &mut egui::Ui) {
        // Left: a selectable list of files + the names glossary.
        egui::SidePanel::left("tr_files")
            .resizable(true)
            .default_width(220.0)
            .show_inside(ui, |ui| {
                ui.label(egui::RichText::new("Files").strong());
                ui.add_space(2.0);
                egui::ScrollArea::vertical().auto_shrink([false, false]).show(ui, |ui| {
                    let tr = &mut self.state.translation;
                    let Some(model) = &tr.model else { return };
                    // The names glossary entry first.
                    let names_label = format!(
                        "Names ({}/{})",
                        model.names.iter().filter(|r| r.is_translated()).count(),
                        model.names.len()
                    );
                    if ui
                        .selectable_label(tr.selected == SelectedEntry::Names, names_label)
                        .clicked()
                    {
                        tr.selected = SelectedEntry::Names;
                    }
                    ui.separator();
                    for (i, f) in model.files.iter().enumerate() {
                        let label = format!(
                            "{} {}  ({}/{})",
                            kind_icon(f.kind),
                            f.display_name(),
                            f.translated_count(),
                            f.rows.len()
                        );
                        if ui
                            .selectable_label(tr.selected == SelectedEntry::File(i), label)
                            .clicked()
                        {
                            tr.selected = SelectedEntry::File(i);
                        }
                    }
                });
            });

        // Right: the filter/toggle/counter bar + the rows table for the selected entry.
        egui::CentralPanel::default().show_inside(ui, |ui| {
            self.translation_rows_pane(ui);
        });
    }

    /// The right pane: filter box, untranslated toggle, live counter, and the editable rows table.
    fn translation_rows_pane(&mut self, ui: &mut egui::Ui) {
        use egui_extras::{Column, TableBuilder};

        let tr = &mut self.state.translation;
        let Some(model) = &mut tr.model else { return };

        // Resolve the selected entry's rows.
        let rows = match tr.selected {
            SelectedEntry::Names => &mut model.names,
            SelectedEntry::File(i) => match model.files.get_mut(i) {
                Some(f) => &mut f.rows,
                None => {
                    tr.selected = SelectedEntry::Names;
                    &mut model.names
                }
            },
        };

        // Filter/toggle/counter bar.
        let (translated, total) = (rows.iter().filter(|r| r.is_translated()).count(), rows.len());
        ui.horizontal(|ui| {
            ui.label("Filter:");
            ui.add(
                egui::TextEdit::singleline(&mut tr.filter)
                    .hint_text("search source or translation")
                    .desired_width(220.0),
            );
            ui.checkbox(&mut tr.untranslated_only, "untranslated only")
                .on_hover_text("Show only rows you have not translated yet.");
            ui.separator();
            ui.label(
                egui::RichText::new(format!("{translated} / {total} translated")).strong(),
            );
        });
        ui.add_space(4.0);

        // Which row indices pass the filter/toggle. With no text filter and the toggle off we address
        // rows directly (no per-frame index Vec), so an unfiltered file of thousands of lines costs
        // nothing beyond the now-virtualized body.
        let needle = tr.filter.to_lowercase();
        let active = !needle.is_empty() || tr.untranslated_only;
        let filtered: Option<Vec<usize>> = if !active {
            None
        } else {
            Some(
                rows.iter()
                    .enumerate()
                    .filter(|(_, r)| {
                        if tr.untranslated_only && r.is_translated() {
                            return false;
                        }
                        needle.is_empty()
                            || r.source.to_lowercase().contains(&needle)
                            || r.translation.to_lowercase().contains(&needle)
                    })
                    .map(|(i, _)| i)
                    .collect(),
            )
        };
        let count = filtered.as_ref().map_or(rows.len(), Vec::len);
        if count == 0 {
            widgets::caption(ui, "No rows match the current filter.");
            return;
        }

        let text_h = egui::TextStyle::Body.resolve(ui.style()).size;
        TableBuilder::new(ui)
            .striped(true)
            .resizable(true)
            .cell_layout(egui::Layout::left_to_right(egui::Align::TOP))
            .column(Column::remainder().at_least(180.0)) // Source
            .column(Column::remainder().at_least(180.0)) // Translation
            .column(Column::auto().at_least(90.0)) // Note/Loc
            .header(text_h + 6.0, |mut header| {
                header.col(|ui| {
                    ui.strong("Source");
                });
                header.col(|ui| {
                    ui.strong("Translation");
                });
                header.col(|ui| {
                    ui.strong("Note / Loc");
                });
            })
            // Virtualized: only on-screen rows are built, so a file with thousands of lines (the
            // unpacked .txt scenes) does not lay out every TextEdit every frame.
            .body(|body| {
                body.rows(text_h * 3.2, count, |mut r| {
                    let idx = filtered.as_ref().map_or(r.index(), |v| v[r.index()]);
                    let row = &mut rows[idx];
                    r.col(|ui| {
                        ui.add(
                            egui::Label::new(egui::RichText::new(&row.source).monospace())
                                .wrap(),
                        );
                    });
                    r.col(|ui| {
                        ui.add(
                            egui::TextEdit::multiline(&mut row.translation)
                                .desired_rows(2)
                                .desired_width(f32::INFINITY),
                        );
                    });
                    r.col(|ui| {
                        ui.vertical(|ui| {
                            ui.add(
                                egui::Label::new(
                                    egui::RichText::new(&row.location).weak().small(),
                                )
                                .wrap(),
                            );
                            if !row.note.is_empty() {
                                ui.add(
                                    egui::Label::new(
                                        egui::RichText::new(&row.note).weak().small(),
                                    )
                                    .wrap(),
                                );
                            }
                        });
                    });
                });
            });
    }

    /// The small name-conflict panel, shown below the grid when the last check found any.
    fn translation_conflicts_panel(&mut self, ui: &mut egui::Ui) {
        let tr = &mut self.state.translation;
        if tr.conflicts.is_empty() {
            return;
        }
        ui.add_space(6.0);
        ui.separator();
        ui.colored_label(
            egui::Color32::from_rgb(0xE0, 0xB0, 0x40),
            format!("Warning: {} name(s) translated inconsistently:", tr.conflicts.len()),
        );
        egui::ScrollArea::vertical()
            .max_height(120.0)
            .auto_shrink([false, true])
            .show(ui, |ui| {
                for c in &tr.conflicts {
                    ui.label(format!(
                        "{:?} → {}",
                        c.source,
                        c.variants
                            .iter()
                            .map(|v| format!("{:?}", v.text))
                            .collect::<Vec<_>>()
                            .join("  ·  ")
                    ));
                }
            });
        if ui.button("Clear conflicts").clicked() {
            tr.conflicts.clear();
        }
    }

    // --- Translation background jobs + sync helpers ---------------------------------------

    /// Drain the heavy-result side-channel: a finished job hands its rebuilt model / conflicts here.
    fn poll_translation_result(&mut self) {
        let Some(rx) = &self.state.translation.result_rx else {
            return;
        };
        // Take whatever is available. The channel closes when the worker drops its sender.
        let mut disconnected = false;
        loop {
            match rx.try_recv() {
                Ok(TrResult::Model(m)) => {
                    let nfiles = m.files.len();
                    self.state.translation.model = Some(*m);
                    // Keep the user's current selection across inject/merge/check (the model comes
                    // back the same shape). Only fix it up if it now points past the end (a fresh
                    // extract with fewer files, or no files at all).
                    let stale = match self.state.translation.selected {
                        SelectedEntry::File(i) => i >= nfiles,
                        SelectedEntry::Names => false,
                    };
                    if stale {
                        self.state.translation.selected =
                            if nfiles > 0 { SelectedEntry::File(0) } else { SelectedEntry::Names };
                    }
                }
                Ok(TrResult::Conflicts(c)) => self.state.translation.conflicts = c,
                Err(std::sync::mpsc::TryRecvError::Empty) => break,
                Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                    disconnected = true;
                    break;
                }
            }
        }
        if disconnected && !self.jobs.is_running() {
            self.state.translation.result_rx = None;
        }
    }

    /// Spawn the Extract job: build the editable model off the worker thread, hand it back via the
    /// side-channel, and report counts through the job log/progress (the scaffold's pattern).
    fn start_extract_job(&mut self) {
        let Some(dir) = self.state.translation.source_dir.clone() else {
            return;
        };
        // A fresh extract invalidates any prior conflict findings.
        self.state.translation.conflicts.clear();
        let (tx, rx) = std::sync::mpsc::channel();
        self.state.translation.result_rx = Some(rx);
        self.jobs.run(format!("Extract {}", dir.display()), &mut self.log, move |rep| {
            rep.progress(0.0, "scanning folder…");
            let outcome = translation::extract_model(&dir, |frac, msg| rep.progress(frac, msg))?;
            for w in &outcome.warnings {
                rep.warn(w.clone());
            }
            let strings: usize = outcome.model.files.iter().map(|f| f.rows.len()).sum();
            let names = outcome.model.names.len();
            let nfiles = outcome.model.files.len();
            send_model(&tx, outcome.model);
            rep.progress(1.0, "done");
            Ok(format!("{strings} strings across {nfiles} file(s), {names} names"))
        });
    }

    /// Spawn the Inject job: serialize the edited model and apply it via the library inject paths.
    fn start_inject_job(&mut self) {
        // The model lives in section state and carries the edits, so re-extracting would drop them.
        // Take the model out, run inject, and put it back via the side-channel so the (unchanged)
        // model returns to the UI.
        let Some(model) = self.state.translation.model.take() else {
            return;
        };
        let opts = InjectOptions {
            allow_code_drift: self.state.translation.allow_code_drift,
            normalize_punct: self.state.translation.en_punct,
        };
        let target = match self.state.translation.out_dir.clone() {
            Some(od) => InjectTarget::OutDir(od),
            None => InjectTarget::InPlace,
        };
        let where_label = match &target {
            InjectTarget::InPlace => "in place".to_string(),
            InjectTarget::OutDir(p) => format!("→ {}", p.display()),
        };
        let (tx, rx) = std::sync::mpsc::channel();
        self.state.translation.result_rx = Some(rx);
        self.jobs.run(format!("Inject ({where_label})"), &mut self.log, move |rep| {
            let mut model = model;
            rep.progress(0.0, "injecting…");
            let result = translation::inject_model(
                &mut model,
                &opts,
                &target,
                |frac, msg| rep.progress(frac, msg),
            );
            // Whatever happens, hand the model back so the UI keeps the user's edits.
            let report = match result {
                Ok(reports) => {
                    let (mut a, mut s, mut d) = (0, 0, 0);
                    for r in &reports {
                        rep.info(format!(
                            "  {} — {} applied, {} skipped, {} drifted",
                            r.file, r.applied, r.skipped, r.drifted
                        ));
                        a += r.applied;
                        s += r.skipped;
                        d += r.drifted;
                    }
                    Ok(format!("{a} applied, {s} skipped, {d} drifted across {} file(s)", reports.len()))
                }
                Err(e) => Err(e),
            };
            send_model(&tx, model);
            rep.progress(1.0, "done");
            report
        });
    }

    /// Spawn the Merge job: pick old translation file(s)/dir, carry their translations into the model.
    fn start_merge_job(&mut self) {
        // Pick the old translations on the UI thread (file dialogs must not run on a worker).
        let mut old: Vec<PathBuf> = Vec::new();
        if let Some(dir) = widgets::pick_folder() {
            old.push(dir);
        } else if let Some(files) =
            rfd::FileDialog::new().add_filter("Translation JSON", &["json"]).pick_files()
        {
            old.extend(files);
        }
        if old.is_empty() {
            return;
        }
        let Some(model) = self.state.translation.model.take() else {
            return;
        };
        let (tx, rx) = std::sync::mpsc::channel();
        self.state.translation.result_rx = Some(rx);
        self.jobs.run("Merge older translation".to_string(), &mut self.log, move |rep| {
            let mut model = model;
            rep.progress(0.1, "building translation memory…");
            let result = translation::merge_into_model(&mut model, &old);
            let summary = match &result {
                Ok(m) => Ok(format!("carried {} translation(s); {} still new", m.carried, m.still_new)),
                Err(e) => Err(e.clone()),
            };
            send_model(&tx, model);
            rep.progress(1.0, "done");
            summary
        });
    }

    /// Spawn the Check-names job: run the conflict check over the model, surface findings in the panel.
    fn start_check_job(&mut self) {
        let Some(model) = self.state.translation.model.take() else {
            return;
        };
        let (tx, rx) = std::sync::mpsc::channel();
        self.state.translation.result_rx = Some(rx);
        self.jobs.run("Check names".to_string(), &mut self.log, move |rep| {
            let mut model = model;
            rep.progress(0.2, "scanning for conflicts…");
            let conflicts = translation::check_conflicts(&mut model);
            let n = conflicts.len();
            // Hand both the (unchanged) model and the conflict list back.
            let _ = tx.send(TrResult::Model(Box::new(model)));
            let _ = tx.send(TrResult::Conflicts(conflicts));
            rep.progress(1.0, "done");
            if n == 0 {
                Ok("no name-translation conflicts".to_string())
            } else {
                Ok(format!("{n} name(s) translated inconsistently — see the panel"))
            }
        });
    }

    /// Save the whole model to a single project JSON (synchronous, serialization is fast).
    fn translation_save_project(&mut self) {
        let Some(model) = self.state.translation.model.as_mut() else {
            return;
        };
        let Some(path) = widgets::save_file(
            "translation.wdtr.json",
            &[("WolfDawn translation", &["json"])],
        ) else {
            return;
        };
        match translation::save_to_path(model, &path) {
            Ok(()) => self.log.info(format!("saved translation project → {}", path.display())),
            Err(e) => self.log.error(format!("save failed: {e}")),
        }
    }

    /// Load a model from a project JSON (synchronous).
    fn translation_load_project(&mut self) {
        let Some(path) = widgets::pick_file(&[("WolfDawn translation", &["json"])]) else {
            return;
        };
        match translation::load_from_path(&path) {
            Ok(model) => {
                let total = model.total_rows();
                self.state.translation.selected =
                    if model.files.is_empty() { SelectedEntry::Names } else { SelectedEntry::File(0) };
                if self.state.translation.source_dir.is_none() {
                    self.state.translation.source_dir = Some(model.data_dir.clone());
                }
                self.state.translation.model = Some(model);
                self.state.translation.conflicts.clear();
                self.log.info(format!("loaded translation project ({total} rows) from {}", path.display()));
            }
            Err(e) => self.log.error(format!("load failed: {e}")),
        }
    }

    fn ui_saves(&mut self, ui: &mut egui::Ui) {
        // Pump any background result (a freshly inspected / re-inspected save) into the section state
        // first, so the rest of this frame renders what the just-finished job produced.
        self.poll_saves_result();

        ui.heading("Saves");
        widgets::caption(ui, "Refresh a baked save's title and player-facing strings to match the translated build.");
        widgets::caption(
            ui,
            "A save bakes in the game's title; a translated build rejects a save whose title doesn't \
             match its own Game.dat (\"trying to load from another game\"). Rewriting the title is \
             exactly what lets an old / Japanese save load in the translated build.",
        );
        ui.add_space(6.0);

        // Default the open path / batch dir to the project's Save dir the first time we're shown.
        self.saves_default_paths();

        // A shared backup toggle (used by both the single-file and batch writes).
        widgets::labeled_checkbox(
            ui,
            &mut self.state.saves.backup,
            "Back up original",
            "Copy each save to a *.bak (single file) or a save_backup_<timestamp>/ folder (batch) \
             before overwriting it. Leave this ON unless you have your own backups.",
        );
        ui.add_space(6.0);

        egui::CollapsingHeader::new("Single save")
            .default_open(true)
            .show(ui, |ui| self.saves_single_pane(ui));

        ui.add_space(8.0);

        egui::CollapsingHeader::new("Batch update a save folder")
            .default_open(false)
            .show(ui, |ui| self.saves_batch_pane(ui));
    }

    /// Seed the batch folder from the open project's scanned `Save/` dir, once (only when empty, so a
    /// folder the user picked is never clobbered).
    fn saves_default_paths(&mut self) {
        if self.state.saves.batch_dir.is_none() {
            if let Some(dir) = self.project.as_ref().and_then(|p| p.save_dir.clone()) {
                self.state.saves.batch_dir = Some(dir);
            }
        }
    }

    /// The single-save pane: open a `.sav`, Inspect it, edit the title + baked strings, and save.
    fn saves_single_pane(&mut self, ui: &mut egui::Ui) {
        // A project dropdown of the scanned saves (Save/*.sav), above the Browse field.
        if let Some(saves) = self.project.as_ref().map(|p| p.saves.clone()) {
            let mut path = self.state.saves.sav_path.clone();
            if project_combo(
                ui,
                "saves_combo",
                "Project save",
                &saves,
                &mut path,
                "Pick a .sav from the open game's Save/ folder (or Browse below for one elsewhere).",
            ) {
                self.state.saves.sav_path = path;
            }
        }

        let start = self.state.saves.batch_dir.clone();
        let mut path = self.state.saves.sav_path.clone();
        widgets::path_field(
            ui,
            "Save file",
            &mut path,
            "A single .sav to inspect and edit.",
            move || {
                widgets::pick_file_in(start.as_deref(), &[("Wolf save", &["sav"]), ("All files", &["*"])])
            },
        );
        self.state.saves.sav_path = path;

        ui.add_space(4.0);
        let running = self.jobs.is_running();
        let have = self.state.saves.sav_path.is_some();
        ui.horizontal(|ui| {
            ui.add_enabled_ui(have && !running, |ui| {
                if ui
                    .button("Inspect")
                    .on_hover_text("Read the save on a background thread: detect its format, decode the title, and list its baked strings.")
                    .clicked()
                {
                    self.start_inspect_job();
                }
            });
            if self.state.saves.loaded.is_some()
                && ui
                    .button("Close save")
                    .on_hover_text("Clear the loaded save and free its memory (discards unsaved edits).")
                    .clicked()
            {
                self.unload_save();
            }
        });
        if !have {
            widgets::caption(ui, "Pick a .sav (or open a game with a Save/ folder) and press Inspect.");
        }

        ui.add_space(6.0);
        if self.state.saves.loaded.is_some() {
            ui.separator();
            ui.add_space(4.0);
            self.saves_editor(ui);
        }
    }

    /// The loaded-save editor: a format/encoding badge, the editable title, the baked-string table,
    /// and the Save-changes button. For an unsupported save, editing is disabled with a clear note.
    fn saves_editor(&mut self, ui: &mut egui::Ui) {
        let running = self.jobs.is_running();
        let loaded = self.state.saves.loaded.as_mut().expect("loaded checked by caller");

        // Format badge + encoding.
        ui.horizontal(|ui| {
            let (label, color) = match loaded.format {
                SaveFormat::Standard => ("Standard", egui::Color32::from_rgb(0x40, 0xA0, 0x60)),
                SaveFormat::GameProPro => ("GamePro Pro", egui::Color32::from_rgb(0x40, 0x80, 0xE0)),
                SaveFormat::Unsupported => ("Unsupported", egui::Color32::from_rgb(0xE0, 0x60, 0x60)),
            };
            ui.label(egui::RichText::new(format!(" {label} ")).strong().background_color(color).color(egui::Color32::BLACK))
                .on_hover_text("The detected save codec. Standard and GamePro Pro can be edited; an unsupported save is read-only.");
            ui.separator();
            ui.label(format!("Encoding: {}", loaded.encoding))
                .on_hover_text("How the baked strings are stored (utf8 or sjis). A Shift-JIS save can only hold characters representable in Shift-JIS.");
            ui.separator();
            ui.label(egui::RichText::new(loaded.path.display().to_string()).weak());
        });
        ui.add_space(6.0);

        if loaded.format == SaveFormat::Unsupported {
            ui.colored_label(
                egui::Color32::from_rgb(0xE0, 0xB0, 0x40),
                "Warning: This save's format isn't supported yet, so it can't be edited. Only standard and \
                 GamePro Pro saves can be rewritten.",
            );
            return;
        }

        // Editable title (in a shared form row so it aligns with the section's path rows).
        widgets::text_row(
            ui,
            "Title",
            &mut loaded.title,
            "The baked game identity. Set this to the translated build's Game.dat title so the \
             save loads there. This is the field that fixes \"trying to load from another game\".",
            "",
        );
        if loaded.title_changed() {
            ui.label(
                egui::RichText::new(format!("was: {}", loaded.original_title)).weak().small(),
            );
        }
        ui.add_space(6.0);

        // Baked-string filter + counter.
        let changed = loaded.changed_count();
        let total = loaded.strings.len();
        ui.horizontal(|ui| {
            ui.label("Filter:");
            ui.add(
                egui::TextEdit::singleline(&mut self.state.saves.filter)
                    .hint_text("search baked strings")
                    .desired_width(220.0),
            );
            ui.separator();
            ui.label(egui::RichText::new(format!("{changed} edited · {total} strings")).strong());
        });
        ui.add_space(4.0);

        self.saves_string_table(ui);

        ui.add_space(8.0);
        let loaded = self.state.saves.loaded.as_ref().expect("loaded");
        let dirty = loaded.title_changed() || loaded.changed_count() > 0;
        ui.add_enabled_ui(dirty && !running, |ui| {
            if ui
                .button("Save changes ▶")
                .on_hover_text("Write the edited title + changed baked strings back into the save (backing up the original first if the box is checked).")
                .clicked()
            {
                self.start_save_changes_job();
            }
        });
        if !dirty {
            widgets::caption(ui, "Edit the title or a baked string to enable Save changes.");
        }
    }

    /// The baked-string table: a `TableBuilder` with one editable `TextEdit` per string and the
    /// original shown dim alongside. Honours the filter box.
    fn saves_string_table(&mut self, ui: &mut egui::Ui) {
        use egui_extras::{Column, TableBuilder};

        let loaded = self.state.saves.loaded.as_mut().expect("loaded");
        let needle = self.state.saves.filter.to_lowercase();
        let visible: Vec<usize> = loaded
            .strings
            .iter()
            .enumerate()
            .filter(|(_, r)| {
                needle.is_empty()
                    || r.original.to_lowercase().contains(&needle)
                    || r.edited.to_lowercase().contains(&needle)
            })
            .map(|(i, _)| i)
            .collect();

        if loaded.strings.is_empty() {
            widgets::caption(ui, "This save has no baked player-facing strings to edit.");
            return;
        }
        if visible.is_empty() {
            widgets::caption(ui, "No baked strings match the current filter.");
            return;
        }

        let text_h = egui::TextStyle::Body.resolve(ui.style()).size;
        TableBuilder::new(ui)
            .striped(true)
            .resizable(true)
            .cell_layout(egui::Layout::left_to_right(egui::Align::TOP))
            .column(Column::remainder().at_least(180.0)) // Original (dim)
            .column(Column::remainder().at_least(180.0)) // Edited
            .header(text_h + 6.0, |mut header| {
                header.col(|ui| {
                    ui.strong("Original");
                });
                header.col(|ui| {
                    ui.strong("Edited");
                });
            })
            .body(|mut body| {
                for &i in &visible {
                    let row = &mut loaded.strings[i];
                    body.row(text_h * 2.0, |mut r| {
                        r.col(|ui| {
                            ui.add(
                                egui::Label::new(
                                    egui::RichText::new(&row.original).monospace().weak(),
                                )
                                .wrap(),
                            );
                        });
                        r.col(|ui| {
                            ui.add(
                                egui::TextEdit::singleline(&mut row.edited)
                                    .desired_width(f32::INFINITY),
                            );
                        });
                    });
                }
            });
    }

    /// The batch pane: pick a save folder, choose a new title (typed or from a translated Game.dat)
    /// and/or a translations file/dir, then run update_save over every *.sav (mirrors the CLI).
    fn saves_batch_pane(&mut self, ui: &mut egui::Ui) {
        widgets::caption(
            ui,
            "Apply a new title and/or refreshed baked strings to every .sav in a folder at once - \
             the same as the command-line save-update.",
        );
        ui.add_space(4.0);

        let mut dir = self.state.saves.batch_dir.clone();
        let start = dir.clone();
        widgets::path_field(
            ui,
            "Save folder",
            &mut dir,
            "The folder holding the .sav files (e.g. the game's Save/ folder).",
            move || widgets::pick_folder_in(start.as_deref()),
        );
        self.state.saves.batch_dir = dir;
        ui.add_space(6.0);

        // Title source: None / Typed / from Game.dat.
        let sv = &mut self.state.saves;
        ui.horizontal(|ui| {
            ui.label("New title:").on_hover_text(
                "What to set every save's baked title to. Pick \"From Game.dat\" to copy the \
                 translated build's title, so the saves load there.",
            );
            ui.radio_value(&mut sv.batch_title_mode, BatchTitleMode::None, "leave as-is")
                .on_hover_text("Don't change the title; only refresh baked strings (needs a translations file below).");
            ui.radio_value(&mut sv.batch_title_mode, BatchTitleMode::Typed, "type one");
            ui.radio_value(&mut sv.batch_title_mode, BatchTitleMode::FromGameDat, "from Game.dat")
                .on_hover_text("Read the title from a translated Game.dat (the same value the game checks).");
        });

        match self.state.saves.batch_title_mode {
            BatchTitleMode::Typed => {
                widgets::text_row(
                    ui,
                    "Title text",
                    &mut self.state.saves.batch_title,
                    "",
                    "the translated game title",
                );
            }
            BatchTitleMode::FromGameDat => {
                let mut gd = self.state.saves.batch_game_dat.clone();
                widgets::path_field(
                    ui,
                    "Game.dat",
                    &mut gd,
                    "A translated Game.dat; its Title is read and applied to every save.",
                    || widgets::pick_file(&[("Game data", &["dat"]), ("All files", &["*"])]),
                );
                self.state.saves.batch_game_dat = gd;
            }
            BatchTitleMode::None => {}
        }
        ui.add_space(6.0);

        // Optional translations source for the baked-string refresh.
        let mut tr = self.state.saves.batch_translations.clone();
        widgets::path_field(
            ui,
            "Translations",
            &mut tr,
            "Optional: a translation .json file or a folder of them. Their source→target text is \
             used to refresh the saves' baked strings (the same map the game itself uses).",
            || {
                // Prefer a folder, fall back to a single JSON file.
                widgets::pick_folder().or_else(|| widgets::pick_file(&[("Translation JSON", &["json"])]))
            },
        );
        self.state.saves.batch_translations = tr;

        ui.add_space(8.0);
        let running = self.jobs.is_running();
        let have_dir = self.state.saves.batch_dir.is_some();
        // Something to do? a title source that yields a title, or a translations path.
        let has_title = match self.state.saves.batch_title_mode {
            BatchTitleMode::None => false,
            BatchTitleMode::Typed => !self.state.saves.batch_title.trim().is_empty(),
            BatchTitleMode::FromGameDat => self.state.saves.batch_game_dat.is_some(),
        };
        let has_tr = self.state.saves.batch_translations.is_some();
        let ready = have_dir && (has_title || has_tr);
        ui.add_enabled_ui(ready && !running, |ui| {
            if ui
                .button("Batch update ▶")
                .on_hover_text("Update every .sav in the folder. Unsupported saves are skipped, not mangled.")
                .clicked()
            {
                self.start_batch_job();
            }
        });
        if !ready {
            widgets::caption(
                ui,
                "Pick a save folder and choose a new title and/or a translations file to enable Batch update.",
            );
        }
    }

    // --- Saves background jobs + sync helpers ---------------------------------------------

    /// Drain the heavy-result side-channel: a finished single-file job hands its (re-)inspected save
    /// here (mirrors `poll_translation_result`).
    fn poll_saves_result(&mut self) {
        let Some(rx) = &self.state.saves.result_rx else {
            return;
        };
        let mut disconnected = false;
        loop {
            match rx.try_recv() {
                Ok(SaveResult::Loaded(s)) => {
                    self.state.saves.loaded = Some(*s);
                    self.state.saves.filter.clear();
                }
                Err(std::sync::mpsc::TryRecvError::Empty) => break,
                Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                    disconnected = true;
                    break;
                }
            }
        }
        if disconnected && !self.jobs.is_running() {
            self.state.saves.result_rx = None;
        }
    }

    /// Spawn the Inspect job: read + inspect the save off the worker thread, hand the editable model
    /// back via the side-channel, and report the format/encoding/counts through the job log.
    fn start_inspect_job(&mut self) {
        let Some(path) = self.state.saves.sav_path.clone() else {
            return;
        };
        let (tx, rx) = std::sync::mpsc::channel();
        self.state.saves.result_rx = Some(rx);
        self.jobs.run(format!("Inspect {}", path.display()), &mut self.log, move |rep| {
            rep.progress(0.2, "reading save…");
            let loaded = saves::inspect(&path)?;
            let summary = format!(
                "{} save, {} encoding, title {:?}, {} baked string(s)",
                loaded.format.label(),
                loaded.encoding,
                loaded.original_title,
                loaded.strings.len()
            );
            if !loaded.editable() {
                rep.warn("this save's format isn't supported; it opened read-only");
            }
            let _ = tx.send(SaveResult::Loaded(Box::new(loaded)));
            rep.progress(1.0, "done");
            Ok(summary)
        });
    }

    /// Spawn the Save-changes job: write the edited save (backing up first), then re-inspect the
    /// written bytes and hand the fresh model back so the UI shows the persisted state.
    fn start_save_changes_job(&mut self) {
        // Move the loaded save onto the worker. It comes back (re-inspected) via the side-channel.
        let Some(loaded) = self.state.saves.loaded.take() else {
            return;
        };
        let backup = self.state.saves.backup;
        let (tx, rx) = std::sync::mpsc::channel();
        self.state.saves.result_rx = Some(rx);
        self.jobs.run("Save changes".to_string(), &mut self.log, move |rep| {
            rep.progress(0.2, "writing save…");
            let path = loaded.path.clone();
            let result = saves::save_changes(&loaded, backup);
            // Whatever happens, hand a model back so the editor isn't left empty: the re-inspected
            // file on success, or the (unchanged) in-memory model on failure.
            match result {
                Ok(stats) => {
                    rep.info(format!(
                        "title changed: {} · strings replaced: {} · encoding: {}",
                        stats.title_changed, stats.strings_replaced, stats.encoding
                    ));
                    if backup {
                        rep.info(format!("backed up original → {}.bak", path.display()));
                    }
                    match saves::inspect(&path) {
                        Ok(fresh) => {
                            let _ = tx.send(SaveResult::Loaded(Box::new(fresh)));
                        }
                        Err(e) => {
                            rep.warn(format!("re-inspect after write failed: {e}"));
                            let _ = tx.send(SaveResult::Loaded(Box::new(loaded)));
                        }
                    }
                    rep.progress(1.0, "done");
                    Ok(format!(
                        "saved {} (title {}, {} string(s) replaced)",
                        path.display(),
                        if stats.title_changed { "updated" } else { "unchanged" },
                        stats.strings_replaced
                    ))
                }
                Err(e) => {
                    // Put the model back unchanged so the user's edits aren't lost.
                    let _ = tx.send(SaveResult::Loaded(Box::new(loaded)));
                    rep.progress(1.0, "done");
                    Err(e)
                }
            }
        });
    }

    /// Spawn the Batch job: resolve the title (typed or from Game.dat) + the string map (from the
    /// translations path) on the UI thread, then run update_save over every *.sav on the worker.
    fn start_batch_job(&mut self) {
        let sv = &self.state.saves;
        let Some(dir) = sv.batch_dir.clone() else {
            return;
        };
        // Resolve the new title up front (Game.dat read is cheap and surfaces errors immediately).
        let new_title: Option<String> = match sv.batch_title_mode {
            BatchTitleMode::None => None,
            BatchTitleMode::Typed => {
                let t = sv.batch_title.trim();
                (!t.is_empty()).then(|| t.to_string())
            }
            BatchTitleMode::FromGameDat => match &sv.batch_game_dat {
                Some(gd) => match saves::title_from_game_dat(gd) {
                    Ok(t) => {
                        self.log.info(format!("batch: title from {} = {t:?}", gd.display()));
                        Some(t)
                    }
                    Err(e) => {
                        self.log.error(format!("batch: {e}"));
                        return;
                    }
                },
                None => None,
            },
        };
        // Build the baked-string map from the translations path, if given.
        let map = match &sv.batch_translations {
            Some(p) => match saves::build_string_map(std::slice::from_ref(p)) {
                Ok((m, conflicts)) => {
                    if conflicts > 0 {
                        self.log.warn(format!(
                            "batch: {conflicts} source(s) had divergent translations across files; kept the first"
                        ));
                    }
                    m
                }
                Err(e) => {
                    self.log.error(format!("batch: {e}"));
                    return;
                }
            },
            None => std::collections::HashMap::new(),
        };
        let backup = sv.backup;

        self.jobs.run(format!("Batch update {}", dir.display()), &mut self.log, move |rep| {
            rep.progress(0.0, "scanning saves…");
            let outcome = saves::batch_update(
                &dir,
                new_title.as_deref(),
                &map,
                backup,
                |frac, msg| rep.progress(frac, msg),
            )?;
            if let Some(bdir) = &outcome.backup_dir {
                rep.info(format!("backed up originals → {}", bdir.display()));
            }
            for entry in &outcome.entries {
                match entry {
                    saves::BatchEntry::Updated(name, stats) => rep.info(format!(
                        "  {name}: title={} strings={} enc={}",
                        u8::from(stats.title_changed),
                        stats.strings_replaced,
                        stats.encoding
                    )),
                    saves::BatchEntry::Skipped(name) => {
                        rep.warn(format!("  {name}: SKIPPED (unsupported save format)"))
                    }
                    saves::BatchEntry::Failed(name, msg) => {
                        rep.error(format!("  {name}: {msg}"))
                    }
                }
            }
            rep.progress(1.0, "done");
            Ok(format!(
                "{} updated, {} skipped, {} failed",
                outcome.updated(),
                outcome.skipped(),
                outcome.failed()
            ))
        });
    }

    fn ui_verify(&mut self, ui: &mut egui::Ui) {
        // Pump any background result (a single verdict / a corpus outcome) into section state first.
        self.poll_verify_result();

        ui.heading("Verify");
        widgets::caption(
            ui,
            "Verify confirms a file decodes and re-encodes without loss (byte-exact where possible) \
             — your safety net before shipping.",
        );
        ui.add_space(6.0);

        // Default the corpus folder to the open project's data dir the first time we're shown.
        if self.state.verify.corpus_dir.is_none() {
            if let Some(d) = self.project.as_ref().and_then(|p| p.data_dir.clone()) {
                self.state.verify.corpus_dir = Some(d);
            }
        }

        egui::CollapsingHeader::new("Single file")
            .default_open(true)
            .show(ui, |ui| self.verify_single_pane(ui));

        ui.add_space(8.0);

        egui::CollapsingHeader::new("Corpus (a whole folder)")
            .default_open(true)
            .show(ui, |ui| self.verify_corpus_pane(ui));
    }

    /// The single-file pane: pick a data file, Verify it, show a PASS/FAIL/ERR result panel.
    fn verify_single_pane(&mut self, ui: &mut egui::Ui) {
        let mut file = self.state.verify.file.clone();
        widgets::path_field(
            ui,
            "Data file",
            &mut file,
            "Any single data file (.mps map, CommonEvent.dat, Game.dat, or a database .project).",
            || {
                widgets::pick_file(&[
                    ("Wolf data", &["mps", "dat", "project"]),
                    ("All files", &["*"]),
                ])
            },
        );
        self.state.verify.file = file;

        // Warn early if the pick isn't a verifiable file type. Verify still runs and gives an ERR verdict.
        if let Some(f) = &self.state.verify.file {
            if !verify::is_supported(f) {
                ui.colored_label(
                    egui::Color32::from_rgb(0xE0, 0xB0, 0x40),
                    "Warning: this is not a verifiable file type (.mps, CommonEvent.dat, Game.dat, or a database .project).",
                );
            }
        }

        ui.add_space(4.0);
        let running = self.jobs.is_running();
        let have = self.state.verify.file.is_some();
        ui.add_enabled_ui(have && !running, |ui| {
            if ui
                .button("Verify ▶")
                .on_hover_text("Round-trip this file on a background thread and report PASS / FAIL.")
                .clicked()
            {
                self.start_verify_file_job();
            }
        });
        if !have {
            widgets::caption(ui, "Pick a data file to verify.");
        }

        // The result panel for the last single-file verdict.
        if let Some((path, verdict)) = &self.state.verify.file_verdict {
            ui.add_space(6.0);
            let (color, tag) = verdict_color(verdict);
            ui.horizontal(|ui| {
                ui.label(
                    egui::RichText::new(format!(" {tag} "))
                        .strong()
                        .background_color(color)
                        .color(egui::Color32::BLACK),
                );
                ui.label(egui::RichText::new(path.display().to_string()).weak());
            });
            ui.label(verdict.detail());
        }
    }

    /// The corpus pane: pick a folder, Verify all, show a per-file table + the byte-exact summary.
    fn verify_corpus_pane(&mut self, ui: &mut egui::Ui) {
        let start = self.state.verify.corpus_dir.clone();
        let mut dir = self.state.verify.corpus_dir.clone();
        widgets::path_field(
            ui,
            "Folder",
            &mut dir,
            "A folder of game data; every supported file under it is round-tripped.",
            move || widgets::pick_folder_in(start.as_deref()),
        );
        self.state.verify.corpus_dir = dir;

        ui.add_space(4.0);
        let running = self.jobs.is_running();
        let have = self.state.verify.corpus_dir.is_some();
        ui.add_enabled_ui(have && !running, |ui| {
            if ui
                .button("Verify all ▶")
                .on_hover_text("Walk the folder and round-trip every supported file on a background thread.")
                .clicked()
            {
                self.start_verify_corpus_job();
            }
        });
        if !have {
            widgets::caption(ui, "Pick a folder to verify its files.");
        }

        if let Some(outcome) = &self.state.verify.corpus {
            ui.add_space(6.0);
            let (pass, fail, err, total) =
                (outcome.passed(), outcome.failed(), outcome.errored(), outcome.total());
            let summary = egui::RichText::new(format!("{pass}/{total} byte-exact"))
                .strong()
                .color(if fail == 0 && err == 0 {
                    egui::Color32::from_rgb(0x40, 0xA0, 0x60)
                } else {
                    egui::Color32::from_rgb(0xE0, 0xB0, 0x40)
                });
            ui.horizontal(|ui| {
                ui.label(summary);
                if fail > 0 || err > 0 {
                    ui.label(
                        egui::RichText::new(format!("· {fail} differ · {err} error")).weak(),
                    );
                }
            });
            ui.add_space(4.0);
            self.verify_corpus_table(ui);
        }
    }

    /// The per-file corpus result table: file | result.
    fn verify_corpus_table(&mut self, ui: &mut egui::Ui) {
        use egui_extras::{Column, TableBuilder};

        let Some(outcome) = &self.state.verify.corpus else {
            return;
        };
        let text_h = egui::TextStyle::Body.resolve(ui.style()).size;
        TableBuilder::new(ui)
            .striped(true)
            .resizable(true)
            .cell_layout(egui::Layout::left_to_right(egui::Align::TOP))
            .column(Column::remainder().at_least(200.0)) // File
            .column(Column::auto().at_least(220.0)) // Result
            .header(text_h + 6.0, |mut header| {
                header.col(|ui| {
                    ui.strong("File");
                });
                header.col(|ui| {
                    ui.strong("Result");
                });
            })
            .body(|mut body| {
                for row in &outcome.rows {
                    body.row(text_h * 1.8, |mut r| {
                        r.col(|ui| {
                            ui.add(
                                egui::Label::new(egui::RichText::new(&row.rel).monospace()).wrap(),
                            );
                        });
                        r.col(|ui| {
                            let (color, tag) = verdict_color(&row.verdict);
                            ui.horizontal(|ui| {
                                ui.label(
                                    egui::RichText::new(format!(" {tag} "))
                                        .strong()
                                        .background_color(color)
                                        .color(egui::Color32::BLACK),
                                );
                                if !row.verdict.is_pass() {
                                    ui.add(
                                        egui::Label::new(
                                            egui::RichText::new(row.verdict.detail()).weak().small(),
                                        )
                                        .wrap(),
                                    );
                                }
                            });
                        });
                    });
                }
            });
    }

    // --- Verify background jobs + sync helpers ---------------------------------------------

    /// Drain the heavy-result side-channel: a finished verify job hands its verdict / corpus here
    /// (mirrors `poll_translation_result` / `poll_saves_result`).
    fn poll_verify_result(&mut self) {
        let Some(rx) = &self.state.verify.result_rx else {
            return;
        };
        let mut disconnected = false;
        loop {
            match rx.try_recv() {
                Ok(VerifyResult::Single(path, v)) => {
                    self.state.verify.file_verdict = Some((path, *v));
                }
                Ok(VerifyResult::Corpus(c)) => self.state.verify.corpus = Some(*c),
                Err(std::sync::mpsc::TryRecvError::Empty) => break,
                Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                    disconnected = true;
                    break;
                }
            }
        }
        if disconnected && !self.jobs.is_running() {
            self.state.verify.result_rx = None;
        }
    }

    /// Spawn the single-file Verify job: round-trip the file on a worker thread, hand the verdict
    /// back via the side-channel, and log a PASS/FAIL/ERR line.
    fn start_verify_file_job(&mut self) {
        let Some(path) = self.state.verify.file.clone() else {
            return;
        };
        let (tx, rx) = std::sync::mpsc::channel();
        self.state.verify.result_rx = Some(rx);
        self.jobs.run(format!("Verify {}", path.display()), &mut self.log, move |rep| {
            rep.progress(0.2, "round-tripping…");
            let verdict = verify::verify_file(&path);
            let summary = format!("{} — {}", verdict.tag(), verdict.detail());
            match &verdict {
                Verdict::Pass => rep.info(summary.clone()),
                Verdict::Fail { .. } => rep.warn(summary.clone()),
                Verdict::Error(_) => rep.error(summary.clone()),
            }
            let _ = tx.send(VerifyResult::Single(path.clone(), Box::new(verdict)));
            rep.progress(1.0, "done");
            Ok(summary)
        });
    }

    /// Spawn the Corpus Verify job: walk + round-trip every supported file on a worker thread, hand
    /// the outcome back via the side-channel, and log the summary.
    fn start_verify_corpus_job(&mut self) {
        let Some(dir) = self.state.verify.corpus_dir.clone() else {
            return;
        };
        let (tx, rx) = std::sync::mpsc::channel();
        self.state.verify.result_rx = Some(rx);
        self.jobs.run(format!("Verify corpus {}", dir.display()), &mut self.log, move |rep| {
            let outcome = verify::verify_corpus(&dir, |frac, msg| rep.progress(frac, msg))?;
            let (pass, fail, err, total) =
                (outcome.passed(), outcome.failed(), outcome.errored(), outcome.total());
            // Surface every non-pass file in the log too.
            for row in &outcome.rows {
                if !row.verdict.is_pass() {
                    rep.warn(format!("  {} — {}: {}", row.verdict.tag(), row.rel, row.verdict.detail()));
                }
            }
            let _ = tx.send(VerifyResult::Corpus(Box::new(outcome)));
            Ok(format!("{pass}/{total} byte-exact ({fail} differ, {err} error)"))
        });
    }

    fn ui_settings(&mut self, ui: &mut egui::Ui) {
        ui.heading("Settings");
        widgets::caption(ui, "Theme and tool preferences. These persist across runs.");
        ui.add_space(8.0);

        // --- Theme ---
        ui.label(egui::RichText::new("Theme").strong());
        ui.add_space(2.0);
        ui.horizontal(|ui| {
            // A Dark/Light selector. Applying the visuals immediately on a change keeps it live.
            let mut dark = self.settings.dark_mode;
            let mut changed = ui
                .selectable_value(&mut dark, true, "Dark")
                .on_hover_text("Dark theme (the default).")
                .changed();
            changed |= ui
                .selectable_value(&mut dark, false, "Light")
                .on_hover_text("Light theme.")
                .changed();
            if changed {
                self.settings.dark_mode = dark;
                self.apply_theme(ui.ctx());
            }
        });
        ui.add_space(8.0);
        ui.separator();
        ui.add_space(8.0);

        // --- Translation defaults ---
        ui.label(egui::RichText::new("Translation defaults").strong());
        ui.add_space(2.0);
        widgets::caption(
            ui,
            "Used to initialise the Translation section's inject options; changing one here doesn't \
             override what you've already set this session.",
        );
        widgets::labeled_checkbox(
            ui,
            &mut self.settings.default_en_punct,
            "Default --en-punct on",
            "Start the Translation section with \"convert Japanese punctuation to ASCII\" enabled.",
        );
        widgets::labeled_checkbox(
            ui,
            &mut self.settings.default_allow_code_drift,
            "Default --allow-code-drift on",
            "Start the Translation section with the strict control-code guard relaxed (risky - leave \
             OFF unless you know you need it).",
        );
        ui.add_space(8.0);
        ui.separator();
        ui.add_space(8.0);

        // --- Saves / Database defaults ---
        ui.label(egui::RichText::new("Saves & Database defaults").strong());
        ui.add_space(2.0);
        widgets::labeled_checkbox(
            ui,
            &mut self.settings.default_backup,
            "Back up originals by default",
            "Start the Saves / Database / Game.dat sections with \"back up originals before \
             overwriting\" enabled. Leave ON unless you keep your own backups.",
        );
        ui.add_space(8.0);
        ui.separator();
        ui.add_space(8.0);

        // --- Auto-detect ---
        ui.label(egui::RichText::new("Files").strong());
        ui.add_space(2.0);
        widgets::labeled_checkbox(
            ui,
            &mut self.settings.auto_detect,
            "Auto-detect new files",
            "While a game is open, periodically re-scan its folders so newly-added maps / databases \
             / saves (e.g. right after an Unpack) appear in the per-section dropdowns automatically.",
        );
        if !self.settings.auto_detect {
            widgets::caption(
                ui,
                "Auto-detect is off — use the Refresh button on the Project section to re-scan.",
            );
        }

        ui.add_space(10.0);
        widgets::caption(ui, "Settings are saved automatically when you close the app.");
    }

    // --- chrome ---------------------------------------------------------------------------

    /// Top panel: app title + a one-line summary of the open project.
    fn top_bar(&mut self, ctx: &egui::Context) {
        egui::TopBottomPanel::top("top_bar").show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.heading("WolfDawn Studio");
                ui.separator();
                match &self.project {
                    None => {
                        ui.label(egui::RichText::new("No project").weak());
                    }
                    Some(p) => {
                        let title = if p.title.is_empty() { "(untitled)" } else { &p.title };
                        ui.label(egui::RichText::new(title).strong());
                        ui.separator();
                        ui.label(project::encoding_label(p.utf8));
                        if !p.version.is_empty() {
                            ui.separator();
                            ui.label(&p.version);
                        }
                        if !p.font.is_empty() {
                            ui.separator();
                            ui.label(format!("font: {}", p.font));
                        }
                    }
                }
            });
        });
    }

    /// Left panel: one selectable button per section.
    fn side_bar(&mut self, ctx: &egui::Context) {
        egui::SidePanel::left("nav")
            .resizable(false)
            .exact_width(150.0)
            .show(ctx, |ui| {
                ui.add_space(6.0);
                ui.spacing_mut().item_spacing.y = 2.0;
                for section in Section::ALL {
                    let selected = self.section == section;
                    if nav_button(ui, selected, section.name()).clicked() {
                        self.section = section;
                    }
                }
            });
    }

    /// Bottom panel: the log, plus the progress bar while a job runs.
    fn bottom_bar(&mut self, ctx: &egui::Context) {
        egui::TopBottomPanel::bottom("status")
            .resizable(true)
            .default_height(150.0)
            .show(ctx, |ui| {
                if self.jobs.is_running() {
                    ui.horizontal(|ui| {
                        ui.label(egui::RichText::new(self.jobs.label()).strong());
                        if !self.jobs.status().is_empty() {
                            ui.label(egui::RichText::new(self.jobs.status()).weak());
                        }
                    });
                    ui.add(
                        egui::ProgressBar::new(self.jobs.progress())
                            .show_percentage()
                            .animate(true),
                    );
                    ui.separator();
                }
                ui.label(egui::RichText::new("Log").weak());
                self.log.show(ui);
            });
    }
}

impl WolfDawnApp {
    /// Lay out and render one frame's worth of UI into `ctx`: pump the job channel, draw the four
    /// panels, and request a repaint while a job runs. This is the whole per-frame body, factored
    /// out of [`eframe::App::update`] so the headless tests can drive a full frame without an
    /// `eframe::Frame` (which has no public constructor).
    pub fn render_frame(&mut self, ctx: &egui::Context) {
        // Pump the background job channel first so progress/log are current for this frame.
        let running = self.jobs.poll(&mut self.log);

        // A job just finished this frame (running→idle): if it was an Unpack, immediately rescan the
        // project index so the extracted files appear in the dropdowns now, not on the next throttle.
        if self.job_was_running && !running {
            self.on_job_finished();
        }
        self.job_was_running = running;

        // Live auto-detect: while a project is open (and auto-detect is enabled), periodically
        // re-walk its small index dirs so files added externally (or by a just-finished Unpack)
        // surface in the per-section dropdowns without a manual refresh.
        self.tick_auto_detect();

        self.top_bar(ctx);
        self.side_bar(ctx);
        self.bottom_bar(ctx);
        egui::CentralPanel::default().show(ctx, |ui| {
            self.render_current_section(ui);
        });

        // While a job runs, keep animating even without user input so the bar moves and messages
        // arrive promptly (otherwise egui only repaints on interaction).
        if running {
            ctx.request_repaint();
        } else if self.project.is_some() && self.settings.auto_detect {
            // Keep the auto-detect tick running without user input while a project is open: ask for
            // a repaint ~1s out so the throttled rescan keeps firing even on an idle window.
            ctx.request_repaint_after(Duration::from_secs(1));
        }
    }

    /// The throttled auto-detect tick: when a project is open and auto-detect is on, re-walk its
    /// index at most every ~1.5s. Log a one-line summary only when the file set actually changed.
    fn tick_auto_detect(&mut self) {
        /// How long between background rescans of the open project's index dirs.
        const RESCAN_EVERY: Duration = Duration::from_millis(1500);

        if self.project.is_none() || !self.settings.auto_detect {
            // Reset the clock so re-enabling / re-opening rescans promptly rather than waiting.
            self.last_scan = None;
            return;
        }
        let due = self.last_scan.map_or(true, |t| t.elapsed() >= RESCAN_EVERY);
        if !due {
            return;
        }
        self.last_scan = Some(Instant::now());
        if let Some(project) = self.project.as_mut() {
            if project.rescan() {
                self.log.info(format!(
                    "detected file changes ({} code file(s), {} database(s), {} save(s))",
                    project.code_files.len(),
                    project.databases.len(),
                    project.saves.len(),
                ));
            }
        }
    }

    /// Handle a job finishing (the running→idle transition). When the finished job was an Unpack and
    /// a project is open: adopt the output dir as `data_dir` if it sits under the project root (so
    /// Translation/Verify default to the just-extracted folder), then rescan the index immediately
    /// so the freshly-extracted code/databases/saves populate the dropdowns at once.
    fn on_job_finished(&mut self) {
        let Some(out) = self.pending_unpack_out.take() else {
            return;
        };
        let Some(project) = self.project.as_mut() else {
            return;
        };
        // Adopt the unpack output as the data dir when it lives under (or is) the project root.
        if out.starts_with(&project.root) && project.data_dir.as_deref() != Some(out.as_path()) {
            project.data_dir = Some(out.clone());
            self.log.info(format!("data dir set to unpack output: {}", out.display()));
        }
        if project.rescan() {
            self.log.info(format!(
                "detected file changes ({} code file(s), {} database(s), {} save(s)) after unpack",
                project.code_files.len(),
                project.databases.len(),
                project.saves.len(),
            ));
        }
        // Force the next throttled tick to run promptly too (the index just moved).
        self.last_scan = Some(Instant::now());
    }
}

impl eframe::App for WolfDawnApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.render_frame(ctx);
    }

    /// Persist the user [`Settings`] to eframe's on-disk storage. eframe calls this periodically and
    /// on exit (the `persistence` feature provides the storage backend under the OS config dir).
    fn save(&mut self, storage: &mut dyn eframe::Storage) {
        eframe::set_value(storage, Self::SETTINGS_KEY, &self.settings);
    }
}

/// Render the open project's details into the Project body.
fn project_details(ui: &mut egui::Ui, p: &Project) {
    egui::Grid::new("project_details")
        .num_columns(2)
        .spacing([16.0, 6.0])
        .striped(true)
        .show(ui, |ui| {
            row(ui, "Title", if p.title.is_empty() { "—".into() } else { p.title.clone() });
            row(ui, "Version", if p.version.is_empty() { "—".into() } else { p.version.clone() });
            row(ui, "Encoding", project::encoding_label(p.utf8).to_string());
            row(ui, "Font", if p.font.is_empty() { "—".into() } else { p.font.clone() });
            row(ui, "Game root", p.root.display().to_string());
            row(ui, "Data.wolf", opt_path(&p.data_wolf));
            row(ui, "Data dir", opt_path(&p.data_dir));
            row(ui, "Game.dat", opt_path(&p.game_dat));
            row(
                ui,
                "Indexed",
                format!(
                    "{} code file(s) · {} database(s) · {} save(s)",
                    p.code_files.len(),
                    p.databases.len(),
                    p.saves.len(),
                ),
            );
        });

    if !p.game_dat_ok {
        ui.add_space(8.0);
        ui.colored_label(
            egui::Color32::from_rgb(0xE0, 0xB0, 0x40),
            "Warning: Game.dat was not found or could not be read - the project is open with what was located. See the log below.",
        );
    }
}

fn row(ui: &mut egui::Ui, key: &str, value: String) {
    ui.label(egui::RichText::new(key).strong());
    ui.label(value);
    ui.end_row();
}

fn opt_path(p: &Option<PathBuf>) -> String {
    p.as_ref().map(|p| p.display().to_string()).unwrap_or_else(|| "—".into())
}

/// Hand a (possibly large) model back to the UI thread over the translation side-channel. Boxed so
/// the `TrResult` enum stays small. A send failure (UI hung up / app closing) is a no-op.
fn send_model(tx: &Sender<TrResult>, model: TranslationModel) {
    let _ = tx.send(TrResult::Model(Box::new(model)));
}

/// A project-file dropdown: a `ComboBox` over `options` (the scanned index for this section). The
/// shown text is each path's basename (or its tail relative to a common ancestor when basenames
/// collide, so two `Map001.mps` from different folders stay distinguishable). The *full* path is
/// stored into `target` on selection. Returns `true` when the selection changed this frame.
///
/// Paths are stored as `Option<PathBuf>` everywhere in the sections (matching `widgets::path_field`),
/// so the dropdown reuses that type rather than a raw `String`. Renders nothing (and returns false)
/// when there are no options, so a section with an empty index falls back to its Browse button.
fn project_combo(
    ui: &mut egui::Ui,
    id: &str,
    label: &str,
    options: &[PathBuf],
    target: &mut Option<PathBuf>,
    tooltip: &str,
) -> bool {
    if options.is_empty() {
        return false;
    }
    let mut changed = false;
    // Use the shared form row so the combo's label sits in the same fixed left column as the path
    // rows, and fill the width up to the same right edge those rows' inputs reach (leaving the
    // BTN_COL reserve), so the dropdown lines up with the Browse fields under it.
    widgets::form_row(ui, label, tooltip, |ui| {
        // The selected text: the current target's display name, or a prompt when none is chosen.
        let selected_text = target
            .as_ref()
            .map(|p| combo_label(p, options))
            .unwrap_or_else(|| "— pick from project —".to_string());
        let combo_w = (ui.available_width() - widgets::BTN_COL_W).max(120.0);
        egui::ComboBox::from_id_salt(id)
            .selected_text(selected_text)
            .width(combo_w)
            .show_ui(ui, |ui| {
                for opt in options {
                    let is_sel = target.as_deref() == Some(opt.as_path());
                    if ui
                        .selectable_label(is_sel, combo_label(opt, options))
                        .on_hover_text(opt.display().to_string())
                        .clicked()
                        && !is_sel
                    {
                        *target = Some(opt.clone());
                        changed = true;
                    }
                }
            })
            .response
            .on_hover_text(tooltip);
    });
    changed
}

/// The label shown for one project-combo entry: the file's basename, disambiguated with its parent
/// dir's name when another option shares the same basename (e.g. `MapData/Map001.mps`).
fn combo_label(path: &Path, options: &[PathBuf]) -> String {
    let base = path
        .file_name()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| path.display().to_string());
    let collides = options
        .iter()
        .filter(|o| o.as_path() != path)
        .any(|o| o.file_name() == path.file_name());
    if collides {
        if let Some(parent) = path.parent().and_then(|p| p.file_name()) {
            return format!("{}/{}", parent.to_string_lossy(), base);
        }
    }
    base
}

/// A full-width sidebar nav row. Text-only (no icon column): emoji pictographs render as tofu on
/// systems lacking an emoji font, so the sidebar shows just the section name, left-aligned at a
/// fixed x so every row's text starts at the same column. Mimics `SelectableLabel` visuals.
fn nav_button(ui: &mut egui::Ui, selected: bool, name: &str) -> egui::Response {
    let height = 26.0;
    let (rect, resp) =
        ui.allocate_exact_size(egui::vec2(ui.available_width(), height), egui::Sense::click());
    let visuals = ui.style().interact_selectable(&resp, selected);
    if selected {
        ui.painter()
            .rect_filled(rect, 4.0, ui.visuals().selection.bg_fill);
    } else if resp.hovered() {
        ui.painter().rect_filled(rect, 4.0, visuals.weak_bg_fill);
    }
    let color = visuals.text_color();
    let font = egui::FontId::proportional(15.0);
    let mid_y = rect.center().y;
    ui.painter().text(
        egui::pos2(rect.left() + 10.0, mid_y),
        egui::Align2::LEFT_CENTER,
        name,
        font,
        color,
    );
    resp
}

/// A full-width, multi-line-aware selectable list row (used by the Database type list). Unlike
/// `ui.selectable_label`, this allocates the row at the *wrapped* text height and paints its own
/// rounded, padded highlight, so a long type name that wraps to two lines (e.g.
/// `アニメーション / Animation (34 rows)`) is fully contained by the highlight instead of being
/// clipped by a harsh single-line fill. Mirrors `nav_button`'s painting approach: selected uses
/// `selection.bg_fill`, hovered uses a subtle `weak_bg_fill`, with readable selected-text colour.
/// Returns the row's `Response` (so the caller handles `.clicked()`).
fn selectable_row(ui: &mut egui::Ui, selected: bool, text: &str) -> egui::Response {
    /// Inner padding around the label inside the highlight.
    const PAD_X: f32 = 8.0;
    const PAD_Y: f32 = 4.0;
    /// Rounded-corner radius of the highlight (matches `nav_button`).
    const ROUNDING: f32 = 4.0;

    let full_w = ui.available_width();
    // Lay out the label wrapped to the row width (minus the horizontal padding) so we know how tall
    // the row must be to contain every wrapped line.
    let wrap_w = (full_w - 2.0 * PAD_X).max(1.0);
    let galley = ui.painter().layout(
        text.to_owned(),
        egui::TextStyle::Body.resolve(ui.style()),
        // PLACEHOLDER so the glyph colour is taken from the `fallback_color` passed to
        // `painter.galley` below, the interaction visuals' (selected-aware) text colour.
        egui::Color32::PLACEHOLDER,
        wrap_w,
    );
    let row_h = galley.size().y + 2.0 * PAD_Y;

    let (rect, resp) =
        ui.allocate_exact_size(egui::vec2(full_w, row_h), egui::Sense::click());
    let visuals = ui.style().interact_selectable(&resp, selected);
    if selected {
        ui.painter()
            .rect_filled(rect, ROUNDING, ui.visuals().selection.bg_fill);
    } else if resp.hovered() {
        ui.painter().rect_filled(rect, ROUNDING, visuals.weak_bg_fill);
    }
    // Draw the (already-wrapped) label with padding inside the highlight, using the interaction
    // visuals' text colour so the selected row stays readable.
    ui.painter().galley(
        egui::pos2(rect.left() + PAD_X, rect.top() + PAD_Y),
        galley,
        visuals.text_color(),
    );
    resp
}

/// Parse a cryptVersion from the Repack "match version" field: accepts `0x14b` (hex) or a decimal
/// number, mirroring `cmd_pack`'s `--version` parsing. `None` for anything that doesn't parse.
fn parse_crypt_version(text: &str) -> Option<u16> {
    let t = text.trim();
    if t.is_empty() {
        return None;
    }
    let stripped = t.trim_start_matches("0x").trim_start_matches("0X");
    u16::from_str_radix(stripped, 16).ok().or_else(|| t.parse().ok())
}

/// The badge colour + tag word for a verify [`Verdict`] (green PASS / amber FAIL / red ERR).
fn verdict_color(verdict: &Verdict) -> (egui::Color32, &'static str) {
    match verdict {
        Verdict::Pass => (egui::Color32::from_rgb(0x40, 0xA0, 0x60), "PASS"),
        Verdict::Fail { .. } => (egui::Color32::from_rgb(0xE0, 0xB0, 0x40), "FAIL"),
        Verdict::Error(_) => (egui::Color32::from_rgb(0xE0, 0x60, 0x60), "ERR"),
    }
}

/// Append a Japanese system font as a fallback so CJK glyphs render. egui ships Latin-only fonts, so
/// without this every Japanese string in the tool shows as tofu (□). The JP font goes to the END of
/// both families, so Latin keeps the crisp default and only glyphs the default lacks (kana/kanji)
/// fall back to it. Tries a few common Windows fonts. If none is found it's a no-op (Latin only).
fn install_cjk_font(ctx: &egui::Context) {
    const CANDIDATES: &[&str] = &[
        r"C:\Windows\Fonts\YuGothR.ttc",
        r"C:\Windows\Fonts\meiryo.ttc",
        r"C:\Windows\Fonts\msgothic.ttc",
        r"C:\Windows\Fonts\YuGothM.ttc",
        r"C:\Windows\Fonts\msmincho.ttc",
    ];
    let Some(bytes) = CANDIDATES.iter().find_map(|p| std::fs::read(p).ok()) else {
        return;
    };
    let mut fonts = egui::FontDefinitions::default();
    fonts
        .font_data
        .insert("jp".to_owned(), egui::FontData::from_owned(bytes));
    for family in [egui::FontFamily::Proportional, egui::FontFamily::Monospace] {
        fonts.families.entry(family).or_default().push("jp".to_owned());
    }
    ctx.set_fonts(fonts);
}

/// A short, always-renderable text tag for each translatable file kind in the left list (shown in
/// brackets before the file name). Replaces the old emoji icons so the list never tofus.
fn kind_icon(kind: FileKind) -> &'static str {
    match kind {
        FileKind::Map => "[Map]",
        FileKind::CommonEvent => "[Common]",
        FileKind::Database => "[DB]",
        FileKind::GameDat => "[Game]",
        FileKind::TxtEvent => "[Text]",
    }
}
