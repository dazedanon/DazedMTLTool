//! Player-facing text extraction and injection for translation. Produces a curated,
//! speaker-attributed, scene-grouped view rather than a full structural string dump.
//!
//! Extracts only text shown to the player. The allowlist below was derived from the command
//! table and verified against real GamePro data. It skips comments, debug text, file paths,
//! and DB structural names. Each dialogue line is attributed to a speaker, reconstructed from
//! the engine's `\s[n]` name-variable codes, a literal nameplate line, or the face-graphic
//! window gate. Lines are grouped per event for context.
//!
//! Injection is patch-style, keyed by command index plus string-arg index so it is
//! reorder-safe. A translator edits only the `text` field. Untouched lines recompile
//! byte-exact.

use std::collections::HashMap;
use std::fmt::Write as _;

use serde_json::Value;
use wolf_formats::command::RawCommand;
use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::database::Database;
use wolf_formats::game_dat::GameDat;
use wolf_formats::map::Map;

use crate::json::value_slots;
use crate::text::{decode_wstr, text_to_wstr};

// ----------------------------------------------------------------------------
// Player-text allowlist (which command string args are shown to the player)
// ----------------------------------------------------------------------------

/// The player-facing string-arg indices of a command, given its ints. Empty means nothing to
/// translate. Keeps only dialogue, choice, and on-screen text. Never debug, comment, label,
/// path, condition-literal, or structural-name strings.
fn player_str_indices(cmd: &RawCommand) -> Vec<usize> {
    let a = &cmd.int_args;
    match cmd.cid {
        // Message: the dialogue text.
        101 => vec![0],
        // Choices: each option label (count = low nibble of arg0), skipping trailing empties.
        102 => {
            let n = a.first().copied().unwrap_or(0) & 0x0F;
            (0..n as usize)
                .filter(|&i| {
                    cmd.str_args
                        .get(i)
                        .map(|w| {
                            !decode_wstr(w, true).is_empty() && !decode_wstr(w, false).is_empty()
                        })
                        .unwrap_or(false)
                })
                .collect()
        }
        // Picture: str0 is on-screen text only when the picture type (bits 4-7 of arg0) == 2.
        150 if (a.first().copied().unwrap_or(0) >> 4) & 0x0F == 2 => vec![0],
        // SetString: a literal assigned to a string var. Player text only when it is visible
        // text, not a file path, not empty, and not a pure control/substitution token.
        122 => {
            if let Some(w) = cmd.str_args.first() {
                if is_displayable_literal(w, cmd) {
                    return vec![0];
                }
            }
            vec![]
        }
        // CommonEvent (by id) / CommonEventByName: the string inputs passed to the called event
        // become its CSelf5/6/7 and get rendered by display-helper events (the `\cself[5/6/7]`
        // shown in Messages). A literal passed here is on-screen text. For 210 the inputs start
        // at str0. For 300 str0 is the event name (structural), so inputs are str1..=3. Keep
        // only displayable literals, dropping the `\r\n`, path, and empty slots.
        210 => (0..cmd.str_args.len())
            .filter(|&i| {
                cmd.str_args
                    .get(i)
                    .map(|w| is_displayable_literal(w, cmd))
                    .unwrap_or(false)
            })
            .collect(),
        300 => (1..=3)
            .filter(|&i| {
                cmd.str_args
                    .get(i)
                    .map(|w| is_displayable_literal(w, cmd))
                    .unwrap_or(false)
            })
            .collect(),
        // Database read/write: str0 is the literal value written into a cell. str1/2/3 are
        // structural type/data/field name operands, never on-screen. Player text only when it
        // is a field-by-name write (flagWord bit 0x40000) into a content field (str3 = the field
        // name). This keeps the `<装備を外す>` and `装備を解除します。` window writes and skips the
        // `x` and `------` affix-sentinel writes into 付与文字列.
        250 | 252 => {
            let flag = a.get(3).copied().unwrap_or(0);
            let by_name = flag & 0x40000 != 0;
            // str0 is displayable and has real words. Rejects the `x`, `------`, and `\x00`
            // sentinels by value, plus paths and `<<…>>` directives.
            let str0_ok = cmd
                .str_args
                .first()
                .map(|w| is_displayable_literal(w, cmd) && has_translatable_text(&decode_either(w)))
                .unwrap_or(false);
            if by_name {
                // By-name write: keep only when the destination (str3) is a content field. This
                // keeps `<装備を外す>` and `装備を解除します。` and excludes the by-name affix sentinels
                // written into 付与文字列, a non-content field.
                let field_ok = cmd
                    .str_args
                    .get(3)
                    .map(|w| field_name_is_content(&decode_either(w)))
                    .unwrap_or(false);
                if field_ok && str0_ok {
                    return vec![0];
                }
                vec![]
            } else if str0_ok {
                // By-ID write: no field name to classify. The displayable plus translatable gate
                // keeps the base-system `…を習得！` level-up message written into the 基本ｼｽﾃﾑ用変数
                // scratch slot. That slot exists in no DB, so it has no other extraction path. The
                // by-name sentinels never reach here.
                vec![0]
            } else {
                vec![]
            }
        }
        _ => vec![],
    }
}

/// Both-encoding decode. Try UTF-8, fall back to Shift-JIS when the call site does not know
/// the file encoding. Whichever decodes non-empty wins.
pub(crate) fn decode_either(w: &wolf_formats::WStr) -> String {
    let u = decode_wstr(w, true);
    if u.is_empty() {
        decode_wstr(w, false)
    } else {
        u
    }
}

/// Heuristic: is a SetString, CommonEvent-input, or Database-write literal player-visible text
/// rather than an internal path, flag, or engine directive.
fn is_displayable_literal(w: &wolf_formats::WStr, _cmd: &RawCommand) -> bool {
    displayable_text(&decode_either(w))
}

/// The displayable-literal test on already-decoded text (split out so it is unit-testable).
fn displayable_text(s: &str) -> bool {
    let t = s.trim();
    if t.is_empty() {
        return false;
    }
    // Strip inline Wolf codes first. A backslash begins every code (\cself, \c, \i, \f, \cdb,
    // and so on), never a path separator. A plain `contains('\\')` test would drop every
    // on-screen UI string that embeds a variable, colour, or icon code such as
    // `\f[\cself[19]]Sell`, `Buy Voucher A (\cself[20])`, or `\cself[11]rose!`.
    let body = strip_control_codes(t);
    let body = body.trim();
    if body.is_empty() || body == "," {
        return false;
    }
    // Engine name-lookup directive (`<<GET_COMMONEVENT_ID_FROM_NAME>>…`, `<< \sys[100] % >>`).
    // Resolved at runtime, never shown.
    if body.contains("<<") && body.contains(">>") {
        return false;
    }
    // File path or resource: a known asset extension, or a forward slash inside a spaceless
    // token (a bare path like `Save/System.sav` or `Data/`). A `/` inside a sentence, like
    // "Skills/Items" or a price separator, is ordinary punctuation and stays.
    let lower = body.to_ascii_lowercase();
    for ext in [
        ".png", ".ogg", ".mp3", ".mid", ".wav", ".sav", ".wolfx", ".json", ".mps",
    ] {
        if lower.ends_with(ext) {
            return false;
        }
    }
    if body.contains('/') && !body.chars().any(char::is_whitespace) {
        return false;
    }
    true
}

/// True for Japanese (or other CJK) script: hiragana, katakana (full and half width), and kanji.
/// Used to keep the noise-token filter from ever rejecting real Japanese text.
fn has_cjk(s: &str) -> bool {
    s.chars().any(|c| {
        let u = c as u32;
        (0x3040..=0x30FF).contains(&u)      // hiragana + katakana
            || (0x3400..=0x4DBF).contains(&u) // CJK extension A
            || (0x4E00..=0x9FFF).contains(&u) // CJK unified ideographs
            || (0xFF66..=0xFF9F).contains(&u) // half-width katakana
    })
}

/// An engine-data token rather than prose: a string the parser used to pull into the grid that a
/// translator should never touch. Two shapes, both checked on the control-code-stripped body and
/// only ever firing when there is no CJK in it (so Japanese text is never rejected):
///   * a single ASCII alphanumeric, the id/index cells like `a`/`b`/`5` that fill columns such as
///     `英字id` (alphabet id) or a skill-tree layer flag, and
///   * a bare ASCII identifier carrying a digit or underscore (`A006`, `nx1`, `_syst00`,
///     `m_09_01`), an internal CG/asset/variable code.
/// A plain ASCII word (`Sell`, `HP`, `OK`, `Nofile`) or any phrase with whitespace is kept, since
/// those carry no digit or underscore and are real on-screen text.
fn is_noise_token(body: &str) -> bool {
    if body.is_empty() || has_cjk(body) {
        return false;
    }
    // A lone angle-bracket placeholder. A `\cdb`/`\cself` DB-read concatenated with a literal
    // `<Notfound>`/`<NoFile>` fallback strips down to just the bracket token. The `has_cjk` guard
    // above means a real CJK menu label like `<装備を外す>` never reaches here, and the
    // exactly-one-bracket test keeps `<Initialize> <Equipment>` (two pairs) and `put <X> in` (text
    // around the bracket) as real.
    let b = body.trim();
    if b.starts_with('<')
        && b.ends_with('>')
        && b.matches('<').count() == 1
        && b.matches('>').count() == 1
    {
        return true;
    }
    if body.chars().count() == 1 && body.chars().all(|c| c.is_ascii_alphanumeric()) {
        return true;
    }
    body.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
        && body.chars().any(|c| c.is_ascii_digit() || c == '_')
}

/// A comma-separated list whose every token is a tiny CG/layer code: a single lowercase letter
/// followed by 1 to 3 digits (`a0`, `c1`, `l100`), or a single lowercase letter carrying a
/// `\cself` substitution (`g\cself[44]`). These build the engine's CG layer arguments and are
/// never player text. Checked on the RAW source, not the stripped body, because `g\cself[44]`
/// strips down to a bare `g` which is indistinguishable from a real initials list once stripped.
///
/// The single-lowercase-letter lead is load-bearing: it keeps real short comma lists out of scope
/// (`OK,Cancel`, `HP,MP`, `Buy,Sell`, `Lv1,Lv2`, `L1,R1`, `Fire,Ice`, `1,2,3`), since those lead
/// with a capital, a second letter, or a non-letter.
fn is_code_list(raw: &str) -> bool {
    if has_cjk(raw) || !raw.contains(',') {
        return false;
    }
    let mut codes = 0usize;
    for tok in raw.split(',') {
        let body = strip_control_codes(tok);
        let body = body.trim();
        if body.is_empty() {
            continue; // a leading/trailing comma or a lone substitution
        }
        // The token must lead with exactly one lowercase ASCII letter.
        let single_lower = body.chars().next().map_or(false, |c| c.is_ascii_lowercase())
            && body.chars().nth(1).map_or(true, |c| !c.is_ascii_alphabetic());
        let rest: String = body.chars().skip(1).collect();
        // `a0`/`l100`: the lead letter then 1 to 3 digits.
        let is_code_digit = single_lower
            && (1..=3).contains(&rest.chars().count())
            && rest.chars().all(|c| c.is_ascii_digit());
        // `g\cself[44]`: just the lead letter, and the raw token carried a backslash code.
        let is_code_cself = single_lower && rest.is_empty() && tok.contains('\\');
        if !(is_code_digit || is_code_cself) {
            return false;
        }
        codes += 1;
    }
    codes >= 2
}

/// True if the string has actual translatable words: at least one letter in any script once the
/// inline control codes (`\cself[..]`, `\s[..]`, `\f[..]`, `\E`, and so on) are removed, and the
/// remainder is real text rather than an engine-data token. Filters out pure
/// variable-substitution, symbol, and punctuation entries like `\cself[5]`, `\f[\cself[18]]\E▲`,
/// or a lone `+`, the id/index and CG/asset codes (`a`, `A006`, `nx1`, `_syst00`), and the
/// comma-separated CG layer code lists (`a0,b0,c1`).
pub(crate) fn has_translatable_text(s: &str) -> bool {
    if is_code_list(s) {
        return false;
    }
    let body = strip_control_codes(s);
    let trimmed = body.trim();
    trimmed.chars().any(|c| c.is_alphabetic()) && !is_noise_token(trimmed)
}

/// Remove Wolf inline control codes so the remaining real text can be measured. Used by the
/// displayable heuristic and name detection.
///
/// A Wolf code is `\` plus a name (a run of ASCII letters/digits like `cself`/`space`/`f`/`E`,
/// or a single symbol like `-`/`>`/`<`/`.`/`|`/`!`/`^`) plus an optional `[..]` argument whose
/// brackets may nest, as in `\f[\cself[19]]`. The code name must be a maximal run so `\cself`
/// is consumed whole rather than leaving a bogus `self`, and nested args must be tracked so a
/// stray `]…` does not leak. Both would otherwise read as translatable text. The line-alignment
/// tags `<R>` and `<C>` are also dropped since they are formatting, not words.
///
/// Ruby/furigana `\r[base,reading]` is special-cased. It renders `base` with `reading` as
/// furigana, so the translatable-text check keeps the base (the text before the first comma)
/// and drops the `\r[`, the `,reading`, and the `]`. A ruby-only line thus counts as
/// translatable because its base is real words. All other codes are stripped whole. An escaped
/// literal `\\r[..]` is not ruby. The walk reads the first `\` then the second `\` as the
/// single-symbol code `\\`, leaving `r[..]` as plain text, so it never reaches the `name == "r"`
/// branch.
fn strip_control_codes(s: &str) -> String {
    let mut out = String::new();
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '\\' => {
                // The code name: a maximal alphanumeric run, else a single symbol char.
                let mut name = String::new();
                if matches!(chars.peek(), Some(c) if c.is_ascii_alphanumeric()) {
                    while matches!(chars.peek(), Some(c) if c.is_ascii_alphanumeric()) {
                        name.push(chars.next().unwrap());
                    }
                } else if let Some(c) = chars.next() {
                    name.push(c);
                }
                // An optional `[..]` argument, honouring nested brackets. Capture its body so
                // the ruby base can be re-emitted.
                let mut arg = String::new();
                let has_arg = chars.peek() == Some(&'[');
                if has_arg {
                    chars.next();
                    let mut depth = 1usize;
                    while depth > 0 {
                        match chars.next() {
                            Some('[') => {
                                depth += 1;
                                arg.push('[');
                            }
                            Some(']') => {
                                depth -= 1;
                                if depth > 0 {
                                    arg.push(']');
                                }
                            }
                            Some(c) => arg.push(c),
                            None => break,
                        }
                    }
                }
                // Ruby `\r[base,reading]`: keep the base (before the first comma), drop reading.
                if name == "r" && has_arg {
                    let base = arg.split(',').next().unwrap_or(&arg);
                    out.push_str(base);
                }
            }
            // Line-alignment tags `<R>` and `<C>` (right and centre). Pure formatting.
            '<' => {
                let mut look = chars.clone();
                if matches!(look.next(), Some('R' | 'C' | 'r' | 'c')) && look.next() == Some('>') {
                    chars.next();
                    chars.next();
                } else {
                    out.push('<');
                }
            }
            _ => out.push(c),
        }
    }
    out
}

// ----------------------------------------------------------------------------
// Speaker attribution
// ----------------------------------------------------------------------------

/// The global string-var slots that carry a speaker name in the BasicSystem engine (S[k]).
/// Maps the slot to a stable role label. The concrete name is resolved at render time or left
/// to the translator. Derived from SysDatabase 文字列変数名 and verified against `\s[..]`
/// frequency in GamePro.
fn speaker_role(slot: u32) -> Option<&'static str> {
    Some(match slot {
        9 | 10 => "Heroine",
        12 => "Rival",
        13 => "Professor",
        15 => "Opponent",
        16 => "Opponent",
        31 => "Ally Trainer",
        32 => "Ally Monster",
        33 => "Enemy Trainer",
        34 => "Enemy Monster",
        999 => "Player",
        _ => return None,
    })
}

/// Speaker attribution state carried across an event's command stream.
#[derive(Default)]
struct SpeakerCtx {
    /// Last `call "メッセージ顔グラフィック変更"(Face Graphic Number=N)` value. The window-type gate.
    last_face: Option<i64>,
}

impl SpeakerCtx {
    /// Update state from a face-graphic-change call. `utf8` is the file encoding.
    fn observe(&mut self, cmd: &RawCommand, utf8: bool) {
        // call "メッセージ顔グラフィック変更"(Face Graphic Number=N) is cid 300 by-name.
        if cmd.cid == 300 {
            if let Some(name) = cmd.str_args.first() {
                if decode_wstr(name, utf8) == "メッセージ顔グラフィック変更" {
                    self.last_face = cmd.int_args.get(2).map(|&v| v as i32 as i64);
                }
            }
        }
    }

    /// Resolve the speaker + source for a Message's text (its decoded line 1).
    fn speaker_of(&self, text: &str) -> (String, String) {
        // Strip a leading window-option prefix `@<digits>\n`.
        let body = if let Some(rest) = text.strip_prefix('@') {
            rest.split_once('\n').map(|(_, b)| b).unwrap_or(text)
        } else {
            text
        };
        let line1 = body.split('\n').next().unwrap_or("").trim();

        // (a) Leading speaker string-var code `\s[k]`, including the `\s[9]\s[10]` heroine combo.
        if let Some(role) = leading_name_var(line1) {
            return (role.to_string(), "string_var".to_string());
        }

        // (b) Literal short nameplate line for map NPCs. A nameplate face window precedes, and
        //     line 1 is a short token with no control codes or sentence punctuation, followed by
        //     a body. Confidence is encoded in the source tag.
        let has_more = body.contains('\n');
        let nameplate_face = matches!(self.last_face, Some(n) if n >= 2);
        if has_more
            && !line1.is_empty()
            && !line1.contains('\\')
            && line1.chars().count() <= 16
            && !line1.ends_with(['。', '！', '？', '」', '.', '!', '?'])
            && !line1.starts_with(['「', '『', '【'])
        {
            let src = if nameplate_face {
                "literal_line1"
            } else {
                "literal_line1_lowconf"
            };
            return (line1.to_string(), src.to_string());
        }

        // (c) No in-text speaker. Treat as narration.
        ("Narration".to_string(), "narration".to_string())
    }
}

/// If `line1` begins with a known speaker name-var code (`\s[k]` or the `\s[9]\s[10]` combo),
/// return the role label.
fn leading_name_var(line1: &str) -> Option<&'static str> {
    let s = line1.strip_prefix("\\s[")?;
    let (num, _) = s.split_once(']')?;
    let k: u32 = num.parse().ok()?;
    speaker_role(k)
}

// ----------------------------------------------------------------------------
// Extraction model
// ----------------------------------------------------------------------------

/// One extracted player-facing line, with its injection locator and speaker.
pub struct Line {
    /// Command index within the event/page (stable inject key).
    pub cmd: usize,
    /// String-arg index within that command.
    pub str_idx: usize,
    pub speaker: String,
    pub speaker_src: String,
    pub source: String,
}

/// A scene is one event (a common event, or a map event plus page), with its player-facing
/// lines in command order.
pub struct Scene {
    pub event: u32,
    pub page: Option<usize>,
    pub name: String,
    pub lines: Vec<Line>,
}

/// Walk one command list, returning its player-facing lines with speakers attributed by a
/// stateful pass (face-graphic gate plus name-var and nameplate detection).
///
/// `is_debug` marks the developer Debug common event, whose menu is built by cid250/252 DB writes
/// of internal operation labels (`変数操作`, `所持金等MAX`). Those are skipped there. The gate is
/// purely structural (the caller matched the exact event name plus the DB-write cids), so it never
/// inspects a string value. Real dialogue in that event is a Message (cid101) and survives.
fn scene_lines(cmds: &[RawCommand], utf8: bool, is_debug: bool) -> Vec<Line> {
    let mut ctx = SpeakerCtx::default();
    let mut out = Vec::new();
    for (ci, cmd) in cmds.iter().enumerate() {
        ctx.observe(cmd, utf8);
        if is_debug && matches!(cmd.cid, 250 | 252) {
            continue;
        }
        for si in player_str_indices(cmd) {
            let Some(w) = cmd.str_args.get(si) else {
                continue;
            };
            let source = decode_wstr(w, utf8);
            // Skip pure control-code, symbol, or punctuation entries like a `\cself[5]` dynamic
            // choice, a `\f[..]\E▲` UI arrow, or a lone `+`. Nothing for a translator to touch.
            if !has_translatable_text(&source) {
                continue;
            }
            let (speaker, speaker_src) = if cmd.cid == 101 && si == 0 {
                ctx.speaker_of(&source)
            } else if cmd.cid == 102 {
                ("Choice".to_string(), "choice".to_string())
            } else {
                ("UI".to_string(), "ui".to_string())
            };
            out.push(Line {
                cmd: ci,
                str_idx: si,
                speaker,
                speaker_src,
                source,
            });
        }
    }
    out
}

/// Extract every scene with player text from a common-events file (ordered by event id).
pub fn extract_common_events(ce: &CommonEventsFile) -> Vec<Scene> {
    let mut scenes = Vec::new();
    for ev in &ce.events {
        // The developer Debug menu event builds itself from internal cid250/252 DB writes whose
        // values are operation labels, not player text. Match the exact event name so sibling
        // test events (デバtest, テスト) that hold real dialogue are untouched. Also accept the
        // half-width spelling. To keep the Debug-menu labels instead, drop this flag.
        let name = decode_wstr(&ev.name, ce.utf8);
        let is_debug = name == "デバッグ" || name == "ﾃﾞﾊﾞｯｸﾞ";
        let lines = scene_lines(&ev.commands, ce.utf8, is_debug);
        if !lines.is_empty() {
            scenes.push(Scene {
                event: ev.int_id,
                page: None,
                name,
                lines,
            });
        }
    }
    scenes
}

/// Extract every scene with player text from a map (ordered by event, then page).
pub fn extract_map(map: &Map) -> Vec<Scene> {
    let mut scenes = Vec::new();
    for ev in &map.events {
        for (pi, page) in ev.pages.iter().enumerate() {
            // Maps have no developer Debug common event, so the debug gate is always off here.
            let lines = scene_lines(&page.commands, map.utf8, false);
            if !lines.is_empty() {
                scenes.push(Scene {
                    event: ev.id,
                    page: Some(pi),
                    name: decode_wstr(&ev.name, map.utf8),
                    lines,
                });
            }
        }
    }
    scenes
}

// ----------------------------------------------------------------------------
// JSON serialization (text starts equal to source, the translator edits `text`)
// ----------------------------------------------------------------------------

/// Render extracted scenes as translation JSON. `text` starts equal to `source` and a
/// translator edits `text`. `source` is kept for drift detection on inject.
pub fn scenes_to_json(file: &str, kind: &str, scenes: &[Scene]) -> String {
    let mut s = String::new();
    s.push_str("{\n");
    let _ = write!(s, "  \"file\": {},\n", jstr(file));
    let _ = write!(s, "  \"kind\": {},\n", jstr(kind));
    s.push_str("  \"scenes\": [\n");
    for (si, sc) in scenes.iter().enumerate() {
        s.push_str("    {\n");
        let _ = write!(s, "      \"event\": {},\n", sc.event);
        if let Some(p) = sc.page {
            let _ = write!(s, "      \"page\": {p},\n");
        }
        let _ = write!(s, "      \"name\": {},\n", jstr(&sc.name));
        s.push_str("      \"lines\": [\n");
        for (li, ln) in sc.lines.iter().enumerate() {
            let _ = write!(
                s,
                "        {{\"cmd\": {}, \"str\": {}, \"speaker\": {}, \"speaker_src\": {}, \"source\": {}, \"text\": {}}}",
                ln.cmd,
                ln.str_idx,
                jstr(&ln.speaker),
                jstr(&ln.speaker_src),
                jstr(&ln.source),
                jstr(&ln.source)
            );
            s.push_str(if li + 1 == sc.lines.len() {
                "\n"
            } else {
                ",\n"
            });
        }
        s.push_str("      ]\n    }");
        s.push_str(if si + 1 == scenes.len() { "\n" } else { ",\n" });
    }
    s.push_str("  ]\n}\n");
    s
}

// ----------------------------------------------------------------------------
// Injection (apply edited translations back, byte-exact, drift-checked)
// ----------------------------------------------------------------------------

/// Outcome of an inject. `applied`, `untranslated`, and `drifted` are the normal path.
/// `code_mismatch` and `unrepresentable` count lines skipped by a safety guard, left untouched
/// and reported. A non-zero count means the caller should exit non-zero even though the good
/// lines were written.
#[derive(Default)]
pub struct InjectStats {
    pub applied: usize,
    pub untranslated: usize,
    pub drifted: usize,
    /// Translation dropped/added/altered an inline control code vs the source (skipped).
    pub code_mismatch: usize,
    /// Translation has a char not representable in the file's (Shift-JIS) encoding (skipped).
    pub unrepresentable: usize,
}

/// Inject behaviour knobs.
#[derive(Default, Clone, Copy)]
pub struct InjectOptions {
    /// Relax the inline-code preservation guard. Allows a translation whose `\code`, `@<n>`
    /// window prefix, or `<R>`/`<C>` tags differ from the source. Off by default, which is the
    /// strict per-line block.
    pub allow_code_drift: bool,
    /// Normalize CJK punctuation in the translated text to ASCII equivalents (`「」` to `"`, `。`
    /// to `.`, full-width `！？` to `!?`, and so on) at inject time, via [`normalize_en_punct`].
    /// Off by default. For English targets. Other languages and translators who keep CJK
    /// punctuation are unaffected. Applied after the code-drift guard, before encoding.
    pub normalize_punct: bool,
}

/// Map CJK punctuation to its ASCII equivalent in `s`, leaving everything else untouched
/// (ASCII, kana, kanji, and decorative symbols like ♥ ♪ ✨ ♂). Opt-in normalization for English
/// targets, applied to the translated text on inject (see [`InjectOptions::normalize_punct`]).
///
/// Safe to run over a whole string including inline control codes. Every Wolf code (`\cself[8]`,
/// `<R>`, `@1`) is pure ASCII and contains none of these characters, so codes pass through
/// verbatim. Most entries are a 1:1 char remap. The multi-char expansions (`…` to `...`, `‥` to
/// `..`, `→` to `->`, `←` to `<-`) are spelled out. Brackets map to their open/close ASCII form.
pub fn normalize_en_punct(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            // Quote brackets -> straight double quote.
            '「' | '」' | '『' | '』' => out.push('"'),
            // Square / lenticular brackets -> ASCII square brackets.
            '【' | '〔' => out.push('['),
            '】' | '〕' => out.push(']'),
            // Angle brackets -> ASCII angle brackets.
            '〈' | '《' => out.push('<'),
            '〉' | '》' => out.push('>'),
            // Wave dashes -> tilde.
            '～' | '〜' => out.push('~'),
            // Ideographic full stop / commas.
            '。' => out.push('.'),
            '、' | '，' => out.push(','),
            // Middle dot -> hyphen.
            '・' => out.push('-'),
            // Full-width ASCII-equivalent punctuation.
            '！' => out.push('!'),
            '？' => out.push('?'),
            '：' => out.push(':'),
            '；' => out.push(';'),
            '％' => out.push('%'),
            '＆' => out.push('&'),
            // Ellipses.
            '…' => out.push_str("..."),
            '‥' => out.push_str(".."),
            // Reference mark -> asterisk.
            '※' => out.push('*'),
            // Dashes (em/en/full-width/horizontal-bar/hyphen) -> hyphen.
            '―' | '─' | '－' | '—' | '‐' => out.push('-'),
            // Curly quotes -> straight quotes.
            '“' | '”' => out.push('"'),
            '‘' | '’' => out.push('\''),
            // Math-ish symbols.
            '×' => out.push('x'),
            '−' => out.push('-'),
            '÷' => out.push('/'),
            // Arrows.
            '→' => out.push_str("->"),
            '←' => out.push_str("<-"),
            '↑' => out.push('^'),
            '↓' => out.push('v'),
            // Filled / hollow squares -> asterisk.
            '■' | '□' => out.push('*'),
            other => out.push(other),
        }
    }
    out
}

/// The ordered multiset of inline codes that must survive a translation edit, so a guard can
/// confirm none was dropped, added, or altered. Holds each `\<name>` (alnum run or single
/// symbol) with its full nested `[..]` body, each `<R>`/`<C>` alignment tag, and a leading
/// `@<digits>` window prefix. Sorted, so reordering is allowed but the set must match, including
/// which variable each `\code` references.
///
/// Ruby/furigana `\r[base,reading]` is excluded (a `name == "r"` code with a `[..]` body). An
/// English translation legitimately drops the ruby markup, rendering the base with no furigana,
/// so it must not be in the must-preserve set. An escaped `\\r[..]` is unaffected. It parses as
/// the `\\` code plus literal `r[..]` text, so the `name == "r"` body branch is never reached.
fn code_multiset(s: &str) -> Vec<String> {
    let mut codes = Vec::new();
    if let Some(rest) = s.strip_prefix('@') {
        let digits: String = rest.chars().take_while(char::is_ascii_digit).collect();
        if !digits.is_empty() {
            codes.push(format!("@{digits}"));
        }
    }
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '\\' => {
                let mut code = String::from("\\");
                let mut name = String::new();
                if matches!(chars.peek(), Some(c) if c.is_ascii_alphanumeric()) {
                    while matches!(chars.peek(), Some(c) if c.is_ascii_alphanumeric()) {
                        let ch = chars.next().unwrap();
                        name.push(ch);
                        code.push(ch);
                    }
                } else if let Some(c) = chars.next() {
                    name.push(c);
                    code.push(c);
                }
                let has_arg = chars.peek() == Some(&'[');
                if has_arg {
                    code.push(chars.next().unwrap());
                    let mut depth = 1usize;
                    while depth > 0 {
                        match chars.next() {
                            Some('[') => {
                                depth += 1;
                                code.push('[');
                            }
                            Some(']') => {
                                depth -= 1;
                                code.push(']');
                            }
                            Some(ch) => code.push(ch),
                            None => break,
                        }
                    }
                }
                // Ruby `\r[base,reading]` is droppable markup, not a must-preserve code.
                if name == "r" && has_arg {
                    continue;
                }
                codes.push(code);
            }
            '<' => {
                let mut look = chars.clone();
                if matches!(look.next(), Some('R' | 'C' | 'r' | 'c')) && look.next() == Some('>') {
                    let ch = chars.next().unwrap();
                    chars.next();
                    codes.push(format!("<{ch}>"));
                }
            }
            _ => {}
        }
    }
    codes.sort();
    codes
}

/// Run the per-line safety guards and, if they pass, encode and write the translation into
/// `cell`. The caller has already confirmed the drift guard so the base still holds `source`.
/// Updates `stats` and emits a located diagnostic on a guarded skip.
pub(crate) fn write_translation(
    cell: &mut wolf_formats::WStr,
    source: &str,
    text: &str,
    utf8: bool,
    opts: &InjectOptions,
    stats: &mut InjectStats,
    locator: &dyn Fn() -> String,
) {
    // (1) Inline control-code preservation. Dropping or altering a \code, @<n> prefix, or
    // <R>/<C> tag would break rendering, or for a \cself-referenced variable, logic. The guard
    // runs on the pre-normalization `text`. The code multiset is pure ASCII and the punct map
    // never touches ASCII, so the choice does not affect the result, but checking before
    // normalization keeps the diagnostic showing the translator's actual edit.
    if !opts.allow_code_drift {
        let (a, b) = (code_multiset(source), code_multiset(text));
        if a != b {
            stats.code_mismatch += 1;
            eprintln!(
                "{}: control-code mismatch - source has {a:?}, translation has {b:?}; edit the words but keep the \\codes and @window prefix (or pass --allow-code-drift)",
                locator()
            );
            return;
        }
    }
    // (1b) Optional CJK to ASCII punctuation normalization for English targets. Applied after
    // the code-drift guard, before encoding. Control codes are pure ASCII so they pass through.
    let normalized;
    let text = if opts.normalize_punct {
        normalized = normalize_en_punct(text);
        normalized.as_str()
    } else {
        text
    };
    // (2) Encoding. A char not representable in the file's encoding (Shift-JIS games) must not
    // be silently substituted. Skip this line and report so the rest of the batch still applies.
    match text_to_wstr(text, utf8) {
        Ok(w) => {
            *cell = w;
            stats.applied += 1;
        }
        Err(_) => {
            stats.unrepresentable += 1;
            eprintln!(
                "{}: text not representable in Shift-JIS: {text:?}; choose an SJIS-encodable equivalent",
                locator()
            );
        }
    }
}

/// Apply a translation JSON back onto a common-events file. A line is applied only when its
/// `text` differs from `source` and the base command still holds `source` (drift guard).
pub fn inject_common_events(
    json: &str,
    base: &mut CommonEventsFile,
    opts: &InjectOptions,
) -> Result<InjectStats, String> {
    let root: Value = serde_json::from_str(json).map_err(|e| format!("invalid JSON: {e}"))?;
    let utf8 = base.utf8;
    let by_id: HashMap<u32, usize> = base
        .events
        .iter()
        .enumerate()
        .map(|(i, ev)| (ev.int_id, i))
        .collect();
    let mut stats = InjectStats::default();
    for sc in scenes_array(&root)? {
        let ev_id = u(sc, "event")? as u32;
        let &idx = by_id
            .get(&ev_id)
            .ok_or_else(|| format!("common event {ev_id} not in base"))?;
        apply_lines(sc, &mut base.events[idx].commands, utf8, opts, &mut stats)?;
    }
    Ok(stats)
}

/// Apply a translation JSON back onto a map, keyed by event id plus page.
pub fn inject_map(json: &str, base: &mut Map, opts: &InjectOptions) -> Result<InjectStats, String> {
    let root: Value = serde_json::from_str(json).map_err(|e| format!("invalid JSON: {e}"))?;
    let utf8 = base.utf8;
    let by_id: HashMap<u32, usize> = base
        .events
        .iter()
        .enumerate()
        .map(|(i, ev)| (ev.id, i))
        .collect();
    let mut stats = InjectStats::default();
    for sc in scenes_array(&root)? {
        let ev_id = u(sc, "event")? as u32;
        let page = u(sc, "page")? as usize;
        let &idx = by_id
            .get(&ev_id)
            .ok_or_else(|| format!("map event {ev_id} not in base"))?;
        let cmds = base.events[idx]
            .pages
            .get_mut(page)
            .map(|p| &mut p.commands)
            .ok_or_else(|| format!("map event {ev_id} page {page} out of range"))?;
        apply_lines(sc, cmds, utf8, opts, &mut stats)?;
    }
    Ok(stats)
}

fn apply_lines(
    sc: &Value,
    cmds: &mut [RawCommand],
    utf8: bool,
    opts: &InjectOptions,
    stats: &mut InjectStats,
) -> Result<(), String> {
    let ev = sc.get("event").and_then(Value::as_u64).unwrap_or(0);
    let page = sc.get("page").and_then(Value::as_u64);
    let lines = sc
        .get("lines")
        .and_then(Value::as_array)
        .ok_or("scene has no `lines`")?;
    for ln in lines {
        let ci = u(ln, "cmd")? as usize;
        let si = u(ln, "str")? as usize;
        let source = ln.get("source").and_then(Value::as_str).unwrap_or("");
        let text = ln.get("text").and_then(Value::as_str).unwrap_or(source);
        if text == source {
            stats.untranslated += 1;
            continue;
        }
        let Some(cmd) = cmds.get_mut(ci) else {
            stats.drifted += 1;
            continue;
        };
        let Some(slot) = cmd.str_args.get_mut(si) else {
            stats.drifted += 1;
            continue;
        };
        // Drift guard: only overwrite if the base still holds the recorded source text.
        if decode_wstr(slot, utf8) != source {
            stats.drifted += 1;
            continue;
        }
        let loc = || match page {
            Some(p) => format!("event {ev} page {p} cmd {ci} str {si}"),
            None => format!("event {ev} cmd {ci} str {si}"),
        };
        write_translation(slot, source, text, utf8, opts, stats, &loc);
    }
    Ok(())
}

fn scenes_array(root: &Value) -> Result<&Vec<Value>, String> {
    root.get("scenes")
        .and_then(Value::as_array)
        .ok_or_else(|| "translation JSON has no `scenes` array".to_string())
}

fn u(v: &Value, key: &str) -> Result<u64, String> {
    v.get(key)
        .and_then(Value::as_u64)
        .ok_or_else(|| format!("missing/invalid `{key}`"))
}

// ----------------------------------------------------------------------------
// Database player-text extraction (item/skill/term/message content)
// ----------------------------------------------------------------------------

/// Field/type names (JP or EN) that mark a string field as internal: file, graphic, audio,
/// memo, sort, path, or formula. Never player text.
pub(crate) const DB_INTERNAL: &[&str] = &[
    "ファイル",
    "画像",
    "ｸﾞﾗﾌｨｯｸ",
    "グラフィック",
    "効果音",
    "BGM",
    "BGS",
    "メモ",
    "ソート",
    "パス",
    "計算",
    // `日本語移動名` and similar is the internal map-transition key namespace, compared in
    // StringConditions and never displayed. Translating it breaks the map-move override. The EN
    // glossary renders it "...Move Name" or "...Name", so it must be denylisted here, checked
    // first, rather than merely absent from DB_CONTENT, or the broad "Name" content keyword would
    // re-admit it. The player-visible map name lives in a separate, still-extracted field.
    "移動名",
    "File",
    "Graphic",
    "Image",
    "Sound",
    "Path",
    "Memo",
    "Sort",
    "Formula",
    "Move Name",
];

/// Field/type names (JP or EN) that mark a string field as a single-string name: an identity
/// string with no sentence context that the game may look rows up by. These are owned by the
/// project glossary (`names.rs`) so the row name and every by-name reference stay consistent.
///
/// `移動名` / "Move Name" is included here. The `日本語移動名` field is the internal map-transition
/// key namespace, compared in cid112 StringConditions, but also the on-screen location-banner
/// name. The glossary owns it and keeps it consistent with the cid250/cid112 references that
/// read it. The genuine-internal denylist in [`db_field_role`] is `DB_INTERNAL` minus `移動名`,
/// so this entry is reached as a name rather than rejected as internal.
pub(crate) const DB_NAME: &[&str] = &[
    "名前",
    "名称",
    "なまえ",
    "タイトル",
    "肩書",
    "表示名",
    "用語",
    "メニュー",
    "コマンド名",
    "ｺﾏﾝﾄﾞ",
    "単位",
    "項目",
    "愛称",
    "呼び方",
    "移動名",
    "Name",
    "Title",
    "Term",
    "Menu",
    "Command",
    "Unit",
    "Display",
    "Move Name",
];

/// Field/type names (JP or EN) that mark a string field as description or dialogue: a
/// contextual sentence, not an identity string. These stay independently translatable in the
/// per-file `db-strings` path. Two different translations of a description are not a conflict.
/// Dialogue fields (`セリフ`/`ｾﾘﾌ`/`効果文`) land here.
pub(crate) const DB_DESC: &[&str] = &[
    "説明",
    "文章",
    "効果文",
    "メッセージ",
    "セリフ",
    "ｾﾘﾌ",
    "Description",
    "Message",
    "Text",
];

/// A DB string-field value that is actually an asset path (file or folder selector content),
/// not player text. Used to exclude `type_byte == 1` folder-picker cells whose value is a path
/// while keeping `type_byte == 1` cells that hold a plain display name (status `表示名`). NUL-safe.
pub(crate) fn value_is_asset_path(s: &str) -> bool {
    let t = s.trim().trim_end_matches('\0').trim();
    if t.is_empty() {
        return false;
    }
    let lower = t.to_ascii_lowercase();
    const ASSET_EXT: &[&str] = &[
        ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".ogg", ".mp3", ".wav", ".mid",
    ];
    if ASSET_EXT.iter().any(|e| lower.ends_with(e)) {
        return true;
    }
    // A '/' inside a spaceless token is a bare folder/asset path, e.g. SE/[System]Cancel02.ogg.
    t.contains('/') && !t.chars().any(char::is_whitespace)
}

/// A DB cell whose every non-blank line is an asset path: a multi-line `.png` CG list, or a bare
/// folder. Tighter than [`value_is_asset_path`] so a one-line UI string with a single slash stays
/// text: a line counts as a path only with an asset extension, a trailing `/`, or two or more `/`.
/// CJK-bearing values return early, so no Japanese is ever dropped, and any line with whitespace
/// disqualifies the whole value (`1/4 of max HP`, `Buy/Sell` and friends stay).
fn value_is_asset_path_list(s: &str) -> bool {
    if has_cjk(s) {
        return false;
    }
    const ASSET_EXT: &[&str] = &[
        ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".ogg", ".mp3", ".wav", ".mid",
    ];
    let body = strip_control_codes(s);
    let mut any = false;
    for line in body.split(['\r', '\n']) {
        let line = line.trim().trim_end_matches('\0').trim();
        if line.is_empty() {
            continue;
        }
        any = true;
        if line.chars().any(char::is_whitespace) {
            return false;
        }
        let lower = line.to_ascii_lowercase();
        let is_path = ASSET_EXT.iter().any(|e| lower.ends_with(e))
            || line.ends_with('/')
            || line.matches('/').count() >= 2;
        if !is_path {
            return false;
        }
    }
    any
}

/// A DB id/code cell: the control-code-stripped, trimmed body is exactly 2 or 3 lowercase ASCII
/// letters (`za`, `kc`, `abc`), the values that fill id/layer columns like `英字id` / `abc` /
/// skill-tree layer flags. `is_ascii_lowercase` already rules out digits, uppercase, CJK and
/// symbols, so capitalised names (`Iris`) and uppercase labels (`OK`, `HP`) are never caught.
/// DB-extractor ONLY: in the command stream this same shape is real UI text (`gem`, `ml`), so it
/// must never go into the shared [`is_noise_token`] / [`has_translatable_text`].
fn is_db_short_code(s: &str) -> bool {
    let b = strip_control_codes(s);
    let b = b.trim();
    let n = b.chars().count();
    (n == 2 || n == 3) && b.chars().all(|c| c.is_ascii_lowercase())
}

/// The translation-ownership role of a DB string cell. Exactly one extractor owns each role, so
/// a DB name is never translated in two places.
///   * [`Role::Internal`]: file, graphic, audio, memo, path, sort, formula, or temp. Never
///     translated.
///   * [`Role::Name`]: a single-string identity name. Owned by the project glossary
///     (`names.rs`), which keeps the row name and every by-name reference consistent.
///   * [`Role::Content`]: a description or dialogue sentence, or an unlabeled non-internal
///     field. Owned by the per-file `db-strings` path, independently translatable.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Role {
    Internal,
    Name,
    Content,
}

/// Tests for a temp or separator type. Wolf marks scratch types with a leading `×` or `x `.
/// Separators are an all-dash label.
fn is_temp_or_separator_type(type_name: &str) -> bool {
    let tn = type_name.trim();
    tn.is_empty() || tn.starts_with('×') || tn.starts_with("x ") || tn.chars().all(|c| c == '-')
}

/// `DB_INTERNAL` minus the `移動名`/`Move Name` map-key namespace. The genuine-internal denylist:
/// file, graphic, sound, BGM, memo, path, sort, formula. `移動名` is excluded so it is reachable
/// as a `Name`, the displayed location banner the glossary owns, not rejected as internal.
fn matches_genuine_internal(name: &str) -> bool {
    const NAME_KEEP: &[&str] = &["移動名", "Move Name"];
    // Match ASCII case-insensitively. Japanese terms are unaffected by `to_ascii_lowercase`, so a
    // field labelled `…memo` or `…File` is caught as internal regardless of case. Without this, a
    // lowercase dev-note field like `100~199memo` would leak past the upper-case `Memo`/`File`
    // entries.
    let lower = name.to_ascii_lowercase();
    DB_INTERNAL
        .iter()
        .filter(|p| !NAME_KEEP.contains(p))
        .any(|p| lower.contains(&p.to_ascii_lowercase()))
}

/// The single source of truth for a DB string cell's translation-ownership [`Role`]. Evaluated
/// in strict order: internal first, then description/dialogue, then name, default content.
///
/// 1. `Internal`: `type_byte` not in {0,1} (only 0/1 hold strings), a temp/separator type, or a
///    genuine-internal field name (`DB_INTERNAL` minus the `移動名` map-key namespace).
/// 2. `Content`: the field or the type name matches a description/dialogue keyword
///    ([`DB_DESC`]). A contextual sentence, independently translatable in `db-strings`.
/// 3. `Name`: `is_first_string` (the canonical by-name column, even with an empty/unknown
///    label) or the field/type name matches a name keyword ([`DB_NAME`]).
/// 4. `Content` by default. An unlabeled non-internal non-desc field is independently
///    translatable. Safer than forcing glossary consistency on an unrecognised label.
///
/// The per-cell `value_is_asset_path` exclusion for `type_byte == 1` cells is applied separately
/// at the call sites, since it depends on the row value.
pub(crate) fn db_field_role(
    type_byte: u8,
    type_name: &str,
    field_jp: &str,
    field_en: &str,
    is_first_string: bool,
) -> Role {
    // (1) Internal: structural gate, temp/separator type, or a genuine-internal field name.
    if !matches!(type_byte, 0 | 1) || is_temp_or_separator_type(type_name) {
        return Role::Internal;
    }
    let names = [field_jp, field_en];
    if names.iter().any(|n| matches_genuine_internal(n)) {
        return Role::Internal;
    }
    let tn = type_name.trim();
    // (2) Content: a description/dialogue field or type, e.g. a …セリフ dialogue table or a 説明
    // field. Checked before Name so a `説明`/`セリフ` sentence is never pulled into the glossary.
    if DB_DESC.iter().any(|p| tn.contains(p))
        || names.iter().any(|n| DB_DESC.iter().any(|p| n.contains(p)))
    {
        return Role::Content;
    }
    // (3) Name: the canonical by-name column, or a recognised name field or type (用語設定 Terms).
    if is_first_string
        || DB_NAME.iter().any(|p| tn.contains(p))
        || names.iter().any(|n| DB_NAME.iter().any(|p| n.contains(p)))
    {
        return Role::Name;
    }
    // (4) Default: an unlabeled or unrecognised non-internal field is independently translatable.
    Role::Content
}

/// Is this string field owned by the per-file `db-strings` path (description/dialogue content)?
/// True only for [`Role::Content`]. Name fields are owned by the glossary, so the two extractors
/// have disjoint ownership of DB string cells. The `is_first_string` flag (the canonical by-name
/// column) is supplied by the caller. A `db-strings`-only call site that lacks it passes `false`.
/// A first-string column with a recognised name label still classifies as `Name` either way.
pub(crate) fn db_player_field(
    type_byte: u8,
    type_name: &str,
    field_jp: &str,
    field_en: &str,
    is_first_string: bool,
) -> bool {
    db_field_role(type_byte, type_name, field_jp, field_en, is_first_string) == Role::Content
}

/// Field-name-only "not internal" test for the command stream (cid 250/252 by-name writes),
/// where there is a destination field name but no full DB type context. A cid250 write into
/// either a description/dialogue field or a name field is player text, so this accepts `Name` or
/// `Content`, everything except `Internal`. The `×`/separator and `type_byte` gates do not apply
/// without type context, so it classifies on the field name alone against the genuine-internal
/// denylist.
fn field_name_is_content(name: &str) -> bool {
    if matches_genuine_internal(name) {
        return false;
    }
    // A bare field name with no type context is player text unless it is genuinely internal.
    // Mirrors the Name or Content union (everything non-internal) of [`db_field_role`].
    true
}

/// One extracted DB string cell with its (type, row, field) locator and bilingual field label.
pub struct DbLine {
    pub type_id: usize,
    pub row: usize,
    pub field: usize,
    pub row_name: String,
    pub field_label: String,
    pub source: String,
}

/// Player-facing string cells of one DB type.
pub struct DbGroup {
    pub type_id: usize,
    pub type_label: String,
    pub lines: Vec<DbLine>,
}

fn bilingual_name(jp: &str, glossary: &HashMap<String, String>) -> String {
    match glossary.get(jp) {
        Some(en) if en != jp => format!("{en} · {jp}"),
        _ => jp.to_string(),
    }
}

/// Extract every player-facing string cell from a database (item, skill, term, message
/// content), grouped by type. `glossary` provides bilingual labels and powers EN field matching.
pub fn extract_db_strings(db: &Database, glossary: &HashMap<String, String>) -> Vec<DbGroup> {
    let utf8 = db.utf8;
    let mut groups = Vec::new();
    for (ti, t) in db.types.iter().enumerate() {
        let type_name = decode_wstr(&t.name, utf8);
        let fields_size = (t.dat_fields_size as usize).min(t.fields.len());
        let slots = value_slots(t, fields_size, utf8);
        // Collect the player-facing content fields (Role::Content, since name fields are owned by
        // the glossary) with their string-value slot and type_byte. The type_byte drives the per-cell
        // value-is-path exclusion below. `is_first_string` tracks the canonical by-name column so
        // the role classifier can recognise it.
        let mut keep: Vec<(usize, usize, String, u8)> = Vec::new(); // (field_idx, slot, label, tb)
        let mut seen_string = false;
        for (fi, (_, is_str, slot)) in slots.iter().enumerate() {
            if !is_str {
                continue;
            }
            let is_first_string = !seen_string;
            seen_string = true;
            let fjp = decode_wstr(&t.fields[fi].name, utf8);
            let fen = glossary.get(&fjp).map(String::as_str).unwrap_or(&fjp);
            let tb = t.fields[fi].type_byte;
            if db_player_field(tb, &type_name, &fjp, fen, is_first_string) {
                keep.push((fi, *slot, bilingual_name(&fjp, glossary), tb));
            }
        }
        if keep.is_empty() {
            continue;
        }
        let mut lines = Vec::new();
        for (ri, row) in t.data.iter().enumerate() {
            let row_name = decode_wstr(&row.name, utf8);
            for (fi, slot, label, tb) in &keep {
                let source = row
                    .string_values
                    .get(*slot)
                    .map(|w| decode_wstr(w, utf8))
                    .unwrap_or_default();
                if !has_translatable_text(&source) {
                    continue;
                }
                // A folder-picker (type_byte 1) cell whose value is an asset path is not text.
                if *tb == 1 && value_is_asset_path(&source) {
                    continue;
                }
                // A list of asset paths (multi-line .png CG list, bare folder), any field type.
                if value_is_asset_path_list(&source) {
                    continue;
                }
                // A short lowercase id/code value (英字id, abc, skill-tree layer flags). DB-only.
                if is_db_short_code(&source) {
                    continue;
                }
                lines.push(DbLine {
                    type_id: ti,
                    row: ri,
                    field: *fi,
                    row_name: row_name.clone(),
                    field_label: label.clone(),
                    source,
                });
            }
        }
        if !lines.is_empty() {
            groups.push(DbGroup {
                type_id: ti,
                type_label: bilingual_name(&type_name, glossary),
                lines,
            });
        }
    }
    groups
}

/// Render DB player-text groups as translation JSON. `text` starts equal to `source`.
pub fn db_strings_to_json(file: &str, groups: &[DbGroup]) -> String {
    let mut s = String::new();
    s.push_str("{\n");
    let _ = write!(s, "  \"file\": {},\n", jstr(file));
    s.push_str("  \"kind\": \"db\",\n");
    s.push_str("  \"groups\": [\n");
    for (gi, g) in groups.iter().enumerate() {
        s.push_str("    {\n");
        let _ = write!(s, "      \"type\": {},\n", g.type_id);
        let _ = write!(s, "      \"typeName\": {},\n", jstr(&g.type_label));
        s.push_str("      \"lines\": [\n");
        for (li, ln) in g.lines.iter().enumerate() {
            let _ = write!(
                s,
                "        {{\"row\": {}, \"field\": {}, \"rowName\": {}, \"fieldName\": {}, \"source\": {}, \"text\": {}}}",
                ln.row,
                ln.field,
                jstr(&ln.row_name),
                jstr(&ln.field_label),
                jstr(&ln.source),
                jstr(&ln.source)
            );
            s.push_str(if li + 1 == g.lines.len() { "\n" } else { ",\n" });
        }
        s.push_str("      ]\n    }");
        s.push_str(if gi + 1 == groups.len() { "\n" } else { ",\n" });
    }
    s.push_str("  ]\n}\n");
    s
}

/// Apply DB translations back onto a database, keyed by type/row/field. Only lines whose `text`
/// differs from `source` and still match the base cell are changed. Unchanged cells keep their
/// exact bytes, so the database re-serializes byte-exact except for the edited strings.
pub fn inject_db_strings(
    json: &str,
    db: &mut Database,
    opts: &InjectOptions,
) -> Result<InjectStats, String> {
    let root: Value = serde_json::from_str(json).map_err(|e| format!("invalid JSON: {e}"))?;
    let utf8 = db.utf8;
    let groups = root
        .get("groups")
        .and_then(Value::as_array)
        .ok_or("DB translation JSON has no `groups` array")?;
    let mut stats = InjectStats::default();
    for g in groups {
        let ti = u(g, "type")? as usize;
        let dt = db
            .types
            .get_mut(ti)
            .ok_or_else(|| format!("type id {ti} out of range"))?;
        let fields_size = (dt.dat_fields_size as usize).min(dt.fields.len());
        // Map field index to its string-value slot. Only string fields have one.
        let slot_of: HashMap<usize, usize> = value_slots(dt, fields_size, utf8)
            .into_iter()
            .enumerate()
            .filter(|(_, (_, is_str, _))| *is_str)
            .map(|(fi, (_, _, slot))| (fi, slot))
            .collect();
        let lines = g
            .get("lines")
            .and_then(Value::as_array)
            .ok_or("DB group has no `lines`")?;
        for ln in lines {
            let ri = u(ln, "row")? as usize;
            let fi = u(ln, "field")? as usize;
            let source = ln.get("source").and_then(Value::as_str).unwrap_or("");
            let text = ln.get("text").and_then(Value::as_str).unwrap_or(source);
            if text == source {
                stats.untranslated += 1;
                continue;
            }
            let Some(&slot) = slot_of.get(&fi) else {
                stats.drifted += 1;
                continue;
            };
            let Some(row) = dt.data.get_mut(ri) else {
                stats.drifted += 1;
                continue;
            };
            let Some(cell) = row.string_values.get_mut(slot) else {
                stats.drifted += 1;
                continue;
            };
            if decode_wstr(cell, utf8) != source {
                stats.drifted += 1;
                continue;
            }
            let loc = || format!("db type {ti} row {ri} field {fi}");
            write_translation(cell, source, text, utf8, opts, &mut stats, &loc);
        }
    }
    Ok(stats)
}

// ----------------------------------------------------------------------------
// Game.dat player-text extraction + injection (Title / TitlePlus / messages)
// ----------------------------------------------------------------------------

/// The player-facing Game.dat strings, keyed by a stable label. Only these are extracted for
/// translation. Fonts, graphics, the decrypt key, and the fixed magic string are structural and
/// never shown to the player. The accessor pairs each key with the relevant `Option<WStr>` cell.
/// Some cells are gated on the file's `string_count`, so absent cells are skipped.
fn game_dat_fields(gd: &GameDat) -> Vec<(&'static str, &wolf_formats::WStr)> {
    let mut out: Vec<(&'static str, &wolf_formats::WStr)> = vec![("Title", &gd.title)];
    if let Some(s) = &gd.title_plus {
        out.push(("TitlePlus", s));
    }
    if let Some(s) = &gd.start_up_msg {
        out.push(("StartUpMsg", s));
    }
    if let Some(s) = &gd.title_msg {
        out.push(("TitleMsg", s));
    }
    out
}

/// Extract the player-facing Game.dat strings as translation JSON. Each line is `{key, source,
/// text}` with `text` starting equal to `source`. Empty strings are skipped. `source` is kept
/// for drift detection on inject.
pub fn extract_game_dat(gd: &GameDat) -> String {
    let utf8 = gd.utf8;
    let mut lines: Vec<(&'static str, String)> = Vec::new();
    for (key, w) in game_dat_fields(gd) {
        let source = decode_wstr(w, utf8);
        if source.is_empty() {
            continue;
        }
        lines.push((key, source));
    }

    let mut s = String::new();
    s.push_str("{\n");
    s.push_str("  \"file\": \"Game.dat\",\n");
    s.push_str("  \"kind\": \"gamedat\",\n");
    s.push_str("  \"lines\": [\n");
    for (li, (key, source)) in lines.iter().enumerate() {
        let _ = write!(
            s,
            "    {{\"key\": {}, \"source\": {}, \"text\": {}}}",
            jstr(key),
            jstr(source),
            jstr(source)
        );
        s.push_str(if li + 1 == lines.len() { "\n" } else { ",\n" });
    }
    s.push_str("  ]\n}\n");
    s
}

/// Apply a Game.dat translation JSON back onto the parsed file, keyed by field name. A line is
/// applied only when its `text` differs from `source` and the base cell still holds `source`
/// (drift guard). The shared [`write_translation`] helper enforces the control-code and encoding
/// guards, so untouched fields keep their exact bytes and the file re-serializes byte-exact.
pub fn inject_game_dat(
    json: &str,
    gd: &mut GameDat,
    opts: &InjectOptions,
) -> Result<InjectStats, String> {
    let root: Value = serde_json::from_str(json).map_err(|e| format!("invalid JSON: {e}"))?;
    let utf8 = gd.utf8;
    let lines = root
        .get("lines")
        .and_then(Value::as_array)
        .ok_or("Game.dat translation JSON has no `lines` array")?;
    let mut stats = InjectStats::default();
    for ln in lines {
        let key = ln
            .get("key")
            .and_then(Value::as_str)
            .ok_or("Game.dat line missing `key`")?;
        let source = ln.get("source").and_then(Value::as_str).unwrap_or("");
        let text = ln.get("text").and_then(Value::as_str).unwrap_or(source);
        if text == source {
            stats.untranslated += 1;
            continue;
        }
        // Resolve the target cell for this key. Only the gated optionals can be absent.
        let Some(cell) = game_dat_cell(gd, key) else {
            stats.drifted += 1;
            continue;
        };
        // Drift guard: only overwrite if the base still holds the recorded source text.
        if decode_wstr(cell, utf8) != source {
            stats.drifted += 1;
            continue;
        }
        let loc = || format!("gamedat {key}");
        write_translation(cell, source, text, utf8, opts, &mut stats, &loc);
    }
    Ok(stats)
}

/// Mutable accessor for a player-facing Game.dat field by its extraction key. None if the cell
/// is absent for this file's `string_count`.
fn game_dat_cell<'a>(gd: &'a mut GameDat, key: &str) -> Option<&'a mut wolf_formats::WStr> {
    match key {
        "Title" => Some(&mut gd.title),
        "TitlePlus" => gd.title_plus.as_mut(),
        "StartUpMsg" => gd.start_up_msg.as_mut(),
        "TitleMsg" => gd.title_msg.as_mut(),
        _ => None,
    }
}

fn jstr(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

// ----------------------------------------------------------------------------
// Game.dat FULL editing (every editable string field, not just player text)
// ----------------------------------------------------------------------------
//
// A broader view than the player-text `extract_game_dat`/`inject_game_dat` pair above.
// `dump_game_dat`/`apply_game_dat` expose all editable string fields (fonts, graphics, image
// paths, the opaque trailing string) as a flat JSON object, mirroring the `db-json`/`db-apply`
// design. Structural fields (indicator, magic, decrypt key, magic string, and the size/offset
// housekeeping) are never exposed and never touched. `GameDat::write` recomputes the three
// housekeeping offsets from the edited string lengths, so untouched fields re-serialize
// byte-exact.

/// The non-optional editable scalar string fields, keyed by their JSON name. Every Game.dat
/// carries them, so they round-trip unconditionally, including when empty. `SubFonts` is emitted
/// separately by [`dump_game_dat`] since it is an array, not a scalar.
fn game_dat_full_fixed(gd: &GameDat) -> Vec<(&'static str, &wolf_formats::WStr)> {
    vec![
        ("Title", &gd.title),
        ("Font", &gd.font),
        ("DefaultPcGraphic", &gd.default_pc_graphic),
    ]
}

/// The optional editable string fields, keyed by their JSON name. Present only when the file's
/// `string_count` carries them. `dump_game_dat` skips a `None` with no phantom key, and
/// `apply_game_dat` refuses to materialize one that was absent, editing only existing cells.
fn game_dat_full_optionals(gd: &GameDat) -> Vec<(&'static str, Option<&wolf_formats::WStr>)> {
    vec![
        ("TitlePlus", gd.title_plus.as_ref()),
        ("RoadImg", gd.road_img.as_ref()),
        ("GaugeImg", gd.gauge_img.as_ref()),
        ("StartUpMsg", gd.start_up_msg.as_ref()),
        ("TitleMsg", gd.title_msg.as_ref()),
        ("UnknownString14", gd.unknown_string14.as_ref()),
    ]
}

/// Mutable accessor for a single full-view scalar field by its JSON key. Returns `None` when the
/// key is unknown or refers to an optional cell that is absent for this file, so `apply_game_dat`
/// never creates or destroys an `Option`. `SubFonts` is handled separately since it is an array.
fn game_dat_full_cell<'a>(
    gd: &'a mut GameDat,
    key: &str,
) -> Option<&'a mut wolf_formats::WStr> {
    match key {
        "Title" => Some(&mut gd.title),
        "Font" => Some(&mut gd.font),
        "DefaultPcGraphic" => Some(&mut gd.default_pc_graphic),
        "TitlePlus" => gd.title_plus.as_mut(),
        "RoadImg" => gd.road_img.as_mut(),
        "GaugeImg" => gd.gauge_img.as_mut(),
        "StartUpMsg" => gd.start_up_msg.as_mut(),
        "TitleMsg" => gd.title_msg.as_mut(),
        "UnknownString14" => gd.unknown_string14.as_mut(),
        _ => None,
    }
}

/// Dump every editable Game.dat string field to a pretty JSON object keyed by field name, with
/// each `WStr` decoded to a UTF-8 string. `encoding` (`"utf8"`/`"shiftjis"`) is informational and
/// read-only. Optional fields absent for this file's `string_count` are omitted with no phantom
/// keys. Empty strings are kept as empty strings. `SubFonts` is a 3-element array. The inverse is
/// [`apply_game_dat`]. The round-trip (dump, apply, [`GameDat::write`]) reproduces the file
/// byte-exact when no value was changed.
pub fn dump_game_dat(gd: &GameDat) -> String {
    let utf8 = gd.utf8;
    let mut s = String::new();
    s.push_str("{\n");
    let _ = write!(
        s,
        "  \"encoding\": {},\n",
        jstr(if utf8 { "utf8" } else { "shiftjis" })
    );

    // Fixed scalars, always present.
    for (key, w) in game_dat_full_fixed(gd) {
        let _ = write!(s, "  {}: {},\n", jstr(key), jstr(&decode_wstr(w, utf8)));
    }

    // SubFonts is a fixed 3-element array.
    s.push_str("  \"SubFonts\": [");
    for (i, f) in gd.sub_fonts.iter().enumerate() {
        if i > 0 {
            s.push_str(", ");
        }
        s.push_str(&jstr(&decode_wstr(f, utf8)));
    }
    s.push_str("],\n");

    // Optionals: emit only those present for this file. Track the last one to drop the trailing
    // comma without a dangling separator, since the object's prior lines all end in `,`.
    let present: Vec<(&'static str, String)> = game_dat_full_optionals(gd)
        .into_iter()
        .filter_map(|(k, w)| w.map(|w| (k, decode_wstr(w, utf8))))
        .collect();
    for (i, (key, val)) in present.iter().enumerate() {
        let sep = if i + 1 == present.len() { "\n" } else { ",\n" };
        let _ = write!(s, "  {}: {}{}", jstr(key), jstr(val), sep);
    }
    if present.is_empty() {
        // No optionals: the SubFonts line above still ended in `,`. Trim it to keep valid JSON.
        if let Some(stripped) = s.strip_suffix(",\n") {
            s = format!("{stripped}\n");
        }
    }

    s.push_str("}\n");
    s
}

/// Apply a full-view Game.dat JSON (from [`dump_game_dat`]) back onto a parsed file. For each
/// present, recognized key, the field is re-encoded to the file's encoding (the same `WStr` path
/// as `inject_game_dat`) and set. A value equal to the current one is a no-op. Returns the number
/// of fields actually changed.
///
/// Guarantees: never creates or destroys an `Option` field that was not present in the base. A
/// key for an absent optional is treated as drift, counted nowhere, and skipped with a warning.
/// Never touches structural fields. The `encoding` key is read-only. Unknown keys are ignored
/// with a warning. Errors only on malformed JSON or a value not representable in the file's
/// encoding.
pub fn apply_game_dat(gd: &mut GameDat, json: &str) -> Result<usize, String> {
    let root: Value = serde_json::from_str(json).map_err(|e| format!("invalid JSON: {e}"))?;
    let obj = root
        .as_object()
        .ok_or("Game.dat full JSON must be a JSON object")?;
    let utf8 = gd.utf8;
    let mut changed = 0usize;

    // Recognized keys: scalars, the SubFonts array, and the read-only encoding marker. Lets
    // unknown keys be reported without confusing them for structural fields.
    const SCALAR_KEYS: &[&str] = &[
        "Title",
        "Font",
        "DefaultPcGraphic",
        "TitlePlus",
        "RoadImg",
        "GaugeImg",
        "StartUpMsg",
        "TitleMsg",
        "UnknownString14",
    ];

    for (key, val) in obj {
        match key.as_str() {
            "encoding" => {} // informational, read-only
            "SubFonts" => {
                let arr = val.as_array().ok_or("`SubFonts` must be a JSON array")?;
                if arr.len() != gd.sub_fonts.len() {
                    return Err(format!(
                        "`SubFonts` must have exactly {} entries (got {})",
                        gd.sub_fonts.len(),
                        arr.len()
                    ));
                }
                for (i, entry) in arr.iter().enumerate() {
                    let text = entry
                        .as_str()
                        .ok_or("`SubFonts` entries must be strings")?;
                    let cur = decode_wstr(&gd.sub_fonts[i], utf8);
                    if cur == text {
                        continue;
                    }
                    let w = text_to_wstr(text, utf8)
                        .map_err(|e| format!("SubFonts[{i}]: {e}"))?;
                    gd.sub_fonts[i] = w;
                    changed += 1;
                }
            }
            k if SCALAR_KEYS.contains(&k) => {
                let text = val
                    .as_str()
                    .ok_or_else(|| format!("`{k}` must be a string"))?;
                // Optional cells absent for this file must not be materialized. Treat as drift.
                let Some(cell) = game_dat_full_cell(gd, k) else {
                    eprintln!(
                        "gamedat-apply: `{k}` is not present in this Game.dat (string_count too low); skipping"
                    );
                    continue;
                };
                if decode_wstr(cell, utf8) == text {
                    continue; // no change
                }
                let w = text_to_wstr(text, utf8).map_err(|e| format!("{k}: {e}"))?;
                *cell = w;
                changed += 1;
            }
            other => {
                eprintln!("gamedat-apply: ignoring unknown key `{other}`");
            }
        }
    }
    Ok(changed)
}

// ----------------------------------------------------------------------------
// Coverage audit (QA): every string arg in the corpus plus whether extraction keeps
// it, so precision (kept-but-not-text) and recall (text-but-dropped) can be judged
// against the actual bytes rather than guessed.
// ----------------------------------------------------------------------------

/// One string occurrence in a command stream, tagged with extraction status.
struct StrAudit {
    cid: u32,
    cmd: usize,
    str_idx: usize,
    text: String,
    extracted: bool,
}

/// Every non-empty string arg of every command in a list, tagged with whether the player-text
/// extractor keeps it. Matched against `scene_lines`, so the allowlist and filters are exactly
/// the live ones.
fn audit_commands(cmds: &[RawCommand], utf8: bool) -> Vec<StrAudit> {
    use std::collections::HashSet;
    // The QA audit reports raw extraction coverage, so the Debug-event gate is left off here.
    let kept: HashSet<(usize, usize)> = scene_lines(cmds, utf8, false)
        .iter()
        .map(|l| (l.cmd, l.str_idx))
        .collect();
    let mut out = Vec::new();
    for (ci, cmd) in cmds.iter().enumerate() {
        for (si, w) in cmd.str_args.iter().enumerate() {
            let text = decode_wstr(w, utf8);
            if text.is_empty() {
                continue;
            }
            out.push(StrAudit {
                cid: cmd.cid,
                cmd: ci,
                str_idx: si,
                text,
                extracted: kept.contains(&(ci, si)),
            });
        }
    }
    out
}

fn write_audit_entries(s: &mut String, evt: &str, page: Option<usize>, entries: &[StrAudit]) {
    for e in entries {
        let _ = write!(
            s,
            "    {{\"event\": {evt}, \"page\": {}, \"cmd\": {}, \"cid\": {}, \"cmdName\": {}, \"str\": {}, \"extracted\": {}, \"text\": {}}},\n",
            page.map(|p| p.to_string()).unwrap_or_else(|| "null".into()),
            e.cmd,
            e.cid,
            jstr(&crate::spec::command_name(e.cid)),
            e.str_idx,
            e.extracted,
            jstr(&e.text),
        );
    }
}

/// Full per-string coverage dump of a common-events file. Every event, every string arg.
pub fn audit_common_events_to_json(ce: &CommonEventsFile) -> String {
    let mut s = String::from("{\n  \"kind\": \"common\",\n  \"entries\": [\n");
    for ev in &ce.events {
        write_audit_entries(
            &mut s,
            &ev.int_id.to_string(),
            None,
            &audit_commands(&ev.commands, ce.utf8),
        );
    }
    finish_audit(s)
}

/// Full per-string coverage dump of a map. Every event, every page, every string arg.
pub fn audit_map_to_json(map: &Map) -> String {
    let mut s = String::from("{\n  \"kind\": \"map\",\n  \"entries\": [\n");
    for ev in &map.events {
        for (pi, page) in ev.pages.iter().enumerate() {
            write_audit_entries(
                &mut s,
                &ev.id.to_string(),
                Some(pi),
                &audit_commands(&page.commands, map.utf8),
            );
        }
    }
    finish_audit(s)
}

/// Full per-cell coverage dump of a database. Every string cell across player and internal
/// fields, tagged with `playerField` (whether the field name classifies as content) and
/// `extracted`.
pub fn audit_db_to_json(db: &Database, glossary: &HashMap<String, String>) -> String {
    let utf8 = db.utf8;
    let mut s = String::from("{\n  \"kind\": \"db\",\n  \"entries\": [\n");
    for (ti, t) in db.types.iter().enumerate() {
        let type_name = decode_wstr(&t.name, utf8);
        let fields_size = (t.dat_fields_size as usize).min(t.fields.len());
        let slots = value_slots(t, fields_size, utf8);
        let mut seen_string = false;
        for (fi, (_, is_str, slot)) in slots.iter().enumerate() {
            if !is_str {
                continue;
            }
            let is_first_string = !seen_string;
            seen_string = true;
            let fjp = decode_wstr(&t.fields[fi].name, utf8);
            let fen = glossary.get(&fjp).map(String::as_str).unwrap_or(&fjp);
            let type_byte = t.fields[fi].type_byte;
            let is_player = db_player_field(type_byte, &type_name, &fjp, fen, is_first_string);
            let field_args = &t.fields[fi].string_args;
            // First string-arg of a field config is the file folder or DB-ref selector hint.
            let cfg0 = field_args
                .first()
                .map(|w| decode_wstr(w, utf8))
                .unwrap_or_default();
            for (ri, row) in t.data.iter().enumerate() {
                let text = row
                    .string_values
                    .get(*slot)
                    .map(|w| decode_wstr(w, utf8))
                    .unwrap_or_default();
                if text.is_empty() {
                    continue;
                }
                let extracted = is_player
                    && has_translatable_text(&text)
                    && !(type_byte == 1 && value_is_asset_path(&text));
                let _ = write!(
                    s,
                    "    {{\"type\": {ti}, \"typeName\": {}, \"row\": {ri}, \"rowName\": {}, \"field\": {fi}, \"fieldName\": {}, \"typeByte\": {type_byte}, \"cfg0\": {}, \"playerField\": {is_player}, \"extracted\": {extracted}, \"text\": {}}},\n",
                    jstr(&type_name),
                    jstr(&decode_wstr(&row.name, utf8)),
                    jstr(&fjp),
                    jstr(&cfg0),
                    jstr(&text),
                );
            }
        }
    }
    finish_audit(s)
}

/// Trim the trailing `,\n` and close the audit JSON array and object.
fn finish_audit(mut s: String) -> String {
    if s.ends_with(",\n") {
        s.truncate(s.len() - 2);
        s.push('\n');
    }
    s.push_str("  ]\n}\n");
    s
}

#[cfg(test)]
mod tests {
    use super::*;
    use wolf_formats::WStr;

    #[test]
    fn strip_handles_multichar_codes_and_nesting() {
        // Multi-char names must vanish whole, not decay to `self`.
        assert_eq!(strip_control_codes("\\cself[6]"), "");
        assert_eq!(strip_control_codes("\\space[0]"), "");
        // Nested codes: the font code's argument is itself a substitution.
        assert_eq!(strip_control_codes("\\f[\\cself[19]]\\cself[6]"), "");
        // Symbol codes and alignment tags.
        assert_eq!(
            strip_control_codes("<R>\\space[0]\\f[\\cself[17]]\\-[1]\\E\\cself[6]"),
            ""
        );
        // Real words survive, with their surrounding substitutions stripped for the check.
        assert_eq!(
            strip_control_codes("「\\cself[8]」を手に入れた。"),
            "「」を手に入れた。"
        );
    }

    #[test]
    fn strip_keeps_ruby_base_drops_reading() {
        // Ruby `\r[base,reading]`: the base text is kept as the translatable word. The reading
        // and the markup are dropped. A ruby-only line therefore counts as translatable.
        assert!(strip_control_codes("\\r[市松,いちまつ]").contains("市松"));
        assert_eq!(strip_control_codes("\\r[市松,いちまつ]"), "市松");
        // Ruby base inline among other text and codes.
        assert_eq!(
            strip_control_codes("\\r[市松,いちまつ]\\cself[3]さん"),
            "市松さん"
        );
        // An escaped literal `\\r[..]` is not ruby. The first `\` and second `\` parse as the
        // `\\` single-symbol code, leaving `r[人生,じんせい]` as plain text, so the base is not
        // re-emitted. The literal `r[..]` including the reading stays.
        assert_eq!(
            strip_control_codes("\\\\r[人生,じんせい]"),
            "r[人生,じんせい]"
        );
        // The recall check (used by `has_translatable_text`) sees the ruby base as words.
        assert!(has_translatable_text("\\r[市松,いちまつ]"));
    }

    #[test]
    fn displayable_literal_keeps_coded_text_rejects_internal() {
        // Real UI text that embeds an inline code must be kept. A plain `contains('\\')` path
        // test would wrongly drop all of these.
        assert!(displayable_text("\\f[\\cself[19]]Sell"));
        assert!(displayable_text("Buy Voucher A (\\cself[20])"));
        assert!(displayable_text("\\cself[11]rose!"));
        assert!(displayable_text("\\c[1]3000 chips\\c[0] to start"));
        // A forward slash inside a sentence is ordinary punctuation. Keep it.
        assert!(displayable_text(
            "Save cursor position when opening Skills/Items"
        ));
        // Internal: engine directive, asset paths, bare path tokens, pure substitution.
        assert!(!displayable_text(
            "<<GET_COMMONEVENT_ID_FROM_NAME>>■主人公ピクセル移動切り替え"
        ));
        assert!(!displayable_text("<< \\sys[100] % >>"));
        assert!(!displayable_text("Save/System.sav"));
        assert!(!displayable_text("Data/"));
        assert!(!displayable_text("SE/door.ogg"));
        assert!(!displayable_text("\\cself[5]"));
    }

    #[test]
    fn asset_path_values_rejected_names_kept() {
        // type_byte==1 folder-picker cells: a path value is excluded, a plain display name is kept.
        assert!(value_is_asset_path("Base_window/WindowBaseA.png"));
        assert!(value_is_asset_path("SE/[System]Cancel02.ogg"));
        assert!(value_is_asset_path(
            "BalloonBase_CafeLatte/[CafeLatte]nameL.png"
        ));
        assert!(!value_is_asset_path("Poison")); // a status 表示名
        assert!(!value_is_asset_path("毒")); // a JP status name
        assert!(!value_is_asset_path("Game Over")); // a name with a space, no ext
        assert!(!value_is_asset_path("")); // empty or NUL-only
        assert!(!value_is_asset_path("\u{0}"));
    }

    #[test]
    fn code_multiset_detects_dropped_or_altered_codes() {
        // Same codes in any order compare equal. A dropped, altered, or added code compares different.
        assert_eq!(
            code_multiset("「\\cself[8]」を手に入れた。"),
            vec!["\\cself[8]"]
        );
        assert_eq!(
            code_multiset("Got \\cself[8]!"),
            code_multiset("「\\cself[8]」")
        );
        assert_ne!(code_multiset("「\\cself[8]」"), code_multiset("Got it!")); // dropped
        assert_ne!(code_multiset("\\cself[8]"), code_multiset("\\cself[9]")); // ref changed
                                                                              // @-window prefix and <R>/<C> alignment tags are tracked.
        assert_eq!(
            code_multiset("@1\n\\s[9]Hi"),
            vec!["@1".to_string(), "\\s[9]".to_string()]
        );
        assert_ne!(code_multiset("@1\nHi"), code_multiset("Hi")); // dropped @ prefix
        assert_eq!(code_multiset("<R>\\f[\\cself[3]]X").len(), 2); // <R> plus nested \f[..]
    }

    #[test]
    fn code_multiset_excludes_ruby_keeps_others() {
        // Ruby `\r[..]` is droppable markup, so it never enters the must-preserve set. A
        // translation may drop it without --allow-code-drift.
        assert!(code_multiset("\\r[市松,いちまつ]").is_empty());
        // Other codes around a ruby are still required. Only the `\r[..]` is excluded.
        assert_eq!(
            code_multiset("\\r[x,y]\\cself[3]"),
            vec!["\\cself[3]".to_string()]
        );
        // A ruby-bearing source vs a ruby-dropped translation therefore have equal code sets.
        assert_eq!(
            code_multiset("\\r[市松,いちまつ]"),
            code_multiset("Ichimatsu")
        );
        // An escaped `\\r[..]` is the `\\` code plus literal `r[..]` text. The `\\` is preserved.
        assert_eq!(
            code_multiset("\\\\r[人生,じんせい]"),
            vec!["\\\\".to_string()]
        );
    }

    #[test]
    fn normalize_en_punct_maps_cjk_keeps_rest() {
        // Brackets become straight quotes and the wave dash becomes a tilde. The decorative ♥
        // is untouched.
        assert_eq!(normalize_en_punct("「テスト」～♥"), "\"テスト\"~♥");
        // Control codes are pure ASCII and pass through unchanged.
        assert_eq!(normalize_en_punct("\\cself[8]"), "\\cself[8]");
        assert_eq!(normalize_en_punct("@1\n\\s[9]Hi"), "@1\n\\s[9]Hi");
        // The full map, both 1:1 and multi-char expansions.
        assert_eq!(normalize_en_punct("『』【】〔〕"), "\"\"[][]");
        assert_eq!(normalize_en_punct("〈〉《》"), "<><>");
        assert_eq!(normalize_en_punct("。、，・"), ".,,-");
        assert_eq!(normalize_en_punct("！？：；％＆"), "!?:;%&");
        assert_eq!(normalize_en_punct("…‥※"), ".....*"); // `...` then `..` then `*`
        assert_eq!(normalize_en_punct("―─－—‐"), "-----");
        assert_eq!(normalize_en_punct("“”‘’"), "\"\"''");
        assert_eq!(normalize_en_punct("×−÷"), "x-/");
        assert_eq!(normalize_en_punct("→←↑↓"), "-><-^v");
        assert_eq!(normalize_en_punct("■□"), "**");
        // Decorative symbols and kana, kanji, and ASCII are left exactly as-is.
        assert_eq!(normalize_en_punct("♥♪✨♂ abc 日本語"), "♥♪✨♂ abc 日本語");
    }

    #[test]
    fn write_translation_ruby_drop_ok_but_cself_drop_rejected() {
        let loc = || "test".to_string();
        // Dropping the ruby markup is accepted by default without --allow-code-drift. The source
        // ruby code is excluded from the must-preserve set, so "Ichimatsu" lands cleanly.
        let mut cell = WStr::from("\\r[市松,いちまつ]");
        let mut stats = InjectStats::default();
        write_translation(
            &mut cell,
            "\\r[市松,いちまつ]",
            "Ichimatsu",
            true,
            &InjectOptions::default(),
            &mut stats,
            &loc,
        );
        assert_eq!(stats.applied, 1, "dropping ruby markup must be accepted");
        assert_eq!(stats.code_mismatch, 0);
        assert_eq!(decode_wstr(&cell, true), "Ichimatsu");

        // Dropping a real `\cself[..]` code is still rejected. The line is left untouched.
        let mut cell = WStr::from("「\\cself[8]」を手に入れた。");
        let mut stats = InjectStats::default();
        write_translation(
            &mut cell,
            "「\\cself[8]」を手に入れた。",
            "Got the item!",
            true,
            &InjectOptions::default(),
            &mut stats,
            &loc,
        );
        assert_eq!(stats.applied, 0, "dropping \\cself must be rejected");
        assert_eq!(stats.code_mismatch, 1);
        // Cell untouched, still the source bytes.
        assert_eq!(decode_wstr(&cell, true), "「\\cself[8]」を手に入れた。");
    }

    #[test]
    fn write_translation_en_punct_lands_straight_quotes() {
        let loc = || "test".to_string();
        // With normalize_punct, a translation containing 「」 lands as straight quotes.
        let mut cell = WStr::from("テスト");
        let mut stats = InjectStats::default();
        write_translation(
            &mut cell,
            "テスト",
            "「Hello」",
            true,
            &InjectOptions {
                allow_code_drift: false,
                normalize_punct: true,
            },
            &mut stats,
            &loc,
        );
        assert_eq!(stats.applied, 1);
        assert_eq!(decode_wstr(&cell, true), "\"Hello\"");

        // Off by default, the CJK brackets are preserved verbatim.
        let mut cell = WStr::from("テスト");
        let mut stats = InjectStats::default();
        write_translation(
            &mut cell,
            "テスト",
            "「Hello」",
            true,
            &InjectOptions::default(),
            &mut stats,
            &loc,
        );
        assert_eq!(stats.applied, 1);
        assert_eq!(decode_wstr(&cell, true), "「Hello」");
    }

    #[test]
    fn field_name_content_classifier() {
        // A cid250 by-name write into a name or a description/dialogue field is player text, so
        // the command-stream test accepts everything that is not genuinely internal, the Name or
        // Content union. Description/dialogue and name labels both pass.
        assert!(field_name_is_content("説明文")); // description
        assert!(field_name_is_content("項目文")); // menu-item label (a name)
        assert!(field_name_is_content("愛称")); // nickname (a name)
        // A non-keyword label is not internal, so it is player text (Role::Content). The 付与文字列
        // affix sentinels (`x` and `------`) are still dropped by the str0 translatable gate in
        // `player_str_indices`, not by this field test (see player_str_indices_unchanged_on_*).
        assert!(field_name_is_content("付与文字列[前]"));
        // Genuinely-internal fields are still rejected.
        assert!(!field_name_is_content("ファイル"));
        assert!(!field_name_is_content("戦闘背景画像"));
    }

    #[test]
    fn db_field_role_three_way_split() {
        // (1) Internal: non-string type_byte, temp/separator type, or genuine-internal field.
        assert_eq!(
            db_field_role(2, "Monster", "名前", "Name", true),
            Role::Internal
        );
        assert_eq!(
            db_field_role(0, "×temp", "名前", "Name", true),
            Role::Internal
        );
        assert_eq!(
            db_field_role(0, "------", "名前", "Name", true),
            Role::Internal
        );
        assert_eq!(
            db_field_role(0, "Monster", "ファイル", "File", false),
            Role::Internal
        );
        assert_eq!(
            db_field_role(0, "Skill", "戦闘背景画像", "Graphic", false),
            Role::Internal
        );
        // (2) Content: a description/dialogue field or type. `セリフ`/`ｾﾘﾌ`/`効果文` stay in DESC.
        assert_eq!(
            db_field_role(0, "Skill", "説明", "Description", false),
            Role::Content
        );
        assert_eq!(
            db_field_role(0, "Skill", "効果文", "Description", false),
            Role::Content
        );
        assert_eq!(
            db_field_role(0, "会話セリフ", "", "", false),
            Role::Content
        );
        assert_eq!(
            db_field_role(0, "Item", "メッセージ", "Message", false),
            Role::Content
        );
        // A description field still wins even on the first-string column. DESC beats Name.
        assert_eq!(
            db_field_role(0, "Help", "説明", "Description", true),
            Role::Content
        );
        // (3) Name: first string column (even unlabeled), or a recognised name field or type.
        assert_eq!(db_field_role(0, "Monster", "", "", true), Role::Name);
        assert_eq!(
            db_field_role(0, "Item", "謎ラベル", "謎ラベル", true),
            Role::Name
        );
        assert_eq!(
            db_field_role(0, "Trainer", "愛称", "愛称", false),
            Role::Name
        );
        assert_eq!(
            db_field_role(0, "Element", "呼び方", "呼び方", false),
            Role::Name
        );
        // `移動名` is the displayed location banner, so it is a Name not Internal and the glossary owns it.
        assert_eq!(
            db_field_role(0, "Map", "日本語移動名", "Move Name", false),
            Role::Name
        );
        assert_eq!(
            db_field_role(0, "用語設定", "", "", false),
            Role::Name
        );
        // (4) Default Content: an unlabeled or unrecognised non-internal, non-first field.
        assert_eq!(db_field_role(0, "Misc", "", "", false), Role::Content);
        assert_eq!(
            db_field_role(0, "Misc", "謎ラベル", "謎ラベル", false),
            Role::Content
        );
    }

    #[test]
    fn db_player_field_is_content_only() {
        // db_player_field (db-strings ownership) is true only for Role::Content.
        assert!(db_player_field(0, "Skill", "説明", "Description", false)); // Content
        assert!(!db_player_field(0, "Monster", "名前", "Name", true)); // Name, glossary owns it
        assert!(!db_player_field(0, "Monster", "", "", true)); // first-string Name
        assert!(!db_player_field(0, "Map", "日本語移動名", "Move Name", false)); // Name
        assert!(!db_player_field(0, "Monster", "ファイル", "File", false)); // Internal
        // Default (unlabeled non-first) is Content, so db-strings keeps it.
        assert!(db_player_field(0, "Misc", "謎ラベル", "謎ラベル", false));
    }

    #[test]
    fn translatable_filter_rejects_pure_substitution() {
        // Pure variable refs or UI glyphs. Nothing for a translator.
        assert!(!has_translatable_text("\\cself[5]"));
        assert!(!has_translatable_text("\\f[\\cself[18]]\\E▲"));
        assert!(!has_translatable_text("\\f[\\cself[19]]\\cself[6]"));
        assert!(!has_translatable_text(
            "<R>\\space[0]\\f[\\cself[17]]\\-[1]\\E\\cself[6]"
        ));
        assert!(!has_translatable_text("+"));
        // Real text, including text wrapped around an embedded substitution.
        assert!(has_translatable_text("No data available"));
        assert!(has_translatable_text("「\\cself[8]」を手に入れた。"));
        assert!(has_translatable_text("やめる"));
    }

    #[test]
    fn translatable_filter_rejects_engine_data_tokens() {
        // Single-letter id/index cells (英字id columns, skill-tree layer flags) and CG/asset codes.
        for junk in [
            "a", "b", "z", "5", "A006", "A000", "nx1", "_syst00", "m_09_01", "mc01", "CharaChip2",
        ] {
            assert!(!has_translatable_text(junk), "{junk:?} should be filtered as engine data");
        }
        // A variable-expression that strips to a bare underscore identifier.
        assert!(!has_translatable_text("_syst00\\cself[10]"));
        // Real text must survive: plain ASCII words, labels, measurements, and any CJK.
        for keep in [
            "Sell",
            "HP",
            "OK",
            "Nofile",
            "Lv",
            "No data available",
            "Game Over",
            "138cm\r\n36kg",
            "アイリス",
            "全回復",
            "一", // a lone kanji can be a name, never engine data
        ] {
            assert!(has_translatable_text(keep), "{keep:?} should be kept as translatable");
        }
    }

    #[test]
    fn noise_token_never_fires_on_cjk() {
        // Even a one-character kanji or a kanji glued to ASCII is not engine data.
        assert!(!is_noise_token("一"));
        assert!(!is_noise_token("S淫乱度"));
        assert!(is_noise_token("a"));
        assert!(is_noise_token("A006"));
        assert!(!is_noise_token("Sell"));
    }

    #[test]
    fn angle_token_rejected_but_real_labels_kept() {
        // Lone engine placeholders (a \cdb read concatenated with a literal fallback strip to this).
        for junk in ["<Notfound>", "<NoFile>", "<L>", "<b>", "<br>"] {
            assert!(is_noise_token(junk), "{junk:?} should be engine noise");
            assert!(!has_translatable_text(junk), "{junk:?} not translatable");
        }
        assert!(!has_translatable_text("\\cdb[11:\\cself[21]:0]<Notfound>"));
        // CJK menu labels, multiple bracket pairs, and text around a bracket all stay.
        for keep in [
            "<装備を外す>",
            "<Initialize> <Equipment Adjustment>",
            "put <SCREENSHOT> in the picture",
            "★NoFile>\\cself[5]ファイルがありません",
        ] {
            assert!(has_translatable_text(keep), "{keep:?} should be kept");
        }
    }

    #[test]
    fn code_list_rejected_but_real_short_lists_kept() {
        for junk in [
            "a0,b0,c1,d1,e0,f2,g2,h0,k0,l0,i0",
            "a0,b0,c0,d0,e0,f0",
            "f3,g3",
            "g\\cself[44],h\\cself[44]",
            "p\\cself[12],l100",
            ",p\\cself[44],q\\cself[44]",
        ] {
            assert!(is_code_list(junk), "{junk:?} should read as a code list");
            assert!(!has_translatable_text(junk), "{junk:?} not translatable");
        }
        // Real short comma lists: capitalised, multi-letter, or CJK leads keep them out of scope.
        // None must read as a code list (so the rule never misfires).
        for keep in [
            "OK,Cancel", "Yes,No", "HP,MP", "HP,MP,Lv", "Buy,Sell", "Fire,Ice", "S,A,B,C",
            "Lv1,Lv2", "L1,R1", "No1,No2", "1,2,3", "100,200", "装備,解除",
        ] {
            assert!(!is_code_list(keep), "{keep:?} must NOT read as a code list");
        }
        // The ones carrying real words stay translatable (the pure-number lists have no letters, so
        // they are correctly not translatable regardless, and are not asserted here).
        for keep in ["OK,Cancel", "HP,MP", "Buy,Sell", "Fire,Ice", "Lv1,Lv2", "L1,R1", "装備,解除"] {
            assert!(has_translatable_text(keep), "{keep:?} should be kept");
        }
    }

    #[test]
    fn asset_path_list_rejected_but_real_slashes_kept() {
        for junk in [
            "EVCG_b0/B000/B0_a000.png\r\nEVCG_b0/B000/B0_d000.png",
            "EVCG_a0/A000/",
            "EVCG_e0/E000/E0_a000.png\r\nEVCG_e0/E000/E0_o0\\cself[36]0.png",
            "b/r/i/j/m/zv/zx",
        ] {
            assert!(value_is_asset_path_list(junk), "{junk:?} should read as a path list");
        }
        // A single slash inside a real phrase, a 2-token ratio, or any CJK stays text.
        for keep in ["HP/MP", "Buy/Sell", "スキル/アイテム", "1/4 of max HP", "OK", "<装備を外す>"] {
            assert!(!value_is_asset_path_list(keep), "{keep:?} must stay text");
        }
    }

    #[test]
    fn db_short_code_rejected_but_words_and_names_kept() {
        for junk in ["za", "zb", "kc", "la", "ma", "nn", "ac", "abc", "hb", "hc", "kg", "mg", "nd"] {
            assert!(is_db_short_code(junk), "{junk:?} should read as a DB short code");
        }
        // Words/labels/names: lowercase 2-3 is the only catch, so uppercase or >3 stays.
        // (gem/ml are real in the COMMAND stream, where this rule never runs.)
        for keep in ["OK", "HP", "Lv", "Iris", "Lisa", "Sion", "Fire", "item", "<装備を外す>", "助ける"] {
            assert!(!is_db_short_code(keep), "{keep:?} must NOT read as a short code");
        }
    }
}
