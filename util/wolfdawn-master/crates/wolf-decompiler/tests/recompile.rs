//! Recompiler core gate: `compile(decompile(cmds)) == cmds`.
//!
//! The synthetic test proves the structural reconstruction (marker commands, suppressed `Blank`
//! slots, indent bytes, condition and operator decoding) round-trips exactly. The corpus test
//! measures how many real common events fully round-trip.

use wolf_decompiler::{compile_commands, decompile_commands};
use wolf_formats::command::RawCommand;
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::WStr;

fn leaf(cid: u32, ints: Vec<u32>, indent: u8, strs: &[&str]) -> RawCommand {
    RawCommand {
        cid,
        int_args: ints,
        indent,
        str_args: strs
            .iter()
            .map(|s| WStr(format!("{s}\0").into_bytes()))
            .collect(),
        term: 0,
        move_route: None,
        v35_blob: None,
    }
}

fn bare(cid: u32, ints: Vec<u32>, indent: u8) -> RawCommand {
    leaf(cid, ints, indent, &[])
}

#[test]
fn structural_round_trip_exact() {
    // Mirrors Wolf's on-disk shape: an if (VariableCondition) with one branch plus else,
    // each block body ending in a trailing Blank, plus a nested loop.
    let cmds = vec![
        leaf(101, vec![], 0, &["hello"]),          // Message
        bare(111, vec![0x01, 1_600_000, 1, 2], 0), // if CSelf[0] == 1  (1 group, OR)
        bare(401, vec![1], 0),                     // ChoiceCase (then)
        bare(121, vec![1_100_000, 1, 0, 0], 1),    // SetVariable Self[0] = 1
        bare(170, vec![], 1),                      // loop {
        leaf(101, vec![], 2, &["in loop"]),        // Message
        bare(0, vec![], 2),                        // Blank (loop body trailing)
        bare(498, vec![], 1),                      // LoopEnd
        bare(0, vec![], 1),                        // Blank (then-body trailing)
        bare(420, vec![0], 0),                     // ElseCase (arg0 = 0)
        leaf(106, vec![], 1, &["dbg"]),            // DebugMessage
        bare(0, vec![], 1),                        // Blank (else-body trailing)
        bare(499, vec![], 0),                      // BranchEnd
        bare(0, vec![], 0),                        // Blank (top-level trailing)
    ];

    let text = decompile_commands(&cmds);
    let back = compile_commands(&text).expect("compile failed");

    if back != cmds {
        eprintln!("--- decompiled ---\n{text}");
        for (i, (a, b)) in cmds.iter().zip(back.iter()).enumerate() {
            if a != b {
                eprintln!("differ at {i}:\n  orig: {a:?}\n  back: {b:?}");
            }
        }
        assert_eq!(back.len(), cmds.len(), "length differs");
        panic!("structural round-trip mismatch");
    }
}

#[test]
fn editing_produces_edited_bytes() {
    // Author a small program, decompile it, edit the readable text the way a modder would, then
    // recompile. The round-trip gate only proves identity. This proves the parser builds the byte
    // stream from the text, so changed values and inserted commands take effect, not from any
    // memory of the original.
    let cmds = vec![
        leaf(101, vec![], 0, &["start"]),       // Message "start"
        bare(121, vec![1_100_000, 1, 0, 0], 0), // SetVariable Self[0] = 1
        bare(170, vec![], 0),                   // loop {
        leaf(101, vec![], 1, &["inside"]),      //     Message "inside"
        bare(0, vec![], 1),                     //     (trailing Blank)
        bare(498, vec![], 0),                   // }  LoopEnd
        bare(0, vec![], 0),                     // (top-level trailing Blank)
    ];

    let text = decompile_commands(&cmds);

    // A modder edits the readable text: change a value, add a top-level command, and add a
    // command inside a control-flow block. Source indentation is irrelevant since the parser
    // reconstructs indent from nesting, so the inserted lines need no exact spacing.
    let edited = text
        .replace("SetVariable Self[0] = 1", "SetVariable Self[0] = 42")
        .replace("loop {", "Message \"added\"\nloop {")
        .replace(
            "Message \"inside\"",
            "Message \"inside\"\nDebugMessage \"dbg\"",
        );

    let back = compile_commands(&edited).expect("edited script compiles");

    // 1) changed value landed
    assert!(
        back.iter()
            .any(|c| c.cid == 121 && c.int_args == vec![1_100_000, 42, 0, 0]),
        "value edit not reflected"
    );
    // 2) brand-new top-level command exists at indent 0
    assert!(
        back.iter().any(|c| c.cid == 101
            && c.indent == 0
            && c.str_args
                .first()
                .map_or(false, |s| s.as_bytes() == b"added\0")),
        "inserted top-level command missing"
    );
    // 3) new command inserted inside the loop body got indent 1 (reconstructed from nesting)
    assert!(
        back.iter().any(|c| c.cid == 106 && c.indent == 1),
        "inserted in-block command missing or mis-indented"
    );

    // And the edited program is itself a stable, fully round-tripping file. Decompiling and
    // recompiling it is a no-op. If editing produced something un-recompilable, this fails.
    let again = compile_commands(&decompile_commands(&back)).expect("re-compile edited program");
    assert_eq!(again, back, "edited program is not a round-trip fixpoint");
}

#[test]
fn command_added_at_block_end_takes_the_blank_slot() {
    // A "Blank" is the single trailing empty command Wolf keeps at the end of every block body,
    // hidden in the readable view. The Blank's spot is the end of a block. Adding a command there
    // places it before the auto-regenerated trailing Blank. The modder never sees or manages the
    // Blank. The compiler always emits exactly one per block.
    let src = "loop {\n    Message \"a\"\n    Message \"b\"\n}\n";
    let back = compile_commands(src).expect("compile");

    let shape: Vec<(u32, u8)> = back.iter().map(|c| (c.cid, c.indent)).collect();
    assert_eq!(
        shape,
        vec![
            (170, 0), // loop {
            (101, 1), //     Message "a"
            (101, 1), //     Message "b"   <- added at the end of the block (the Blank's spot)
            (0, 1),   //     Blank         <- exactly one, regenerated AFTER the new command
            (498, 0), // }   LoopEnd
            (0, 0),   // top-level trailing Blank
        ],
        "command added at block end should sit before a single regenerated trailing Blank"
    );
}

#[test]
fn corpus_coverage_report() {
    let path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../../Data/BasicData/CommonEvent.dat");
    let Ok(bytes) = std::fs::read(&path) else {
        eprintln!("corpus not found, skipping");
        return;
    };
    let ce = CommonEventsFile::read(&bytes).unwrap();

    let mut ok = 0usize;
    let total = ce.events.len();
    let mut fail_reason: std::collections::HashMap<String, usize> = Default::default();

    for ev in &ce.events {
        let text = decompile_commands(&ev.commands);
        match compile_commands(&text) {
            Ok(back) if back == ev.commands => ok += 1,
            Ok(back) => {
                let key = back
                    .iter()
                    .zip(&ev.commands)
                    .position(|(a, b)| a != b)
                    .map(|i| format!("mismatch@cid{}", ev.commands[i].cid))
                    .unwrap_or_else(|| format!("len {}!={}", back.len(), ev.commands.len()));
                *fail_reason.entry(key).or_default() += 1;
            }
            Err(e) => {
                let key = format!(
                    "err: {}",
                    e.to_string().chars().take(38).collect::<String>()
                );
                *fail_reason.entry(key).or_default() += 1;
            }
        }
    }

    eprintln!("common-event command round-trip: {ok}/{total} byte-exact");
    if ok != total {
        let mut reasons: Vec<_> = fail_reason.into_iter().collect();
        reasons.sort_by_key(|(_, n)| std::cmp::Reverse(*n));
        for (k, n) in reasons.iter().take(12) {
            eprintln!("  {n:5}  {k}");
        }
    }
    assert_eq!(ok, total, "not all common events recompile byte-exact");
}
