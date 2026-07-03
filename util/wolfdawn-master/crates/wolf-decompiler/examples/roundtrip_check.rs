//! Byte-exact round-trip check for the gated/recompilable path across a corpus root:
//! `compile_commands_enc(decompile_commands_enc(cmds)) == cmds` for every command list.
//! Exercises the new operand banks, flagged compare ops, and operand-decoded route args.
//!
//! Run: `cargo run -p wolf-decompiler --example roundtrip_check -- <root>`

use std::path::PathBuf;

use wolf_decompiler::{compile_commands_enc, decompile_commands_enc};
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::map::Map;

fn main() {
    let root = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("../../.."));

    let mut stack = vec![root];
    let mut ok = 0usize;
    let mut mismatch = 0usize;
    let mut lists = 0usize;
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else {
            continue;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                stack.push(p);
                continue;
            }
            let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("");
            let ext = p.extension().and_then(|s| s.to_str()).unwrap_or("");
            let bytes = std::fs::read(&p).unwrap_or_default();
            let mut programs: Vec<(bool, Vec<_>)> = Vec::new();
            if name == "CommonEvent.dat" {
                if let Ok(ce) = CommonEventsFile::read(&bytes) {
                    for ev in ce.events {
                        programs.push((ce.utf8, ev.commands));
                    }
                }
            } else if ext.eq_ignore_ascii_case("mps") {
                if let Ok(m) = Map::read(&bytes) {
                    for ev in m.events {
                        for pg in ev.pages {
                            programs.push((m.utf8, pg.commands));
                        }
                    }
                }
            }
            for (utf8, cmds) in programs {
                lists += 1;
                let text = decompile_commands_enc(&cmds, utf8);
                match compile_commands_enc(&text, utf8) {
                    Ok(back) if back == cmds => ok += 1,
                    Ok(_) => {
                        mismatch += 1;
                        if mismatch <= 5 {
                            eprintln!(
                                "MISMATCH (structure differs) in {:?}",
                                p.file_name().unwrap()
                            );
                        }
                    }
                    Err(e) => {
                        mismatch += 1;
                        if mismatch <= 5 {
                            eprintln!("COMPILE ERR in {:?}: {e}", p.file_name().unwrap());
                        }
                    }
                }
            }
        }
    }
    println!("command lists: {lists} | byte-exact round-trip OK: {ok} | mismatch: {mismatch}");
    if mismatch != 0 {
        std::process::exit(1);
    }
}
