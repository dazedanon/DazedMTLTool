//! `wolf`. WolfDawn command-line front-end.
//!
//! Subcommands (P0/P1 subset):
//!   wolf decompile <file.mps|CommonEvent.dat> [--mode edit] [-o out.wscript]
//!   wolf compile   <doc.wscript> --base <orig> -o <out>
//!   wolf verify-roundtrip <file> | --corpus <data-dir>
//!
//! Exit codes: 0 ok · 2 round-trip mismatch · 4 read/parse failure · 64 usage.
use std::process::ExitCode;

mod cmd;
use cmd::*;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("decompile") => cmd_decompile(&args[1..]),
        Some("compile") => cmd_compile(&args[1..]),
        Some("pack") => cmd_pack(&args[1..]),
        Some("unpack") => cmd_unpack(&args[1..]),
        Some("unpack-all") => cmd_unpack_all(&args[1..]),
        Some("db-json") => cmd_db_json(&args[1..]),
        Some("db-apply") => cmd_db_apply(&args[1..]),
        Some("gamedat-json") => cmd_gamedat_json(&args[1..]),
        Some("gamedat-apply") => cmd_gamedat_apply(&args[1..]),
        Some("strings-extract") => cmd_strings_extract(&args[1..]),
        Some("strings-audit") => cmd_strings_audit(&args[1..]),
        Some("strings-inject") => cmd_strings_inject(&args[1..]),
        Some("names-extract") => cmd_names_extract(&args[1..]),
        Some("names-inject") => cmd_names_inject(&args[1..]),
        Some("names-check") => cmd_names_check(&args[1..]),
        Some("translations-merge") => cmd_translations_merge(&args[1..]),
        Some("save-update") => cmd_save_update(&args[1..]),
        Some("gui") => cmd_gui(&args[1..]),
        Some("raw") => cmd_raw(&args[1..]),
        Some("xref") => cmd_xref(&args[1..]),
        Some("export-names") => cmd_export_names(&args[1..]),
        Some("verify-roundtrip") => cmd_verify(&args[1..]),
        Some("-h") | Some("--help") | Some("help") | None => {
            usage();
            ExitCode::SUCCESS
        }
        Some(other) => {
            eprintln!("unknown subcommand: {other}\n");
            usage();
            ExitCode::from(64)
        }
    }
}

fn usage() {
    eprintln!(
        "wolf - WolfDawn toolchain\n\n\
         USAGE:\n  \
         wolf decompile <file.mps|CommonEvent.dat> [--mode edit] [-o out.wscript]\n  \
         wolf compile   <doc.wscript> --base <orig> -o <out>\n  \
         wolf pack      <dir> -o <out.wolf> [--encrypt --version 0x14b | --like <orig> | --format ver5|ver6]\n  \
         wolf unpack    <archive.wolf> -o <dir>\n  \
         wolf unpack-all <data-dir|archive.wolf>... [-o <out-dir>]  (unpack every .wolf, each into out/<name>/)\n  \
         wolf db-json   <X.project|data-dir> [-o out]\n  \
         wolf db-apply  <edited.json> --base <X.project> -o <out.project>\n  \
         wolf gamedat-json  <Game.dat> [-o out.json]\n  \
         wolf gamedat-apply <edited.json> --base <Game.dat> -o <out>\n  \
         wolf strings-extract <CommonEvent.dat|map.mps|X.project|Game.dat|event.txt|dir-of-txt> -o <out.json>\n  \
         wolf strings-inject  <edited.json> --base <orig|event.txt|dir-of-txt> -o <out> [--allow-code-drift] [--en-punct]\n  \
         wolf names-extract   <data-dir> -o <names.json>\n  \
         wolf names-inject    <names.json> --data <data-dir> [-o <out-dir>] [--allow-code-drift] [--en-punct]\n  \
         wolf names-check     <file.json>...  (report names translated inconsistently across files)\n  \
         wolf translations-merge --old <path>... --new <dir> -o <out-dir>  (carry old translations into a re-extraction)\n  \
         wolf save-update <save.sav|dir> [-o <out>] [--title <text> | --game <Game.dat>] [--translations <file-or-dir>...]\n  \
         wolf gui        (launch WolfDawn Studio, the desktop GUI)\n  \
         wolf verify-roundtrip <file>\n  \
         wolf verify-roundtrip --corpus <data-dir>\n"
    );
}
