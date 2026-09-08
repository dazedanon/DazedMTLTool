"""Minimal Unity YAML reader.

Unity emits `--- !u!<classID> &<fileID>` document headers and `!u!` local tags
that PyYAML rejects outright. Split into documents ourselves and register a
multi-constructor so each document parses as plain dicts, which keeps the
fileID available as a stable per-object id.
"""
from __future__ import annotations

import re
import yaml

DOC_RE = re.compile(r"^--- !u!(\d+) &(\d+)(?: stripped)?\s*$", re.M)


class _Loader(yaml.SafeLoader):
    pass


def _passthrough(loader, tag_suffix, node):
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)


_Loader.add_multi_constructor("tag:unity3d.com,2011:", _passthrough)
_Loader.add_multi_constructor("!u!", _passthrough)
_Loader.add_multi_constructor("", _passthrough)


def documents(path: str):
    """Yield (class_id, file_id, parsed_dict) for each object in a Unity YAML file."""
    text = open(path, encoding="utf-8", errors="replace").read()
    marks = [(m.start(), m.end(), int(m.group(1)), int(m.group(2)))
             for m in DOC_RE.finditer(text)]
    for i, (start, end, class_id, file_id) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[end:stop]
        try:
            doc = yaml.load(body, Loader=_Loader)
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict):
            yield class_id, file_id, doc


def single(path: str):
    """Parse a one-object asset file (e.g. a ScriptableObject) to a dict."""
    for _cls, _fid, doc in documents(path):
        # The MonoBehaviour body is the single top-level key.
        for v in doc.values():
            if isinstance(v, dict):
                return v
        return doc
    return {}


def walk(node, path=""):
    """Yield (dotted_path, value) for every scalar under a parsed document."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, node
