//! Whole-file recompile gate: `compile(decompile_edit(file), base=file).write() == file`.
//!
//! This is the real edit-to-play round trip. It exercises the document envelope, the patch
//! substitution, and the format writer together, asserting byte-identity across every
//! CommonEvent.dat and .mps reachable (main corpus, every editor version, GamePro and Pro).
//!   cargo test -p wolf-decompiler --test full_file_recompile -- --nocapture

use std::path::{Path, PathBuf};

use wolf_decompiler::{
    compile_common_events_edit, compile_map_edit, decompile_common_events_edit, decompile_map_edit,
};
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::map::Map;

fn wolf_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
}

/// Recurse `dir`, collecting every CommonEvent.dat and *.mps.
fn collect(dir: &Path, ces: &mut Vec<PathBuf>, maps: &mut Vec<PathBuf>) {
    let Ok(rd) = std::fs::read_dir(dir) else {
        return;
    };
    for e in rd.flatten() {
        let p = e.path();
        if p.is_dir() {
            collect(&p, ces, maps);
        } else if p.file_name().and_then(|s| s.to_str()) == Some("CommonEvent.dat") {
            ces.push(p);
        } else if p.extension().and_then(|s| s.to_str()) == Some("mps") {
            maps.push(p);
        }
    }
}

fn ce_roundtrip(bytes: &[u8]) -> Result<bool, String> {
    let ce = CommonEventsFile::read(bytes).map_err(|e| e.to_string())?;
    let doc = decompile_common_events_edit(&ce);
    let mut base = CommonEventsFile::read(bytes).map_err(|e| e.to_string())?;
    compile_common_events_edit(&doc, &mut base).map_err(|e| e.to_string())?;
    Ok(base.write() == bytes)
}

fn map_roundtrip(bytes: &[u8]) -> Result<bool, String> {
    let map = Map::read(bytes).map_err(|e| e.to_string())?;
    let doc = decompile_map_edit(&map);
    let mut base = Map::read(bytes).map_err(|e| e.to_string())?;
    compile_map_edit(&doc, &mut base).map_err(|e| e.to_string())?;
    Ok(base.write() == bytes)
}

#[test]
fn whole_file_round_trip_byte_exact() {
    let root = wolf_root();
    let mut ces = Vec::new();
    let mut maps = Vec::new();
    for sub in ["Data", "ALLWOLFVERSIONS", "GamePro_Data", "GameProData"] {
        collect(&root.join(sub), &mut ces, &mut maps);
    }
    ces.sort();
    ces.dedup();
    maps.sort();
    maps.dedup();

    if ces.is_empty() && maps.is_empty() {
        eprintln!("no corpus found, skipping");
        return;
    }

    let mut ok = 0usize;
    let mut fail = 0usize;
    let mut skip = 0usize;
    let rel = |p: &Path| {
        p.strip_prefix(&root)
            .unwrap_or(p)
            .display()
            .to_string()
            .replace('\\', "/")
    };

    // Encrypted (packaged) files need the archive layer to decrypt first. They are not plaintext
    // inputs to the format/recompile path, so skip rather than fail.
    let mut tally = |p: &Path, r: Result<bool, String>| match r {
        Ok(true) => ok += 1,
        Ok(false) => {
            fail += 1;
            eprintln!("  DIFF  {}", rel(p));
        }
        Err(e) if e.contains("encrypted") => skip += 1,
        Err(e) => {
            fail += 1;
            eprintln!("  ERR   {}  ({e})", rel(p));
        }
    };

    for p in &ces {
        let Ok(bytes) = std::fs::read(p) else {
            continue;
        };
        tally(p, ce_roundtrip(&bytes));
    }
    for p in &maps {
        let Ok(bytes) = std::fs::read(p) else {
            continue;
        };
        tally(p, map_roundtrip(&bytes));
    }

    eprintln!(
        "\nwhole-file recompile: {ok} byte-exact, {fail} fail, {skip} skipped (encrypted)  \
         ({} CE, {} maps)",
        ces.len(),
        maps.len()
    );
    assert_eq!(fail, 0, "some files did not recompile byte-exact");
    assert!(ok > 0, "no files were exercised");
}

#[test]
fn edit_then_compile_takes_effect() {
    // Prove the whole-file path is driven by the document text, not a memory of the base. Edit a
    // Message in the decompiled doc, recompile, and confirm the bytes changed and the new text is
    // present, and that the re-read file still parses.
    let path = wolf_root().join("Data/BasicData/CommonEvent.dat");
    let Ok(bytes) = std::fs::read(&path) else {
        eprintln!("corpus not found, skipping");
        return;
    };
    let ce = CommonEventsFile::read(&bytes).unwrap();
    let doc = decompile_common_events_edit(&ce);

    // Find any Message line to mutate.
    let Some(line) = doc.lines().find(|l| l.trim_start().starts_with("Message ")) else {
        eprintln!("no Message command in corpus doc, skipping");
        return;
    };
    let edited = doc.replacen(line, "Message \"WOLFDAWN_EDIT_MARKER\"", 1);
    assert_ne!(edited, doc, "edit did not change the document");

    let mut base = CommonEventsFile::read(&bytes).unwrap();
    compile_common_events_edit(&edited, &mut base).expect("edited doc compiles");
    let out = base.write();
    assert_ne!(out, bytes, "edited file should differ from the original");

    // Re-read: the marker is present and the file is structurally valid.
    let reread = CommonEventsFile::read(&out).expect("edited file re-parses");
    let found = reread.events.iter().any(|ev| {
        ev.commands.iter().any(|c| {
            c.cid == 101
                && c.str_args
                    .first()
                    .map_or(false, |s| s.as_bytes() == b"WOLFDAWN_EDIT_MARKER\0")
        })
    });
    assert!(found, "edited Message text not found after recompile");
}
