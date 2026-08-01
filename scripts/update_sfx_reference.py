#!/usr/bin/env python3
"""Build the bundled, definitions-only J-Ono SFX reference snapshot.

By default the script downloads the source JSON from the pinned upstream
revision.  ``--source`` accepts an already-downloaded file for offline and test
use.  Manga example metadata and images are deliberately excluded from the
generated asset; only the MIT-licensed dictionary JSON is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "sfx_reference" / "j_ono.json"
UPSTREAM_REPOSITORY = "https://github.com/ObakeConstructs/j-ono-data"
UPSTREAM_REVISION = "673f9f51651122e89948f5ef25794c78efe29f50"
UPSTREAM_PATH = "json/j-ono-data.json"
UPSTREAM_URL = (
    "https://raw.githubusercontent.com/ObakeConstructs/j-ono-data/"
    f"{UPSTREAM_REVISION}/{UPSTREAM_PATH}"
)


def _read_source(path: Path | None) -> bytes:
    if path is not None:
        return path.read_bytes()
    with urlopen(UPSTREAM_URL, timeout=60) as response:  # noqa: S310 - pinned URL
        return response.read()


def _clean_strings(values) -> list[str]:
    cleaned: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def compact_dataset(raw: bytes) -> dict:
    source = json.loads(raw.decode("utf-8"))
    if not isinstance(source, list):
        raise ValueError("J-Ono source must be a JSON array")

    records = {}
    for record in source:
        record_id = str(record.get("id") or "").strip()
        if not record_id or record_id in records:
            raise ValueError(f"Missing or duplicate J-Ono id: {record_id!r}")
        records[record_id] = record

    def resolve_definition(record_id: str, index: int, stack=()) -> dict:
        key = (record_id, index)
        if key in stack:
            raise ValueError(f"Cyclic J-Ono definition reference: {key!r}")
        try:
            definition = records[record_id]["definition"][index]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Invalid J-Ono definition reference: {key!r}") from exc

        equivalents: list[str] = []
        meanings: list[str] = []
        effect_type = ""
        reference = str(definition.get("refer") or "").strip()
        if reference:
            target_id, separator, target_number = reference.rpartition(":")
            if not separator or not target_number.isdigit() or int(target_number) < 1:
                raise ValueError(f"Malformed J-Ono reference: {reference!r}")
            inherited = resolve_definition(
                target_id, int(target_number) - 1, stack + (key,)
            )
            equivalents.extend(inherited["equivalents"])
            meanings.extend(inherited["meanings"])
            effect_type = inherited["type"]

        for equivalent in _clean_strings(definition.get("equivalent")):
            if equivalent not in equivalents:
                equivalents.append(equivalent)
        meaning = str(definition.get("meaning") or "").strip()
        # A handful of referenced upstream records use the one-letter value
        # "s" as an internal "same" marker. It is not a usable definition.
        if meaning == "s":
            meaning = ""
        if meaning and meaning not in meanings:
            meanings.append(meaning)
        effect_type = str(definition.get("type") or "").strip() or effect_type
        if effect_type not in {"o", "v", "s", "m", "e", "c", ""}:
            raise ValueError(f"Unknown J-Ono SFX type: {effect_type!r}")
        return {
            "equivalents": equivalents,
            "meanings": meanings,
            "type": effect_type,
        }

    entries = []
    for record_id, record in records.items():
        hiragana = _clean_strings(record.get("hiragana"))
        katakana = _clean_strings(record.get("katakana"))
        variants = hiragana + [item for item in katakana if item not in hiragana]
        if not variants:
            raise ValueError(f"J-Ono record has no kana variants: {record_id!r}")
        definitions = record.get("definition") or []
        senses = [
            resolve_definition(record_id, index)
            for index in range(len(definitions))
        ]
        senses = [sense for sense in senses if sense["equivalents"] or sense["meanings"]]
        if not senses:
            raise ValueError(f"J-Ono record has no usable definitions: {record_id!r}")
        entries.append({
            "id": record_id,
            "variants": variants,
            "romaji": _clean_strings(record.get("romaji")),
            "senses": senses,
        })

    return {
        "schema_version": 1,
        "source": {
            "name": "J-Ono Data",
            "repository": UPSTREAM_REPOSITORY,
            "revision": UPSTREAM_REVISION,
            "path": UPSTREAM_PATH,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "license": "MIT",
        },
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Use a local upstream JSON file")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    compact = compact_dataset(_read_source(args.source))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(compact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {len(compact['entries'])} SFX records to {args.output} "
        f"from {UPSTREAM_REVISION}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
