//! WolfScript emitter. Renders a command program into readable, indented pseudo-code.
//!
//! Every command renders bespoke. Keystone commands (conditions, choices, SetVariable, calls, and
//! so on) get purpose-built forms decoded from their argument packing. All others use the labeled
//! argument schema in [`crate::spec`]. Nothing falls back to an unlabeled int dump.
//! Conditional/choice branches are reconstructed from the flat marker commands via a small block
//! stack, so `case`/`when` labels carry their real option/condition text. Labels are mapped
//! positionally, which is robust to the engine's non-sequential case indices.

pub(crate) mod ops;
pub use ops::operand;
use ops::*;

use std::cell::Cell;
use std::collections::HashMap;

use wolf_formats::command::RawCommand;
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::map::Map;

use crate::spec;
use crate::symbols::SymbolTable;
use crate::text::{decode_wstr, quote_wstr, wstr_to_literal};

const INDENT_UNIT: &str = "    ";

/// Common-event call-by-ID base. A stored target of `500000 + id` calls common event `id`.
const CALL_BY_ID_BASE: u32 = 500_000;

/// StringCondition lhs flag. When set, the right-hand side is an operand from the rhs section
/// (string-var vs string-var) rather than the literal in `str_args`.
const STRCOND_OPERAND_FLAG: u32 = 0x0100_0000;

/// Tracks the enclosing block so `case`/`when` markers resolve to a real, positional label.
enum Block {
    Choices { options: Vec<String>, next: usize },
    Conditional { conds: Vec<String>, next: usize },
    Other,
}

pub struct Renderer<'a> {
    utf8: bool,
    symbols: &'a SymbolTable,
    /// The common event currently being rendered, so `CSelf[n]` resolves to its own
    /// self-variable names. `None` for maps.
    current_ce: Cell<Option<u32>>,
    /// Display mode. Render the prettiest (bespoke, name-resolved) form for reading, skipping the
    /// recompile self-check that otherwise falls back to `@raw`. The numeric, round-trip-faithful
    /// path (`decompile_commands`) leaves this off.
    display: bool,
    /// Annotate mode: the unified read-plus-edit surface. Runs with `display=false` so the
    /// per-leaf `recompilable()` self-check still gates every line, but injects an index-anchored
    /// bilingual label inside the brackets, as in `V[3 "Gold · ゴールド"]`. The index stays the
    /// round-trip authority and the recompiler strips the quoted label. Because the self-check
    /// runs, any label the parser cannot strip back to the identical command auto-falls to the
    /// numeric/`@raw` form, so the file is always byte-exact and the names only affect prettiness.
    annotate: bool,
}

impl<'a> Renderer<'a> {
    pub fn with_symbols(utf8: bool, symbols: &'a SymbolTable) -> Self {
        Renderer {
            utf8,
            symbols,
            current_ce: Cell::new(None),
            display: false,
            annotate: false,
        }
    }

    /// Enable display mode: readable output, no `@raw` fallback.
    pub fn for_display(mut self) -> Self {
        self.display = true;
        self
    }

    /// Enable annotate mode: readable and recompilable, with index-anchored bilingual labels.
    pub fn for_edit(mut self) -> Self {
        self.annotate = true;
        self
    }

    /// `English · 日本語` when the engine glossary translates the name, else the raw name.
    fn bilingual(&self, jp: &str) -> String {
        let en = self.symbols.tr(jp);
        if en != jp {
            format!("{en} · {jp}")
        } else {
            jp.to_string()
        }
    }

    /// Decode a Wolf operand id into a readable, name-resolved reference. See [`ops::operand`] for
    /// the structural, symbol-free mirror that the recompiler's parser inverts.
    fn op(&self, v: u32) -> String {
        match v {
            0..=999_999 => v.to_string(),
            // This-event intrinsic data: position, graphic, or direction of the running event.
            1_000_000..=1_099_999 => this_event_ref(v),
            // Map-event self vars are unnamed by the engine. Kept numeric by design.
            1_100_000..=1_199_999 => format!("Self[{}]", v - 1_100_000),
            1_600_000..=1_699_999 => {
                let n = v - 1_600_000;
                match self.cself_name(n) {
                    Some(name) if self.annotate => {
                        format!("CSelf[{n} \"{}\"]", escape(&self.bilingual(&name)))
                    }
                    Some(name) => format!("CSelf[{}]", name_tok(self.symbols.tr(&name))),
                    None => format!("CSelf[{n}]"),
                }
            }
            1_200_000..=1_599_999 | 1_700_000..=1_999_999 => format!("Self*[{}]", v - 1_000_000),
            2_000_000..=2_999_999 => {
                self.global_ref(&self.symbols.globals.normal, v - 2_000_000, "V")
            }
            3_000_000..=3_999_999 => {
                self.global_ref(&self.symbols.globals.string, v - 3_000_000, "S")
            }
            // Random 0..N reference. The engine computes `rand % (N+1)`, N = v-8_000_000.
            8_000_000..=8_999_999 => format!("Rand[{}]", v - 8_000_000),
            9_000_000..=9_099_999 => {
                self.global_ref(&self.symbols.globals.system, v - 9_000_000, "Sys")
            }
            // On-map character data: party member 9.1M, current character 9.18M.
            9_100_000..=9_179_999 => chara_ref("Chara", 9_100_000, v),
            9_180_000..=9_189_999 => chara_ref("Chara2", 9_180_000, v),
            9_190_000..=9_999_999 => {
                self.global_ref(&self.symbols.globals.system, v - 9_000_000, "Sys")
            }
            _ => lit(v),
        }
    }

    /// Render a global reference. Annotate mode anchors on the index and adds a bilingual label
    /// (`V[3 "Gold · ゴールド"]`). Display mode shows the translated name (`V["Gold"]`). Numeric
    /// mode is the bare index (`V[3]`).
    fn global_ref(&self, map: &HashMap<u32, String>, n: u32, sigil: &str) -> String {
        match map.get(&n) {
            Some(name) if self.annotate => {
                format!("{sigil}[{n} \"{}\"]", escape(&self.bilingual(name)))
            }
            Some(name) => format!("{sigil}[{}]", name_tok(self.symbols.tr(name))),
            None => format!("{sigil}[{n}]"),
        }
    }

    fn cself_name(&self, n: u32) -> Option<String> {
        let ce = self.current_ce.get()?;
        self.symbols.common_event(ce)?.self_vars.get(&n).cloned()
    }

    fn decode_str(&self, w: &wolf_formats::WStr) -> String {
        decode_wstr(w, self.utf8)
    }

    fn quote(&self, w: &wolf_formats::WStr) -> String {
        // Display favours readability, where a lossy `from_utf8_lossy` is fine. The numeric/edit
        // path must round-trip, so it uses the byte-exact literal (readable text or `x"HEX"`).
        if self.display {
            quote_wstr(w, self.utf8)
        } else {
            wstr_to_literal(w, self.utf8)
        }
    }

    fn str_arg(&self, cmd: &RawCommand, idx: usize) -> String {
        cmd.str_args
            .get(idx)
            .map(|s| self.quote(s))
            .unwrap_or_else(|| "\"\"".to_string())
    }

    fn is_blank_slot(cmd: &RawCommand) -> bool {
        cmd.cid == 0
            && cmd.int_args.is_empty()
            && cmd.str_args.is_empty()
            && cmd.move_route.is_none()
    }

    /// Render a flat command list, reconstructing block labels via a stack.
    pub fn commands(&self, cmds: &[RawCommand]) -> String {
        // Wolf Pro v3.5: every command carries a trailing blob, almost always empty. When
        // present, the recompiler re-adds an empty blob to each command by default, so a command
        // can still render pretty when its own blob is empty. A non-empty blob forces the lossless
        // `@raw` form.
        let v35 = cmds.iter().any(|c| c.v35_blob.is_some());
        let mut out = String::new();
        let mut stack: Vec<Block> = Vec::new();

        for cmd in cmds {
            if Self::is_blank_slot(cmd) {
                continue;
            }
            let blob_empty = cmd.v35_blob.as_deref().map_or(true, |b| b.is_empty()) || self.display;
            // Case markers consume the next positional label from the enclosing block.
            let line = match cmd.cid {
                401 if blob_empty => case_marker(cmd, &mut stack),
                402 if blob_empty => {
                    format!("}} case* {} {{", cmd.int_args.first().copied().unwrap_or(0))
                }
                421 if blob_empty => "} cancel {".to_string(),
                // Display mode: render the prettiest form for reading, no recompile gate.
                _ if self.display => self.line(cmd),
                _ => {
                    // Self-check chain: pretty, then labeled, then lossless @raw, picking the
                    // first form that round-trips exactly.
                    let pretty = self.line(cmd);
                    if is_block_opener(cmd.cid) {
                        // Openers are reconstructed structurally. A rare non-empty blob is carried
                        // inline as a ` @b:HEX` suffix the parser strips and re-attaches.
                        match cmd.v35_blob.as_deref() {
                            Some(b) if !b.is_empty() => format!("{pretty} @b:{}", hex(b)),
                            _ => pretty,
                        }
                    } else if (is_structural(cmd.cid) && blob_empty)
                        || self.recompilable(cmd, &pretty, v35)
                    {
                        pretty
                    } else {
                        let labeled = self.labeled(cmd);
                        if self.recompilable(cmd, &labeled, v35) {
                            labeled
                        } else {
                            raw_form(cmd)
                        }
                    }
                }
            };
            for _ in 0..cmd.indent as usize {
                out.push_str(INDENT_UNIT);
            }
            out.push_str(&line);
            out.push('\n');

            match cmd.cid {
                102 => stack.push(Block::Choices {
                    options: self.choice_options(cmd),
                    next: 0,
                }),
                111 | 112 => stack.push(Block::Conditional {
                    conds: self.branch_conditions(cmd),
                    next: 0,
                }),
                170 | 179 => stack.push(Block::Other),
                498 | 499 => {
                    stack.pop();
                }
                _ => {}
            }
        }
        out
    }

    /// True if the leaf line parses back to exactly this command (a lossless display form). Under
    /// v3.5 the recompiler re-adds an empty trailing blob to each command, so a pretty form is
    /// lossless exactly when the command's own blob is empty.
    fn recompilable(&self, cmd: &RawCommand, line: &str, v35: bool) -> bool {
        match crate::compile::cmd::parse_leaf(line, cmd.indent, self.utf8) {
            Ok(mut p) => {
                if v35 && p.v35_blob.is_none() {
                    p.v35_blob = Some(Vec::new());
                }
                &p == cmd
            }
            Err(_) => false,
        }
    }

    fn line(&self, cmd: &RawCommand) -> String {
        let a = &cmd.int_args;
        match cmd.cid {
            101 => format!("Message {}", self.str_arg(cmd, 0)),
            103 => format!(
                "# {}",
                escape_inline(&self.decode_str(&cmd.str_args.first().cloned().unwrap_or_default()))
            ),
            106 => format!("DebugMessage {}", self.str_arg(cmd, 0)),
            121 => self.set_variable(cmd),
            122 => self.set_string(cmd),
            102 => format!(
                "choose {} [{}] {{",
                a.first().copied().unwrap_or(0),
                self.join_choice_options(cmd)
            ),
            111 | 112 => {
                if a.first().copied().unwrap_or(0) & 0x10 != 0 {
                    "branch all {".to_string() // AND, all conditions must hold
                } else {
                    "branch {".to_string() // OR, first match
                }
            }
            420 => "} else {".to_string(),
            498 | 499 => "}".to_string(),
            170 => "loop {".to_string(),
            // StartLoop2 (176) is not a block opener. It has no matching LoopEnd in data.
            179 => format!(
                "loop {} times {{",
                a.first().map(|&v| self.op(v)).unwrap_or_default()
            ),
            210 | 211 => self.call_common_event(cmd),
            300 => self.call_common_event_by_name(cmd),
            201 => self.move_command(cmd),
            140 => self.sound(cmd),
            250 => self.database(cmd),
            151 => self.change_color(cmd),
            130 => self.teleport(cmd),
            180 => format!("Wait {}", a.first().copied().unwrap_or(0)),
            _ => self.labeled(cmd),
        }
    }

    // --- keystone renderers ------------------------------------------------

    fn choice_options(&self, cmd: &RawCommand) -> Vec<String> {
        cmd.str_args.iter().map(|s| self.decode_str(s)).collect()
    }

    fn join_choice_options(&self, cmd: &RawCommand) -> String {
        cmd.str_args
            .iter()
            .map(|s| self.quote(s))
            .collect::<Vec<_>>()
            .join(", ")
    }

    /// Decode a VariableCondition/StringCondition into per-branch condition strings.
    fn branch_conditions(&self, cmd: &RawCommand) -> Vec<String> {
        let a = &cmd.int_args;
        let Some(&header) = a.first() else {
            return Vec::new();
        };
        let n = (header & 0x0F) as usize;
        let is_and = header & 0x10 != 0;

        let groups: Vec<String> = if cmd.cid == 112 {
            // StringCondition layout: `[header][lhs×n][rhs×k]`. Each lhs word packs the left
            // string operand in the low 24 bits, the right-is-variable flag in bit 24
            // (`0x01000000`), and the comparison type in the high nibble (bits 28-31): 0=eq,
            // 1=ne, 2=contains, 3=!contains. A variable right reads from the rhs section. A
            // literal right reads `str_args[g]`. `k` is the count of variable-right conditions.
            let mut rhs_ptr = 1 + n;
            (0..n)
                .map(|g| {
                    let raw = a.get(1 + g).copied().unwrap_or(0);
                    let operand = raw & 0x00FF_FFFF;
                    let cmp = strcmp_op_str((raw >> 28) & 0xF);
                    if raw & STRCOND_OPERAND_FLAG != 0 {
                        let rhs = a.get(rhs_ptr).copied().unwrap_or(0);
                        rhs_ptr += 1;
                        format!("{} {cmp} {}", self.op(operand), self.op(rhs))
                    } else {
                        format!("{} {cmp} {}", self.op(operand), self.str_arg(cmd, g))
                    }
                })
                .collect()
        } else {
            (0..n)
                .map(|g| {
                    let base = 1 + g * 3;
                    let left = a.get(base).map(|&v| self.op(v)).unwrap_or_default();
                    let right = a.get(base + 1).map(|&v| self.op(v)).unwrap_or_default();
                    let op = a.get(base + 2).copied().unwrap_or(0);
                    format!("{left} {} {right}", compare_op_str(op))
                })
                .collect()
        };

        if is_and {
            vec![groups.join(" && ")]
        } else {
            groups
        }
    }

    fn set_variable(&self, cmd: &RawCommand) -> String {
        let a = &cmd.int_args;
        if a.len() < 4 {
            return self.labeled(cmd);
        }
        let target = self.op(a[0]);
        let left = self.op(a[1]);
        let right = a[2];
        let modify = modify_op(a[3]);
        let binop_nibble = (a[3] >> 12) & 0x0F;
        let real = a[3] & 0x04 != 0;

        let mut s = if right == 0 && binop_nibble == 0 {
            format!("SetVariable {target} {modify} {left}")
        } else {
            format!(
                "SetVariable {target} {modify} {left} {} {}",
                binary_op(a[3]),
                self.op(right)
            )
        };
        if real {
            s.push_str("  // real");
        }
        s
    }

    fn set_string(&self, cmd: &RawCommand) -> String {
        let target = cmd
            .int_args
            .first()
            .map(|&v| self.op(v))
            .unwrap_or_else(|| "S[?]".to_string());
        format!("SetString {target} = {}", self.str_arg(cmd, 0))
    }

    fn call_common_event(&self, cmd: &RawCommand) -> String {
        let a = &cmd.int_args;
        let target = a.first().copied().unwrap_or(0);
        let count = a.get(1).map(|&v| (v & 0xFF) as usize).unwrap_or(0);

        // Operand-referenced target: call the event whose id is in a variable.
        if target >= 1_000_000 {
            let passed = self.passed_args(a, 2, count);
            let head = format!("call [{}]", self.op(target));
            return if passed.is_empty() {
                head
            } else {
                format!("{head}({passed})")
            };
        }

        let id = if target >= CALL_BY_ID_BASE {
            target - CALL_BY_ID_BASE
        } else {
            target
        };
        let info = self.symbols.common_event(id);
        let glossed = info.and_then(|i| self.symbols.glossary.get(&i.name));

        // Function name: the English engine glossary for stock events, else JP name, else #id.
        let head = match (info, glossed) {
            (_, Some(g)) => g.en_name.clone(),
            (Some(i), None) => format!("call \"{}\"", i.name),
            (None, _) => format!("call #{id}"),
        };

        // Passed args, labeled with the callee's input names. English glossary wins over JP inputs.
        let parts =
            self.render_passed_args(a, count, glossed.map(|g| &g.args), info.map(|i| &i.inputs));
        if parts.is_empty() {
            head
        } else {
            format!("{head}({})", parts.join(", "))
        }
    }

    /// Render call arguments, labeling each with its parameter name and resolving DB-entry ids
    /// (`ItemId=17` becomes `ItemId="ポーション"`) when the English param name is typed.
    fn render_passed_args(
        &self,
        a: &[u32],
        count: usize,
        en_args: Option<&Vec<String>>,
        jp_args: Option<&Vec<String>>,
    ) -> Vec<String> {
        let mut parts = Vec::new();
        for k in 0..count {
            let Some(&v) = a.get(2 + k) else { break };
            let en = en_args.and_then(|x| x.get(k)).map(String::as_str);
            let jp = jp_args.and_then(|x| x.get(k)).map(String::as_str);
            // English param name from the glossary, else the translated JP input name.
            let label: Option<String> = en
                .map(str::to_string)
                .or_else(|| jp.map(|j| self.symbols.tr(j).to_string()));
            let val = self.resolve_arg(en, v);
            match label.as_deref() {
                Some(n) if !n.is_empty() => parts.push(format!("{n}={val}")),
                _ => parts.push(val),
            }
        }
        parts
    }

    /// Render an operand. If it is a literal and the param name names a DB type, resolve it to the
    /// entry name. This stays non-lossy since the recompiler accepts either name or id.
    fn resolve_arg(&self, en_name: Option<&str>, v: u32) -> String {
        if v < 1_000_000 {
            if let Some(type_name) = en_name.and_then(arg_db_type) {
                if let Some(name) = self.symbols.db_entry_name(type_name, v) {
                    return format!("\"{}\"", escape(name));
                }
            }
        }
        self.op(v)
    }

    fn call_common_event_by_name(&self, cmd: &RawCommand) -> String {
        let a = &cmd.int_args;
        let jp = self.decode_str(&cmd.str_args.first().cloned().unwrap_or_default());
        let glossed = self.symbols.glossary.get(&jp);
        let info = self.symbols.common_event_by_name(&jp);

        let head = match glossed {
            Some(g) => g.en_name.clone(),
            None => format!("call \"{jp}\""),
        };

        let count = a.get(1).map(|&v| (v & 0xFF) as usize).unwrap_or(0);
        let parts =
            self.render_passed_args(a, count, glossed.map(|g| &g.args), info.map(|i| &i.inputs));
        if parts.is_empty() {
            head
        } else {
            format!("{head}({})", parts.join(", "))
        }
    }

    fn passed_args(&self, a: &[u32], start: usize, count: usize) -> String {
        (0..count)
            .filter_map(|i| a.get(start + i))
            .map(|&v| self.op(v))
            .collect::<Vec<_>>()
            .join(", ")
    }

    /// Render a Database (DB操作) command as an assignment, using the type/data/field names
    /// embedded in the command's string args, falling back to DB lookups or ids. `flagWord` bit0
    /// selects direction: 0 reads DB into a var, 1 writes a value into the DB.
    fn database(&self, cmd: &RawCommand) -> String {
        let a = &cmd.int_args;
        if a.len() < 5 {
            return self.labeled(cmd);
        }
        let (type_raw, data_raw, field_raw, flag, value) = (a[0], a[1], a[2], a[3], a[4]);

        // JP names from the embedded string args drive the DB lookups. Display is then translated
        // via the engine-text glossary.
        let type_jp = self.str_name_jp(cmd, 1);
        let data_jp = self.str_name_jp(cmd, 2);
        let field_jp = self.str_name_jp(cmd, 3);

        let kind = type_jp
            .as_deref()
            .and_then(|t| self.symbols.db_kind_of_type(t))
            .unwrap_or("DB");

        let type_tok = match &type_jp {
            Some(t) => name_tok(self.symbols.tr(t)),
            None if type_raw >= 1_000_000 => self.op(type_raw),
            None => format!("#{}", type_raw as i32),
        };
        let row = if let Some(d) = &data_jp {
            name_tok(self.symbols.tr(d))
        } else if data_raw >= 1_000_000 {
            self.op(data_raw)
        } else if let Some(name) = type_jp
            .as_deref()
            .and_then(|t| self.symbols.db_entry_name(t, data_raw))
        {
            name_tok(self.symbols.tr(name))
        } else {
            format!("#{}", data_raw as i32)
        };
        let field = if let Some(f) = &field_jp {
            Some(name_tok(self.symbols.tr(f)))
        } else if let Some(name) = type_jp
            .as_deref()
            .and_then(|t| self.symbols.db_field_name(t, field_raw))
        {
            Some(name_tok(self.symbols.tr(name)))
        } else if field_raw == 0 {
            None
        } else {
            Some(format!("#{field_raw}"))
        };

        let cell = match field {
            Some(f) => format!("{kind}[{type_tok}][{row}].{f}"),
            None => format!("{kind}[{type_tok}][{row}]"),
        };

        if flag & 0xF == 1 {
            let op = match (flag >> 4) & 0xF {
                0 => "=",
                1 => "+=",
                2 => "-=",
                3 => "*=",
                4 => "/=",
                5 => "%=",
                6 => "max=",
                7 => "min=",
                _ => "=",
            };
            format!("{cell} {op} {}", self.op(value))
        } else {
            format!("{} = {cell}", self.op(value))
        }
    }

    /// The decoded JP text of a string arg, untranslated and used for DB lookups, if present.
    fn str_name_jp(&self, cmd: &RawCommand, idx: usize) -> Option<String> {
        cmd.str_args
            .get(idx)
            .map(|s| self.decode_str(s))
            .filter(|d| !d.is_empty())
    }

    fn change_color(&self, cmd: &RawCommand) -> String {
        let a = &cmd.int_args;
        let Some(&c) = a.first() else {
            return self.labeled(cmd);
        };
        let (r, g, b) = (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF);
        let dur = a.get(1).copied().unwrap_or(0);
        if dur == 0 {
            format!("ChangeColor(R={r}, G={g}, B={b})")
        } else {
            format!("ChangeColor(R={r}, G={g}, B={b}, {dur}f)")
        }
    }

    fn teleport(&self, cmd: &RawCommand) -> String {
        let a = &cmd.int_args;
        let target = match a.first().copied() {
            Some(0xFFFF_FFFF) => "player".to_string(),
            Some(0xFFFF_FFFE) => "thisEvent".to_string(),
            Some(v) if v >= 1_000_000 => self.op(v),
            Some(v) => format!("event#{v}"),
            None => return self.labeled(cmd),
        };
        let x = a.get(1).map(|&v| self.op(v)).unwrap_or_default();
        let y = a.get(2).map(|&v| self.op(v)).unwrap_or_default();
        format!("Teleport {target} -> ({x}, {y})")
    }

    /// Decode the Sound command's packed control word into op nibble, sound-type nibble,
    /// addressing mode, and resource number.
    fn sound(&self, cmd: &RawCommand) -> String {
        let a = &cmd.int_args;
        let Some(&w) = a.first() else {
            return self.labeled(cmd);
        };
        let op = w & 0x0F;
        let ty = match (w >> 4) & 0x0F {
            0 => "BGM",
            1 => "BGS",
            2 => "SE",
            _ => "Snd",
        };
        let mode = (w >> 24) & 0x0F;
        let resnum = (w >> 8) & 0xFFFF;

        match op {
            0 => {
                let src = match mode {
                    0x2 => self.str_arg(cmd, 0),
                    0x0 => format!("#{resnum}"),
                    0x1 => format!("[{}]", a.get(2).map(|&v| self.op(v)).unwrap_or_default()),
                    _ => format!("0x{w:08X}"),
                };
                let vol = a.get(4).copied().unwrap_or(100);
                let pitch = a.get(5).copied().unwrap_or(100);
                let mut s = format!("Play{ty} {src}");
                if vol != 100 || pitch != 100 {
                    s.push_str(&format!(" vol={vol} pitch={pitch}"));
                }
                s
            }
            1 => format!("Stop{ty}"),
            2 => format!("Release{ty}"),
            3 => "StopAllSound".to_string(),
            _ => self.labeled(cmd),
        }
    }

    /// Lossless, readable Move(201): `Move(target=…) "strs" @route(t=<term>, f=<flags>,
    /// h=<5 header bytes>) { RouteCmd; RouteCmd(args); … }`. The route header bytes, flags, and
    /// terminator are carried verbatim so the pretty form fully round-trips with no `@raw`.
    fn move_command(&self, cmd: &RawCommand) -> String {
        let spec = spec::command(cmd.cid);
        let mut parts = Vec::new();
        for (i, &val) in cmd.int_args.iter().enumerate() {
            // Default to operand-ref so targets like `CSelf[3]` or `-2` read naturally.
            let (label, is_ref) = match spec.and_then(|s| s.int_args.get(i)) {
                Some(f) => (short_label(&f.label), f.kind == "operand-ref"),
                None => (format!("arg{i}"), true),
            };
            let rendered = if is_ref { self.op(val) } else { lit(val) };
            parts.push(format!("{label}={rendered}"));
        }
        let mut head = String::from("Move");
        if !parts.is_empty() {
            head.push('(');
            head.push_str(&parts.join(", "));
            head.push(')');
        }
        for sa in &cmd.str_args {
            head.push(' ');
            head.push_str(&self.quote(sa));
        }
        match &cmd.move_route {
            Some(r) => format!(
                "{head} @route(t={}, f={}, h={}) {{ {} }}",
                cmd.term,
                r.flags,
                hex(&r.unknown),
                render_route(r)
            ),
            None => head,
        }
    }

    // --- generic-but-labeled fallback --------------------------------------

    fn labeled(&self, cmd: &RawCommand) -> String {
        let name = spec::command_name(cmd.cid);
        self.labeled_inner(cmd, &name)
    }

    fn labeled_inner(&self, cmd: &RawCommand, name: &str) -> String {
        let spec = spec::command(cmd.cid);
        let mut parts = Vec::new();
        for (i, &val) in cmd.int_args.iter().enumerate() {
            let (label, is_ref) = match spec.and_then(|s| s.int_args.get(i)) {
                Some(f) => (short_label(&f.label), f.kind == "operand-ref"),
                None => (format!("arg{i}"), false),
            };
            let rendered = if is_ref { self.op(val) } else { lit(val) };
            parts.push(format!("{label}={rendered}"));
        }
        let mut s = name.to_string();
        if !parts.is_empty() {
            s.push('(');
            s.push_str(&parts.join(", "));
            s.push(')');
        }
        for sa in &cmd.str_args {
            s.push(' ');
            s.push_str(&self.quote(sa));
        }
        if let Some(route) = &cmd.move_route {
            s.push_str(&format!(" {{ {} }}", render_route(route)));
        }
        s
    }
}

// ----------------------------------------------------------------------------
// Block-marker helpers (need &mut stack)
// ----------------------------------------------------------------------------

fn case_marker(cmd: &RawCommand, stack: &mut [Block]) -> String {
    let arg0 = cmd.int_args.first().copied().unwrap_or(0);
    match stack.last_mut() {
        // Choices: show the real ChoiceCase index, which is recompile-safe. A label comment keeps
        // it readable.
        Some(Block::Choices { options, next }) => {
            let label = options.get(*next).cloned();
            *next += 1;
            match label.filter(|l| !l.is_empty()) {
                Some(l) => format!("}} case {arg0} {{  # {}", escape_inline(&l)),
                None => format!("}} case {arg0} {{"),
            }
        }
        Some(Block::Conditional { conds, next }) => {
            let cond = conds.get(*next).cloned().unwrap_or_else(|| "?".to_string());
            *next += 1;
            format!("}} when ({cond}) {{")
        }
        _ => format!("}} case {arg0} {{"),
    }
}

// ----------------------------------------------------------------------------
// Public entry points
// ----------------------------------------------------------------------------

/// Decompile a flat command list (UTF-8, no symbols).
pub fn decompile_commands(cmds: &[RawCommand]) -> String {
    decompile_commands_enc(cmds, true)
}

/// Decompile a flat command list in the file's encoding (no symbols). The recompilable form uses
/// numeric operands and byte-exact string literals, so `compile_commands_enc(_, utf8)` is its
/// exact inverse regardless of Shift-JIS or UTF-8.
pub fn decompile_commands_enc(cmds: &[RawCommand], utf8: bool) -> String {
    let symbols = SymbolTable::new();
    let body = Renderer::with_symbols(utf8, &symbols).commands(cmds);
    // A leading `@v35` directive tells the recompiler to re-add per-command blobs.
    if cmds.iter().any(|c| c.v35_blob.is_some()) {
        format!("@v35\n{body}")
    } else {
        body
    }
}

/// Decompile a flat command list in annotate mode, the unified read-plus-edit form. Readable
/// index-anchored bilingual labels (`V[3 "Gold · ゴールド"]`) that `compile_commands_enc` strips
/// back to the identical bytes. The per-leaf self-check guarantees byte-exactness, so any label
/// the parser cannot strip degrades to the numeric form. `ce_id` sets the current common event so
/// `CSelf[n]` resolves to its self-var names. Pass `None` for maps.
pub fn decompile_commands_annotated(
    cmds: &[RawCommand],
    utf8: bool,
    symbols: &SymbolTable,
    ce_id: Option<u32>,
) -> String {
    let r = Renderer::with_symbols(utf8, symbols).for_edit();
    r.current_ce.set(ce_id);
    let body = r.commands(cmds);
    if cmds.iter().any(|c| c.v35_blob.is_some()) {
        format!("@v35\n{body}")
    } else {
        body
    }
}

/// Decompile an entire map, resolving names via `symbols`.
pub fn decompile_map(map: &Map, symbols: &SymbolTable) -> String {
    let r = Renderer::with_symbols(map.utf8, symbols).for_display();
    let mut out = format!(
        "# map  version=0x{:x}  tileset={}  {}x{}  events={}\n\n",
        map.version,
        map.tileset_id,
        map.width,
        map.height,
        map.events.len()
    );
    for ev in &map.events {
        out.push_str(&format!(
            "event {} {} @({}, {}) {{\n",
            ev.id,
            r.quote(&ev.name),
            ev.x,
            ev.y
        ));
        for (pi, page) in ev.pages.iter().enumerate() {
            out.push_str(&format!("{INDENT_UNIT}page {pi} {{\n"));
            for line in r.commands(&page.commands).lines() {
                out.push_str(&format!("{INDENT_UNIT}{INDENT_UNIT}{line}\n"));
            }
            out.push_str(&format!("{INDENT_UNIT}}}\n"));
        }
        out.push_str("}\n\n");
    }
    out
}

/// Decompile a CommonEvent file, resolving names via `symbols`.
pub fn decompile_common_events(ce: &CommonEventsFile, symbols: &SymbolTable) -> String {
    let r = Renderer::with_symbols(ce.utf8, symbols).for_display();
    let mut out = format!("# common-events  count={}\n\n", ce.events.len());
    for ev in &ce.events {
        r.current_ce.set(Some(ev.int_id));
        let jp_name = decode_wstr(&ev.name, ce.utf8);
        let header = match symbols.glossary.get(&jp_name) {
            Some(g) => format!(
                "commonEvent {} {} {} {{",
                ev.int_id,
                g.en_name,
                r.quote(&ev.name)
            ),
            None => format!("commonEvent {} {} {{", ev.int_id, r.quote(&ev.name)),
        };
        out.push_str(&header);
        out.push('\n');
        for line in r.commands(&ev.commands).lines() {
            out.push_str(&format!("{INDENT_UNIT}{line}\n"));
        }
        out.push_str("}\n\n");
    }
    out
}

// ----------------------------------------------------------------------------
// Move route rendering
// ----------------------------------------------------------------------------
