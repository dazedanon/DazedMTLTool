//! Diagnostic probe (reports, never asserts): point our readers at a second, Wolf-Pro
//! game's files to discover format/version/encryption gaps. Run with:
//!   cargo test -p wolf-formats --test gamepro_probe -- --nocapture

use std::path::PathBuf;

use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::database::Database;
use wolf_formats::map::Map;

fn pro_data() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
        .join("GamePro_Data")
}

fn entropy(b: &[u8]) -> f64 {
    if b.is_empty() {
        return 0.0;
    }
    let mut counts = [0usize; 256];
    for &x in b {
        counts[x as usize] += 1;
    }
    let n = b.len() as f64;
    -counts
        .iter()
        .filter(|&&c| c > 0)
        .map(|&c| {
            let p = c as f64 / n;
            p * p.log2()
        })
        .sum::<f64>()
}

fn report_head(label: &str, bytes: &[u8]) {
    let n = bytes.len().min(16);
    let hex: String = bytes[..n].iter().map(|b| format!("{b:02x} ")).collect();
    let ent = entropy(&bytes[..bytes.len().min(4096)]);
    eprintln!(
        "  {label:24} {} bytes  head: {hex}  entropy(4k)={ent:.2}",
        bytes.len()
    );
}

#[test]
fn probe_common_event() {
    let p = pro_data().join("BasicData").join("CommonEvent.dat");
    let Ok(bytes) = std::fs::read(&p) else {
        eprintln!("missing {}", p.display());
        return;
    };
    report_head("CommonEvent.dat", &bytes);
    let ce = CommonEventsFile::read(&bytes).expect("parse Pro CommonEvent.dat");
    let rt = ce.write();
    eprintln!(
        "  PARSED: {} events; round-trip {}",
        ce.events.len(),
        if rt == bytes { "BYTE-EXACT" } else { "DIFF" }
    );
    assert_eq!(rt, bytes, "Pro CommonEvent.dat must round-trip byte-exact");
}

#[test]
fn probe_databases() {
    let dir = pro_data().join("BasicData");
    for (proj, dat) in [
        ("DataBase.project", "DataBase.dat"),
        ("CDataBase.project", "CDataBase.dat"),
        ("SysDatabase.project", "SysDatabase.dat"),
    ] {
        let (pp, dp) = (dir.join(proj), dir.join(dat));
        let (Ok(pb), Ok(db_bytes)) = (std::fs::read(&pp), std::fs::read(&dp)) else {
            continue;
        };
        report_head(dat, &db_bytes);
        let db =
            Database::read(&pb, &db_bytes).unwrap_or_else(|e| panic!("parse {proj}/{dat}: {e}"));
        let (po, dout) = db.write();
        eprintln!(
            "  {proj}/{dat} PARSED: {} types; proj {} dat {}",
            db.types.len(),
            if po == pb { "ok" } else { "DIFF" },
            if dout == db_bytes {
                "BYTE-EXACT"
            } else {
                "DIFF"
            }
        );
        assert_eq!(po, pb, "{proj} must round-trip byte-exact");
        assert_eq!(dout, db_bytes, "{dat} must round-trip byte-exact");
    }
}

#[test]
fn probe_maps() {
    let dir = pro_data().join("MapData");
    let Ok(entries) = std::fs::read_dir(&dir) else {
        eprintln!("missing {}", dir.display());
        return;
    };
    let mut ok = 0;
    let mut fail = 0;
    let mut diff = 0;
    let mut total = 0;
    let mut first_err = String::new();
    let mut versions: std::collections::BTreeMap<u32, usize> = Default::default();
    for e in entries {
        let path = e.unwrap().path();
        if path.extension().and_then(|s| s.to_str()) != Some("mps") {
            continue;
        }
        let bytes = std::fs::read(&path).unwrap();
        total += 1;
        // map version lives at offset 20 (after 10-byte 0x00 pad + WOLFM magic + 'U'/byte).
        if bytes.len() > 23 {
            let v = u32::from_le_bytes([bytes[20], bytes[21], bytes[22], bytes[23]]);
            *versions.entry(v).or_default() += 1;
        }
        match Map::read(&bytes) {
            Ok(m) => {
                let rt = m.write();
                if rt == bytes {
                    ok += 1;
                } else {
                    diff += 1;
                }
            }
            Err(e) => {
                fail += 1;
                if first_err.is_empty() {
                    first_err = format!("{}: {e}", path.file_name().unwrap().to_string_lossy());
                }
            }
        }
    }
    eprintln!("  maps: total={total} byte-exact={ok} diff={diff} parse-fail={fail}");
    eprintln!("  map versions seen: {versions:?}");
    if !first_err.is_empty() {
        eprintln!("  first parse error: {first_err}");
    }
    assert_eq!(fail, 0, "all Pro maps must parse");
    assert_eq!(ok, total, "all Pro maps must round-trip byte-exact");
}
