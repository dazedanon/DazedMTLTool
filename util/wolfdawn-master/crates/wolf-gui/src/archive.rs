//! The Archive section's headless logic: unpack a `.wolf` to a folder and repack a folder back
//! into a `.wolf`, calling the **same** `wolf_archive` library functions the CLI's `cmd_unpack` /
//! `cmd_pack` use (no shelling out). The egui rendering lives in `app.rs`. This module owns the
//! file-level work so the whole flow can be exercised headlessly in tests.
//!
//!   * [`unpack`] mirrors `cmd_unpack`: read the archive, call [`wolf_archive::extract_archive`]
//!     (which handles any supported crypt regime), then write each file into the
//!     output dir under a *sanitised* relative path (the same `..`/`.`-stripping the CLI does, so a
//!     hostile or malformed archive path can't escape the output folder).
//!   * [`repack`] mirrors `cmd_pack`: gather `(relative-path, bytes)` for every file under the input
//!     folder, then call the matching `wolf_archive::pack_*` path for the chosen [`PackOptions`]
//!     (plaintext / encrypted / new-crypt / `--like` an existing archive / the legacy ver5|ver6
//!     containers).
//!
//! Repack fidelity: an unpack/repack/unpack round-trips the *file set and contents* byte-for-byte,
//! but a fresh `.wolf` is not guaranteed byte-identical to an editor-produced original (see the
//! `wolf_archive::pack` notes, the header/compression differs slightly). The library's own
//! `extract_archive` reads our output back losslessly, which is what the verify/round-trip tests
//! assert.

use std::path::{Path, PathBuf};

/// The CLI's default cryptVersion when `--encrypt` is given without an explicit `--version`
/// (Wolf v3.00). Kept in sync with `cmd_pack`'s `version` default.
pub const DEFAULT_CRYPT_VERSION: u16 = 0x12C;

/// The default new-crypt password used when encrypting a new-crypt version (`0x14B`/`0x15E`)
/// without a `--like` source or an explicit password. Mirrors `cmd_pack`'s `default_pwd`. The
/// archive embeds whatever password it was built with, so it stays self-describing.
const DEFAULT_NEWCRYPT_PWD: [u8; 15] = *b"WolfDawnRepack!";

/// The container format the user picked, mirroring the CLI `pack --format` flag. `Auto` is the
/// modern VER8 container (plaintext, or encrypted per [`PackOptions::encrypt`]); `Ver5`/`Ver6` are
/// the legacy DXArchive containers for Wolf 2.0x.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum PackFormat {
    #[default]
    Auto,
    Ver5,
    Ver6,
}

impl PackFormat {
    /// The dropdown label.
    pub fn label(self) -> &'static str {
        match self {
            PackFormat::Auto => "auto",
            PackFormat::Ver5 => "ver5",
            PackFormat::Ver6 => "ver6",
        }
    }
}

/// Where the encryption parameters for an encrypted repack come from. Mutually exclusive (a small
/// radio in the UI): the CLI default cryptVersion, a manually-typed version, or inherited from an
/// existing `.wolf` (`--like`). Only consulted when [`PackOptions::encrypt`] is set and the format
/// is [`PackFormat::Auto`].
#[derive(Clone, PartialEq, Eq, Debug)]
pub enum CryptSource {
    /// The CLI default cryptVersion ([`DEFAULT_CRYPT_VERSION`]).
    Default,
    /// A manually-entered cryptVersion (e.g. `0x14b`).
    Version(u16),
    /// Inherit cryptVersion + embedded password from an existing archive (turnkey repack).
    Like(PathBuf),
}

impl Default for CryptSource {
    fn default() -> Self {
        CryptSource::Default
    }
}

/// The repack options, assembled from the UI controls. The GUI equivalent of `cmd_pack`'s flags.
#[derive(Clone, Debug)]
pub struct PackOptions {
    /// Encrypt the output (the `--encrypt` flag). Ignored for the legacy ver5/ver6 formats, which
    /// have their own (un-keyed) container.
    pub encrypt: bool,
    /// Where the crypt params come from when `encrypt` is set on an `Auto`-format archive.
    pub crypt: CryptSource,
    /// The container format.
    pub format: PackFormat,
}

impl Default for PackOptions {
    fn default() -> Self {
        Self {
            encrypt: false,
            crypt: CryptSource::Default,
            format: PackFormat::Auto,
        }
    }
}

/// The outcome of an [`unpack`]: how many files were written, and the (already-logged) names of any
/// files whose archive path had to be sanitised (rare, a malformed/hostile path).
pub struct UnpackOutcome {
    /// Number of files written to the output dir.
    pub written: usize,
    /// `(original archive path, sanitised path)` for files whose name needed `..`/`.` stripped.
    pub sanitised: Vec<(String, String)>,
    /// The output directory files were written under.
    pub out_dir: PathBuf,
}

/// Sanitise an archive's inner path into a safe relative path: drop empty/`.`/`..` segments and the
/// drive/leading-separator, exactly like `cmd_unpack`, so a file can never escape the output dir.
fn safe_relative(path: &str) -> PathBuf {
    path.split(['\\', '/'])
        .filter(|s| !s.is_empty() && *s != "." && *s != "..")
        .collect()
}

/// Extract every file from a `.wolf` archive into `out_dir`, preserving the inner directory tree.
/// Calls the library's [`wolf_archive::extract_archive`] (the same path `cmd_unpack` uses), which
/// handles every crypt regime and is resilient to odd archives. `report` drives a progress bar. Pass
/// a no-op in tests. Returns the file count + any sanitised-path warnings.
///
/// The empty key string (`b""`) lets the library pick the right default WolfPro key, matching the
/// CLI. Files are written under a sanitised relative path so a malformed archive entry cannot write
/// outside `out_dir`.
pub fn unpack(
    archive: &Path,
    out_dir: &Path,
    mut report: impl FnMut(f32, String),
) -> Result<UnpackOutcome, String> {
    report(0.05, "reading archive…".to_string());
    let data = std::fs::read(archive)
        .map_err(|e| format!("cannot read {}: {e}", archive.display()))?;

    report(0.3, "decoding archive…".to_string());
    let files = wolf_archive::extract_archive(&data, b"")
        .map_err(|e| format!("not a readable Wolf archive ({e})"))?;
    let total = files.len();
    if total == 0 {
        return Err("the archive holds no files".to_string());
    }

    std::fs::create_dir_all(out_dir)
        .map_err(|e| format!("cannot create {}: {e}", out_dir.display()))?;

    let mut sanitised = Vec::new();
    let mut written = 0usize;
    for (i, (path, bytes)) in files.iter().enumerate() {
        // Progress over the back 0.3..1.0 of the bar (the table decode took the first 0.3).
        if total > 0 {
            let frac = 0.3 + 0.7 * (i as f32) / (total as f32);
            report(frac, format!("writing {path}"));
        }
        let safe = safe_relative(path);
        if safe.as_os_str().is_empty() {
            // A path that sanitised away to nothing (all `.`/`..`); skip it rather than write to the
            // dir root. Record it so the caller can warn.
            sanitised.push((path.clone(), String::new()));
            continue;
        }
        // If sanitising changed the path, note it (so the UI can warn about the odd entry).
        let safe_str = safe.to_string_lossy().replace('\\', "/");
        let orig_norm = path.replace('\\', "/");
        if safe_str != orig_norm {
            sanitised.push((path.clone(), safe_str.clone()));
        }
        let target = out_dir.join(&safe);
        if let Some(parent) = target.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("cannot create {}: {e}", parent.display()))?;
        }
        std::fs::write(&target, bytes)
            .map_err(|e| format!("cannot write {}: {e}", target.display()))?;
        written += 1;
    }
    report(1.0, "done".to_string());
    Ok(UnpackOutcome {
        written,
        sanitised,
        out_dir: out_dir.to_path_buf(),
    })
}

/// The outcome of an [`unpack_all`]: how many archives unpacked, how many failed, the total file
/// count, the output root, and a per-archive `(name, written-or-error)` list for the log.
pub struct UnpackAllOutcome {
    pub ok: usize,
    pub failed: usize,
    pub files: usize,
    pub out_root: PathBuf,
    pub details: Vec<(String, Result<usize, String>)>,
}

/// Unpack every `.wolf` archive directly inside `dir` into `<out_root>/<stem>/`. A per-category
/// game splits its data across many archives (BasicData.wolf, MapData.wolf, Evtext.wolf, ...);
/// this takes the whole set apart in one pass. Each `Name.wolf` lands in `<out_root>/Name/`, which
/// mirrors how the engine maps a category archive to a `Name/` folder, so the result is a loose
/// data tree the game can load and the per-file extractors can read. One bad archive is recorded
/// and skipped rather than aborting the run. Mirrors the CLI `unpack-all`.
pub fn unpack_all(
    dir: &Path,
    out_root: &Path,
    mut report: impl FnMut(f32, String),
) -> Result<UnpackAllOutcome, String> {
    let mut archives: Vec<PathBuf> = std::fs::read_dir(dir)
        .map_err(|e| format!("cannot read {}: {e}", dir.display()))?
        .flatten()
        .map(|e| e.path())
        .filter(|p| {
            p.is_file()
                && p.extension()
                    .and_then(|x| x.to_str())
                    .map(|x| x.eq_ignore_ascii_case("wolf"))
                    .unwrap_or(false)
        })
        .collect();
    archives.sort();
    if archives.is_empty() {
        return Err(format!("no .wolf archives found in {}", dir.display()));
    }

    let total = archives.len();
    let mut out = UnpackAllOutcome {
        ok: 0,
        failed: 0,
        files: 0,
        out_root: out_root.to_path_buf(),
        details: Vec::with_capacity(total),
    };
    for (i, arc) in archives.iter().enumerate() {
        let stem = arc
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("archive")
            .to_string();
        let name = arc
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or(&stem)
            .to_string();
        report(i as f32 / total as f32, format!("unpacking {name}…"));
        let dest = out_root.join(&stem);
        // Swallow the inner per-file progress; the outer bar steps once per archive.
        match unpack(arc, &dest, |_f, _m| {}) {
            Ok(o) => {
                out.ok += 1;
                out.files += o.written;
                out.details.push((name, Ok(o.written)));
            }
            Err(e) => {
                out.failed += 1;
                out.details.push((name, Err(e)));
            }
        }
    }
    report(1.0, "done".to_string());
    Ok(out)
}

/// The outcome of a [`repack`]: the output path, the file count packed, and the output size.
pub struct RepackOutcome {
    pub out: PathBuf,
    pub files: usize,
    pub bytes: usize,
    /// A short human description of the crypto mode used (for the log).
    pub mode: String,
}

/// Recursively gather `(relative-path, bytes)` for every file under `dir`, the same as `cmd_pack`'s
/// `gather_files` (slashes normalised so the archive's inner paths are platform-independent).
fn gather_files(base: &Path, dir: &Path, out: &mut Vec<(String, Vec<u8>)>) -> Result<(), String> {
    let rd = std::fs::read_dir(dir).map_err(|e| format!("cannot read {}: {e}", dir.display()))?;
    for entry in rd {
        let p = entry.map_err(|e| e.to_string())?.path();
        if p.is_dir() {
            gather_files(base, &p, out)?;
        } else {
            let rel = p
                .strip_prefix(base)
                .unwrap_or(&p)
                .to_string_lossy()
                .replace('\\', "/");
            let bytes = std::fs::read(&p).map_err(|e| format!("cannot read {}: {e}", p.display()))?;
            out.push((rel, bytes));
        }
    }
    Ok(())
}

/// Pack every file under `input_dir` into a `.wolf` at `out`, using the crypto/format the
/// [`PackOptions`] describe. Dispatches to the same `wolf_archive::pack_*` functions `cmd_pack` does.
/// `report` drives a progress bar. Pass a no-op in tests.
///
/// For an encrypted `Auto` archive the cryptVersion (and, for `--like`, the embedded password) is
/// resolved up front. New-crypt versions (`0x14B`/`0x15E`) use the embedded default password when no
/// `--like` source is given. The output is written to `out` and its size reported.
pub fn repack(
    input_dir: &Path,
    out: &Path,
    opts: &PackOptions,
    mut report: impl FnMut(f32, String),
) -> Result<RepackOutcome, String> {
    report(0.05, "gathering files…".to_string());
    let mut files: Vec<(String, Vec<u8>)> = Vec::new();
    gather_files(input_dir, input_dir, &mut files)?;
    if files.is_empty() {
        return Err(format!("no files found under {}", input_dir.display()));
    }
    files.sort();
    report(0.4, format!("packing {} file(s)…", files.len()));

    // Resolve the crypto mode, mirroring cmd_pack's dispatch.
    let (bytes, mode) = match opts.format {
        PackFormat::Ver5 => (
            wolf_archive::pack_ver5(&files)?,
            "ver5 (Wolf 2.0x)".to_string(),
        ),
        PackFormat::Ver6 => (
            wolf_archive::pack_ver6(&files)?,
            "ver6 (Wolf 2.0x)".to_string(),
        ),
        PackFormat::Auto if !opts.encrypt => {
            (wolf_archive::pack_plaintext(&files)?, "unencrypted".to_string())
        }
        PackFormat::Auto => {
            // Resolve cryptVersion (+ embedded password for --like).
            let (version, pwd, src_note) = match &opts.crypt {
                CryptSource::Default => (DEFAULT_CRYPT_VERSION, None, ""),
                CryptSource::Version(v) => (*v, None, ""),
                CryptSource::Like(orig) => {
                    let params = std::fs::read(orig)
                        .ok()
                        .and_then(|d| wolf_archive::archive_crypt_params(&d));
                    match params {
                        Some((cv, p)) => (cv, Some(p), " (--like)"),
                        None => {
                            return Err(format!(
                                "could not read crypt params from {}",
                                orig.display()
                            ))
                        }
                    }
                }
            };
            let packed = if matches!(version, 0x14B | 0x15E) {
                wolf_archive::pack_newcrypt(&files, version, &pwd.unwrap_or(DEFAULT_NEWCRYPT_PWD))?
            } else {
                wolf_archive::pack_encrypted(&files, version)?
            };
            (packed, format!("encrypted cryptVersion={version:#x}{src_note}"))
        }
    };

    if let Some(parent) = out.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("cannot create {}: {e}", parent.display()))?;
        }
    }
    std::fs::write(out, &bytes).map_err(|e| format!("cannot write {}: {e}", out.display()))?;
    report(1.0, "done".to_string());
    Ok(RepackOutcome {
        out: out.to_path_buf(),
        files: files.len(),
        bytes: bytes.len(),
        mode,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Resolve a fixture by its clean relative path under `WOLFDAWN_TEST_DATA`. Returns `None` when
    /// the var is unset or the file is missing, so the data-dependent tests skip gracefully.
    fn test_data(rel: &str) -> Option<PathBuf> {
        let base = std::env::var_os("WOLFDAWN_TEST_DATA")?;
        let p = Path::new(&base).join(rel);
        p.exists().then_some(p)
    }

    fn tmp_dir(tag: &str) -> PathBuf {
        let p = std::env::temp_dir().join(format!(
            "wolfdawn_archive_{tag}_{}_{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        ));
        let _ = std::fs::create_dir_all(&p);
        p
    }

    /// Unpack the Chamber fixture's Data.wolf (if present) and confirm the data files appear. Writes
    /// only to a temp dir, never touches the game folder. Skips gracefully when the archive is absent.
    #[test]
    fn unpack_chamber_archive() {
        let Some(archive) = test_data("chamber/Data.wolf") else {
            eprintln!("skip unpack_chamber_archive: archive fixture not present");
            return;
        };
        let out = tmp_dir("unpack");
        let outcome = unpack(&archive, &out, |_, _| {}).expect("unpack");
        assert!(outcome.written > 0, "some files should have been written");
        assert!(
            out.join("BasicData/CommonEvent.dat").exists(),
            "the unpacked tree should contain BasicData/CommonEvent.dat"
        );
        let _ = std::fs::remove_dir_all(&out);
    }

    /// Pack a small temp folder to a `.wolf`, unpack it again, and confirm the files round-trip with
    /// identical content. Uses copies of a couple of fixture data files (never modifies the fixtures root).
    #[test]
    fn repack_round_trip() {
        // Source a couple of small, real data files from the fixtures root (read-only).
        let present: Vec<PathBuf> = [
            "chamber/Data/BasicData/Game.dat",
            "chamber/Data/BasicData/CommonEvent.dat",
            "chamber/Data/MapData/TitleMap.mps",
        ]
        .iter()
        .filter_map(|r| test_data(r))
        .collect();
        if present.is_empty() {
            eprintln!("skip repack_round_trip: no data fixtures present");
            return;
        }

        // Build a small input folder of COPIES (with a nested subdir to exercise the tree).
        let src = tmp_dir("repack_src");
        let _ = std::fs::create_dir_all(src.join("BasicData"));
        let mut expect: Vec<(String, Vec<u8>)> = Vec::new();
        for (i, p) in present.iter().enumerate() {
            let name = p.file_name().unwrap().to_string_lossy().to_string();
            let rel = format!("BasicData/{name}");
            let dst = src.join("BasicData").join(&name);
            std::fs::copy(p, &dst).expect("copy");
            expect.push((rel, std::fs::read(p).expect("read source")));
            // Only take up to two files to keep the archive small.
            if i >= 1 {
                break;
            }
        }

        let out_wolf = tmp_dir("repack_out").join("Data.wolf");
        let outcome = repack(&src, &out_wolf, &PackOptions::default(), |_, _| {}).expect("repack");
        assert!(outcome.files >= 1, "at least one file should be packed");
        assert!(outcome.bytes > 0, "the archive should be non-empty");

        // Unpack the freshly-built archive and confirm every input file comes back with the same bytes.
        let back = tmp_dir("repack_back");
        let un = unpack(&out_wolf, &back, |_, _| {}).expect("unpack repacked");
        assert!(un.written >= 1, "files should extract from the repacked archive");
        for (rel, bytes) in &expect {
            let got = back.join(rel);
            assert!(got.exists(), "{rel} should round-trip through repack");
            assert_eq!(&std::fs::read(&got).expect("read back"), bytes, "{rel} content must match");
        }

        let _ = std::fs::remove_dir_all(&src);
        let _ = std::fs::remove_dir_all(out_wolf.parent().unwrap());
        let _ = std::fs::remove_dir_all(&back);
    }
}
