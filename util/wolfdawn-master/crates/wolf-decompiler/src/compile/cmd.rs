//! Leaf-command and block-opener reconstruction (numeric operand forms).
//!
//! Inverts the readable rendering back to exact `RawCommand`s. Commands whose pretty form is
//! fully invertible (Message, Comment, SetVariable, SetString, Wait, conditions, loops, choices)
//! are handled here. Lossy-pretty commands (Sound, Picture, Database, and so on) carry a trailing
//! `@raw(...)` annotation so the byte layer stays recoverable. The round-trip gate reports exactly
//! which commands still need it.

use wolf_formats::command::{MoveRoute, RawCommand, RouteCommand};
use wolf_formats::{Error, Reader, Result, WStr};

use crate::text::text_to_wstr;

/// Parse the lossless `@raw <cid> i:<ints> s:<hex,…> t:<term> m:<route-hex|-> v:<v35-hex|->`.
fn parse_raw(line: &str, indent: u8) -> std::result::Result<RawCommand, String> {
    let rest = &line["@raw ".len()..];
    let mut toks = rest.split(' ');
    let cid = toks
        .next()
        .ok_or("@raw: missing cid")?
        .parse::<u32>()
        .map_err(|_| "@raw: bad cid")?;
    let (mut ints, mut strs, mut term, mut route, mut v35) =
        (Vec::new(), Vec::new(), 0u8, None, None);
    for tok in toks {
        if let Some(v) = tok.strip_prefix("i:") {
            if !v.is_empty() {
                ints = v
                    .split(',')
                    .map(|x| {
                        x.parse::<i64>()
                            .map(|n| n as u32)
                            .map_err(|_| "@raw: bad int")
                    })
                    .collect::<std::result::Result<_, _>>()?;
            }
        } else if let Some(v) = tok.strip_prefix("s:") {
            if !v.is_empty() {
                strs = v
                    .split(',')
                    .map(|h| from_hex(h).map(WStr))
                    .collect::<std::result::Result<_, _>>()?;
            }
        } else if let Some(v) = tok.strip_prefix("t:") {
            term = v.parse().map_err(|_| "@raw: bad term")?;
        } else if let Some(v) = tok.strip_prefix("m:") {
            if v != "-" {
                let bytes = from_hex(v)?;
                route = Some(MoveRoute::read(&mut Reader::new(&bytes)).map_err(|e| e.to_string())?);
            }
        } else if let Some(v) = tok.strip_prefix("v:") {
            if v != "-" {
                v35 = Some(from_hex(v)?);
            }
        }
    }
    Ok(RawCommand {
        cid,
        int_args: ints,
        indent,
        str_args: strs,
        term,
        move_route: route,
        v35_blob: v35,
    })
}

/// Parse the lossless Move(201) form: `Move(ints) "strs" @route(t=…, f=…, h=…) { cmds }`.
fn parse_move(line: &str, indent: u8, utf8: bool) -> std::result::Result<RawCommand, String> {
    let (head, rest) = line.split_once(" @route(").ok_or("Move: missing @route")?;
    let (ints, strs) = parse_move_head(head, utf8)?;
    let (params, body) = rest.split_once(") {").ok_or("Move: @route missing `) {`")?;
    let (term, flags, hdr) = parse_route_params(params)?;
    let body = body
        .trim()
        .strip_suffix('}')
        .ok_or("Move: route missing `}`")?;
    let commands = parse_route_cmds(body.trim())?;
    Ok(RawCommand {
        cid: 201,
        int_args: ints,
        indent,
        str_args: strs,
        term,
        move_route: Some(MoveRoute {
            unknown: hdr,
            flags,
            commands,
        }),
        v35_blob: None,
    })
}

fn parse_move_head(head: &str, utf8: bool) -> std::result::Result<(Vec<u32>, Vec<WStr>), String> {
    let rest = head
        .trim()
        .strip_prefix("Move")
        .ok_or("Move: expected `Move`")?
        .trim_start();
    let mut ints = Vec::new();
    let after = if let Some(r) = rest.strip_prefix('(') {
        let close = r.find(')').ok_or("Move: missing `)`")?;
        ints = parse_labeled_args(&r[..close])?;
        r[close + 1..].trim()
    } else {
        rest
    };
    Ok((ints, parse_trailing_strings(after, utf8)?))
}

fn parse_route_params(s: &str) -> std::result::Result<(u8, u8, [u8; 5]), String> {
    let (mut term, mut flags, mut hdr) = (0u8, 0u8, [0u8; 5]);
    for part in s.split(',') {
        let part = part.trim();
        if let Some(v) = part.strip_prefix("t=") {
            term = v.parse().map_err(|_| "Move: bad route t")?;
        } else if let Some(v) = part.strip_prefix("f=") {
            flags = v.parse().map_err(|_| "Move: bad route f")?;
        } else if let Some(v) = part.strip_prefix("h=") {
            let bytes = from_hex(v)?;
            if bytes.len() != 5 {
                return Err(format!(
                    "Move: route header must be 5 bytes, got {}",
                    bytes.len()
                ));
            }
            hdr.copy_from_slice(&bytes);
        }
    }
    Ok((term, flags, hdr))
}

fn parse_route_cmds(body: &str) -> std::result::Result<Vec<RouteCommand>, String> {
    let mut out = Vec::new();
    for part in body.split(';') {
        let part = part.trim();
        if part.is_empty() {
            continue;
        }
        let (name, args) = if let Some(open) = part.find('(') {
            let close = part.find(')').ok_or("route cmd: missing `)`")?;
            let args = part[open + 1..close]
                .split(',')
                .filter(|s| !s.trim().is_empty())
                .map(|s| operand(s.trim()))
                .collect::<std::result::Result<Vec<_>, _>>()?;
            (part[..open].trim(), args)
        } else {
            (part, Vec::new())
        };
        let id = crate::spec::route_id_for_name(name)
            .ok_or_else(|| format!("unknown route command: {name:?}"))? as u8;
        out.push(RouteCommand {
            id,
            args,
            terminator: [1, 0],
        });
    }
    Ok(out)
}

/// Decode an even-length hex string. Errors on odd length or any non-hex digit rather than
/// silently dropping bytes, so a corrupted hand-edited `@raw`, `x"…"`, route, or blob fails loud.
fn from_hex(s: &str) -> std::result::Result<Vec<u8>, String> {
    if s.len() % 2 != 0 {
        return Err(format!("odd-length hex: {s:?}"));
    }
    (0..s.len() / 2)
        .map(|i| {
            u8::from_str_radix(&s[i * 2..i * 2 + 2], 16).map_err(|_| format!("bad hex: {s:?}"))
        })
        .collect()
}

fn cmd(cid: u32, ints: Vec<u32>, indent: u8, strs: Vec<WStr>) -> RawCommand {
    RawCommand {
        cid,
        int_args: ints,
        indent,
        str_args: strs,
        term: 0,
        move_route: None,
        v35_blob: None,
    }
}

/// Parse one leaf command line. `utf8` selects the string encoding (Shift-JIS vs UTF-8).
pub fn parse_leaf(line: &str, indent: u8, utf8: bool) -> std::result::Result<RawCommand, String> {
    if line.starts_with("@raw ") {
        return parse_raw(line, indent);
    }
    if line.contains(" @route(") {
        return parse_move(line, indent, utf8);
    }
    if let Some(rest) = line.strip_prefix("# ") {
        return Ok(cmd(103, vec![], indent, vec![wstr(rest, utf8)?]));
    }
    if line == "#" {
        return Ok(cmd(103, vec![], indent, vec![wstr("", utf8)?]));
    }
    if let Some(rest) = line.strip_prefix("Message ") {
        return Ok(cmd(101, vec![], indent, vec![parse_str(rest, utf8)?]));
    }
    if let Some(rest) = line.strip_prefix("DebugMessage ") {
        return Ok(cmd(106, vec![], indent, vec![parse_str(rest, utf8)?]));
    }
    if let Some(rest) = line.strip_prefix("Wait ") {
        return Ok(cmd(
            180,
            vec![rest.trim().parse().map_err(|_| "bad Wait arg")?],
            indent,
            vec![],
        ));
    }
    if let Some(rest) = line.strip_prefix("SetVariable ") {
        return parse_set_variable(rest, indent);
    }
    if let Some(rest) = line.strip_prefix("SetString ") {
        return parse_set_string(rest, indent, utf8);
    }
    parse_generic(line, indent, utf8)
}

/// Inverse of the labeled fallback `Name(label=val, …) "str" …` (and `Name` or `Name "str"`).
/// Lossless for the common term==0, no-move, no-v35 case.
fn parse_generic(line: &str, indent: u8, utf8: bool) -> std::result::Result<RawCommand, String> {
    use crate::spec;

    // An int-arg list `(...)` only counts if it appears before any string arg. Otherwise a `(`
    // inside a quoted string would be mistaken for an arg list.
    let paren = line.find('(');
    let quote = line.find('"');
    let has_args = match (paren, quote) {
        (Some(p), Some(q)) => p < q,
        (Some(_), None) => true,
        _ => false,
    };
    if let Some(open) = paren.filter(|_| has_args) {
        let name = line[..open].trim();
        // Int-arg lists never contain nested parens, so the first `)` after `(` closes them.
        let close = open + 1 + line[open + 1..].find(')').ok_or("missing `)`")?;
        let cid = spec::cid_for_name(name).ok_or_else(|| format!("unknown command: {name:?}"))?;
        let ints = parse_labeled_args(&line[open + 1..close])?;
        let strs = parse_trailing_strings(line[close + 1..].trim(), utf8)?;
        return Ok(cmd(cid, ints, indent, strs));
    }

    // `Name` or `Name "str" "str"`
    let (name, after) = line.split_once(' ').unwrap_or((line, ""));
    let cid = spec::cid_for_name(name).ok_or_else(|| format!("unrecognized command: {line:?}"))?;
    let strs = parse_trailing_strings(after.trim(), utf8)?;
    Ok(cmd(cid, vec![], indent, strs))
}

fn parse_labeled_args(s: &str) -> std::result::Result<Vec<u32>, String> {
    let s = s.trim();
    if s.is_empty() {
        return Ok(vec![]);
    }
    s.split(", ")
        .map(|part| {
            let val = part.split_once('=').map(|(_, v)| v).unwrap_or(part);
            operand(val.trim())
        })
        .collect()
}

fn parse_trailing_strings(s: &str, utf8: bool) -> std::result::Result<Vec<WStr>, String> {
    parse_quoted_seq(s, utf8)
}

/// Parse a whitespace/comma-separated sequence of string literals. Each is either readable
/// `"text"` (escapes and empty strings) or byte-exact `x"HEX"` (raw bytes, NUL included).
fn parse_quoted_seq(s: &str, utf8: bool) -> std::result::Result<Vec<WStr>, String> {
    let mut out = Vec::new();
    let mut chars = s.chars().peekable();
    loop {
        while matches!(chars.peek(), Some(' ') | Some(',')) {
            chars.next();
        }
        match read_one_literal(&mut chars, s, utf8)? {
            Some(w) => out.push(w),
            None => break,
        }
    }
    Ok(out)
}

/// Read a single string literal at the cursor: `x"HEX"` (raw bytes) or `"text"` (escaped,
/// re-encoded in the file's encoding plus a trailing NUL). Returns `None` at end of input.
fn read_one_literal(
    chars: &mut std::iter::Peekable<std::str::Chars>,
    ctx: &str,
    utf8: bool,
) -> std::result::Result<Option<WStr>, String> {
    match chars.peek().copied() {
        None => return Ok(None),
        // `x"HEX"` byte-exact form.
        Some('x') => {
            let mut look = chars.clone();
            look.next(); // the 'x'
            if look.peek() == Some(&'"') {
                chars.next(); // 'x'
                chars.next(); // '"'
                let mut hex = String::new();
                loop {
                    match chars.next() {
                        Some('"') => break,
                        Some(c) => hex.push(c),
                        None => return Err(format!("unterminated x\"…\" literal in {ctx:?}")),
                    }
                }
                return Ok(Some(WStr(from_hex(&hex)?)));
            }
            return Err(format!("expected string, got 'x' in {ctx:?}"));
        }
        Some('"') => chars.next(),
        Some(c) => return Err(format!("expected string, got {c:?} in {ctx:?}")),
    };
    let mut buf = String::new();
    loop {
        match chars.next() {
            Some('\\') => {
                let e = chars.next().ok_or("dangling escape")?;
                buf.push('\\');
                buf.push(e);
            }
            Some('"') => break,
            Some(c) => buf.push(c),
            None => return Err(format!("unterminated string in {ctx:?}")),
        }
    }
    Ok(Some(wstr(&buf, utf8)?))
}

fn parse_set_variable(rest: &str, indent: u8) -> std::result::Result<RawCommand, String> {
    // <target> <modify> <left> [<binop> <right>]. Drop a trailing `// real` note. Split at the
    // top level so annotated operands like `V[3 "Gold · ゴールド"]` stay intact.
    let rest = rest.split("//").next().unwrap_or(rest).trim();
    let toks = split_top(rest);
    if toks.len() != 3 && toks.len() != 5 {
        return Err(format!("SetVariable arity: {rest:?}"));
    }
    let target = operand(&toks[0])?;
    let modify = modify_nibble(&toks[1])?;
    let left = operand(&toks[2])?;
    let (binop, right) = if toks.len() == 5 {
        (binop_nibble(&toks[3])?, operand(&toks[4])?)
    } else {
        (0, 0)
    };
    let arg3 = (modify << 8) | (binop << 12);
    Ok(cmd(121, vec![target, left, right, arg3], indent, vec![]))
}

fn parse_set_string(rest: &str, indent: u8, utf8: bool) -> std::result::Result<RawCommand, String> {
    // <target> = "text"
    let (target, val) = rest.split_once(" = ").ok_or("SetString missing `=`")?;
    let target = operand(target.trim())?;
    Ok(cmd(
        122,
        vec![target, 0],
        indent,
        vec![parse_str(val.trim(), utf8)?],
    ))
}

/// StringCondition lhs flag. The rhs is an operand (string-var vs string-var) from the rhs
/// section rather than a literal in `str_args`. Mirrors the renderer's `STRCOND_OPERAND_FLAG`.
const STRCOND_OPERAND_FLAG: u32 = 0x0100_0000;

/// Strip a trailing ` @b:HEX` blob suffix carried by v3.5 block openers with a non-empty
/// per-command blob, returning the cleaned line and the decoded blob.
pub fn split_blob_suffix(line: &str) -> (&str, Option<Vec<u8>>) {
    if let Some(idx) = line.rfind(" @b:") {
        let h = &line[idx + 4..];
        if let Ok(bytes) = from_hex(h) {
            if !bytes.is_empty() {
                return (&line[..idx], Some(bytes));
            }
        }
    }
    (line, None)
}

/// Split a StringCondition group on its comparison operator into `(left, type, right)`. Types:
/// `eq`=0, `ne`=1, `contains`=2, `!contains`=3, `strcmp<N>`=N. Picks the earliest operator so a
/// token inside a right-hand string literal, such as `A eq "x contains y"`, cannot hijack the
/// split.
fn split_strcmp(group: &str) -> Option<(&str, u32, &str)> {
    let mut best: Option<(usize, usize, u32)> = None; // (pos, token_len, type)
    for (tok, ty) in [
        (" eq ", 0u32),
        (" ne ", 1),
        (" contains ", 2),
        (" !contains ", 3),
    ] {
        if let Some(pos) = group.find(tok) {
            if best.map_or(true, |(bp, _, _)| pos < bp) {
                best = Some((pos, tok.len(), ty));
            }
        }
    }
    if let Some((pos, len, ty)) = best {
        return Some((&group[..pos], ty, &group[pos + len..]));
    }
    // strcmp<N> fallback for unknown comparison types.
    let pos = group.find(" strcmp")?;
    let after = &group[pos + " strcmp".len()..];
    let sp = after.find(' ')?;
    let ty = after[..sp].parse::<u32>().ok()?;
    Some((&group[..pos], ty, &after[sp + 1..]))
}

/// Build a VariableCondition (111) or StringCondition (112) from the readable `when` conditions.
/// A string comparison operator (`eq`, `ne`, `contains`, `!contains`, `strcmp<N>`) selects 112.
/// Its layout is `[header][lhs×n][rhs×k]` where each lhs packs the operand (low 24 bits), the
/// variable-right flag (bit 24), and the comparison type (high nibble).
pub fn build_condition(
    conds: &[&str],
    is_and: bool,
    indent: u8,
    blob: Option<Vec<u8>>,
    utf8: bool,
) -> Result<RawCommand> {
    // AND mode renders as a single `when` joined by ` && `. OR mode is one `when` per group.
    let groups: Vec<&str> = if is_and {
        conds
            .first()
            .map(|c| c.split(" && ").collect())
            .unwrap_or_default()
    } else {
        conds.to_vec()
    };
    let n = groups.len() as u32;
    let header = n | if is_and { 0x10 } else { 0 };

    let is_string = groups.iter().any(|g| split_strcmp(g).is_some());
    let mut c = if is_string {
        let mut lhs = Vec::new();
        let mut rhs = Vec::new();
        let mut strs: Vec<WStr> = vec![WStr(vec![0]); 4]; // group-indexed literal slots
        for (g, group) in groups.iter().enumerate() {
            let (l, ty, r) = split_strcmp(group)
                .ok_or_else(|| Error::invalid(format!("bad string condition: {group:?}")))?;
            let l_op = operand(l.trim()).map_err(Error::invalid)?;
            let cmp_bits = ty << 28; // comparison type in the high nibble
            let r = r.trim();
            if r.starts_with('"') || r.starts_with("x\"") {
                lhs.push(l_op | cmp_bits);
                // The engine stores exactly 4 group-indexed literal slots. Guard the index so a
                // malformed condition with more than 4 string groups errors instead of panicking.
                if g >= strs.len() {
                    return Err(Error::invalid(format!(
                        "string condition has too many string groups ({})",
                        groups.len()
                    )));
                }
                strs[g] = parse_str(r, utf8).map_err(Error::invalid)?;
            } else {
                lhs.push(l_op | STRCOND_OPERAND_FLAG | cmp_bits);
                rhs.push(operand(r).map_err(Error::invalid)?);
            }
        }
        let mut ints = vec![header];
        ints.extend(lhs);
        ints.extend(rhs);
        cmd(112, ints, indent, strs)
    } else {
        let mut args = vec![header];
        for g in groups {
            let (left, right, op) = parse_compare(g).map_err(Error::invalid)?;
            args.push(left);
            args.push(right);
            args.push(op);
        }
        cmd(111, args, indent, vec![])
    };
    c.v35_blob = blob;
    Ok(c)
}

pub fn build_loop(line: &str, indent: u8) -> Result<RawCommand> {
    let (line, blob) = split_blob_suffix(line);
    let mut c = if line == "loop {" {
        cmd(170, vec![], indent, vec![])
    } else if let Some(inner) = line
        .strip_prefix("loop ")
        .and_then(|s| s.strip_suffix(" times {"))
    {
        let n = operand(inner.trim()).map_err(Error::invalid)?;
        cmd(179, vec![n], indent, vec![])
    } else {
        return Err(Error::invalid(format!("bad loop opener: {line:?}")));
    };
    c.v35_blob = blob;
    Ok(c)
}

pub fn build_choices(line: &str, indent: u8, utf8: bool) -> Result<RawCommand> {
    // choose <arg0> ["a", "b"] {
    let (line, blob) = split_blob_suffix(line);
    let rest = line
        .strip_prefix("choose ")
        .and_then(|s| s.strip_suffix(" {"))
        .ok_or_else(|| Error::invalid(format!("bad choose opener: {line:?}")))?;
    let (arg0_s, opts) = rest
        .split_once(" [")
        .ok_or_else(|| Error::invalid(format!("bad choose opener: {line:?}")))?;
    let arg0 = arg0_s
        .trim()
        .parse::<u32>()
        .map_err(|_| Error::invalid(format!("bad choose arg0: {arg0_s:?}")))?;
    let inner = opts
        .strip_suffix(']')
        .ok_or_else(|| Error::invalid(format!("bad choose options: {opts:?}")))?;
    let strs = parse_str_list(inner, utf8).map_err(Error::invalid)?;
    let mut c = cmd(102, vec![arg0], indent, strs);
    c.v35_blob = blob;
    Ok(c)
}

// --- operand / operator parsing -------------------------------------------------------

fn operand(s: &str) -> std::result::Result<u32, String> {
    let s = s.trim();
    // `Self*[n]` must be tried before `Self[n]` because of the prefix overlap.
    if let Some(n) = bracketed(s, "Self*") {
        return Ok(1_000_000 + n);
    }
    if let Some(n) = bracketed(s, "Self") {
        return Ok(1_100_000 + n);
    }
    if let Some(n) = bracketed(s, "CSelf") {
        return Ok(1_600_000 + n);
    }
    if let Some(n) = bracketed(s, "V") {
        return Ok(2_000_000 + n);
    }
    if let Some(n) = bracketed(s, "S") {
        return Ok(3_000_000 + n);
    }
    if let Some(n) = bracketed(s, "Sys") {
        return Ok(9_000_000 + n);
    }
    if let Some(n) = bracketed(s, "Rand") {
        return Ok(8_000_000 + n);
    }
    // On-map character data: `Chara[m].Field` (9.1M) or `Chara2[m].Field` (9.18M).
    if let Some(v) = parse_chara(s, "Chara2", 9_180_000) {
        return Ok(v);
    }
    if let Some(v) = parse_chara(s, "Chara", 9_100_000) {
        return Ok(v);
    }
    // This-event intrinsic data: `ThisEv.Field` or `ThisEv[k]`.
    if let Some(v) = parse_this_event(s) {
        return Ok(v);
    }
    // Bare literal, optionally followed by an edit-form ` "label"` annotation. The leading
    // numeric token is the authority.
    let head = s.split_once(" \"").map(|(h, _)| h).unwrap_or(s);
    head.trim()
        .parse::<i64>()
        .map(|v| v as u32)
        .map_err(|_| format!("bad operand: {s:?}"))
}

/// Split a line on whitespace at the top level only. Whitespace inside `[]`/`()` brackets or
/// `"…"` quotes is kept, so an annotated operand like `V[3 "Gold · ゴールド"]` stays one token.
pub(crate) fn split_top(s: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut depth = 0i32;
    let mut in_str = false;
    for ch in s.chars() {
        match ch {
            '"' => {
                in_str = !in_str;
                cur.push(ch);
            }
            '[' | '(' if !in_str => {
                depth += 1;
                cur.push(ch);
            }
            ']' | ')' if !in_str => {
                depth -= 1;
                cur.push(ch);
            }
            c if c.is_whitespace() && !in_str && depth == 0 => {
                if !cur.is_empty() {
                    out.push(std::mem::take(&mut cur));
                }
            }
            c => cur.push(c),
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

/// Parse a character-data reference `prefix[member].Field` back to its operand id.
fn parse_chara(s: &str, prefix: &str, base: u32) -> Option<u32> {
    let rest = s.strip_prefix(prefix)?.strip_prefix('[')?;
    let (member_s, tail) = rest.split_once(']')?;
    let member: u32 = member_s.parse().ok()?;
    let field = tail.strip_prefix('.')?;
    let f = crate::wolfscript::ops::chara_field_index(field)
        .or_else(|| field.strip_prefix('f').and_then(|d| d.parse().ok()))?;
    Some(base + member * 10 + f)
}

/// Parse a this-event reference `ThisEv.Field` or `ThisEv[k]` back to its operand id.
fn parse_this_event(s: &str) -> Option<u32> {
    let rest = s.strip_prefix("ThisEv")?;
    if let Some(field) = rest.strip_prefix('.') {
        return crate::wolfscript::ops::chara_field_index(field).map(|f| 1_000_000 + f);
    }
    let inner = rest.strip_prefix('[')?.strip_suffix(']')?;
    inner.parse::<u32>().ok().map(|k| 1_000_000 + k)
}

fn bracketed(s: &str, sigil: &str) -> Option<u32> {
    let inner = s
        .strip_prefix(sigil)?
        .strip_prefix('[')?
        .strip_suffix(']')?;
    // The edit form anchors on the index and may carry a ` "label"` annotation inside the
    // brackets, as in `V[3 "Gold · ゴールド"]`. Take the leading numeric token, ignore the rest.
    let head = inner.split_once(' ').map(|(h, _)| h).unwrap_or(inner);
    head.trim().parse().ok()
}

fn parse_compare(s: &str) -> std::result::Result<(u32, u32, u32), String> {
    // Longest symbols first so `<=` and `>=` win over `<` and `>`. Each symbol can carry a
    // `~<flags>` high-nibble suffix, the per-term flag, so `==~1` becomes op 0x12.
    for (sym, code) in [
        ("<=", 0u32),
        (">=", 1),
        ("==", 2),
        ("!=", 3),
        ("<", 4),
        (">", 5),
        ("&", 6),
    ] {
        // Flagged form: ` sym~<flags> `.
        if let Some((l, rest)) = s.split_once(&format!(" {sym}~")) {
            if let Some((flags_s, r)) = rest.split_once(' ') {
                if let Ok(flags) = flags_s.parse::<u32>() {
                    return Ok((operand(l.trim())?, operand(r.trim())?, code | (flags << 4)));
                }
            }
        }
        if let Some((l, r)) = s.split_once(&format!(" {sym} ")) {
            return Ok((operand(l.trim())?, operand(r.trim())?, code));
        }
    }
    // Unknown compare op rendered as ` cmp<N> ` (reversible for any byte value).
    if let Some((l, rest)) = s.split_once(" cmp") {
        if let Some((num, r)) = rest.split_once(' ') {
            if let Ok(op) = num.parse::<u32>() {
                return Ok((operand(l.trim())?, operand(r.trim())?, op));
            }
        }
    }
    Err(format!("bad condition: {s:?}"))
}

fn modify_nibble(s: &str) -> std::result::Result<u32, String> {
    Ok(match s {
        "=" => 0,
        "+=" => 1,
        "-=" => 2,
        "*=" => 3,
        "/=" => 4,
        "%=" => 5,
        _ => return Err(format!("bad modify op: {s:?}")),
    })
}

fn binop_nibble(s: &str) -> std::result::Result<u32, String> {
    Ok(match s {
        "+" => 0,
        "-" => 1,
        "*" => 2,
        "%" => 3,
        "~" => 4,
        "&" => 6,
        "|" => 7,
        "^" => 8,
        "<<" => 9,
        _ => return Err(format!("bad binop: {s:?}")),
    })
}

// --- string parsing -------------------------------------------------------------------

/// Encode (already-quoted-stripped) literal text into a Wolf string in the file's encoding.
fn wstr(s: &str, utf8: bool) -> std::result::Result<WStr, String> {
    text_to_wstr(&unescape(s), utf8)
}

/// Parse exactly one string literal (`"text"` or `x"HEX"`).
fn parse_str(s: &str, utf8: bool) -> std::result::Result<WStr, String> {
    let s = s.trim();
    let mut chars = s.chars().peekable();
    let w = read_one_literal(&mut chars, s, utf8)?
        .ok_or_else(|| format!("expected string literal: {s:?}"))?;
    if chars.next().is_some() {
        return Err(format!("trailing content after string literal: {s:?}"));
    }
    Ok(w)
}

fn parse_str_list(s: &str, utf8: bool) -> std::result::Result<Vec<WStr>, String> {
    parse_quoted_seq(s, utf8)
}

fn unescape(s: &str) -> String {
    let mut out = String::new();
    let mut chars = s.chars();
    while let Some(c) = chars.next() {
        if c != '\\' {
            out.push(c);
            continue;
        }
        match chars.next() {
            Some('n') => out.push('\n'),
            Some('r') => out.push('\r'),
            Some('t') => out.push('\t'),
            Some('"') => out.push('"'),
            Some('\\') => out.push('\\'),
            Some(other) => {
                out.push('\\');
                out.push(other);
            }
            None => out.push('\\'),
        }
    }
    out
}
