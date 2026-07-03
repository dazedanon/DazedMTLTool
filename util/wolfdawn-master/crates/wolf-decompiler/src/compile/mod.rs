//! The recompiler: parse WolfScript text back into the byte-faithful `RawCommand` stream.
//!
//! This is the inverse of [`crate::wolfscript`]. It reconstructs exactly what the decompiler
//! dropped for readability:
//!   * Marker commands. `branch`/`when`/`else`/`}` become VariableCondition/ChoiceCase/
//!     ElseCase/BranchEnd. `loop`/`}` become StartLoop/LoopEnd. `choose`/`case`/`}` become
//!     Choices/ChoiceCase/CancelCase/BranchEnd.
//!   * Indent bytes, reconstructed from block nesting depth (Wolf's indent equals depth).
//!   * Suppressed `Blank` slots. The editor keeps one trailing empty command at the end of every
//!     block body, re-inserted on compile.
//!
//! Correctness is driven by the round-trip gate `parse(decompile(cmds)) == cmds`. Operands are
//! parsed in their numeric form here (`Self[n]`, `V[n]`, `CSelf[n]`, literal). Name resolution
//! (the reverse glossary/symbol lookup) layers on top.

pub(crate) mod cmd;
mod lex;

use wolf_formats::command::RawCommand;
use wolf_formats::{Error, Result};

use lex::Line;

/// Parse a WolfScript command program (numeric operand forms) into a `RawCommand` stream.
/// Strings are encoded as UTF-8. Use [`compile_commands_enc`] for Shift-JIS files.
pub fn compile_commands(text: &str) -> Result<Vec<RawCommand>> {
    compile_commands_enc(text, true)
}

/// Parse a WolfScript command program, encoding string literals in the file's encoding (`utf8`).
/// The exact inverse of [`crate::wolfscript::decompile_commands_enc`].
pub fn compile_commands_enc(text: &str, utf8: bool) -> Result<Vec<RawCommand>> {
    let lines = lex::lines(text);

    // A leading `@v35` directive marks a Wolf Pro v3.5 program: every command carries a trailing
    // blob, empty unless an `@raw v:` form supplies one. Strip the directive, parse normally, then
    // default every command's blob to empty.
    let v35 = lines.first().map(|l| l.text == "@v35").unwrap_or(false);
    let body = if v35 { &lines[1..] } else { &lines[..] };

    let mut p = Parser {
        lines: body,
        pos: 0,
        utf8,
    };
    let mut out = Vec::new();
    p.block_body(0, &mut out)?;
    if p.pos != p.lines.len() {
        return Err(Error::invalid(format!(
            "trailing content at line {}: {:?}",
            p.lines[p.pos].no, p.lines[p.pos].text
        )));
    }

    if v35 {
        for c in &mut out {
            if c.v35_blob.is_none() {
                c.v35_blob = Some(Vec::new());
            }
        }
    }
    Ok(out)
}

struct Parser<'a> {
    lines: &'a [Line],
    pos: usize,
    utf8: bool,
}

impl<'a> Parser<'a> {
    fn peek(&self) -> Option<&'a Line> {
        self.lines.get(self.pos)
    }

    /// Parse the statements of one block body at `depth`, appending commands plus a trailing
    /// Blank to `out`. Stops at a line that closes or continues the parent block (`}`, `} when`,
    /// `} else`, `} case`, `} cancel`) without consuming it.
    fn block_body(&mut self, depth: u8, out: &mut Vec<RawCommand>) -> Result<()> {
        loop {
            let Some(line) = self.peek() else { break };
            let t = line.text.as_str();
            if t == "}" || t.starts_with("} ") {
                break;
            }
            self.statement(depth, out)?;
        }
        // Wolf keeps one empty trailing command at the end of every block body.
        out.push(blank(depth));
        Ok(())
    }

    fn statement(&mut self, depth: u8, out: &mut Vec<RawCommand>) -> Result<()> {
        let line = self.peek().unwrap();
        let t = line.text.clone();
        let no = line.no;

        // A block opener may carry an inline ` @b:HEX` blob suffix (rare, v3.5 only).
        let (head, opener_blob) = cmd::split_blob_suffix(&t);
        if head == "branch {" {
            self.pos += 1;
            return self.conditional(depth, out, no, false, opener_blob);
        }
        if head == "branch all {" {
            self.pos += 1;
            return self.conditional(depth, out, no, true, opener_blob);
        }
        if head == "loop {" || head.starts_with("loop ") && head.ends_with("times {") {
            return self.loop_block(depth, out);
        }
        if head.starts_with("choose ") && head.ends_with('{') {
            return self.choose_block(depth, out);
        }

        // A leaf command.
        let cmd = cmd::parse_leaf(&t, depth, self.utf8)
            .map_err(|e| Error::invalid(format!("line {no}: {e}")))?;
        self.pos += 1;
        out.push(cmd);
        Ok(())
    }

    /// `branch { } when (cond) { … } else { … }` becomes a VariableCondition/StringCondition
    /// opener plus ChoiceCase/ElseCase markers plus BranchEnd.
    fn conditional(
        &mut self,
        depth: u8,
        out: &mut Vec<RawCommand>,
        open_no: u32,
        is_and: bool,
        blob: Option<Vec<u8>>,
    ) -> Result<()> {
        let mut whens: Vec<(String, Vec<RawCommand>)> = Vec::new();
        let mut else_body: Option<Vec<RawCommand>> = None;

        loop {
            let Some(line) = self.peek() else {
                return Err(Error::invalid(format!(
                    "line {open_no}: unterminated branch"
                )));
            };
            let t = line.text.clone();
            if t == "}" {
                self.pos += 1;
                break;
            } else if let Some(rest) = t
                .strip_prefix("} when (")
                .and_then(|s| s.strip_suffix(") {"))
            {
                self.pos += 1;
                let mut body = Vec::new();
                self.block_body(depth + 1, &mut body)?;
                whens.push((rest.to_string(), body));
            } else if t == "} else {" {
                self.pos += 1;
                let mut body = Vec::new();
                self.block_body(depth + 1, &mut body)?;
                else_body = Some(body);
            } else {
                return Err(Error::invalid(format!(
                    "line {}: unexpected in branch: {t:?}",
                    line.no
                )));
            }
        }

        let opener = cmd::build_condition(
            &whens.iter().map(|(c, _)| c.as_str()).collect::<Vec<_>>(),
            is_and,
            depth,
            blob,
            self.utf8,
        )?;
        out.push(opener);
        for (i, (_, body)) in whens.into_iter().enumerate() {
            out.push(choice_case((i + 1) as u32, depth));
            out.extend(body);
        }
        if let Some(body) = else_body {
            out.push(cmd_with(420, vec![0], depth)); // ElseCase (arg0 = 0)
            out.extend(body);
        }
        out.push(marker(499, depth)); // BranchEnd
        Ok(())
    }

    fn loop_block(&mut self, depth: u8, out: &mut Vec<RawCommand>) -> Result<()> {
        let line = self.peek().unwrap().text.clone();
        self.pos += 1;
        let opener = cmd::build_loop(&line, depth)?;
        out.push(opener);
        let mut body = Vec::new();
        self.block_body(depth + 1, &mut body)?;
        out.extend(body);
        // consume the closing `}`
        self.expect_close()?;
        out.push(marker(498, depth)); // LoopEnd
        Ok(())
    }

    fn choose_block(&mut self, depth: u8, out: &mut Vec<RawCommand>) -> Result<()> {
        let line = self.peek().unwrap().text.clone();
        self.pos += 1;
        let opener = cmd::build_choices(&line, depth, self.utf8)?;
        out.push(opener);

        loop {
            let Some(l) = self.peek() else {
                return Err(Error::invalid("unterminated choose".to_string()));
            };
            let t = l.text.clone();
            if t == "}" {
                self.pos += 1;
                break;
            }
            // `} case <arg0> {`, the special `} case* <arg0> {`, or `} cancel {`.
            let (cid, arg0) = if let Some(a) = t.strip_prefix("} case* ") {
                (402, parse_case_arg(a)?)
            } else if let Some(a) = t.strip_prefix("} case ") {
                (401, parse_case_arg(a)?)
            } else if t == "} cancel {" {
                (421, 0)
            } else {
                return Err(Error::invalid(format!("unexpected in choose: {t:?}")));
            };
            self.pos += 1;
            out.push(cmd_with(cid, vec![arg0], depth));
            let mut body = Vec::new();
            self.block_body(depth + 1, &mut body)?;
            out.extend(body);
        }
        out.push(marker(499, depth)); // BranchEnd
        Ok(())
    }

    fn expect_close(&mut self) -> Result<()> {
        match self.peek() {
            Some(l) if l.text == "}" => {
                self.pos += 1;
                Ok(())
            }
            other => Err(Error::invalid(format!("expected `}}`, got {other:?}"))),
        }
    }
}

fn blank(indent: u8) -> RawCommand {
    RawCommand {
        cid: 0,
        int_args: Vec::new(),
        indent,
        str_args: Vec::new(),
        term: 0,
        move_route: None,
        v35_blob: None,
    }
}

fn marker(cid: u32, indent: u8) -> RawCommand {
    RawCommand {
        cid,
        int_args: Vec::new(),
        indent,
        str_args: Vec::new(),
        term: 0,
        move_route: None,
        v35_blob: None,
    }
}

fn cmd_with(cid: u32, ints: Vec<u32>, indent: u8) -> RawCommand {
    RawCommand {
        cid,
        int_args: ints,
        indent,
        str_args: Vec::new(),
        term: 0,
        move_route: None,
        v35_blob: None,
    }
}

/// Extract the leading case index from `<n> {` or `<n> {  # label`.
fn parse_case_arg(a: &str) -> Result<u32> {
    a.split_whitespace()
        .next()
        .and_then(|s| s.parse().ok())
        .ok_or_else(|| Error::invalid(format!("bad case arg: {a:?}")))
}

fn choice_case(idx: u32, indent: u8) -> RawCommand {
    RawCommand {
        cid: 401,
        int_args: vec![idx],
        indent,
        str_args: Vec::new(),
        term: 0,
        move_route: None,
        v35_blob: None,
    }
}
