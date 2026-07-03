//! Legacy `SysDataBaseBasic` (Wolf 2.x) round-trip gate: the `.project` schema is parsed and
//! re-emitted byte-exact, the magic-less `.dat` is carried opaque, so the pair reproduces
//! byte-for-byte. This file is preserved losslessly rather than dropped.
//!   cargo test -p wolf-formats --test basic_database -- --nocapture

use std::path::{Path, PathBuf};

use wolf_formats::database::{dat_has_db_magic, BasicDatabase};

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
        .join("ALLWOLFVERSIONS")
}

/// Collect every `SysDataBaseBasic.project` under `dir`.
fn collect(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(rd) = std::fs::read_dir(dir) else {
        return;
    };
    for e in rd.flatten() {
        let p = e.path();
        if p.is_dir() {
            collect(&p, out);
        } else if p.file_name().and_then(|s| s.to_str()) == Some("SysDataBaseBasic.project") {
            out.push(p);
        }
    }
}

#[test]
fn basic_database_round_trips_byte_exact() {
    let mut projects = Vec::new();
    collect(&root(), &mut projects);
    projects.sort();
    projects.dedup();

    if projects.is_empty() {
        eprintln!("no SysDataBaseBasic found, skipping");
        return;
    }

    let mut ok = 0usize;
    for proj in &projects {
        let dat = proj.with_extension("dat");
        let (Ok(pb), Ok(db_)) = (std::fs::read(proj), std::fs::read(&dat)) else {
            continue;
        };
        // The legacy .dat must indeed lack the container magic (else it is a normal DB).
        assert!(
            !dat_has_db_magic(&db_),
            "{} unexpectedly has DB magic",
            dat.display()
        );

        let parsed = BasicDatabase::read(&pb, &db_).expect("basic database parses");
        let (proj_out, dat_out) = parsed.write();
        assert_eq!(proj_out, pb, "{}: .project not byte-exact", proj.display());
        assert_eq!(dat_out, db_, "{}: .dat not byte-exact", dat.display());
        ok += 1;
    }
    eprintln!(
        "SysDataBaseBasic byte-exact round-trips: {ok}/{}",
        projects.len()
    );
    assert!(ok > 0, "no basic databases were exercised");
}
