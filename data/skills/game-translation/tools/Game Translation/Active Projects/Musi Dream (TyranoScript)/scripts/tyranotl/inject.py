"""Write translations back into the project files.

Injection is a pure span splice: every site records ``(file, line, start, end)``
in the *original* line, so applying the sites of a line right-to-left rebuilds it
without any re-parsing. Two properties are asserted rather than assumed:

* the lexer reproduces every source file byte-for-byte, and
* every site's recorded ``raw`` still equals the characters at its span.

``tl.py selftest`` runs both against the real project before a token is spent.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import codes, jsstr, kslex
from .store import Site, Store, Unit


@dataclass
class Patch:
    start: int
    end: int
    text: str
    unit: str


class Conflict(Exception):
    pass


#: Sites whose text is read back out of a *quoted KAG attribute*, and therefore
#: has to survive the parser deleting literal spaces. ``iscript`` bodies and the
#: engine ``.js`` files are raw source that ``makeTag`` never sees, so their
#: spaces are safe and must be left alone - an NBSP in raw JS outside a string
#: literal would be a syntax error.
_RAW_TAGS = ("iscript", "js")


def inside_kag_attribute(site: Site) -> bool:
    """Is this site's text read back out of a quoted KAG attribute value?

    ``attr`` / ``nested``  a KAG attribute value                    -> yes
    ``jsstr``              a JS literal, which may sit inside an ``exp=`` /
                           ``cond=`` attribute (``site.tag`` is then the KAG
                           tag name) or in an ``[iscript]`` body or a plain
                           ``.js`` file, neither of which ``makeTag`` sees
    ``bare``               message text, outside any tag            -> no
    """
    if site.form in ("attr", "nested"):
        return True
    return site.form == "jsstr" and site.tag not in _RAW_TAGS


def render(unit: Unit, site: Site, units: dict[str, Unit] | None = None) -> str:
    """The literal characters that replace this site's span.

    ``en is None`` means untranslated; ``en == ""`` means deliberately empty,
    which is a real answer for a fragment with no English counterpart - the
    counter reads "同居3日目" in Japanese and simply "Day 3" in English, so the
    trailing 日目 translates to nothing at all.
    """
    if unit.en is None:
        return site.raw
    tokens = list(site.tokens)
    for token_index, start, end, child_id in site.nested:
        child = (units or {}).get(child_id)
        if child is None or not child.en:
            continue
        child_site = next((s for s in child.sites if s.form == "nested"
                           and s.raw == tokens[token_index][start:end]), child.sites[0])
        replacement = render(child, child_site, units)
        tokens[token_index] = tokens[token_index][:start] + replacement + tokens[token_index][end:]
    text = codes.restore(unit.en, tokens)

    # musi_dream ships KeepSpaceInParameterValue=2. Its own parser preserves
    # internal ASCII spaces. Do not copy the reference game's NBSP workaround.

    if site.form in ("jsstr",):
        quote = site.quote or "'"
        return quote + jsstr.encode(text, quote) + quote

    if site.form in ("attr", "nested"):
        if not site.quote:
            # An unquoted attribute value cannot contain whitespace.
            return text if not any(c.isspace() for c in text) else '"' + text.replace('"', "'") + '"'
        quote = site.quote
        if quote in text:
            other = "'" if quote == '"' else '"'
            quote = other if other not in text else quote
        if quote in text:
            raise ValueError("Attribute contains both quote styles; use typographic quotes or revise the wording")
        return quote + text + quote

    return text


def collect(store: Store) -> dict[str, dict[int, list[Patch]]]:
    out: dict[str, dict[int, list[Patch]]] = defaultdict(lambda: defaultdict(list))
    units = store.by_id()
    for unit in store.all_units():
        for site in unit.sites:
            if site.form == "nested":
                continue   # spliced into its parent's token map instead
            out[site.file][site.line].append(
                Patch(site.start, site.end, render(unit, site, units), unit.id))
    return out


def apply_to_line(text: str, patches: list[Patch]) -> str:
    ordered = sorted(patches, key=lambda p: (p.start, p.end))
    last = 0
    for patch in ordered:
        if patch.start < last:
            raise Conflict(f"overlapping spans at offset {patch.start} (unit {patch.unit})")
        last = patch.end
    for patch in reversed(ordered):
        text = text[:patch.start] + patch.text + text[patch.end:]
    return text


def _adjacent_tag(text: str, at_end: bool) -> str:
    """Name of the tag flush against this edge of the text, if any."""
    for m in codes.TAG_RE.finditer(text):
        if (m.end() == len(text)) if at_end else (m.start() == 0):
            if at_end or m.start() == 0:
                return m.group(1)
    return ""


def pad_inline_inserts(line_text: str, patch: Patch, emitters: set[str]) -> str:
    """Space a translated run off an inline word-insert that sits next to it.

    ``split_affixes`` peels a leading or trailing run of tags off the unit so the
    model sees clean text, which means an emitter sitting right against the run -
    ``[emb exp="f.name2"]で宜しいでしょうか。`` - is *outside* the unit and cannot
    be fixed from inside it. Japanese needed no space there; English does, or the
    player reads "NeroIs that alright?".
    """
    if not emitters or not patch.text:
        return patch.text
    text = patch.text
    before = _adjacent_tag(line_text[:patch.start], at_end=True)
    if before in emitters and codes.WORD_RE.match(text[0]):
        text = " " + text
    after = _adjacent_tag(line_text[patch.end:], at_end=False)
    if after in emitters and codes.WORD_RE.match(text[-1]):
        text = text + " "
    return text


def write(app_root: Path, out_root: Path, store: Store,
          emitters: set[str] | None = None) -> tuple[int, int]:
    """Render every touched file into ``out_root``. Returns ``(files, spans)``."""
    patches = collect(store)
    emitters = emitters or set()
    files = spans = 0
    for rel, by_line in sorted(patches.items()):
        script = kslex.read(app_root / rel, rel)
        for line in script.lines:
            todo = by_line.get(line.number)
            if not todo:
                continue
            todo = [Patch(p.start, p.end, pad_inline_inserts(line.text, p, emitters), p.unit)
                    for p in todo]
            line.text = apply_to_line(line.text, todo)
            spans += len(todo)
        target = out_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(script.render().encode("utf-8"))
        files += 1
    return files, spans


def verify(app_root: Path, store: Store) -> list[str]:
    """Prove the extraction is reversible before anything is translated."""
    problems: list[str] = []
    by_file: dict[str, list[tuple[Unit, Site]]] = defaultdict(list)
    for unit in store.all_units():
        for site in unit.sites:
            by_file[site.file].append((unit, site))

    for rel, entries in sorted(by_file.items()):
        source = app_root / rel
        original = source.read_bytes()
        script = kslex.read(source, rel)
        if script.render().encode("utf-8") != original:
            problems.append(f"{rel}: lexer does not round-trip")
            continue

        lines = {line.number: line.text for line in script.lines}
        for unit, site in entries:
            if site.form == "nested":
                plain = codes.restore(unit.src, site.tokens)
                if site.quote + plain + site.quote != site.raw:
                    problems.append(f"{rel}:{site.line}: nested attribute mask is lossy")
                continue
            text = lines.get(site.line)
            if text is None:
                problems.append(f"{rel}:{site.line}: line missing")
                continue
            actual = text[site.start:site.end]
            if actual != site.raw:
                problems.append(
                    f"{rel}:{site.line}: span drifted -> {actual!r} != {site.raw!r}")
                continue
            plain = codes.restore(unit.src, site.tokens)
            expected = plain
            if site.form == "jsstr":
                expected = site.quote + jsstr.encode(plain, site.quote) + site.quote
                if jsstr.decode(site.raw[1:-1]) != plain:
                    problems.append(f"{rel}:{site.line}: JS literal does not decode to unit source")
            elif site.form == "attr":
                expected = site.quote + plain + site.quote if site.quote else plain
                if expected != site.raw:
                    problems.append(f"{rel}:{site.line}: attribute mask is lossy")
            elif plain != site.raw:
                problems.append(f"{rel}:{site.line}: message mask is lossy")

        patched = kslex.read(source, rel)
        for line in patched.lines:
            todo = [Patch(s.start, s.end, s.raw, u.id)
                    for u, s in entries if s.line == line.number and s.form != "nested"]
            if todo:
                line.text = apply_to_line(line.text, todo)
        if patched.render().encode("utf-8") != original:
            problems.append(f"{rel}: identity injection is not byte-identical")

    return problems
