//! Stateless rendering helpers: operand and operator decoding, move-route rendering, the
//! lossless `@raw` fallback, and small string/format utilities.

use crate::spec;
use wolf_formats::command::{MoveRoute, RawCommand, RouteCommand};

pub(crate) fn render_route(route: &MoveRoute) -> String {
    route
        .commands
        .iter()
        .map(render_route_command)
        .collect::<Vec<_>>()
        .join("; ")
}

pub(crate) fn render_route_command(rc: &RouteCommand) -> String {
    let name = spec::route_name(rc.id as u32);
    if rc.args.is_empty() {
        name
    } else {
        // Route args are variable-call values, resolved by the engine through the same operand
        // resolver, so decode them as references: `Wait(CSelf[5])`, not `Wait(1600005)`.
        let args: Vec<String> = rc.args.iter().map(|&v| operand(v)).collect();
        format!("{name}({})", args.join(", "))
    }
}

// ----------------------------------------------------------------------------
// Operand / operator decoding
// ----------------------------------------------------------------------------

/// Decode a Wolf operand id into a readable reference. Ranges: map-event self vars at
/// `1_100_000+n` (`Self[n]`), common-event self vars at `1_600_000+n` (`CSelf[n]`), normal vars
/// `2_000_000+n`, strings `3_000_000+n`, random `8_000_000+N` as `Rand[N]`, system vars
/// `9_000_000..9_099_999`, on-map character data `9_100_000+` and `9_180_000+`, and this-event
/// intrinsic data `1_000_000+`. This standalone decoder mirrors [`super::Renderer::op`] for the
/// symbol-free and route-arg path. Both invert [`crate::compile::cmd`]'s `operand` parser.
pub fn operand(v: u32) -> String {
    match v {
        0..=999_999 => v.to_string(),
        1_000_000..=1_099_999 => this_event_ref(v),
        1_100_000..=1_199_999 => format!("Self[{}]", v - 1_100_000),
        1_600_000..=1_699_999 => format!("CSelf[{}]", v - 1_600_000),
        1_200_000..=1_599_999 | 1_700_000..=1_999_999 => format!("Self*[{}]", v - 1_000_000),
        2_000_000..=2_999_999 => format!("V[{}]", v - 2_000_000),
        3_000_000..=3_999_999 => format!("S[{}]", v - 3_000_000),
        8_000_000..=8_999_999 => format!("Rand[{}]", v - 8_000_000),
        9_000_000..=9_099_999 => format!("Sys[{}]", v - 9_000_000),
        9_100_000..=9_179_999 => chara_ref("Chara", 9_100_000, v),
        9_180_000..=9_189_999 => chara_ref("Chara2", 9_180_000, v),
        9_190_000..=9_999_999 => format!("Sys[{}]", v - 9_000_000),
        _ => lit(v),
    }
}

/// On-map Character intrinsic-data field names, shared by the this-event (`1_000_000`),
/// party-character (`9_100_000`), and current-character (`9_180_000`) operand banks. Maps to
/// Character-struct offsets: +36/+40 position, +184 height, +272 graphic, +68 direction,
/// +344/+348 move remainder. The field index is `refNum % 10`. Positions are stored doubled, so
/// the halved tile coordinate (field 0/1) and the raw precise coordinate (field 2/3) coexist.
pub(crate) fn chara_field_name(f: u32) -> Option<&'static str> {
    Some(match f {
        0 => "X",
        1 => "Y",
        2 => "PreciseX",
        3 => "PreciseY",
        4 => "Height",
        5 => "Graphic",
        6 => "Dir",
        7 => "RemX",
        8 => "RemY",
        9 => "Name",
        _ => return None,
    })
}

/// Inverse of [`chara_field_name`] for the recompiler.
pub(crate) fn chara_field_index(name: &str) -> Option<u32> {
    (0..10).find(|&f| chara_field_name(f) == Some(name))
}

/// Render an on-map character-data reference (`Chara[m].Field`). `member = (v-base)/10`,
/// `field = v % 10`.
pub(crate) fn chara_ref(prefix: &str, base: u32, v: u32) -> String {
    let off = v - base;
    let member = off / 10;
    match chara_field_name(off % 10) {
        Some(f) => format!("{prefix}[{member}].{f}"),
        None => format!("{prefix}[{member}].f{}", off % 10),
    }
}

/// Render a this-event intrinsic-data reference. Sub-object 0 (`1_000_000..=1_000_009`) is the
/// position/graphic block, shown as `ThisEv.Field`. Deeper sub-objects stay structural
/// (`ThisEv[k]`) so the byte survives the round-trip without an over-claimed field name.
pub(crate) fn this_event_ref(v: u32) -> String {
    let off = v - 1_000_000;
    match chara_field_name(off) {
        Some(f) => format!("ThisEv.{f}"),
        None => format!("ThisEv[{off}]"),
    }
}

/// Render a literal int, showing 2's-complement negatives (e.g. 0xFFFFFFFF becomes -1).
pub(crate) fn lit(v: u32) -> String {
    (v as i32).to_string()
}

/// Render a VariableCondition (111) compare-op word reversibly. The low nibble is the comparison
/// (editor order: 0=<=,1=>=,2===,3=!=,4=<,5=>,6=bitAND). The high nibble carries per-term flags,
/// such as the 0x10 right-side-is-variable flag seen in GamePro (op 0x12 = `==~1`). Known low
/// nibbles render as a symbol, plus `~<flags>` when set. Anything else stays `cmp<N>` so the exact
/// byte survives the round-trip.
pub(crate) fn compare_op_str(v: u32) -> String {
    let base = match v & 0x0F {
        0 => "<=",
        1 => ">=",
        2 => "==",
        3 => "!=",
        4 => "<",
        5 => ">",
        6 => "&", // bitAND != 0
        _ => return format!("cmp{v}"),
    };
    match v >> 4 {
        0 => base.to_string(),
        flags => format!("{base}~{flags}"),
    }
}

/// StringCondition (112) comparison-type token (the high nibble of the condition word):
/// 0=same, 1=different, 2=contains, 3=not-contains. Unknown types use a reversible `strcmp<N>`.
pub(crate) fn strcmp_op_str(ty: u32) -> String {
    match ty {
        0 => "eq".to_string(),
        1 => "ne".to_string(),
        2 => "contains".to_string(),
        3 => "!contains".to_string(),
        other => format!("strcmp{other}"),
    }
}

pub(crate) fn modify_op(arg3: u32) -> &'static str {
    match (arg3 >> 8) & 0x0F {
        0 => "=",
        1 => "+=",
        2 => "-=",
        3 => "*=",
        4 => "/=",
        5 => "%=",
        6 => "= floor",
        7 => "= ceil",
        8 => "= abs",
        9 => "= angle",
        0xA => "= sin",
        0xB => "= cos",
        0xC => "= sqrt",
        _ => "=?",
    }
}

pub(crate) fn binary_op(arg3: u32) -> &'static str {
    match (arg3 >> 12) & 0x0F {
        0 => "+",
        1 => "-",
        2 => "*",
        3 => "%",
        4 => "~",
        5 | 6 => "&",
        7 => "|",
        8 => "^",
        9 => "<<",
        _ => "?",
    }
}

pub(crate) fn short_label(label: &str) -> String {
    label
        .split(|c: char| c == '(' || c == ' ' || c == '/')
        .next()
        .unwrap_or(label)
        .to_string()
}

pub(crate) fn escape(s: &str) -> String {
    s.replace('\\', "\\\\").replace('"', "\\\"")
}

/// Escape control characters so a value stays on one line, for unquoted contexts like comments.
/// Inverse of the parser's `unescape`.
pub(crate) fn escape_inline(s: &str) -> String {
    s.replace('\\', "\\\\")
        .replace('\r', "\\r")
        .replace('\n', "\\n")
        .replace('\t', "\\t")
}

/// Fully lossless fallback for commands the pretty or labeled forms cannot reproduce, such as
/// `Move` with a route block, or v3.5 trailing blobs.
pub(crate) fn raw_form(cmd: &RawCommand) -> String {
    use wolf_formats::Writer;
    let ints = cmd
        .int_args
        .iter()
        .map(|v| v.to_string())
        .collect::<Vec<_>>()
        .join(",");
    let strs = cmd
        .str_args
        .iter()
        .map(|s| hex(s.as_bytes()))
        .collect::<Vec<_>>()
        .join(",");
    let route = match &cmd.move_route {
        Some(mr) => {
            let mut w = Writer::new();
            mr.write(&mut w);
            hex(&w.into_bytes())
        }
        None => "-".to_string(),
    };
    let v35 = cmd
        .v35_blob
        .as_ref()
        .map(|b| hex(b))
        .unwrap_or_else(|| "-".to_string());
    format!(
        "@raw {} i:{ints} s:{strs} t:{} m:{route} v:{v35}",
        cmd.cid, cmd.term
    )
}

pub(crate) fn hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{b:02x}"));
    }
    s
}

/// Block-structure commands (openers, else, closers) reconstructed by the parser from the
/// readable block syntax. Not subject to the leaf self-check.
pub(crate) fn is_structural(cid: u32) -> bool {
    matches!(cid, 102 | 111 | 112 | 170 | 179 | 420 | 498 | 499)
}

/// Block openers (condition, loop, choose), the structural commands that begin a block and can
/// carry an inline ` @b:HEX` blob suffix under v3.5.
pub(crate) fn is_block_opener(cid: u32) -> bool {
    matches!(cid, 102 | 111 | 112 | 170 | 179)
}

/// Render a resolved name as a token: bare if it is a simple identifier, quoted otherwise, so
/// multi-word names like `Max Party Count` are unambiguous and parser-friendly.
pub(crate) fn name_tok(s: &str) -> String {
    let simple = !s.is_empty() && s.chars().all(|c| c.is_alphanumeric() || c == '_');
    if simple {
        s.to_string()
    } else {
        format!("\"{}\"", escape(s))
    }
}

/// Map an English parameter name (from the glossary) to the User-DB type that holds its entries,
/// so a literal id can be shown as the entry's name. Keyword-based. Falls back to the raw id when
/// the type is not present, so non-Basic-System games degrade gracefully.
pub(crate) fn arg_db_type(en_name: &str) -> Option<&'static str> {
    let n = en_name.to_ascii_lowercase();
    if n.contains("item") {
        Some("アイテム")
    } else if n.contains("weapon") {
        Some("武器")
    } else if n.contains("armor") {
        Some("防具")
    } else if n.contains("skill") {
        Some("技能")
    } else if n.contains("enemy") {
        Some("敵ｷｬﾗ個体ﾃﾞｰﾀ")
    } else if n.contains("state") || n.contains("status") {
        Some("状態設定")
    } else {
        None
    }
}
