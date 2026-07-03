//! The Decompile section's headless logic: turn a binary event file (a `.mps` map or
//! `CommonEvent.dat`) into readable, editable WolfScript, then recompile the edited text back into a
//! runnable file using the original as a *base* so every opaque byte is preserved.
//!
//! This mirrors the CLI's `decompile --mode edit` (`decompile_edit_path`) and `compile`
//! (`cmd_compile`) exactly, calling the same `wolf_decompiler` library functions directly (no
//! shelling out), so the GUI and CLI produce identical output:
//!
//!   * [`decompile_edit`] reads the input, parses it with the matching `wolf_formats` reader, builds
//!     a symbol-aware table (CommonEvent + the three databases under the game's BasicData), and
//!     renders the **edit** document (`decompile_*_edit_annotated`), the recompilable, bilingual
//!     form `compile` consumes.
//!   * [`compile_to`] re-reads the *base* file (the original input), applies the edited WolfScript
//!     onto it (`compile_*_edit`), and writes the result. The base supplies all opaque metadata.
//!     Only the command bodies are swapped in, so untouched code re-serializes byte-identical.
//!
//! Only code-bearing files (`.mps`, `CommonEvent.dat`) are supported. Anything else is rejected with
//! a clear message, matching the CLI.

use std::path::{Path, PathBuf};

use wolf_decompiler::{
    compile_common_events_edit, compile_map_edit, decompile_common_events_edit_annotated,
    decompile_map_edit_annotated, SymbolTable,
};
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::database::Database;
use wolf_formats::map::Map;

/// Which kind of code-bearing file we're working with. Decides the reader/decompiler/compiler
/// pair, mirroring the CLI's `classify` (only the two code-bearing variants are relevant here).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum CodeKind {
    Map,
    CommonEvent,
}

/// Classify a path as a map / common-event, or `None` for anything decompile does not understand
/// (a database, Game.dat, an unrelated file). Mirrors the relevant arms of the CLI's `classify`.
fn classify(path: &Path) -> Option<CodeKind> {
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
        "mps" => Some(CodeKind::Map),
        "dat" if name == "commonevent.dat" => Some(CodeKind::CommonEvent),
        _ => None,
    }
}

/// True when `path` is a file decompile understands (a `.mps` map or `CommonEvent.dat`), so the UI
/// can warn early on an unsupported pick. The action still runs and gives a clear error.
pub fn is_supported(path: &Path) -> bool {
    classify(path).is_some()
}

/// Load the three standard databases under `basic` into `symbols`, exactly like the CLI's
/// `add_databases`. Skips any that are missing or fail to parse (symbols are best-effort labels).
fn add_databases(symbols: &mut SymbolTable, basic: &Path) {
    for (kind, stem) in [("UDB", "DataBase"), ("CDB", "CDataBase"), ("SDB", "SysDatabase")] {
        let proj = basic.join(format!("{stem}.project"));
        let dat = basic.join(format!("{stem}.dat"));
        if let (Ok(p), Ok(d)) = (std::fs::read(&proj), std::fs::read(&dat)) {
            if let Ok(db) = Database::read(&p, &d) {
                symbols.add_database(kind, &db);
            }
        }
    }
}

/// Build the symbol table for a map, locating the game's BasicData folder the same way the CLI's
/// `load_symbols` does (`.../Data/MapData/X.mps` → `.../Data/BasicData`) and loading CommonEvent +
/// the databases + the embedded glossaries. Best-effort: a missing BasicData just yields fewer labels.
fn map_symbols(map_path: &Path) -> SymbolTable {
    let mut symbols = SymbolTable::new();
    let basic = map_path.parent().and_then(|p| p.parent()).map(|data| data.join("BasicData"));
    let Some(basic) = basic else {
        return symbols;
    };
    if let Ok(bytes) = std::fs::read(basic.join("CommonEvent.dat")) {
        if let Ok(ce) = CommonEventsFile::read(&bytes) {
            symbols.add_common_events(&ce);
        }
    }
    add_databases(&mut symbols, &basic);
    symbols.set_glossary(wolf_decompiler::symbols::load_embedded_glossary());
    symbols.set_engine_text(wolf_decompiler::symbols::load_embedded_engine_glossary());
    symbols
}

/// Build the symbol table for a CommonEvent.dat: its own events, plus the sibling databases in the
/// same folder + the embedded glossaries (mirrors the CLI's `decompile_edit_path` CommonEvent arm).
fn common_event_symbols(ce: &CommonEventsFile, ce_dir: Option<&Path>) -> SymbolTable {
    let mut symbols = SymbolTable::new();
    symbols.add_common_events(ce);
    if let Some(dir) = ce_dir {
        add_databases(&mut symbols, dir);
    }
    symbols.set_glossary(wolf_decompiler::symbols::load_embedded_glossary());
    symbols.set_engine_text(wolf_decompiler::symbols::load_embedded_engine_glossary());
    symbols
}

/// Decompile `input` to the **edit** WolfScript document (the recompilable, identity-delimited form
/// `compile` consumes), exactly like the CLI's `decompile --mode edit`. Symbol-aware: each operand
/// carries its index and a bilingual label, so the one file is both readable and recompilable.
/// Returns the WolfScript text. Errors for an unsupported file or a parse failure.
pub fn decompile_edit(input: &Path) -> Result<String, String> {
    let bytes = std::fs::read(input).map_err(|e| format!("cannot read {}: {e}", input.display()))?;
    match classify(input) {
        Some(CodeKind::Map) => {
            let map = Map::read(&bytes).map_err(|e| e.to_string())?;
            Ok(decompile_map_edit_annotated(&map, &map_symbols(input)))
        }
        Some(CodeKind::CommonEvent) => {
            let ce = CommonEventsFile::read(&bytes).map_err(|e| e.to_string())?;
            let symbols = common_event_symbols(&ce, input.parent());
            Ok(decompile_common_events_edit_annotated(&ce, &symbols))
        }
        None => Err(format!(
            "{} is not a code-bearing file (decompile supports .mps maps and CommonEvent.dat)",
            input.display()
        )),
    }
}

/// The outcome of a [`compile_to`] run, for the log: the bytes written, whether the result is
/// byte-identical to the base (i.e. the code was untouched), and the output path.
pub struct CompileOutcome {
    pub out: PathBuf,
    pub bytes: usize,
    pub byte_identical: bool,
}

/// Compile the edited WolfScript `text` back into a runnable file, using `base` (the original input
/// the text was decompiled from) as the base, and write the result to `output`. Mirrors the CLI's
/// `cmd_compile`: the base supplies all opaque metadata, only the command bodies are swapped in, so
/// with the code untouched the output is byte-identical to the base.
///
/// As a safety net (and what the GUI's round-trip test asserts), the freshly compiled bytes are
/// re-parsed with the matching reader before the write is reported, so a structurally-corrupt result
/// never lands on disk silently.
pub fn compile_to(text: &str, base: &Path, output: &Path) -> Result<CompileOutcome, String> {
    let base_bytes =
        std::fs::read(base).map_err(|e| format!("cannot read base {}: {e}", base.display()))?;
    let out_bytes = match classify(base) {
        Some(CodeKind::CommonEvent) => {
            let mut ce = CommonEventsFile::read(&base_bytes)
                .map_err(|e| format!("base parse failed: {e}"))?;
            compile_common_events_edit(text, &mut ce).map_err(|e| format!("compile failed: {e}"))?;
            let out = ce.write();
            // Re-parse before reporting: never ship a structurally-corrupt file.
            CommonEventsFile::read(&out)
                .map_err(|e| format!("internal error: compiled CommonEvent no longer parses ({e})"))?;
            out
        }
        Some(CodeKind::Map) => {
            let mut map = Map::read(&base_bytes).map_err(|e| format!("base parse failed: {e}"))?;
            compile_map_edit(text, &mut map).map_err(|e| format!("compile failed: {e}"))?;
            let out = map.write();
            Map::read(&out)
                .map_err(|e| format!("internal error: compiled map no longer parses ({e})"))?;
            out
        }
        None => {
            return Err(format!(
                "base {} must be a .mps map or CommonEvent.dat",
                base.display()
            ))
        }
    };

    let byte_identical = out_bytes == base_bytes;
    std::fs::write(output, &out_bytes)
        .map_err(|e| format!("cannot write {}: {e}", output.display()))?;
    Ok(CompileOutcome {
        out: output.to_path_buf(),
        bytes: out_bytes.len(),
        byte_identical,
    })
}

/// One match of a find query in the editor text, as a half-open range of *character* indices
/// `[start, end)` (not byte offsets). Character indices are what egui's `CCursor` wants, so the find
/// bar can set the editor selection directly from these. Kept here (not in `app.rs`) so the
/// match-finding logic is unit-testable without a UI.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct FindMatch {
    /// Inclusive start, as a character index into the script.
    pub start: usize,
    /// Exclusive end, as a character index into the script.
    pub end: usize,
}

/// Find every (non-overlapping) occurrence of `query` in `haystack`, returning each as a character
/// range [`FindMatch`]. Empty when `query` is empty or has no match. When `case_sensitive` is false
/// the comparison is ASCII-case-insensitive (lowercasing both sides). CJK text is unaffected by
/// case folding, so the default insensitive mode is safe for the Japanese content this tool edits.
///
/// Matching is done on chars (not bytes), and the returned ranges are char indices, so they map
/// straight onto egui's `CCursor`/selection model. Overlapping matches are skipped (search resumes
/// after each hit), matching a typical "find next" stepping behaviour.
pub fn find_matches(haystack: &str, query: &str, case_sensitive: bool) -> Vec<FindMatch> {
    if query.is_empty() {
        return Vec::new();
    }
    // Work on char vectors so the reported indices are char positions (what egui's CCursor uses),
    // not byte offsets. Fold per char (1:1) so case-insensitive matching never shifts those indices.
    let hay: Vec<char> = haystack.chars().map(|c| fold_char(c, case_sensitive)).collect();
    let need: Vec<char> = query.chars().map(|c| fold_char(c, case_sensitive)).collect();

    let mut out = Vec::new();
    if need.len() > hay.len() {
        return out;
    }
    let mut i = 0usize;
    while i + need.len() <= hay.len() {
        if hay[i..i + need.len()] == need[..] {
            out.push(FindMatch { start: i, end: i + need.len() });
            i += need.len(); // non-overlapping: resume after the match.
        } else {
            i += 1;
        }
    }
    out
}

/// Case-fold one char without changing the char count (so character indices stay aligned with the
/// original string). For Latin + CJK content this is exactly ASCII lowercasing. CJK is returned
/// unchanged. Using a 1:1 fold keeps the [`find_matches`] ranges valid as `CCursor` char indices.
fn fold_char(c: char, case_sensitive: bool) -> char {
    if case_sensitive {
        c
    } else {
        c.to_ascii_lowercase()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `find_matches` returns the correct char ranges for ASCII, is case-insensitive by default,
    /// honours a case-sensitive flag, handles non-overlapping repeats, and is char- (not byte-)
    /// indexed across multi-byte (CJK) text.
    #[test]
    fn find_matches_ranges_are_correct() {
        // Basic ASCII, case-insensitive (default).
        let hay = "abc ABC abc";
        let m = find_matches(hay, "abc", false);
        assert_eq!(m.len(), 3, "three case-insensitive hits");
        assert_eq!(m[0], FindMatch { start: 0, end: 3 });
        assert_eq!(m[1], FindMatch { start: 4, end: 7 });
        assert_eq!(m[2], FindMatch { start: 8, end: 11 });

        // Case-sensitive: only the two lowercase runs.
        let m = find_matches(hay, "abc", true);
        assert_eq!(m.len(), 2, "two case-sensitive hits");
        assert_eq!(m[0], FindMatch { start: 0, end: 3 });
        assert_eq!(m[1], FindMatch { start: 8, end: 11 });

        // Empty query → no matches.
        assert!(find_matches(hay, "", false).is_empty());
        // No match.
        assert!(find_matches(hay, "zzz", false).is_empty());

        // Non-overlapping: "aa" in "aaaa" → 2 matches (0..2, 2..4), not 3.
        let m = find_matches("aaaa", "aa", false);
        assert_eq!(m, vec![FindMatch { start: 0, end: 2 }, FindMatch { start: 2, end: 4 }]);

        // Char-indexed across CJK: prefix is 2 multi-byte chars, so the match starts at char 2.
        let hay = "あい行 X 行";
        let m = find_matches(hay, "行", false);
        assert_eq!(m.len(), 2, "two occurrences of 行");
        assert_eq!(m[0], FindMatch { start: 2, end: 3 }, "char index, not byte offset");
        // The second 行 is at char index 6 ("あ い 行 ␠ X ␠ 行").
        assert_eq!(m[1], FindMatch { start: 6, end: 7 });
    }


    /// A unique temp dir for a test's scratch output (never under a game folder or the fixtures root).
    fn tmp_dir(tag: &str) -> PathBuf {
        let p = std::env::temp_dir().join(format!(
            "wolfdawn_decompile_{tag}_{}_{}",
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

    /// The first present code-bearing fixture from the fixtures root (read-only). A map is
    /// preferred (it exercises the BasicData symbol lookup), then CommonEvent.dat.
    fn fixture() -> Option<PathBuf> {
        [
            "chamber/Data/MapData/TitleMap.mps",
            "chamber/Data/BasicData/CommonEvent.dat",
        ]
        .into_iter()
        .find_map(test_data)
    }

    /// Decompile a real file to WolfScript (non-empty), compile it back onto the original as base to
    /// a temp output, and assert the result re-decompiles to the same text (semantic round-trip). For
    /// an untouched document compile is byte-exact, so we also assert byte-identity to the base. Never
    /// modifies the fixtures root. Reads the fixture, writes only into a temp dir.
    #[test]
    fn decompile_compile_round_trip() {
        let Some(input) = fixture() else {
            eprintln!("skip decompile_compile_round_trip: no code fixture present");
            return;
        };
        assert!(is_supported(&input), "{input:?} should be supported");

        let text = decompile_edit(&input).expect("decompile");
        assert!(!text.is_empty(), "decompiled WolfScript should be non-empty");

        let work = tmp_dir("rt");
        // Keep the base's file name so the compiled output re-classifies (and re-decompiles) the
        // same way (a `.mps` stays a map, `CommonEvent.dat` stays a common-event).
        let out = work.join(input.file_name().expect("file name"));
        let outcome = compile_to(&text, &input, &out).expect("compile");
        assert!(out.exists(), "compiled output should be written");
        assert!(outcome.bytes > 0, "output should be non-empty");

        // Untouched code is byte-identical to base (the strong guarantee compile gives).
        let base_bytes = std::fs::read(&input).expect("read base");
        let out_bytes = std::fs::read(&out).expect("read out");
        assert_eq!(out_bytes, base_bytes, "untouched compile must be byte-identical to base");
        assert!(outcome.byte_identical, "outcome should report byte-identity");

        // Semantic check: re-decompile the compiled output and compare to a decompile of the *base
        // placed in the same temp dir*. Both share the same (BasicData-less) symbol context, so the
        // bilingual operand labels match. Comparing against the original `text` (decompiled at the
        // real location, where the databases resolve those labels) would differ only in those labels,
        // and the compiler strips labels, so the bytes already proved equal above.
        let base_here = work.join("base").join(input.file_name().unwrap());
        std::fs::create_dir_all(base_here.parent().unwrap()).unwrap();
        std::fs::copy(&input, &base_here).expect("copy base");
        let baseline = decompile_edit(&base_here).expect("decompile base copy");
        let re = decompile_edit(&out).expect("re-decompile");
        assert_eq!(re, baseline, "re-decompiled WolfScript should match the base's own decompile");

        let _ = std::fs::remove_dir_all(&work);
    }

    /// An unsupported file (e.g. a plain .txt) is rejected by both entry points, not panicked on.
    #[test]
    fn unsupported_file_is_rejected() {
        let work = tmp_dir("unsup");
        let f = work.join("notes.txt");
        std::fs::write(&f, b"hello").unwrap();
        assert!(!is_supported(&f));
        assert!(decompile_edit(&f).is_err(), "txt should not decompile");
        assert!(
            compile_to("", &f, &work.join("out")).is_err(),
            "txt base should not compile"
        );
        let _ = std::fs::remove_dir_all(&work);
    }
}
