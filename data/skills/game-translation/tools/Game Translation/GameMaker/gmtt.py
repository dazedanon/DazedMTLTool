"""GameMaker Text Tools: inspection, literal-site export, validation and patching.

Python 3.10+, standard library. The pinned UTMT CLI handles VM bytecode and
archive relocation; an independent FORM/STRG reader checks its text output.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\U00020000-\U000323af]")
SENTINEL = re.compile(r"⟦GM:\d{4,}⟧")


class ToolError(ValueError):
    pass


@contextmanager
def work_directory(root, prefix):
    # Python 3.13+ mkdtemp's Windows mode=0700 DACL excludes sandbox identities.
    # Inherit the explicitly chosen workspace directory's permissions instead.
    root = Path(root).resolve()
    folder = root / (prefix + uuid.uuid4().hex)
    folder.mkdir()
    try:
        yield folder
    finally:
        resolved = folder.resolve()
        if resolved.parent != root or folder.is_symlink():
            raise ToolError("Refusing cleanup outside the requested work directory")
        shutil.rmtree(resolved)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ToolError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects prior translation work and build reports.
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def raw_archive(path):
    """Strict, independent reader. Chunk offsets and lengths are bytes."""
    b = Path(path).read_bytes()

    def u32(pos):
        if pos < 0 or pos + 4 > len(b):
            raise ToolError(f"Truncated uint32 at {pos:#x}")
        return struct.unpack_from("<I", b, pos)[0]

    if len(b) < 8 or b[:4] != b"FORM":
        raise ToolError("Expected a GameMaker FORM archive")
    if u32(4) != len(b) - 8:
        raise ToolError("FORM size does not match file length")
    chunks, tags, pos = [], set(), 8
    while pos < len(b):
        if pos + 8 > len(b):
            raise ToolError("Truncated chunk header")
        tag_bytes, size = b[pos:pos + 4], u32(pos + 4)
        if not re.fullmatch(rb"[A-Z0-9]{4}", tag_bytes):
            raise ToolError(f"Invalid chunk tag at {pos:#x}")
        tag = tag_bytes.decode("ascii")
        if tag in tags or pos + 8 + size > len(b):
            raise ToolError(f"Duplicate or out-of-bounds chunk: {tag}")
        tags.add(tag)
        chunks.append({"tag": tag, "offset": pos, "size": size})
        pos += 8 + size
    chunk = next((c for c in chunks if c["tag"] == "STRG"), None)
    if chunk is None or chunk["size"] < 4:
        raise ToolError("Missing or truncated STRG chunk")
    start, end = chunk["offset"] + 8, chunk["offset"] + 8 + chunk["size"]
    count = u32(start)
    table_end = start + 4 + count * 4
    if table_end > end:
        raise ToolError("STRG pointer table exceeds chunk")
    strings, records = [], []
    for index in range(count):
        ptr = u32(start + 4 + index * 4)
        if ptr < table_end or ptr + 4 > end:
            raise ToolError(f"STRG[{index}] points outside string records")
        length = u32(ptr)
        if ptr + 4 + length >= end or b[ptr + 4 + length] != 0:
            raise ToolError(f"STRG[{index}] length/terminator invalid")
        try:
            text = b[ptr + 4:ptr + 4 + length].decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ToolError(f"STRG[{index}] invalid UTF-8") from exc
        strings.append(text)
        records.append({"id": index, "offset": ptr, "utf8_bytes": length})
    return {"size": len(b), "sha256": hashlib.sha256(b).hexdigest(),
            "chunks": chunks, "strings": strings, "records": records}


def run_utmt(arguments, env=None, log=None):
    exe = Path(os.environ.get("GMTT_UTMT", ROOT / "vendor/utmt/UndertaleModCli.exe"))
    if not exe.is_file():
        raise ToolError("UTMT missing. Run bootstrap.py first, or set GMTT_UTMT.")
    result = subprocess.run([str(exe), *map(str, arguments)], env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    if log:
        Path(log).write_text(result.stdout, encoding="utf-8")
    if result.returncode:
        raise ToolError(f"UTMT exited {result.returncode}:\n{result.stdout[-6000:]}")
    return result.stdout


def bridge(data, config, folder, output=None):
    folder = Path(folder)
    request = folder / "request.json"
    write_json(request, config)
    env = os.environ.copy()
    env["GMTT_REQUEST"] = str(request.resolve())
    args = ["load", Path(data).resolve(), "-s", ROOT / "bridge.csx"]
    if output is not None:
        args += ["-o", Path(output).resolve()]
    run_utmt(args, env, folder / "utmt.log")


def snapshot(data):
    initial_hash = sha256(data)
    temp_root = Path(os.environ.get("GMTT_TEMP_DIR", Path.cwd())).resolve()
    with work_directory(temp_root, ".gmtt-read-") as tmp:
        out = Path(tmp) / "snapshot.json"
        bridge(data, {"mode": "snapshot", "output": str(out)}, tmp)
        if not out.is_file():
            raise ToolError("UTMT returned without producing the snapshot")
        result = read_json(out)
    raw = raw_archive(data)
    if raw["sha256"] != initial_hash:
        raise ToolError("Archive changed while being inspected")
    if result["strings"] != raw["strings"]:
        raise ToolError("Independent STRG reader disagrees with UTMT")
    result["source_sha256"] = raw["sha256"]
    result["source_size"] = raw["size"]
    return result


def mask(text, patterns):
    if "⟦GM:" in text:
        raise ToolError("Source collides with reserved control-code sentinel")
    if not patterns:
        return text, []
    matcher = re.compile("|".join(f"(?:{p})" for p in patterns))
    tokens = []

    def replacement(match):
        if not match.group():
            raise ToolError("Control-code regex matched an empty string")
        token = f"⟦GM:{len(tokens):04d}⟧"
        tokens.append({"token": token, "value": match.group()})
        return token
    return matcher.sub(replacement, text), tokens


def restore(text, tokens):
    expected = [t["token"] for t in tokens]
    if SENTINEL.findall(text) != expected:
        raise ToolError("Missing, added, duplicated or reordered control-code sentinel")
    values = {t["token"]: t["value"] for t in tokens}
    result = SENTINEL.sub(lambda m: values[m.group()], text)
    if "⟦GM:" in result:
        raise ToolError("Malformed control-code sentinel")
    return result


def site_map(snap):
    sites = {}
    for code in snap["code"]:
        for ins in code["instructions"]:
            sid = ins["string_id"]
            if sid < 0:
                continue
            ci, ii = code["index"], ins["index"]
            start, stop = max(0, ii - 3), ii + 4
            context = []
            for near in code["instructions"][start:stop]:
                text = near["asm"]
                if near["string_id"] >= 0:
                    text += " " + json.dumps(snap["strings"][near["string_id"]], ensure_ascii=False)
                context.append(f"{near['index']}: {text}")
            sites[f"CODE:{ci}:{ii}"] = {
                "string_id": sid, "source": snap["strings"][sid], "code_index": ci,
                "instruction_index": ii, "code_name": code["name"], "context": context,
            }
    sid = snap["display_name_id"]
    if sid >= 0:
        sites["GEN8:display_name"] = {"string_id": sid, "source": snap["strings"][sid],
                                      "context": ["Game window caption"]}
    return sites


def make_catalog(snap, selection="cjk", patterns=None):
    if snap["yyc"]:
        raise ToolError("YYC: native code literals are not supported; inspect the pool and native executable separately")
    patterns = [r"\r\n|\r|\n"] if patterns is None else patterns
    entries = []
    for site, info in site_map(snap).items():
        source = info["source"]
        if selection == "cjk" and not CJK.search(source):
            continue
        masked, tokens = mask(source, patterns)
        entries.append({"id": site, **info, "masked_source": masked, "tokens": tokens,
                        "translation": None, "reviewed": False,
                        "font": None, "max_width": None, "max_lines": None})
    return {"schema": 1, "engine": "GameMaker", "source_sha256": snap["source_sha256"],
            "source_size": snap["source_size"], "selection": selection,
            "token_patterns": patterns, "entries": entries}


def font_measure(text, font):
    """Explicit lines, advances and kerning only; no assumed runtime wrapping."""
    glyphs = {g["char"]: g for g in font["glyphs"]}
    missing, widths = set(), []
    for line in re.split(r"\r\n|\r|\n", text):
        width, previous = 0, None
        for ch in line:
            g = glyphs.get(ord(ch))
            if g is None:
                missing.add(ch)
                previous = None
                continue
            width += g["advance"]
            if previous is not None:
                width += next((k["shift"] for k in g["kerning"] if k["char"] == previous), 0)
            previous = ord(ch)
        widths.append(width * font["scale_x"])
    return {"missing_glyphs": sorted(missing), "line_widths": widths, "lines": len(widths)}


def validate_catalog(catalog, snap, require_complete=False):
    errors, warnings, changes, seen = [], [], [], set()
    if catalog.get("schema") != 1:
        raise ToolError("Unsupported catalog schema")
    if catalog.get("source_sha256") != snap["source_sha256"] or catalog.get("source_size") != snap["source_size"]:
        raise ToolError("Catalog belongs to a different source archive; export from the original build")
    if snap["yyc"]:
        raise ToolError("Literal-site patching requires VM bytecode")
    sites = site_map(snap)
    fonts = {f["name"]: f for f in snap["fonts"]}
    patterns = catalog["token_patterns"]
    for entry in catalog["entries"]:
        site = entry["id"]
        if site in seen:
            errors.append(f"{site}: duplicate site")
            continue
        seen.add(site)
        original = sites.get(site)
        if original is None or any(entry.get(k) != original.get(k) for k in ("source", "string_id", "code_index", "instruction_index")):
            errors.append(f"{site}: unknown site or stale source/coordinates")
            continue
        masked, tokens = mask(original["source"], patterns)
        if entry.get("masked_source") != masked or entry.get("tokens") != tokens:
            errors.append(f"{site}: modified source mask or token map")
            continue
        translated = entry.get("translation")
        if translated is None:
            if require_complete:
                errors.append(f"{site}: missing translation")
            continue
        if not isinstance(translated, str):
            errors.append(f"{site}: translation must be a string or null")
            continue
        try:
            text = restore(translated, tokens)
            text.encode("utf-8", errors="strict")
            _, restored_tokens = mask(text, patterns)
            if [t["value"] for t in restored_tokens] != [t["value"] for t in tokens]:
                raise ToolError("Added or altered raw control code; use the exported sentinels")
        except (ToolError, UnicodeError) as exc:
            errors.append(f"{site}: {exc}")
            continue
        if text == original["source"]:
            if require_complete and CJK.search(text):
                errors.append(f"{site}: source language remains")
            continue
        if entry.get("reviewed") is not True:
            errors.append(f"{site}: mark reviewed=true only after checking this use in GML")
        if "\x00" in text:
            errors.append(f"{site}: embedded NUL in replacement")
        if not text and original["source"]:
            errors.append(f"{site}: empty replacement")
        if CJK.search(text):
            (errors if require_complete else warnings).append(f"{site}: source-language characters remain")
        if len(text) > max(80, len(original["source"]) * 3):
            warnings.append(f"{site}: substantial expansion; check runtime layout")
        font_name = entry.get("font")
        if font_name is None:
            warnings.append(f"{site}: font/layout unmeasured")
        elif font_name not in fonts:
            errors.append(f"{site}: unknown font {font_name}")
        elif tokens:
            warnings.append(f"{site}: font/layout requires rendered control-code expansion")
        else:
            measure = font_measure(text, fonts[font_name])
            if measure["missing_glyphs"]:
                errors.append(f"{site}: glyphs missing from {font_name}: {measure['missing_glyphs']}")
            if entry.get("max_width") is not None and max(measure["line_widths"], default=0) > entry["max_width"]:
                errors.append(f"{site}: explicit line exceeds max_width")
            if entry.get("max_lines") is not None and measure["lines"] > entry["max_lines"]:
                errors.append(f"{site}: explicit lines exceed max_lines")
        changes.append({"id": site, **{k: original[k] for k in ("source", "string_id", "code_index", "instruction_index") if k in original}, "text": text})
    return {"errors": errors, "warnings": warnings, "changes": changes,
            "entries": len(catalog["entries"]), "changed_sites": len(changes)}


def verify_snapshots(before, after, changes):
    """Verify every instruction, original string, resource identity, font and media hash."""
    expected = copy.deepcopy(before)
    for change in changes:
        sid = len(expected["strings"])
        expected["strings"].append(change["text"])
        if change["id"] == "GEN8:display_name":
            expected["display_name_id"] = sid
        else:
            expected["code"][change["code_index"]]["instructions"][change["instruction_index"]]["string_id"] = sid
    checked = [k for k in expected if k not in {"source_sha256", "source_size"}]
    mismatches = [k for k in checked if expected[k] != after.get(k)]
    if mismatches:
        raise ToolError("Patched archive verification failed: " + ", ".join(mismatches))
    return {"checked": checked, "changed_sites": len(changes), "original_strings_preserved": len(before["strings"]),
            "instructions_checked": sum(len(c["instructions"]) for c in before["code"]),
            "output_sha256": after["source_sha256"]}


def reject_existing(path):
    if Path(path).exists():
        raise ToolError(f"Destination exists; choose a fresh output to preserve prior work: {path}")


def export_catalog(data, output, selection, patterns):
    reject_existing(output)
    snap = snapshot(data)
    catalog = make_catalog(snap, selection, patterns)
    write_json(output, catalog)
    print(json.dumps({"catalog": str(output), "entries": len(catalog["entries"]),
                      "unique_strings": len({e['string_id'] for e in catalog['entries']})}))


def patch_archive(data, catalog_path, output):
    data, output = Path(data).resolve(), Path(output).resolve()
    if data == output:
        raise ToolError("Use a separate output archive; in-place writes are not supported")
    reject_existing(output)
    report_path = Path(str(output) + ".report.json")
    reject_existing(report_path)
    before = snapshot(data)
    catalog_hash = sha256(catalog_path)
    catalog = read_json(catalog_path)
    validation = validate_catalog(catalog, before)
    if validation["errors"]:
        raise ToolError("Validation failed:\n" + "\n".join(validation["errors"]))
    changes = validation["changes"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with work_directory(output.parent, ".gmtt-build-") as tmp:
        temp_output = Path(tmp) / "patched.win"
        if changes:
            receipt = Path(tmp) / "receipt.json"
            bridge(data, {"mode": "patch", "changes": changes, "receipt": str(receipt)}, tmp, temp_output)
            if not receipt.exists() or read_json(receipt).get("changed") != len(changes) or not temp_output.is_file():
                raise ToolError("UTMT did not produce the requested patch and receipt")
        else:
            shutil.copyfile(data, temp_output)
        after = snapshot(temp_output)
        verification = verify_snapshots(before, after, changes)
        if not changes and before["source_sha256"] != after["source_sha256"]:
            raise ToolError("No-op output is not byte-identical")
        if sha256(data) != before["source_sha256"]:
            raise ToolError("Source archive changed during build")
        if sha256(catalog_path) != catalog_hash:
            raise ToolError("Catalog changed during build")
        report = {"schema": 1, "source_sha256": before["source_sha256"],
                  "catalog_sha256": catalog_hash, "verification": verification,
                  "warnings": validation["warnings"], "changes": changes,
                  "runtime_tested": False, "no_op_byte_identical": not changes}
        # link creates an exclusive final path; never overwrite a racing writer.
        os.link(temp_output, output)
        write_json(report_path, report)
    print(json.dumps({"output": str(output), "changed_sites": len(changes),
                      "verified": True, "warnings": len(validation['warnings']), "report": str(report_path)}))


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "snapshot", "census", "export", "decompile", "validate", "patch", "verify"):
        p = subs.add_parser(name)
        p.add_argument("data", type=Path)
        if name in {"snapshot", "census", "export", "decompile", "patch"}:
            p.add_argument("-o", "--output", type=Path, required=True)
        if name in {"validate", "patch", "verify"}:
            p.add_argument("catalog", type=Path)
        if name == "verify":
            p.add_argument("patched", type=Path)
        if name == "validate":
            p.add_argument("--complete", action="store_true")
        if name == "export":
            p.add_argument("--select", choices=("cjk", "all"), default="cjk")
            p.add_argument("--token-patterns", type=Path, help="JSON array of renderer-specific regexes; default protects line breaks")
    p = subs.add_parser("find")
    p.add_argument("snapshot", type=Path)
    p.add_argument("query")
    p.add_argument("--regex", action="store_true")
    p = subs.add_parser("diff")
    p.add_argument("old", type=Path)
    p.add_argument("new", type=Path)
    args = parser.parse_args(argv)
    if args.command == "inspect":
        raw = raw_archive(args.data)
        print(json.dumps({k: v for k, v in raw.items() if k not in {"strings", "records"}} | {
            "string_count": len(raw["strings"]), "cjk_strings": sum(bool(CJK.search(s)) for s in raw["strings"]),
            "bytecode_present": any(c["tag"] == "CODE" and c["size"] > 4 for c in raw["chunks"])}, indent=2))
    elif args.command == "snapshot":
        reject_existing(args.output)
        result = snapshot(args.data)
        write_json(args.output, result)
        print(json.dumps({"snapshot": str(args.output), "version": result['version'], "strings": len(result['strings'])}))
    elif args.command == "export":
        export_catalog(args.data, args.output, args.select, read_json(args.token_patterns) if args.token_patterns else None)
    elif args.command == "census":
        reject_existing(args.output)
        snap = snapshot(args.data)
        sites = site_map(snap)
        refs = {}
        for site, info in sites.items():
            refs.setdefault(info["string_id"], []).append(site)
        strings = [{"string_id": sid, "source": text, "cjk": bool(CJK.search(text)),
                    "sites": refs.get(sid, []), "status": "review" if sid in refs else "outside_supported_sites"}
                   for sid, text in enumerate(snap["strings"])]
        report = {"source_sha256": snap["source_sha256"], "pool_count": len(strings),
                  "cjk_count": sum(s["cjk"] for s in strings),
                  "cjk_outside_supported_sites": sum(s["cjk"] and not s["sites"] for s in strings), "strings": strings}
        write_json(args.output, report)
        print(json.dumps({k: v for k, v in report.items() if k != "strings"}))
    elif args.command == "decompile":
        reject_existing(args.output)
        args.output.mkdir(parents=True)
        log = run_utmt(["dump", args.data.resolve(), "-o", args.output.resolve(), "-c", "UMT_DUMP_ALL"], log=args.output / "utmt.log")
        files = list(args.output.rglob("*.gml"))
        failed = [str(p) for p in files if "EXCEPTION" in p.read_text(encoding="utf-8-sig")[:1500]]
        snap = snapshot(args.data)
        expected = sum(c["parent"] == -1 for c in snap["code"])
        report = {"source_sha256": snap["source_sha256"], "expected_parent_entries": expected, "files": len(files), "failed": failed}
        write_json(args.output / "manifest.json", report)
        if snap["yyc"] or len(files) != expected or failed or "Failed to decompile" in log:
            raise ToolError("Incomplete decompilation; inspect manifest.json and utmt.log")
        print(json.dumps(report))
    elif args.command == "validate":
        result = validate_catalog(read_json(args.catalog), snapshot(args.data), args.complete)
        print(json.dumps({k: v for k, v in result.items() if k != "changes"}, ensure_ascii=False, indent=2))
        return 1 if result["errors"] else 0
    elif args.command == "patch":
        patch_archive(args.data, args.catalog, args.output)
    elif args.command == "verify":
        before = snapshot(args.data)
        result = validate_catalog(read_json(args.catalog), before)
        if result["errors"]:
            raise ToolError("Catalog validation failed: " + "; ".join(result["errors"]))
        print(json.dumps(verify_snapshots(before, snapshot(args.patched), result["changes"]), indent=2))
    elif args.command == "find":
        snap = read_json(args.snapshot)
        sites = site_map(snap)
        for sid, text in enumerate(snap["strings"]):
            if (re.search(args.query, text) if args.regex else args.query.casefold() in text.casefold()):
                print(json.dumps({"string_id": sid, "source": text, "sites": [k for k, v in sites.items() if v["string_id"] == sid]}, ensure_ascii=False))
    elif args.command == "diff":
        old, new = raw_archive(args.old), raw_archive(args.new)
        a, b = Counter(old['strings']), Counter(new['strings'])
        print(json.dumps({"old_sha256": old['sha256'], "new_sha256": new['sha256'],
                          "added": list((b - a).elements()), "removed": list((a - b).elements()),
                          "note": "String inventory only. Site IDs are build-specific; translations are never auto-migrated."}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ToolError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
