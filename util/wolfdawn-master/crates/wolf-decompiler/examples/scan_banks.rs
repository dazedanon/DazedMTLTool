//! Corpus-wide diagnostic: across every engine version, find unnamed/fallthrough renderings
//! and the raw operand "banks" actually used, so no random index goes unhandled.
//!
//! Run: `cargo run -p wolf-decompiler --example scan_banks -- <root>`

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use wolf_decompiler::{decompile_common_events, decompile_map, SymbolTable};
use wolf_formats::command::RawCommand;
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::map::Map;

fn main() {
    let root = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("../../.."));

    let mut files = Vec::new();
    let mut stack = vec![root];
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else {
            continue;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                stack.push(p);
            } else {
                let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("");
                let ext = p.extension().and_then(|s| s.to_str()).unwrap_or("");
                if name == "CommonEvent.dat" || ext.eq_ignore_ascii_case("mps") {
                    files.push(p);
                }
            }
        }
    }
    files.sort();

    // token name -> (count, sample)
    let mut tokens: BTreeMap<&'static str, (usize, String)> = BTreeMap::new();
    // operand bank (v/100000) -> (count, set of (cid,argidx) sites)
    let mut banks: BTreeMap<u32, (usize, BTreeMap<(u32, usize), usize>)> = BTreeMap::new();
    // every command cid used, and every route sub-command id used
    let mut cids: BTreeMap<u32, usize> = BTreeMap::new();
    let mut route_ids: BTreeMap<u32, usize> = BTreeMap::new();
    let mut read_fail: BTreeMap<String, usize> = BTreeMap::new();
    let mut n_maps = 0usize;
    let mut n_ce = 0usize;

    let sym = SymbolTable::new();
    for p in &files {
        let bytes = std::fs::read(p).unwrap_or_default();
        let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("");
        let ver = version_of(p);
        if name == "CommonEvent.dat" {
            match CommonEventsFile::read(&bytes) {
                Ok(ce) => {
                    n_ce += 1;
                    let text = decompile_common_events(&ce, &sym);
                    scan_text(&text, p, &mut tokens);
                    for ev in &ce.events {
                        for c in &ev.commands {
                            scan_cmd(c, &mut banks, &mut cids, &mut route_ids);
                        }
                    }
                }
                Err(e) => *read_fail.entry(format!("{ver} CE: {e}")).or_default() += 1,
            }
        } else {
            match Map::read(&bytes) {
                Ok(m) => {
                    n_maps += 1;
                    let text = decompile_map(&m, &sym);
                    scan_text(&text, p, &mut tokens);
                    for ev in &m.events {
                        for pg in &ev.pages {
                            for c in &pg.commands {
                                scan_cmd(c, &mut banks, &mut cids, &mut route_ids);
                            }
                        }
                    }
                }
                Err(e) => *read_fail.entry(format!("{ver} MAP: {e}")).or_default() += 1,
            }
        }
    }

    println!("== scanned: {n_maps} maps + {n_ce} common-event files ==\n");

    // Cross-check against what the spec catalogues.
    let unknown_cids: Vec<(u32, usize)> = cids
        .iter()
        .filter(|(cid, _)| wolf_decompiler::spec::command(**cid).is_none())
        .map(|(c, n)| (*c, *n))
        .collect();
    let unknown_routes: Vec<(u32, usize)> = route_ids
        .iter()
        .map(|(k, n)| (k / 1000, *n))
        .filter(|(id, _)| wolf_decompiler::spec::route_name(*id) == format!("route{id}"))
        .collect();
    println!("-- UNKNOWN COMMAND CIDS (no schema -> Cmd<n>) --");
    if unknown_cids.is_empty() {
        println!("  none\n");
    } else {
        for (c, n) in &unknown_cids {
            println!("  cid {c:5}  {n}x");
        }
        println!();
    }
    println!("-- UNNAMED ROUTE SUB-COMMAND IDS (-> route<n>) --");
    if unknown_routes.is_empty() {
        println!("  none\n");
    } else {
        for (c, n) in &unknown_routes {
            println!("  route id {c:5}  {n}x");
        }
        println!();
    }
    println!("-- ALL ROUTE IDS USED (id #args, count, current name) --");
    for (key, n) in &route_ids {
        let id = key / 1000;
        let argc = key % 1000;
        println!(
            "  id {id:3}  args {argc}  {n:7}x  {}",
            wolf_decompiler::spec::route_name(id)
        );
    }
    println!();

    println!("-- READ FAILURES (silently skipped by gates) --");
    if read_fail.is_empty() {
        println!("  none\n");
    } else {
        for (k, v) in &read_fail {
            println!("  {v:4}x  {k}");
        }
        println!();
    }

    println!("-- FALLTHROUGH TOKENS in rendered output --");
    if tokens.is_empty() {
        println!("  none\n");
    } else {
        for (tok, (cnt, sample)) in &tokens {
            println!("  {cnt:6}x  {tok:12}  e.g. {sample}");
        }
        println!();
    }

    println!("-- RAW OPERAND BANKS (every int_arg >= 1,000,000, bucketed by /100000) --");
    println!("   bank = the millions/hundred-thousands prefix; sites = distinct (cid,argIndex)");
    for (bank, (cnt, sites)) in &banks {
        let label = bank_label(*bank);
        let mut site_str: Vec<String> = sites
            .iter()
            .map(|((cid, ai), n)| format!("cmd{cid}#{ai}x{n}"))
            .collect();
        site_str.sort();
        let shown = site_str.len().min(8);
        println!(
            "  {bank:>4} ({label:<22}) {cnt:8}x  sites[{}]: {}",
            site_str.len(),
            site_str[..shown].join(" ")
        );
    }
}

fn scan_cmd(
    c: &RawCommand,
    banks: &mut BTreeMap<u32, (usize, BTreeMap<(u32, usize), usize>)>,
    cids: &mut BTreeMap<u32, usize>,
    route_ids: &mut BTreeMap<u32, usize>,
) {
    *cids.entry(c.cid).or_default() += 1;
    // Diagnostic: dump VariableCondition (111) terms whose op code is out of the known 0..6 set.
    if c.cid == 111 {
        if let Some(&header) = c.int_args.first() {
            let n = (header & 0x0F) as usize;
            for g in 0..n {
                if let Some(&op) = c.int_args.get(1 + g * 3 + 2) {
                    if op > 6 {
                        eprintln!(
                            "WEIRD cmd111 op={op} (0x{op:x}) header=0x{header:x} n={n} args={:?}",
                            c.int_args
                        );
                    }
                }
            }
        }
    }
    if let Some(mr) = &c.move_route {
        for rc in &mr.commands {
            // encode (id, argcount) so we can see the real shape: id*1000 + argc
            *route_ids
                .entry(rc.id as u32 * 1000 + rc.args.len() as u32)
                .or_default() += 1;
        }
    }
    for (i, &v) in c.int_args.iter().enumerate() {
        if v >= 1_000_000 && v != 0xFFFF_FFFF && v != 0xFFFF_FFFE {
            let bank = v / 100_000;
            let e = banks.entry(bank).or_default();
            e.0 += 1;
            *e.1.entry((c.cid, i)).or_default() += 1;
        }
    }
}

fn scan_text(text: &str, p: &Path, tokens: &mut BTreeMap<&'static str, (usize, String)>) {
    let checks: &[(&'static str, fn(&str) -> bool)] = &[
        ("Self*[", |l| l.contains("Self*[")),
        ("@raw", |l| l.contains("@raw ")),
        ("Cmd<n>", |l| has_prefixed_num(l, "Cmd")),
        ("route<n>", |l| has_route_num(l)),
        ("cmp<n>", |l| has_cmp_num(l)),
        ("strcmp<n>", |l| has_prefixed_num(l, "strcmp")),
        ("argN", |l| has_argn(l)),
    ];
    for line in text.lines() {
        for (tok, f) in checks {
            if f(line) {
                let e = tokens.entry(*tok).or_insert((0, String::new()));
                e.0 += 1;
                if e.1.is_empty() {
                    e.1 = format!(
                        "{} :: {}",
                        p.file_name().and_then(|s| s.to_str()).unwrap_or(""),
                        line.trim()
                    );
                }
            }
        }
    }
}

/// `prefix` immediately followed by a digit, not part of a longer alnum word before it.
fn has_prefixed_num(line: &str, prefix: &str) -> bool {
    line.match_indices(prefix).any(|(i, _)| {
        let before_ok = i == 0
            || !line[..i]
                .chars()
                .last()
                .map(|c| c.is_alphanumeric())
                .unwrap_or(false);
        let after = &line[i + prefix.len()..];
        before_ok
            && after
                .chars()
                .next()
                .map(|c| c.is_ascii_digit())
                .unwrap_or(false)
    })
}

/// `route` + digit, but NOT `@route(` (the Move route header) and not inside a word.
fn has_route_num(line: &str) -> bool {
    line.match_indices("route").any(|(i, _)| {
        let prev = if i == 0 {
            None
        } else {
            line[..i].chars().last()
        };
        let before_ok = prev
            .map(|c| !c.is_alphanumeric() && c != '@')
            .unwrap_or(true);
        let after = &line[i + 5..];
        before_ok
            && after
                .chars()
                .next()
                .map(|c| c.is_ascii_digit())
                .unwrap_or(false)
    })
}

/// ` cmp` + digit (the VariableCondition unknown-op form), not `strcmp`.
fn has_cmp_num(line: &str) -> bool {
    line.match_indices("cmp").any(|(i, _)| {
        let prev = if i == 0 {
            None
        } else {
            line[..i].chars().last()
        };
        // exclude the `str` of `strcmp`
        let before_ok = prev.map(|c| !c.is_alphanumeric()).unwrap_or(true);
        let after = &line[i + 3..];
        before_ok
            && after
                .chars()
                .next()
                .map(|c| c.is_ascii_digit())
                .unwrap_or(false)
    })
}

fn has_argn(line: &str) -> bool {
    line.match_indices("arg").any(|(i, _)| {
        let prev = if i == 0 {
            None
        } else {
            line[..i].chars().last()
        };
        let before_ok = prev.map(|c| !c.is_alphanumeric()).unwrap_or(true);
        let after = &line[i + 3..];
        let digit = after
            .chars()
            .next()
            .map(|c| c.is_ascii_digit())
            .unwrap_or(false);
        before_ok
            && digit
            && after
                .split_once('=')
                .map(|(k, _)| k.chars().all(|c| c.is_ascii_digit()))
                .unwrap_or(false)
    })
}

fn bank_label(b: u32) -> &'static str {
    match b {
        10 => "1.0M map-event ref",
        11 => "1.1M Self[]",
        12..=15 => "1.2-1.5M ???",
        16 => "1.6M CSelf[]",
        17..=19 => "1.7-1.9M ???",
        20..=29 => "2.x V[] normal",
        30..=39 => "3.x S[] string",
        40..=89 => "4-8M bare-lit ???",
        90..=99 => "9.x Sys[]",
        _ => "10M+ bare-lit ???",
    }
}

fn version_of(p: &Path) -> String {
    for comp in p.components() {
        if let Some(s) = comp.as_os_str().to_str() {
            if s.starts_with("WolfRPGEditor_") {
                return s.to_string();
            }
        }
    }
    "(loose)".to_string()
}
