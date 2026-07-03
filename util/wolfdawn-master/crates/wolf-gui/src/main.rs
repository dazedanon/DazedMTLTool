//! WolfDawn Studio. The desktop GUI front-end for the WolfDawn toolchain.
//!
//! Phase 0 ships the app shell (top/side/bottom/central panel layout), the Project section (which
//! reads a real `Game.dat`), and the shared infrastructure every later section plugs into:
//! background jobs with a progress bar, a colour-coded activity log, native file pickers, and the
//! reusable labelled controls. The CLI is unchanged. This is purely additive.
//!
//! The workspace forbids `unsafe`. eframe/egui/rfd carry their own `unsafe` internally. None is
//! written here.

#![forbid(unsafe_code)]
// On Windows, suppress the console window for a release GUI build. Debug builds keep the console
// so `eprintln!`/panics are visible while developing.
#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

// Use mimalloc so freed memory (after a large extract / decompile / DB load) is returned to the OS
// instead of being held by the default allocator. No unsafe here: the attribute on a static is safe,
// the GlobalAlloc impl lives in the dependency.
#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

mod app;
mod archive;
mod database;
mod decompile;
mod gamedat;
mod log;
mod project;
mod saves;
mod task;
mod translation;
mod verify;
mod widgets;

use app::WolfDawnApp;

fn main() -> eframe::Result<()> {
    let native_options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("WolfDawn Studio")
            .with_inner_size([1000.0, 680.0])
            .with_min_inner_size([720.0, 480.0]),
        ..Default::default()
    };
    eframe::run_native(
        "WolfDawn Studio",
        native_options,
        Box::new(|cc| Ok(Box::new(WolfDawnApp::new(cc)))),
    )
}

#[cfg(test)]
mod tests {
    use super::app::{Section, WolfDawnApp};
    use super::project;
    use std::path::{Path, PathBuf};

    /// Resolve a fixture by its clean relative path under `WOLFDAWN_TEST_DATA`. Returns `None` when
    /// the var is unset or the file/dir is missing, so the data-dependent gates skip gracefully.
    fn test_data(rel: &str) -> Option<PathBuf> {
        let base = std::env::var_os("WOLFDAWN_TEST_DATA")?;
        let p = Path::new(&base).join(rel);
        p.exists().then_some(p)
    }

    /// The first present fixture among `rels`, resolved under `WOLFDAWN_TEST_DATA`.
    fn first_present(rels: &[&str]) -> Option<PathBuf> {
        rels.iter().find_map(|r| test_data(r))
    }

    /// Drive `f` under a fresh headless egui context (no window/GPU), the way the test gates
    /// exercise the UI. `ctx.run` calls the closure to build a frame. `FnMut` since egui may call
    /// it more than once.
    fn run_headless(f: impl FnMut(&egui::Context)) {
        let ctx = egui::Context::default();
        let _ = ctx.run(Default::default(), f);
    }

    /// Every `Section` must render without panicking under a headless context.
    #[test]
    fn every_section_renders() {
        for section in Section::ALL {
            let mut app = WolfDawnApp::default();
            app.set_section(section);
            run_headless(|ctx| {
                egui::CentralPanel::default().show(ctx, |ui| {
                    app.render_current_section(ui);
                });
            });
        }
    }

    /// A full frame (all four panels, the same body `eframe::App::update` runs) must render for
    /// every section without panicking.
    #[test]
    fn full_frame_runs_for_every_section() {
        for section in Section::ALL {
            let mut app = WolfDawnApp::default();
            app.set_section(section);
            // Two frames: the second exercises any state seeded on the first (e.g. the archive
            // section defaulting its selection from the open project).
            for _ in 0..2 {
                run_headless(|ctx| app.render_frame(ctx));
            }
        }
    }

    /// The Translation section must render with a *loaded* model too (the grid, not just the empty
    /// state). Builds the model through the section's own extract code, installs it, and drives a
    /// full headless frame. Skips gracefully when the data fixture is absent.
    #[test]
    fn translation_section_renders_with_model() {
        use super::translation;
        let Some(dir) = test_data("chamber/Data") else {
            eprintln!("skip translation_section_renders_with_model: fixture not present");
            return;
        };
        if !dir.join("BasicData").join("CommonEvent.dat").exists() {
            eprintln!("skip translation_section_renders_with_model: fixture not present");
            return;
        }
        let outcome = translation::extract_model(&dir, |_, _| {}).expect("extract");
        let mut app = WolfDawnApp::default();
        app.set_section(Section::Translation);
        app.set_translation_model(outcome.model);
        // Two frames: the first lays out the grid, the second re-renders after any state settles.
        for _ in 0..2 {
            let ctx = egui::Context::default();
            let _ = ctx.run(Default::default(), |ctx| app.render_frame(ctx));
        }
    }

    /// The Saves section must render with a *loaded* save too (the editor + baked-string table, not
    /// just the empty state). Inspects a COPY of a real save through the section's own code path,
    /// installs it, and drives a full headless frame. Skips gracefully when no fixture is present.
    #[test]
    fn saves_section_renders_with_loaded_save() {
        use super::saves;
        let Some(fixture) =
            first_present(&["chamber/SaveData01.sav", "pachimon/SaveData01.sav"])
        else {
            eprintln!("skip saves_section_renders_with_loaded_save: no save fixture present");
            return;
        };
        // Inspect a COPY so the game folder is never touched.
        let tmp = std::env::temp_dir().join(format!("wolfdawn_gui_saves_{}", std::process::id()));
        let _ = std::fs::create_dir_all(&tmp);
        let copy = tmp.join("SaveData01.sav");
        std::fs::copy(fixture, &copy).expect("copy fixture");
        let loaded = saves::inspect(&copy).expect("inspect");

        let mut app = WolfDawnApp::default();
        app.set_section(Section::Saves);
        app.set_loaded_save(loaded);
        for _ in 0..2 {
            let ctx = egui::Context::default();
            let _ = ctx.run(Default::default(), |ctx| app.render_frame(ctx));
        }
        let _ = std::fs::remove_dir_all(&tmp);
    }

    /// The Saves section's headless code path: inspect a real save (on a COPY), change the title +
    /// one baked string, save it through the section logic, re-inspect from the written bytes, and
    /// assert the title + string changed and the format is preserved. Never touches game folders.
    #[test]
    fn saves_inspect_edit_save_reinspect() {
        use super::saves;
        let Some(fixture) =
            first_present(&["chamber/SaveData01.sav", "pachimon/SaveData01.sav"])
        else {
            eprintln!("skip saves_inspect_edit_save_reinspect: no save fixture present");
            return;
        };
        let tmp = std::env::temp_dir().join(format!("wolfdawn_gui_rt_{}", std::process::id()));
        let _ = std::fs::create_dir_all(&tmp);
        let copy = tmp.join("SaveData01.sav");
        std::fs::copy(fixture, &copy).expect("copy fixture");

        let mut loaded = saves::inspect(&copy).expect("inspect");
        assert!(loaded.editable(), "real save should be editable");
        let fmt = loaded.format;
        let new_title = format!("{} [UI]", loaded.original_title);
        loaded.title = new_title.clone();
        // Edit the first string that re-encodes in this save's encoding.
        let utf8 = loaded.encoding == "utf8";
        let mut marker = None;
        for r in loaded.strings.iter_mut() {
            if r.original.is_empty() {
                continue;
            }
            let cand = format!("{} X", r.original);
            let ok = utf8 || !encoding_rs::SHIFT_JIS.encode(&cand).2;
            if ok {
                r.edited = cand.clone();
                marker = Some(cand);
                break;
            }
        }

        let stats = saves::save_changes(&loaded, true).expect("save");
        assert!(stats.title_changed);
        let re = saves::inspect(&copy).expect("re-inspect");
        assert_eq!(re.format, fmt, "format preserved");
        assert_eq!(re.title, new_title, "title changed");
        if let Some(m) = marker {
            assert!(re.strings.iter().any(|r| r.original == m), "string changed");
        }
        let _ = std::fs::remove_dir_all(&tmp);
    }

    /// The Decompile section must render with a *loaded* WolfScript document too (the code editor +
    /// Compile controls, not just the empty state). Decompiles a real file through the section's own
    /// code path, installs it, and drives a full headless frame. Skips when no code fixture.
    #[test]
    fn decompile_section_renders_with_script() {
        use super::decompile;
        let Some(input) = first_present(&[
            "chamber/Data/MapData/TitleMap.mps",
            "chamber/Data/BasicData/CommonEvent.dat",
        ]) else {
            eprintln!("skip decompile_section_renders_with_script: no code fixture present");
            return;
        };
        let script = decompile::decompile_edit(&input).expect("decompile");
        let mut app = WolfDawnApp::default();
        app.set_section(Section::Decompile);
        app.set_decompile_script(input.clone(), script);
        for _ in 0..2 {
            let ctx = egui::Context::default();
            let _ = ctx.run(Default::default(), |ctx| app.render_frame(ctx));
        }
    }

    /// The Decompile find bar (Ctrl+F) must render + run a query on a loaded script without
    /// panicking: open the bar with a query that occurs in the decompiled WolfScript and drive a few
    /// full headless frames (the find bar sets a selection + scrolls the editor). Skips when no
    /// code fixture is present. This guards the find-bar UI path (selection store + scroll-to).
    #[test]
    fn decompile_find_bar_renders_with_query() {
        use super::decompile;
        let Some(input) = first_present(&[
            "chamber/Data/MapData/TitleMap.mps",
            "chamber/Data/BasicData/CommonEvent.dat",
        ]) else {
            eprintln!("skip decompile_find_bar_renders_with_query: no code fixture present");
            return;
        };
        let script = decompile::decompile_edit(&input).expect("decompile");
        // Pick a query that is guaranteed to occur (the first word of the script, else a common
        // token). An empty match list is fine too. The bar must still render without panicking.
        let query = script
            .split_whitespace()
            .next()
            .map(|s| s.to_string())
            .unwrap_or_else(|| "Event".to_string());

        let mut app = WolfDawnApp::default();
        app.set_section(Section::Decompile);
        app.set_decompile_script(input.to_path_buf(), script);
        app.open_decompile_find(&query);
        // Several frames: open + jump-to-match, then re-render after the selection/scroll settles.
        for _ in 0..3 {
            let ctx = egui::Context::default();
            let _ = ctx.run(Default::default(), |ctx| app.render_frame(ctx));
        }
    }

    /// The Decompile section's headless code path: decompile a real map/common-event to WolfScript,
    /// assert non-empty, compile it back onto the original base to a temp output, and assert the
    /// re-decompiled text matches (and the untouched compile is byte-identical to the base). Never
    /// modifies the fixtures root (reads the fixture, writes only into a temp dir).
    #[test]
    fn decompile_compile_round_trip_via_section() {
        use super::decompile;
        let Some(input) = first_present(&[
            "chamber/Data/MapData/TitleMap.mps",
            "chamber/Data/BasicData/CommonEvent.dat",
        ]) else {
            eprintln!("skip decompile_compile_round_trip_via_section: no code fixture present");
            return;
        };
        let input = input.as_path();
        let text = decompile::decompile_edit(input).expect("decompile");
        assert!(!text.is_empty(), "WolfScript should be non-empty");

        let tmp = std::env::temp_dir().join(format!("wolfdawn_gui_dec_{}", std::process::id()));
        let _ = std::fs::create_dir_all(&tmp);
        // Keep the base's file name so the compiled output re-classifies the same way.
        let out = tmp.join(input.file_name().expect("file name"));
        let outcome = decompile::compile_to(&text, input, &out).expect("compile");
        assert!(out.exists() && outcome.bytes > 0, "compiled output should be written");
        assert!(outcome.byte_identical, "untouched compile is byte-identical to base");
        // Compare the re-decompile against a decompile of the base placed in the same temp dir, so
        // both share the same (BasicData-less) symbol context (the operand labels match). The
        // byte-identity above is the strong guarantee, the labels are stripped by the compiler.
        let base_here = tmp.join("base").join(input.file_name().unwrap());
        std::fs::create_dir_all(base_here.parent().unwrap()).unwrap();
        std::fs::copy(input, &base_here).expect("copy base");
        let baseline = decompile::decompile_edit(&base_here).expect("decompile base copy");
        let re = decompile::decompile_edit(&out).expect("re-decompile");
        assert_eq!(re, baseline, "re-decompiled WolfScript should match the base's own decompile");
        let _ = std::fs::remove_dir_all(&tmp);
    }

    /// The Game.dat section must render with a *loaded* model too (the field form, not just the empty
    /// state). Loads a real Game.dat (on a COPY) through the section's own code path, installs it, and
    /// drives a full headless frame. Skips gracefully when the Game.dat fixture is absent.
    #[test]
    fn gamedat_section_renders_with_loaded() {
        use super::gamedat;
        let Some(fixture) = first_present(&["chamber/Data/BasicData/Game.dat"]) else {
            eprintln!("skip gamedat_section_renders_with_loaded: no Game.dat fixture present");
            return;
        };
        let tmp = std::env::temp_dir().join(format!("wolfdawn_gui_gd_{}", std::process::id()));
        let _ = std::fs::create_dir_all(&tmp);
        let copy = tmp.join("Game.dat");
        std::fs::copy(fixture, &copy).expect("copy fixture");
        let loaded = gamedat::load(&copy).expect("load");

        let mut app = WolfDawnApp::default();
        app.set_section(Section::GameDat);
        app.set_gamedat_loaded(loaded);
        for _ in 0..2 {
            let ctx = egui::Context::default();
            let _ = ctx.run(Default::default(), |ctx| app.render_frame(ctx));
        }
        let _ = std::fs::remove_dir_all(&tmp);
    }

    /// The Game.dat section's headless code path: load a real Game.dat (on a COPY), change Font, save
    /// to a temp output, then reload. Font is new and Title unchanged. A no-change save is byte-exact.
    #[test]
    fn gamedat_edit_font_round_trip_via_section() {
        use super::gamedat;
        let Some(fixture) = first_present(&["chamber/Data/BasicData/Game.dat"]) else {
            eprintln!("skip gamedat_edit_font_round_trip_via_section: no Game.dat fixture present");
            return;
        };
        let tmp = std::env::temp_dir().join(format!("wolfdawn_gui_gdrt_{}", std::process::id()));
        let _ = std::fs::create_dir_all(&tmp);
        let copy = tmp.join("Game.dat");
        std::fs::copy(fixture, &copy).expect("copy fixture");

        let mut g = gamedat::load(&copy).expect("load");
        let title = g.fields.iter().find(|f| f.key == "Title").map(|f| f.value.clone());
        let font = g.fields.iter().find(|f| f.key == "Font").expect("Font present").value.clone();
        let new_font = format!("{font}_X");
        g.fields.iter_mut().find(|f| f.key == "Font").unwrap().value = new_font.clone();

        let out = tmp.join("edited.dat");
        let outcome = gamedat::save(&g, &out, false).expect("save");
        assert_eq!(outcome.changed, 1, "one field changed");
        let re = gamedat::load(&out).expect("reload");
        assert_eq!(
            re.fields.iter().find(|f| f.key == "Font").unwrap().value,
            new_font,
            "Font is the new value"
        );
        assert_eq!(
            re.fields.iter().find(|f| f.key == "Title").map(|f| f.value.clone()),
            title,
            "Title unchanged"
        );

        // No-change save reproduces the original byte-for-byte.
        let pristine = gamedat::load(&copy).expect("reload pristine");
        let noop = tmp.join("noop.dat");
        let n = gamedat::save(&pristine, &noop, false).expect("no-op save");
        assert!(n.byte_identical, "no-change save is byte-identical");
        assert_eq!(std::fs::read(&noop).unwrap(), std::fs::read(&copy).unwrap());
        let _ = std::fs::remove_dir_all(&tmp);
    }

    /// The Database section must render with a *loaded* model too (the type selector + editable grid,
    /// not just the empty state). Loads a real DB (on a COPY of the .project+.dat pair) through the
    /// section's own code path, installs it, and drives a full headless frame. Skips when absent.
    #[test]
    fn database_section_renders_with_loaded() {
        use super::database;
        let Some(src) = test_data("chamber/Data/BasicData/DataBase.project")
            .filter(|p| p.with_extension("dat").exists())
        else {
            eprintln!("skip database_section_renders_with_loaded: no database fixture present");
            return;
        };
        let tmp = std::env::temp_dir().join(format!("wolfdawn_gui_db_{}", std::process::id()));
        let _ = std::fs::create_dir_all(&tmp);
        let proj = tmp.join("DataBase.project");
        std::fs::copy(&src, &proj).expect("copy .project");
        std::fs::copy(src.with_extension("dat"), proj.with_extension("dat")).expect("copy .dat");
        let loaded = database::load(&proj).expect("load");

        let mut app = WolfDawnApp::default();
        app.set_section(Section::Database);
        app.set_database_loaded(loaded);
        for _ in 0..2 {
            let ctx = egui::Context::default();
            let _ = ctx.run(Default::default(), |ctx| app.render_frame(ctx));
        }
        let _ = std::fs::remove_dir_all(&tmp);
    }

    /// Unpack the Chamber fixture's Data.wolf (if present) through the Archive section's own code path
    /// into a temp dir, and assert the data files appear. Never touches the game folder. Skips when
    /// the archive is absent.
    #[test]
    fn archive_unpack_data_wolf() {
        use super::archive;
        let Some(arc) = test_data("chamber/Data.wolf") else {
            eprintln!("skip archive_unpack_data_wolf: archive fixture not present");
            return;
        };
        let out = std::env::temp_dir().join(format!("wolfdawn_gui_unpack_{}", std::process::id()));
        let _ = std::fs::create_dir_all(&out);
        let outcome = archive::unpack(&arc, &out, |_, _| {}).expect("unpack");
        assert!(outcome.written > 0, "files should be written");
        assert!(
            out.join("BasicData/CommonEvent.dat").exists(),
            "BasicData/CommonEvent.dat should be unpacked"
        );
        let _ = std::fs::remove_dir_all(&out);
    }

    /// Repack round-trip through the Archive section: pack a small temp folder (copies of a couple
    /// fixture data files) to a temp .wolf, unpack it, and confirm the files + content come back.
    /// Never modifies the fixtures root (read-only copies + temp dirs).
    #[test]
    fn archive_repack_round_trip() {
        use super::archive;
        let present: Vec<PathBuf> = [
            "chamber/Data/BasicData/Game.dat",
            "chamber/Data/BasicData/CommonEvent.dat",
        ]
        .iter()
        .filter_map(|r| test_data(r))
        .collect();
        if present.is_empty() {
            eprintln!("skip archive_repack_round_trip: no data fixtures present");
            return;
        }
        let base = std::env::temp_dir().join(format!("wolfdawn_gui_repack_{}", std::process::id()));
        let src = base.join("src");
        let _ = std::fs::create_dir_all(src.join("BasicData"));
        let mut expect: Vec<(String, Vec<u8>)> = Vec::new();
        for p in &present {
            let name = p.file_name().unwrap().to_string_lossy().to_string();
            std::fs::copy(p, src.join("BasicData").join(&name)).expect("copy");
            expect.push((format!("BasicData/{name}"), std::fs::read(p).expect("read")));
        }

        let out_wolf = base.join("Data.wolf");
        let outcome =
            archive::repack(&src, &out_wolf, &archive::PackOptions::default(), |_, _| {}).expect("repack");
        assert!(outcome.files >= 1 && outcome.bytes > 0, "should pack a non-empty archive");

        let back = base.join("back");
        archive::unpack(&out_wolf, &back, |_, _| {}).expect("unpack repacked");
        for (rel, bytes) in &expect {
            let got = back.join(rel);
            assert!(got.exists(), "{rel} should round-trip");
            assert_eq!(&std::fs::read(&got).expect("read back"), bytes, "{rel} content matches");
        }
        let _ = std::fs::remove_dir_all(&base);
    }

    /// The Verify section's single-file path: a known-good plaintext data file from the fixtures must
    /// verify PASS. Read-only. Skips when absent.
    #[test]
    fn verify_single_known_good() {
        use super::verify;
        let Some(path) = first_present(&[
            "chamber/Data/MapData/TitleMap.mps",
            "chamber/Data/BasicData/Game.dat",
            "chamber/Data/BasicData/CommonEvent.dat",
        ]) else {
            eprintln!("skip verify_single_known_good: no data fixture present");
            return;
        };
        let verdict = verify::verify_file(&path);
        assert!(
            verdict.is_pass(),
            "{} should PASS, got {}: {}",
            path.display(),
            verdict.tag(),
            verdict.detail()
        );
    }

    /// Opening a known game dir populates the project's Game.dat facts. Skips gracefully when the
    /// fixture is absent (CI without the data corpus).
    #[test]
    fn opens_known_game_dir() {
        let Some(dir) = test_data("chamber/Data") else {
            eprintln!("skip opens_known_game_dir: fixture not present");
            return;
        };
        if !dir.join("BasicData").join("Game.dat").exists() {
            eprintln!("skip opens_known_game_dir: fixture {dir:?} not present");
            return;
        }
        let outcome = project::open_project(&dir);
        let p = outcome.project;
        assert!(p.game_dat_ok, "Game.dat should have parsed for the fixture");
        assert!(p.game_dat.is_some(), "Game.dat path should be recorded");
        assert!(!p.title.is_empty(), "a title should have been decoded");
        // The fixture's BasicData is the data dir. It must have been located.
        assert!(p.data_dir.is_some(), "the data dir should have been located");
    }

    /// Opening a path with no Game.dat is non-fatal: the project still opens, flagged not-ok.
    #[test]
    fn open_missing_game_dat_is_non_fatal() {
        let tmp = std::env::temp_dir().join(format!("wolfdawn_gui_test_{}", std::process::id()));
        let _ = std::fs::create_dir_all(&tmp);
        let outcome = project::open_project(&tmp);
        assert!(!outcome.project.game_dat_ok);
        assert!(outcome.notes.iter().any(|(_, m)| m.contains("Game.dat")));
        let _ = std::fs::remove_dir_all(&tmp);
    }

    /// A unique temp game dir for the index tests, with the minimal layout the scan looks at:
    /// `BasicData/CommonEvent.dat`, `BasicData/DataBase.project`, `MapData/X.mps`, and a
    /// `Save/SaveData01.sav`. The files are fabricated (rescan only *lists* by name/extension, it
    /// never parses), so this never touches real game folders or the fixtures root.
    fn make_temp_game(tag: &str) -> std::path::PathBuf {
        let root = std::env::temp_dir()
            .join(format!("wolfdawn_gui_idx_{tag}_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let data = root.join("Data");
        std::fs::create_dir_all(data.join("BasicData")).expect("mk BasicData");
        std::fs::create_dir_all(data.join("MapData")).expect("mk MapData");
        std::fs::create_dir_all(root.join("Save")).expect("mk Save");
        std::fs::write(data.join("BasicData").join("CommonEvent.dat"), b"x").expect("CommonEvent");
        std::fs::write(data.join("BasicData").join("DataBase.project"), b"x").expect("project");
        std::fs::write(data.join("BasicData").join("DataBase.dat"), b"x").expect("project .dat");
        std::fs::write(data.join("MapData").join("MapA.mps"), b"x").expect("MapA");
        std::fs::write(root.join("Save").join("SaveData01.sav"), b"x").expect("save");
        root
    }

    /// Opening a fabricated game dir populates the scanned index (code files / databases / saves),
    /// and a later `rescan()` after a NEW .mps is added returns `true` and lists the new file.
    #[test]
    fn project_index_and_rescan_detects_new_file() {
        let root = make_temp_game("rescan");

        let mut p = project::open_project(&root).project;
        // CommonEvent.dat + MapA.mps = 2 code files, one .project, one save.
        assert!(
            p.code_files.iter().any(|f| f.ends_with("MapData/MapA.mps")),
            "MapA.mps should be indexed; got {:?}",
            p.code_files
        );
        assert!(
            p.code_files.iter().any(|f| f.ends_with("BasicData/CommonEvent.dat")),
            "CommonEvent.dat should be indexed"
        );
        assert_eq!(p.databases.len(), 1, "one database .project indexed");
        assert_eq!(p.saves.len(), 1, "one save indexed");
        assert!(p.save_dir.is_some(), "the Save/ dir should be recorded");

        // A no-op rescan reports no change.
        assert!(!p.rescan(), "rescan with no fs change returns false");

        // Add a second map, then rescan returns true and the new map appears.
        let new_map = root.join("Data").join("MapData").join("MapB.mps");
        std::fs::write(&new_map, b"x").expect("write MapB");
        assert!(p.rescan(), "rescan after adding a .mps returns true");
        assert!(
            p.code_files.iter().any(|f| f.ends_with("MapData/MapB.mps")),
            "the newly-added MapB.mps should now be indexed; got {:?}",
            p.code_files
        );

        let _ = std::fs::remove_dir_all(&root);
    }

    /// The persisted `Settings` payload round-trips through serde unchanged (covers the eframe
    /// storage value), for both a non-default and the default configuration.
    #[test]
    fn settings_serde_round_trip() {
        use super::app::Settings;
        let custom = Settings {
            dark_mode: false,
            default_en_punct: true,
            default_allow_code_drift: true,
            default_backup: false,
            auto_detect: false,
        };
        let json = serde_json::to_string(&custom).expect("serialize");
        let back: Settings = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(custom, back, "custom settings round-trip equal");

        let def = Settings::default();
        let json = serde_json::to_string(&def).expect("serialize default");
        let back: Settings = serde_json::from_str(&json).expect("deserialize default");
        assert_eq!(def, back, "default settings round-trip equal");
    }

    /// The Settings section must render in a full headless frame with a project loaded (so the
    /// per-section dropdowns also render), without panicking. Uses a fabricated temp game dir.
    #[test]
    fn settings_section_renders_with_project() {
        let root = make_temp_game("render");
        let project = project::open_project(&root).project;

        let mut app = WolfDawnApp::default();
        app.set_project(project);
        // Render the Settings section, then walk a couple sections that show dropdowns, each over
        // two frames so any first-frame state settles.
        for section in [Section::Settings, Section::Decompile, Section::Database, Section::Saves] {
            app.set_section(section);
            for _ in 0..2 {
                let ctx = egui::Context::default();
                let _ = ctx.run(Default::default(), |ctx| app.render_frame(ctx));
            }
        }
        let _ = std::fs::remove_dir_all(&root);
    }

    // ------------------------------------------------------------------------------------------
    // No-emoji guard: the GUI must render its glyphs on ANY system, including ones without an OS
    // emoji font. egui's bundled fonts (and the optional CJK fallback) cover Latin, the Geometric
    // Shapes / Arrows blocks, and CJK, but NOT the Unicode emoji / pictograph blocks, which show
    // as tofu (□) without an emoji font. These two tests keep the UI free of those pictographs.
    // ------------------------------------------------------------------------------------------

    /// The safe non-ASCII glyphs the UI uses in string/char literals: ASCII/Latin-1
    /// punctuation, Geometric Shapes (U+25A0..U+25FF), and Arrows (U+2190..U+21FF). Anything else
    /// non-ASCII in a literal must be CJK-range (Japanese sample/help text). A stray emoji is caught.
    const SAFE_GLYPHS: &[char] = &[
        '×', // U+00D7 multiplication sign, the clear/close button
        '·', // U+00B7 middle dot, separators
        '—', // U+2014 em dash, captions/log separators
        '…', // U+2026 horizontal ellipsis, "Browse…", "Open…"
        '→', // U+2192 rightwards arrow, "src → dst" log lines
        '←', // U+2190 leftwards arrow, "Import DB ← file" log lines
        '▶', // U+25B6 black right-pointing triangle, action buttons / log start marker
        '◀', // U+25C0 black left-pointing triangle, find "Prev"
        '●', // U+25CF black circle, the Database "edited" marker
    ];

    /// Every `.rs` file under `src/`, as (path, contents).
    fn gui_source_files() -> Vec<(std::path::PathBuf, String)> {
        let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
        let mut out = Vec::new();
        for entry in std::fs::read_dir(&src).expect("read src dir") {
            let path = entry.expect("dir entry").path();
            if path.extension().and_then(|e| e.to_str()) == Some("rs") {
                let text = std::fs::read_to_string(&path).expect("read source");
                out.push((path, text));
            }
        }
        assert!(!out.is_empty(), "found no .rs files under {}", src.display());
        out
    }

    /// True for a codepoint in the Unicode emoji / pictograph blocks we must never ship: everything
    /// at/above U+1F000 (Mahjong/Domino/Playing-cards through Symbols & Pictographs Extended-A).
    fn is_emoji_pictograph(c: char) -> bool {
        c as u32 >= 0x1F000
    }

    /// A codepoint that the always-loaded CJK fallback font covers (so it renders, not tofu): the
    /// main CJK/kana blocks plus CJK Symbols & Punctuation and the Fullwidth/Halfwidth Forms used in
    /// Japanese help text (e.g. 「」、。～). Conservative but ample for the tool's sample strings.
    fn is_cjk(c: char) -> bool {
        let u = c as u32;
        (0x3000..=0x30FF).contains(&u)   // CJK Symbols/Punctuation + Hiragana + Katakana
            || (0x3400..=0x4DBF).contains(&u) // CJK Ext A
            || (0x4E00..=0x9FFF).contains(&u) // CJK Unified Ideographs
            || (0xFF00..=0xFFEF).contains(&u) // Halfwidth/Fullwidth Forms
    }

    /// HARD GATE: no emoji-pictograph codepoint (>= U+1F000) may appear ANYWHERE in the GUI source.
    /// Not in strings, not even in comments (there should be none). This makes it impossible to ship
    /// a pictograph that could tofu on a user's machine.
    #[test]
    fn no_emoji_pictographs_in_source() {
        let mut offenders: Vec<String> = Vec::new();
        for (path, text) in gui_source_files() {
            for (lineno, line) in text.lines().enumerate() {
                for c in line.chars() {
                    if is_emoji_pictograph(c) {
                        offenders.push(format!(
                            "{}:{}: U+{:04X} {:?}",
                            path.file_name().unwrap().to_string_lossy(),
                            lineno + 1,
                            c as u32,
                            c
                        ));
                    }
                }
            }
        }
        assert!(
            offenders.is_empty(),
            "found emoji pictograph(s) (>=U+1F000) in GUI source — these tofu on systems without an \
             emoji font; replace with text or a Geometric/Arrow glyph:\n{}",
            offenders.join("\n")
        );
    }

    /// Strip Rust line comments (`//` and doc `///`) from `src`, returning code + string/char
    /// literals only. The GUI source uses line comments exclusively (no `/* */` blocks), and no
    /// string literal contains a `//` sequence, so truncating each line at its first `//` is exact
    /// here. That is more robust than a hand lexer (no lifetime / raw-string / char-literal edge
    /// cases). This keeps benign non-ASCII that lives ONLY in comments (e.g. the tofu glyph □, the
    /// ␠ space marker, a ▼ doc example) from being mistaken for a UI glyph.
    fn strip_comments(src: &str) -> String {
        let mut out = String::with_capacity(src.len());
        for line in src.lines() {
            let code = match line.find("//") {
                Some(idx) => &line[..idx],
                None => line,
            };
            out.push_str(code);
            out.push('\n');
        }
        out
    }

    /// ALLOW-LIST GATE: every non-ASCII glyph that survives comment-stripping (i.e. lives in code or
    /// in a string/char literal) must be either CJK-range (Japanese sample/help text the CJK font
    /// covers) or on the [`SAFE_GLYPHS`] list (Latin-1 punctuation + Geometric/Arrow glyphs the
    /// bundled fonts cover). This catches a future stray dingbat (e.g. ✔ ✖ ⚠ ★) even though it sits
    /// below U+1F000 and so escapes the hard pictograph gate above.
    #[test]
    fn non_ascii_ui_glyphs_are_safe_or_cjk() {
        let mut offenders: Vec<String> = Vec::new();
        for (path, text) in gui_source_files() {
            let code = strip_comments(&text);
            for c in code.chars() {
                if (c as u32) <= 0x7F || c.is_whitespace() {
                    continue;
                }
                if SAFE_GLYPHS.contains(&c) || is_cjk(c) {
                    continue;
                }
                offenders.push(format!(
                    "{}: U+{:04X} {:?}",
                    path.file_name().unwrap().to_string_lossy(),
                    c as u32,
                    c
                ));
            }
        }
        offenders.sort();
        offenders.dedup();
        assert!(
            offenders.is_empty(),
            "found non-ASCII glyph(s) in GUI code/literals that are neither CJK nor on the safe \
             allow-list — they may tofu on systems lacking the right font; use text or a \
             Geometric/Arrow glyph (and extend SAFE_GLYPHS if you added an intentional one):\n{}",
            offenders.join("\n")
        );
    }
}
