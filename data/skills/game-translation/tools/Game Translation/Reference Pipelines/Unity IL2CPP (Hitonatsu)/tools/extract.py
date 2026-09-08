"""Extract every player-facing Japanese string into workspace/units.json.

Three sources, each with its own id namespace so a unit is traceable back to the
exact object it came from:

  db:<conversationId>:<entryId>:<field>   PixelCrushers Dialogue Database
  ui:<fileID>:<fieldpath>                 Release.unity MonoBehaviour fields
  lit:<n>                                 curated IL2CPP string literals

Delivery is a runtime dictionary keyed on the source string, so the ids are for
review and traceability; the injector matches on `src`. Ids still matter: two
units may share a source string and need different English (see `dedupe`).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hitonatsu import common as C  # noqa: E402
from hitonatsu import classify as K  # noqa: E402
from hitonatsu import unityyaml as uy  # noqa: E402
from hitonatsu import voiceopts as V  # noqa: E402

NORM_INDEX = re.compile(r"\[\d+\]")

# IL2CPP literals that are drawn on screen. Everything else in the metadata is a
# Debug.Log string, a .NET calendar era name, or a Unicode range table.
#
# Ruled on individually because a literal carries no context of its own - the only
# thing that says whether a string is drawn or is a .NET internal is which method
# loads it. Each entry names where it is used, and literal caller analysis is how
# that was established rather than assumed. See the note below on 年/月/日.
LITERALS = {
    "デフォルト": "VoiceFaceOverrideController - dropdown caption when no set is chosen.",
    "デフォルト（余韻）": "VoiceFaceOverrideController - afterglow dropdown caption.",
    "余韻": "Voice category label (afterglow).",
    "喘ぎ": "Voice category label (moaning).",
    "絶頂": "Voice category label (climax).",
    "未設定のセット": "Placeholder shown for an unnamed ReplaceSet.",
    "未設定の項目": "Placeholder shown for an unnamed override entry.",
    "美羽": "Character name (Miu). Appears in code, not in the dialogue database.",
}

# 年/月/日/時/分/秒 are NOT extracted, and the reason is worth keeping.
#
# They look exactly like a playtime readout waiting to be translated. They are
# not. literal caller analysis resolves every one of them to
# System.Globalization.DateTimeFormatInfoScanner.get_KnownWords and
# DateTimeFormatInfo.PopulateSpecialTokenHashTable - they are .NET's Japanese
# calendar token tables, reachable from no game code.
#
# The actual playtime is GameInfoManager.UpdateTimerText (RVA 0x776B00), which
# builds String.Format("{0:D2}:{1:D2}:{2:D2}", h, m, s) - language-neutral
# HH:MM:SS with no Japanese in it at all.
#
# Translating them would have put a live `分` -> `m` rule in a dictionary that is
# applied to every string reaching a text component, for no gain.


def norm_path(p: str) -> str:
    return NORM_INDEX.sub("[]", p)


def extract_database() -> list[dict]:
    """Walk the Dialogue Database, taking only the fields ruled DISPLAY."""
    db = uy.single(C.DIALOGUE_DB)
    actors = {}
    for a in db.get("actors") or []:
        f = {x.get("title"): x.get("value") for x in (a.get("fields") or [])}
        actors[a.get("id")] = {
            "name": f.get("Name"),
            "is_player": str(f.get("IsPlayer")).lower() == "true",
        }

    units = []
    for conv in db.get("conversations") or []:
        cid = conv.get("id")
        cfields = {x.get("title"): x.get("value") for x in (conv.get("fields") or [])}
        ctitle = cfields.get("Title")
        entries = conv.get("dialogueEntries") or []
        for order, entry in enumerate(entries):
            eid = entry.get("id")
            fields = {x.get("title"): x.get("value") for x in (entry.get("fields") or [])}
            actor_id = entry.get("ActorID", fields.get("Actor"))
            try:
                actor_id = int(actor_id)
            except (TypeError, ValueError):
                actor_id = None
            actor = actors.get(actor_id, {})
            # Sequence carries the voice clip id (e.g. "Voice(Story_0101_01)"), which
            # encodes day/scene/line. It is the only reliable ordering signal here -
            # the entries are a graph, not a list, and their ids are not in play order.
            seq = fields.get("Sequence") or ""
            m = re.search(r"Voice\(([^)]+)\)", seq)
            voice = m.group(1) if m else None
            for title, value in fields.items():
                if not C.has_jp(value):
                    continue
                kind = K.classify(title, K.DB_DISPLAY, K.DB_INTERNAL)
                if kind != "display":
                    continue
                masked, codes = C.mask(value)
                units.append({
                    "id": f"db:{cid}:{eid}:{title.replace(' ', '')}",
                    "kind": "choice" if title == "Menu Text" else "dialogue",
                    "src": value,
                    "masked": masked,
                    "codes": codes,
                    "speaker_id": actor_id,
                    "speaker": actor.get("name"),
                    "is_player": actor.get("is_player"),
                    "conversation": ctitle,
                    "voice": voice,
                    "scene": voice.rsplit("_", 1)[0] if voice else None,
                    "note": fields.get("Description"),
                    "order": order,
                    "outgoing": [l.get("destinationDialogueID")
                                 for l in (entry.get("outgoingLinks") or [])],
                    "tl": "",
                })
    return units


def extract_scene() -> list[dict]:
    """Walk Release.unity. Any JP path not ruled on raises and stops the run."""
    units = []
    for _cls, fid, doc in uy.documents(C.SCENE):
        for path, value in uy.walk(doc):
            if not C.has_jp(value):
                continue
            kind = K.classify(norm_path(path), K.DISPLAY, K.INTERNAL)
            if kind != "display":
                continue
            masked, codes = C.mask(value)
            units.append({
                "id": f"ui:{fid}:{path}",
                "kind": "dropdown" if ("dropdown" in path.lower()
                                       or "m_Options" in path) else "ui",
                "src": value,
                "masked": masked,
                "codes": codes,
                "field": norm_path(path),
                "why": K.DISPLAY[norm_path(path)],
                "tl": "",
            })
    return units


def extract_literals() -> list[dict]:
    """Curated IL2CPP literals, verified present in the shipped metadata."""
    present = set()
    if os.path.exists(C.STRINGLITERAL):
        data = json.load(open(C.STRINGLITERAL, encoding="utf-8"))
        for row in data:
            v = row.get("value") if isinstance(row, dict) else row
            if isinstance(v, str):
                present.add(v)

    units = []
    for i, (src, why) in enumerate(sorted(LITERALS.items())):
        if present and src not in present:
            raise SystemExit(
                f"literal {src!r} is not in the shipped metadata any more - the game "
                f"build changed. Re-check tools/extract.py LITERALS."
            )
        masked, codes = C.mask(src)
        units.append({
            "id": f"lit:{i}", "kind": "literal", "src": src, "masked": masked,
            "codes": codes, "why": why, "tl": "",
        })
    return units


def extract_voice_options() -> list[dict]:
    """The runtime-built voice dropdown. Translated by construction, not by the model."""
    import catalog_addresses as CA

    if not os.path.exists(CA.CATALOG):
        raise SystemExit(f"missing {CA.CATALOG} - cannot enumerate the voice dropdown")
    runs = CA.utf16_strings(open(CA.CATALOG, "rb").read())
    addrs = V.addresses(runs)
    if not addrs:
        raise SystemExit(
            "found no OverrideVoice addresses in catalog.bin. Either the game build "
            "changed the address scheme, or the UTF-16LE read broke - do not ship a "
            "silently empty voice dropdown."
        )

    units = []
    for i, addr in enumerate(addrs):
        en = V.translate(addr)
        masked, codes = C.mask(addr)
        units.append({
            "id": f"voice:{i}",
            "kind": "voice",
            "src": addr,
            "masked": masked,
            "codes": codes,
            "tl": en,
            "locked": True,
            "why": "TMP_Dropdown option built at runtime from the Addressables address "
                   "(ReplaceSet.setName, RVA 0x792780). Generated, so the whole family "
                   "stays consistent by construction.",
        })
    return units


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=C.UNITS)
    args = ap.parse_args()

    units = (extract_database() + extract_scene() + extract_literals()
             + extract_voice_options())

    # Refuse to shrink the store. Extraction reads the game folder, and once a
    # patch is installed there that folder is the ENGLISH build - a re-run would
    # find nothing and cheerfully save the emptiness over real work.
    if os.path.exists(args.out):
        old = json.load(open(args.out, encoding="utf-8"))
        if len(units) < len(old.get("units", [])) * 0.9:
            raise SystemExit(
                f"refusing to write: found {len(units)} units but the store already holds "
                f"{len(old['units'])}. Extraction probably ran against a patched build. "
                f"Pass --out elsewhere if this shrink is genuinely intended."
            )
        by_id = {u["id"]: u for u in old.get("units", [])}
        for u in units:
            if u.get("locked"):
                continue   # generated: the source of truth is the generator
            prev = by_id.get(u["id"])
            if prev and prev.get("tl"):
                u["tl"] = prev["tl"]
                u["locked"] = prev.get("locked", False)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    counts: dict[str, int] = {}
    for u in units:
        counts[u["kind"]] = counts.get(u["kind"], 0) + 1
    doc = {
        "game": "ひと夏の思い出",
        "source": {"database": C.DIALOGUE_DB, "scene": C.SCENE,
                   "literals": C.STRINGLITERAL},
        "counts": counts,
        "distinct_sources": len({u["src"] for u in units}),
        "units": units,
    }
    json.dump(doc, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"units: {len(units)}  distinct sources: {doc['distinct_sources']}")
    for k in sorted(counts):
        print(f"  {counts[k]:>4}  {k}")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
