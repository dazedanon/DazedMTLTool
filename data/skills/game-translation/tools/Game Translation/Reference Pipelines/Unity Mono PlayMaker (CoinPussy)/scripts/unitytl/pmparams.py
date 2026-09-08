#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pmparams.py — decode PlayMaker `ActionData` blocks out of AssetRipper YAML.

PlayMaker stores every action parameter of a state in ONE flat, column-oriented
record rather than per action:

    actionNames       [str]   one per action in the state
    actionStartIndex  u32[]   index into paramName where each action's params begin
    paramName         [str]   parameter names, all actions concatenated in order
    paramDataType     i32[]   per param: which typed list holds the value
    paramDataPos      i32[]   per param: index into that list (byte offset for byteData)
    paramByteDataSize i32[]   per param: byte width when the value lives in byteData
    fsmStringParams / stringParams / fsmFloatParams / ... : the typed lists
    byteData          bytes   packed primitives (bool/int/float/enum)

`paramDataType` values are PlayMaker's internal `ParamDataType` enum. The enum is
compiled into PlayMaker.dll, not into any exported script, so instead of guessing
the numbers this module DERIVES the code -> list mapping from the data and then
proves it: for every block, every list must be exactly saturated (each slot
consumed once, positions covering range(len)). See `derive_mapping`.

Only string columns matter downstream, but the whole mapping is solved because
saturation across all columns is what makes the derivation verifiable.
"""

import json
import os

from . import uyaml

# Typed parameter columns, in the order AssetRipper emits them.
LIST_FIELDS = (
    "unityObjectParams", "fsmGameObjectParams", "fsmOwnerDefaultParams",
    "animationCurveParams", "functionCallParams", "fsmTemplateControlParams",
    "fsmEventTargetParams", "fsmPropertyParams", "layoutOptionParams",
    "fsmStringParams", "fsmObjectParams", "fsmVarParams", "fsmArrayParams",
    "fsmEnumParams", "fsmFloatParams", "fsmIntParams", "fsmBoolParams",
    "fsmVector2Params", "fsmVector3Params", "fsmColorParams", "fsmRectParams",
    "fsmQuaternionParams", "stringParams",
)
BYTE_FIELD = "byteData"

# Hex-blob columns of i32 counts rather than YAML sequences. An `Array` param
# (e.g. ES3 SaveMultiple's `keys`) stores only its length here; the elements that
# follow it are ordinary params of the element type, with an empty paramName.
BLOB_I32_FIELDS = ("arrayParamSizes", "customTypeSizes")

# Columns whose entries carry translatable text.
STRING_LISTS = ("fsmStringParams", "stringParams")

MAPPING_NAME = "playmaker_param_types.json"


class ActionData:
    """One decoded `actionData:` block."""

    __slots__ = ("names", "start", "pname", "ptype", "ppos", "pbytes",
                 "lists", "bytelen", "bloblen", "lineno")

    def __init__(self, blk):
        self.lineno = blk.lineno
        self.names = [uyaml.decode_scalar(x) if isinstance(x, str) else ""
                      for x in blk.list("actionNames")]
        self.start = uyaml.hex_u32(blk.s("actionStartIndex"))
        self.pname = [uyaml.decode_scalar(x) if isinstance(x, str) else ""
                      for x in blk.list("paramName")]
        self.ptype = uyaml.hex_i32(blk.s("paramDataType"))
        self.ppos = uyaml.hex_i32(blk.s("paramDataPos"))
        self.pbytes = uyaml.hex_i32(blk.s("paramByteDataSize"))
        self.lists = {f: blk.list(f) for f in LIST_FIELDS}
        self.bytelen = len(uyaml.hexbytes(blk.s(BYTE_FIELD)))
        self.bloblen = {f: len(uyaml.hex_i32(blk.s(f))) for f in BLOB_I32_FIELDS}

    def nparams(self):
        return min(len(self.ptype), len(self.ppos))

    def param_name(self, j):
        """Name of param j. Array elements serialize with an empty name, so the
        owning array param's name (the nearest preceding non-empty one within the
        same action) is inherited — otherwise ES3 `keys` elements look nameless."""
        if j < len(self.pname) and self.pname[j]:
            return self.pname[j]
        floor = 0
        for s in self.start:
            if s <= j:
                floor = s
            else:
                break
        for k in range(min(j, len(self.pname) - 1), floor - 1, -1):
            if self.pname[k]:
                return self.pname[k]
        return ""

    def action_of(self, j):
        """Name of the action that owns param index j (or '' if unresolvable)."""
        if not self.start:
            return self.names[0] if len(self.names) == 1 else ""
        lo = 0
        for k, s in enumerate(self.start):
            if s <= j:
                lo = k
            else:
                break
        return self.names[lo] if lo < len(self.names) else ""

    def string_params(self, mapping):
        """Yield (action, param_name, column, index, raw_value) for string columns."""
        code_to_list = mapping
        for j in range(self.nparams()):
            col = code_to_list.get(str(self.ptype[j]))
            if col not in STRING_LISTS:
                continue
            pos = self.ppos[j]
            seq = self.lists.get(col) or []
            if not (0 <= pos < len(seq)):
                continue
            entry = seq[pos]
            if col == "stringParams":
                raw = entry if isinstance(entry, str) else ""
            else:
                raw = entry.get("value", "") if isinstance(entry, dict) else ""
            yield self.action_of(j), self.param_name(j), col, pos, raw


def iter_action_data(path):
    """Yield ActionData for every `actionData:` block in a YAML asset file.

    Streams one block at a time — the exported scenes reach 93 MB, so holding the
    whole line list would cost gigabytes.
    """
    buf = None
    base = 0
    for rec in uyaml.iter_lines(path):
        _ln, indent, text = rec
        if buf is not None:
            if indent > base:
                buf.append(rec)
                continue
            blk, _ = uyaml.parse_block(buf, 0, base + 2, buf[0][0] if buf else 0)
            yield ActionData(blk)
            buf = None
        if text == "actionData:":
            buf, base = [], indent
    if buf:
        blk, _ = uyaml.parse_block(buf, 0, base + 2, buf[0][0])
        yield ActionData(blk)


# --------------------------------------------------------------------------
# derivation
# --------------------------------------------------------------------------
def _observe(ad, obs):
    """Accumulate per-block (code -> positions) and column lengths into `obs`."""
    counts = {}
    for j in range(ad.nparams()):
        counts.setdefault(ad.ptype[j], []).append(ad.ppos[j])
    lens = {f: len(ad.lists.get(f) or []) for f in LIST_FIELDS}
    lens[BYTE_FIELD] = ad.bytelen
    lens.update(ad.bloblen)
    obs.append((counts, lens))


def derive_mapping(observations):
    """Solve paramDataType code -> column from saturation constraints.

    Every typed column must be exactly filled by the params pointing at it: each
    slot consumed once, positions covering range(len). Blocks where only one code
    is still unknown pin that code down; propagating those pins converges.

    Returns (mapping, report) where mapping is {code:int -> column:str}.
    """
    all_codes = set()
    for counts, _lens in observations:
        all_codes |= set(counts)

    # Elimination: a column is only possible for a code if every observed position
    # is in range in every block where the code appears.
    cands = {}
    for c in all_codes:
        possible = set(LIST_FIELDS) | {BYTE_FIELD} | set(BLOB_I32_FIELDS)
        for counts, lens in observations:
            if c not in counts:
                continue
            pos = counts[c]
            possible = {f for f in possible if all(0 <= p < lens[f] for p in pos)}
            if not possible:
                break
        cands[c] = possible

    mapping = {c: next(iter(v)) for c, v in cands.items() if len(v) == 1}

    # Propagate: in each block, subtract slots already claimed by known codes; a
    # column with leftover capacity and exactly one viable unknown code is solved.
    changed = True
    while changed:
        changed = False
        for counts, lens in observations:
            used = {}
            unknown = []
            for c, pos in counts.items():
                if c in mapping:
                    used[mapping[c]] = used.get(mapping[c], 0) + len(pos)
                else:
                    unknown.append(c)
            if not unknown:
                continue
            open_cols = [f for f in (set(LIST_FIELDS) | {BYTE_FIELD} | set(BLOB_I32_FIELDS))
                         if lens[f] - used.get(f, 0) > 0]
            for f in open_cols:
                fits = [c for c in unknown if f in cands[c]]
                if len(fits) == 1 and len(open_cols) >= 1:
                    c = fits[0]
                    # Only accept when this code is the sole claimant of the column
                    # across every block it appears in.
                    if all(f in cands[c] for _cc, _ll in [(counts, lens)]):
                        mapping[c] = f
                        cands[c] = {f}
                        changed = True
            if len(unknown) == 1 and len(open_cols) == 1:
                mapping[unknown[0]] = open_cols[0]
                cands[unknown[0]] = {open_cols[0]}
                changed = True

    # Verify saturation. byteData is measured in bytes, not slots, so it is
    # reported separately and never counted against the slot check.
    report = {"blocks": len(observations), "codes": len(all_codes),
              "mapped": len(mapping), "unmapped": sorted(all_codes - set(mapping)),
              "violations": [], "ambiguous": {str(c): sorted(v)
                                              for c, v in cands.items() if len(v) != 1}}
    for bi, (counts, lens) in enumerate(observations):
        per_col = {}
        for c, pos in counts.items():
            f = mapping.get(c)
            if f is None:
                continue
            per_col.setdefault(f, []).extend(pos)
        for f, pos in per_col.items():
            if f == BYTE_FIELD:      # measured in bytes, not slots
                continue
            if sorted(pos) != list(range(lens[f])):
                report["violations"].append(
                    {"block": bi, "column": f, "len": lens[f], "positions": sorted(pos)})
    return mapping, report


def mapping_path(store_dir):
    return os.path.join(store_dir, MAPPING_NAME)


def save_mapping(store_dir, mapping, report):
    os.makedirs(store_dir, exist_ok=True)
    payload = {"code_to_column": {str(k): v for k, v in sorted(mapping.items())},
               "report": report}
    tmp = mapping_path(store_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, mapping_path(store_dir))


def load_mapping(store_dir):
    p = mapping_path(store_dir)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("code_to_column", {})
