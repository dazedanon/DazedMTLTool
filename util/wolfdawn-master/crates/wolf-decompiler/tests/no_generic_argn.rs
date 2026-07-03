use wolf_decompiler::{decompile_common_events, decompile_map, SymbolTable};
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::map::Map;
#[test]
fn no_generic_argn() {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let mut stack = vec![root];
    let mut hits = 0;
    let mut files = 0;
    let re = |t: &str| -> usize {
        t.match_indices("arg")
            .filter(|(i, _)| {
                let b = t.as_bytes();
                let j = i + 3;
                j < b.len()
                    && b[j].is_ascii_digit()
                    && t[..*i]
                        .chars()
                        .last()
                        .map_or(true, |c| !c.is_alphanumeric())
                    && t[*i..]
                        .split_once('=')
                        .map_or(false, |(k, _)| k[3..].chars().all(|c| c.is_ascii_digit()))
            })
            .count()
    };
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else {
            continue;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.file_name().and_then(|s| s.to_str()) == Some("CommonEvent.dat") {
                if let Ok(ce) = CommonEventsFile::read(&std::fs::read(&p).unwrap_or_default()) {
                    files += 1;
                    let t = decompile_common_events(&ce, &SymbolTable::new());
                    let h = re(&t);
                    if h > 0 {
                        hits += h;
                        eprintln!("{} argN in {:?}", h, p.file_name().unwrap());
                    }
                }
            } else if p.extension().and_then(|s| s.to_str()) == Some("mps") {
                if let Ok(m) = Map::read(&std::fs::read(&p).unwrap_or_default()) {
                    files += 1;
                    let t = decompile_map(&m, &SymbolTable::new());
                    hits += re(&t);
                }
            }
        }
    }
    eprintln!("scanned {files} files, total generic argN occurrences: {hits}");
    assert_eq!(hits, 0, "generic argN still present");
}
