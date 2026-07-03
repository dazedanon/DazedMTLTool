//! Whole-file recompile: the document envelope around per-event/page command bodies.
//!
//! [`crate::wolfscript`] renders one command list and [`crate::compile`] parses it back.
//! This layer wraps those so an entire file round-trips. Each event (and map page) is emitted
//! under an identity header (`@commonevent <id>`, or `@event <id>` plus `@page <n>`), its body
//! produced by the gated numeric renderer [`decompile_commands`]. That renderer is `@raw`-free on
//! the corpus, so the document stays readable yet fully recompilable.
//!
//! Recompile is patch-style. The original file supplies every opaque metadata field (event names,
//! page graphics and conditions, the CommonEvent `unknown1..12` tail). Only each command body is
//! swapped back in, keyed by identity. Files whose code is untouched re-emit byte-for-byte. Edited
//! bodies recompile in place. This sidesteps round-tripping the large metadata through text and is
//! the real edit-to-play mod loop.

use std::collections::BTreeMap;

use wolf_formats::common_event::CommonEventsFile;
use wolf_formats::map::Map;
use wolf_formats::{Error, Result};

use crate::compile::compile_commands_enc;
use crate::symbols::SymbolTable;
use crate::text::decode_wstr;
use crate::wolfscript::{decompile_commands_annotated, decompile_commands_enc};

const CE_HEADER: &str = "# wolf-edit common-events";
const MAP_HEADER: &str = "# wolf-edit map";

// ----------------------------------------------------------------------------
// CommonEvents
// ----------------------------------------------------------------------------

/// Render a CommonEvent file as a recompilable edit document: one `@commonevent <id> ... @end`
/// block per event, body in the gated numeric form. Metadata is not emitted. It is taken from the
/// base file at compile time.
pub fn decompile_common_events_edit(ce: &CommonEventsFile) -> String {
    let mut out = format!("{CE_HEADER}  (count={})\n\n", ce.events.len());
    for ev in &ce.events {
        let name = decode_wstr(&ev.name, ce.utf8);
        out.push_str(&format!("@commonevent {}", ev.int_id));
        if !name.is_empty() {
            out.push_str(&format!("  # {}", name.replace('\n', " ")));
        }
        out.push('\n');
        let body = decompile_commands_enc(&ev.commands, ce.utf8);
        out.push_str(&body);
        if !body.ends_with('\n') {
            out.push('\n');
        }
        out.push_str("@end\n\n");
    }
    out
}

/// Like [`decompile_common_events_edit`] but in annotate mode. Each command body uses the unified
/// read-plus-edit form (index-anchored bilingual names, `V[3 "Gold · ゴールド"]`), resolved via
/// `symbols`. Recompiles byte-exact through the same [`compile_common_events_edit`], since the
/// parser strips the labels. Names are read-only decoration the recompiler ignores.
pub fn decompile_common_events_edit_annotated(
    ce: &CommonEventsFile,
    symbols: &SymbolTable,
) -> String {
    let mut out = format!("{CE_HEADER}  (count={})\n\n", ce.events.len());
    for ev in &ce.events {
        let name = decode_wstr(&ev.name, ce.utf8);
        out.push_str(&format!("@commonevent {}", ev.int_id));
        if !name.is_empty() {
            out.push_str(&format!("  # {}", name.replace('\n', " ")));
        }
        out.push('\n');
        let body = decompile_commands_annotated(&ev.commands, ce.utf8, symbols, Some(ev.int_id));
        out.push_str(&body);
        if !body.ends_with('\n') {
            out.push('\n');
        }
        out.push_str("@end\n\n");
    }
    out
}

/// Parse an edit document and substitute each event's command body back into `base`, keyed by
/// `int_id`. Events absent from the document keep their original commands, so partial patches are
/// allowed. An `@commonevent` id with no match in `base` is an error.
pub fn compile_common_events_edit(text: &str, base: &mut CommonEventsFile) -> Result<()> {
    let blocks = parse_blocks(text, "commonevent")?;
    let mut by_id: BTreeMap<u32, usize> = BTreeMap::new();
    for (i, ev) in base.events.iter().enumerate() {
        if by_id.insert(ev.int_id, i).is_some() {
            return Err(Error::invalid(format!(
                "base has duplicate common-event id {}; cannot patch by id unambiguously",
                ev.int_id
            )));
        }
    }
    for blk in blocks {
        let &idx = by_id.get(&blk.id).ok_or_else(|| {
            Error::invalid(format!(
                "@commonevent {} (line {}) has no match in the base file",
                blk.id, blk.line
            ))
        })?;
        let cmds = compile_commands_enc(&blk.body, base.utf8)
            .map_err(|e| Error::invalid(format!("@commonevent {}: {e}", blk.id)))?;
        base.events[idx].commands = cmds;
    }
    Ok(())
}

// ----------------------------------------------------------------------------
// Maps
// ----------------------------------------------------------------------------

/// Render a Map as a recompilable edit document: `@event <id>` then one `@page <n> ... @endpage`
/// per page, each body in the gated numeric form. Coordinates and name are a comment for the
/// reader. Truth comes from the base file at compile time.
pub fn decompile_map_edit(map: &Map) -> String {
    let mut out = format!(
        "{MAP_HEADER}  (version=0x{:x}  {}x{}  events={})\n\n",
        map.version,
        map.width,
        map.height,
        map.events.len()
    );
    for ev in &map.events {
        let name = decode_wstr(&ev.name, map.utf8);
        out.push_str(&format!("@event {}", ev.id));
        if !name.is_empty() {
            out.push_str(&format!(
                "  # {} @({},{})",
                name.replace('\n', " "),
                ev.x,
                ev.y
            ));
        }
        out.push('\n');
        for (pi, page) in ev.pages.iter().enumerate() {
            out.push_str(&format!("@page {pi}\n"));
            let body = decompile_commands_enc(&page.commands, map.utf8);
            out.push_str(&body);
            if !body.ends_with('\n') {
                out.push('\n');
            }
            out.push_str("@endpage\n");
        }
        out.push_str("@endevent\n\n");
    }
    out
}

/// Like [`decompile_map_edit`] but in annotate mode (index-anchored bilingual names), resolved
/// via `symbols`. Recompiles byte-exact through [`compile_map_edit`].
pub fn decompile_map_edit_annotated(map: &Map, symbols: &SymbolTable) -> String {
    let mut out = format!(
        "{MAP_HEADER}  (version=0x{:x}  {}x{}  events={})\n\n",
        map.version,
        map.width,
        map.height,
        map.events.len()
    );
    for ev in &map.events {
        let name = decode_wstr(&ev.name, map.utf8);
        out.push_str(&format!("@event {}", ev.id));
        if !name.is_empty() {
            out.push_str(&format!(
                "  # {} @({},{})",
                name.replace('\n', " "),
                ev.x,
                ev.y
            ));
        }
        out.push('\n');
        for (pi, page) in ev.pages.iter().enumerate() {
            out.push_str(&format!("@page {pi}\n"));
            let body = decompile_commands_annotated(&page.commands, map.utf8, symbols, None);
            out.push_str(&body);
            if !body.ends_with('\n') {
                out.push('\n');
            }
            out.push_str("@endpage\n");
        }
        out.push_str("@endevent\n\n");
    }
    out
}

/// Parse a map edit document and substitute each page's command body back into `base`, keyed by
/// event `id` plus page index. Pages absent from the document keep their commands.
pub fn compile_map_edit(text: &str, base: &mut Map) -> Result<()> {
    let events = parse_map_blocks(text)?;
    let mut by_id: BTreeMap<u32, usize> = BTreeMap::new();
    for (i, ev) in base.events.iter().enumerate() {
        if by_id.insert(ev.id, i).is_some() {
            return Err(Error::invalid(format!(
                "base map has duplicate event id {}; cannot patch by id unambiguously",
                ev.id
            )));
        }
    }
    for ev in events {
        let &idx = by_id.get(&ev.id).ok_or_else(|| {
            Error::invalid(format!(
                "@event {} (line {}) has no match in the base map",
                ev.id, ev.line
            ))
        })?;
        for page in ev.pages {
            let page_count = base.events[idx].pages.len();
            let target = base.events[idx].pages.get_mut(page.index).ok_or_else(|| {
                Error::invalid(format!(
                    "@event {} @page {} out of range (map event has {page_count} pages)",
                    ev.id, page.index,
                ))
            })?;
            let cmds = compile_commands_enc(&page.body, base.utf8).map_err(|e| {
                Error::invalid(format!("@event {} @page {}: {e}", ev.id, page.index))
            })?;
            target.commands = cmds;
        }
    }
    Ok(())
}

// ----------------------------------------------------------------------------
// Document parsing (delimiter-based, so command-body braces never confuse it)
// ----------------------------------------------------------------------------

struct Block {
    id: u32,
    line: u32,
    body: String,
}

/// Parse `@<kind> <id> ...` and `@end` blocks. Lines outside a block must be blank or a `#`
/// comment. The body between the header and `@end` is returned verbatim.
fn parse_blocks(text: &str, kind: &str) -> Result<Vec<Block>> {
    let opener = format!("@{kind} ");
    let mut blocks = Vec::new();
    let mut cur: Option<Block> = None;

    for (i, raw) in text.lines().enumerate() {
        let no = (i + 1) as u32;
        let t = raw.trim();
        match &mut cur {
            None => {
                if let Some(rest) = t.strip_prefix(&opener) {
                    cur = Some(Block {
                        id: parse_id(rest, no)?,
                        line: no,
                        body: String::new(),
                    });
                } else if t.is_empty() || t.starts_with('#') {
                    // header, blank, or comment between blocks
                } else {
                    return Err(Error::invalid(format!(
                        "line {no}: expected `{opener}...`, got {t:?}"
                    )));
                }
            }
            Some(b) => {
                if t == "@end" {
                    blocks.push(cur.take().unwrap());
                } else {
                    b.body.push_str(raw);
                    b.body.push('\n');
                }
            }
        }
    }
    if cur.is_some() {
        return Err(Error::invalid("unterminated @-block (missing @end)"));
    }
    Ok(blocks)
}

struct MapEventBlock {
    id: u32,
    line: u32,
    pages: Vec<MapPageBlock>,
}

struct MapPageBlock {
    index: usize,
    body: String,
}

/// Parse `@event <id>` / `@page <n>` / `@endpage` / `@endevent` nesting.
fn parse_map_blocks(text: &str) -> Result<Vec<MapEventBlock>> {
    let mut events: Vec<MapEventBlock> = Vec::new();
    let mut page: Option<MapPageBlock> = None;

    for (i, raw) in text.lines().enumerate() {
        let no = (i + 1) as u32;
        let t = raw.trim();

        if let Some(p) = &mut page {
            if t == "@endpage" {
                let done = page.take().unwrap();
                events
                    .last_mut()
                    .ok_or_else(|| Error::invalid(format!("line {no}: @endpage outside @event")))?
                    .pages
                    .push(done);
            } else if t == "@endevent" || t.starts_with("@event ") || t.starts_with("@page ") {
                // A structural keyword inside a page body means the page was never closed. Fail
                // loudly rather than swallow the rest of the document into this page.
                return Err(Error::invalid(format!(
                    "line {no}: {t:?} inside a page body (missing @endpage?)"
                )));
            } else {
                p.body.push_str(raw);
                p.body.push('\n');
            }
            continue;
        }

        if let Some(rest) = t.strip_prefix("@event ") {
            events.push(MapEventBlock {
                id: parse_id(rest, no)?,
                line: no,
                pages: Vec::new(),
            });
        } else if let Some(rest) = t.strip_prefix("@page ") {
            let index = parse_id(rest, no)? as usize;
            if events.is_empty() {
                return Err(Error::invalid(format!("line {no}: @page outside @event")));
            }
            page = Some(MapPageBlock {
                index,
                body: String::new(),
            });
        } else if t == "@endevent" || t.is_empty() || t.starts_with('#') {
            // event terminator, header, blank, or comment
        } else {
            return Err(Error::invalid(format!(
                "line {no}: unexpected outside a page body: {t:?}"
            )));
        }
    }
    if page.is_some() {
        return Err(Error::invalid("unterminated @page (missing @endpage)"));
    }
    Ok(events)
}

/// Read the leading integer id from a header tail, such as `5` or `5  # name`.
fn parse_id(rest: &str, no: u32) -> Result<u32> {
    rest.split_whitespace()
        .next()
        .and_then(|s| s.parse().ok())
        .ok_or_else(|| Error::invalid(format!("line {no}: missing/invalid id in {rest:?}")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn map_block_well_formed() {
        let doc = "# wolf-edit map\n@event 3\n@page 0\nMessage \"hi\"\n@endpage\n@endevent\n";
        let evs = parse_map_blocks(doc).expect("parse");
        assert_eq!(evs.len(), 1);
        assert_eq!(evs[0].id, 3);
        assert_eq!(evs[0].pages.len(), 1);
        assert_eq!(evs[0].pages[0].index, 0);
    }

    #[test]
    fn missing_endpage_is_an_error_not_a_swallow() {
        // The `@event 4` must not be swallowed into page 0's body.
        let doc = "@event 3\n@page 0\nMessage \"hi\"\n@event 4\n@page 0\n@endpage\n@endevent\n";
        assert!(
            parse_map_blocks(doc).is_err(),
            "missing @endpage must error"
        );
    }

    #[test]
    fn unterminated_page_at_eof_errors() {
        let doc = "@event 3\n@page 0\nMessage \"hi\"\n";
        assert!(parse_map_blocks(doc).is_err());
    }

    #[test]
    fn ce_blocks_parse_and_reject_stray_lines() {
        let blocks = parse_blocks("@commonevent 7\nMessage \"x\"\n@end\n", "commonevent").unwrap();
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].id, 7);
        // A non-`@commonevent` line between blocks is rejected.
        assert!(parse_blocks("garbage\n@commonevent 1\n@end\n", "commonevent").is_err());
    }
}
