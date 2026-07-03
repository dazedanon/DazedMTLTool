//! The Verify section's headless logic: round-trip a data file (or a whole corpus) to prove the
//! library reads and re-writes it without loss. The same check the CLI's `verify-roundtrip` runs.
//!
//! A round-trip is `write(read(bytes)) == bytes`: parse the file with the matching `wolf_formats`
//! reader, re-serialise it, and compare against the original bytes. A match is PASS (byte-exact). A
//! mismatch is FAIL with the first-differing offset for diagnosis. An unreadable file is an error.
//! This module mirrors `cmd.rs`'s `classify` / `roundtrip_path` / `verify_corpus` exactly, so the
//! GUI and CLI agree on what "verified" means.

use std::path::{Path, PathBuf};

use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::database::{BasicDatabase, Database};
use wolf_formats::game_dat::GameDat;
use wolf_formats::map::Map;

/// Which kind of file we're verifying. Decides the reader/writer pair, mirroring the CLI's
/// `FileKind` + `classify`.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum FileKind {
    Map,
    CommonEvent,
    GameDat,
    /// A database, represented by its `.project` (the `.dat` sibling is paired in).
    Database,
    /// Legacy `SysDatabaseBasic` (Wolf 2.x): schema-only `.project` + opaque `.dat`.
    BasicDatabase,
    Unsupported,
}

/// Classify a path by extension/name, exactly like the CLI's `classify`.
fn classify(path: &Path) -> FileKind {
    let ext = path
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    let name = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    match ext.as_str() {
        "mps" => FileKind::Map,
        "project" if name == "sysdatabasebasic.project" => FileKind::BasicDatabase,
        "dat" if name == "sysdatabasebasic.dat" => FileKind::BasicDatabase,
        "project" => FileKind::Database,
        "dat" if name == "commonevent.dat" => FileKind::CommonEvent,
        "dat" if name == "game.dat" => FileKind::GameDat,
        // A .dat with a sibling .project is the value half of a database.
        "dat" if path.with_extension("project").exists() => FileKind::Database,
        _ => FileKind::Unsupported,
    }
}

/// True when the file is one verify understands (so the corpus walk knows what to include and the
/// single-file flow can warn early on an unsupported pick).
pub fn is_supported(path: &Path) -> bool {
    !matches!(classify(path), FileKind::Unsupported)
}

/// The verdict of one file's round-trip.
#[derive(Clone, PartialEq, Eq, Debug)]
pub enum Verdict {
    /// `write(read(bytes)) == bytes`, byte-exact.
    Pass,
    /// Parsed and re-serialised, but the output differs. Carries the first-differing byte offset
    /// and the two lengths, for a clear diagnostic.
    Fail {
        /// Index of the first differing byte (or the shorter length when one is a prefix of the other).
        offset: usize,
        original_len: usize,
        rewritten_len: usize,
    },
    /// The file could not be read/parsed (unreadable, unsupported, or a parse error). Carries the
    /// message.
    Error(String),
}

impl Verdict {
    /// A short status word for the UI/log (`PASS` / `FAIL` / `ERR`).
    pub fn tag(&self) -> &'static str {
        match self {
            Verdict::Pass => "PASS",
            Verdict::Fail { .. } => "FAIL",
            Verdict::Error(_) => "ERR",
        }
    }

    /// A one-line human description of the verdict (the diagnostic).
    pub fn detail(&self) -> String {
        match self {
            Verdict::Pass => "byte-exact round-trip".to_string(),
            Verdict::Fail {
                offset,
                original_len,
                rewritten_len,
            } => format!(
                "differs at byte {offset} (original {original_len} bytes, rewritten {rewritten_len} bytes)"
            ),
            Verdict::Error(e) => e.clone(),
        }
    }

    pub fn is_pass(&self) -> bool {
        matches!(self, Verdict::Pass)
    }
}

/// The index of the first byte that differs between `a` and `b` (or the shorter length when one is
/// a strict prefix of the other). Used to build the [`Verdict::Fail`] diagnostic.
fn first_diff(a: &[u8], b: &[u8]) -> usize {
    a.iter().zip(b.iter()).position(|(x, y)| x != y).unwrap_or_else(|| a.len().min(b.len()))
}

/// Compare an original buffer to a re-serialised one, producing [`Verdict::Pass`] or a
/// [`Verdict::Fail`] with the first-differing offset.
fn compare(original: &[u8], rewritten: Vec<u8>) -> Verdict {
    if rewritten == original {
        Verdict::Pass
    } else {
        Verdict::Fail {
            offset: first_diff(original, &rewritten),
            original_len: original.len(),
            rewritten_len: rewritten.len(),
        }
    }
}

/// Round-trip a single file, returning the [`Verdict`]. Reads the file, parses it with the matching
/// `wolf_formats` reader, re-serialises, and compares. Same logic as the CLI's `roundtrip_path`,
/// but returning a structured verdict (with the diff offset) instead of a bare bool.
///
/// For a database the `.project` is the canonical handle and its sibling `.dat` is paired in. Both
/// halves must re-serialise byte-exact to PASS.
pub fn verify_file(path: &Path) -> Verdict {
    let bytes = match std::fs::read(path) {
        Ok(b) => b,
        Err(e) => return Verdict::Error(format!("cannot read {}: {e}", path.display())),
    };
    match classify(path) {
        FileKind::Map => match Map::read(&bytes) {
            Ok(m) => compare(&bytes, m.write()),
            Err(e) => Verdict::Error(e.to_string()),
        },
        FileKind::CommonEvent => match CommonEventsFile::read(&bytes) {
            Ok(ce) => compare(&bytes, ce.write()),
            Err(e) => Verdict::Error(e.to_string()),
        },
        FileKind::GameDat => match GameDat::read(&bytes) {
            Ok(gd) => compare(&bytes, gd.write()),
            Err(e) => Verdict::Error(e.to_string()),
        },
        FileKind::Database => {
            // `path` may be the .project or its .dat. Verify the pair via the .project.
            let proj_path = path.with_extension("project");
            let dat_path = path.with_extension("dat");
            let (proj_bytes, dat_bytes) =
                match (std::fs::read(&proj_path), std::fs::read(&dat_path)) {
                    (Ok(p), Ok(d)) => (p, d),
                    _ => {
                        return Verdict::Error(format!(
                            "cannot read DB pair {} + {}",
                            proj_path.display(),
                            dat_path.display()
                        ))
                    }
                };
            match Database::read(&proj_bytes, &dat_bytes) {
                Ok(db) => {
                    let (proj_out, dat_out) = db.write();
                    // Report the .project diff first, then the .dat.
                    let proj_v = compare(&proj_bytes, proj_out);
                    if !proj_v.is_pass() {
                        return proj_v;
                    }
                    compare(&dat_bytes, dat_out)
                }
                Err(e) => Verdict::Error(e.to_string()),
            }
        }
        FileKind::BasicDatabase => {
            let proj_path = path.with_extension("project");
            let dat_path = path.with_extension("dat");
            let (proj_bytes, dat_bytes) =
                match (std::fs::read(&proj_path), std::fs::read(&dat_path)) {
                    (Ok(p), Ok(d)) => (p, d),
                    _ => {
                        return Verdict::Error(format!(
                            "cannot read DB pair {} + {}",
                            proj_path.display(),
                            dat_path.display()
                        ))
                    }
                };
            match BasicDatabase::read(&proj_bytes, &dat_bytes) {
                Ok(db) => {
                    let (proj_out, dat_out) = db.write();
                    let proj_v = compare(&proj_bytes, proj_out);
                    if !proj_v.is_pass() {
                        return proj_v;
                    }
                    compare(&dat_bytes, dat_out)
                }
                Err(e) => Verdict::Error(e.to_string()),
            }
        }
        FileKind::Unsupported => {
            Verdict::Error("not a verifiable file type (.mps, CommonEvent.dat, Game.dat, .project)".to_string())
        }
    }
}

/// One file's result in a corpus run: its path relative to the corpus root + its verdict.
pub struct CorpusRow {
    pub rel: String,
    pub verdict: Verdict,
}

/// A whole corpus verify run: the per-file rows + the pass/total summary.
pub struct CorpusOutcome {
    pub rows: Vec<CorpusRow>,
}

impl CorpusOutcome {
    /// How many rows passed (byte-exact).
    pub fn passed(&self) -> usize {
        self.rows.iter().filter(|r| r.verdict.is_pass()).count()
    }
    /// How many rows failed (parsed but differed).
    pub fn failed(&self) -> usize {
        self.rows.iter().filter(|r| matches!(r.verdict, Verdict::Fail { .. })).count()
    }
    /// How many rows errored (could not parse).
    pub fn errored(&self) -> usize {
        self.rows.iter().filter(|r| matches!(r.verdict, Verdict::Error(_))).count()
    }
    /// Total rows checked.
    pub fn total(&self) -> usize {
        self.rows.len()
    }
}

/// Recursively collect every file under `dir` (depth-first), like the CLI's `collect`.
fn collect(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let p = entry.path();
        if p.is_dir() {
            collect(&p, out);
        } else {
            out.push(p);
        }
    }
}

/// Path of `path` relative to `base` (for the per-file table), like the CLI's `rel`.
fn rel(base: &Path, path: &Path) -> String {
    path.strip_prefix(base).unwrap_or(path).display().to_string()
}

/// Walk every supported file under `dir`, round-trip each, and return the per-file rows + summary.
/// The `verify-roundtrip --corpus` path. The lone `.dat` half of a database is skipped (it is
/// verified through its `.project`, matching the CLI). `report` drives a progress bar. Pass a no-op
/// in tests.
pub fn verify_corpus(dir: &Path, mut report: impl FnMut(f32, String)) -> Result<CorpusOutcome, String> {
    if !dir.is_dir() {
        return Err(format!("{} is not a folder", dir.display()));
    }
    report(0.0, "scanning folder…".to_string());
    let mut files: Vec<PathBuf> = Vec::new();
    collect(dir, &mut files);
    files.sort();

    // Keep only the files verify understands. Drop the lone .dat half of a DB pair (verified via the
    // .project) so each pair is checked once.
    let to_check: Vec<PathBuf> = files
        .into_iter()
        .filter(|p| match classify(p) {
            FileKind::Unsupported => false,
            FileKind::Database | FileKind::BasicDatabase
                if p.extension().and_then(|s| s.to_str()) == Some("dat") =>
            {
                false
            }
            _ => true,
        })
        .collect();

    if to_check.is_empty() {
        return Err(format!("no verifiable files found under {}", dir.display()));
    }

    let total = to_check.len();
    let mut rows = Vec::with_capacity(total);
    for (i, path) in to_check.iter().enumerate() {
        let r = rel(dir, path);
        report((i as f32) / (total as f32), format!("verify {r}"));
        let verdict = verify_file(path);
        rows.push(CorpusRow { rel: r, verdict });
    }
    report(1.0, "done".to_string());
    Ok(CorpusOutcome { rows })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Resolve a fixture by its clean relative path under `WOLFDAWN_TEST_DATA`. Returns `None` when
    /// the var is unset or the file/dir is missing, so the data-dependent tests skip gracefully.
    fn test_data(rel: &str) -> Option<PathBuf> {
        let base = std::env::var_os("WOLFDAWN_TEST_DATA")?;
        let p = Path::new(&base).join(rel);
        p.exists().then_some(p)
    }

    /// A known-good plaintext data file from the fixtures root should verify PASS through the
    /// section's own code path. Read-only. Skips when absent.
    #[test]
    fn verify_single_known_good_passes() {
        let Some(path) = [
            "chamber/Data/MapData/TitleMap.mps",
            "chamber/Data/BasicData/Game.dat",
            "chamber/Data/BasicData/CommonEvent.dat",
            "chamber/Data/BasicData/DataBase.project",
        ]
        .iter()
        .find_map(|r| test_data(r)) else {
            eprintln!("skip verify_single_known_good_passes: no data fixture present");
            return;
        };
        let verdict = verify_file(&path);
        assert!(
            verdict.is_pass(),
            "{} should round-trip byte-exact, got {:?}: {}",
            path.display(),
            verdict.tag(),
            verdict.detail()
        );
    }

    /// A corpus walk over the fixtures Data dir produces rows and a sensible summary. Assert it
    /// runs and at least one file passes. Do not require zero failures (the corpus may include
    /// edge files), matching the CLI's tolerant report.
    #[test]
    fn verify_corpus_runs() {
        let Some(dir) = test_data("chamber/Data").filter(|p| p.is_dir()) else {
            eprintln!("skip verify_corpus_runs: data fixture not present");
            return;
        };
        let outcome = verify_corpus(&dir, |_, _| {}).expect("corpus verify");
        assert!(outcome.total() > 0, "corpus should have verifiable files");
        assert!(outcome.passed() > 0, "at least one file should pass");
        assert_eq!(
            outcome.passed() + outcome.failed() + outcome.errored(),
            outcome.total(),
            "every row has exactly one verdict"
        );
    }

    /// An unsupported file type reports an error verdict, not a panic.
    #[test]
    fn unsupported_file_errors() {
        let tmp = std::env::temp_dir().join(format!("wolfdawn_verify_unsup_{}", std::process::id()));
        let _ = std::fs::create_dir_all(&tmp);
        let f = tmp.join("notes.txt");
        std::fs::write(&f, b"hello").unwrap();
        let v = verify_file(&f);
        assert!(matches!(v, Verdict::Error(_)), "txt should be an error verdict");
        assert!(!is_supported(&f));
        let _ = std::fs::remove_dir_all(&tmp);
    }
}
