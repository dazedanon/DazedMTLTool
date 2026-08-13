#!/usr/bin/env python3
"""Score one blind character-name research result against a separate oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SCHEMA_VERSION = 1
REQUIRED_RESULT_FIELDS = (
    "subject_id",
    "recommendation",
    "confidence",
    "lexical_language",
    "lexical_source_word",
    "lexical_meaning",
    "lexical_source_url",
    "kana_discrepancy",
    "rationale",
)


def _read_json(path: str | Path) -> Any:
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def load_oracle(path: str | Path) -> dict[str, Any]:
    oracle = _read_json(path)
    if not isinstance(oracle, dict):
        raise ValueError("Name-reading oracle must be an object")
    if oracle.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported name-reading oracle schema")
    string_fields = (
        "benchmark_id",
        "fixture_file",
        "fixture_sha256",
        "subject_id",
        "recommendation",
        "lexical_language_pattern",
        "lexical_source_word",
    )
    if any(not isinstance(oracle.get(key), str) or not oracle[key] for key in string_fields):
        raise ValueError("Name-reading oracle has invalid identity fields")
    if Path(oracle["fixture_file"]).name != oracle["fixture_file"]:
        raise ValueError("Name-reading fixture_file must be one basename")
    if not re.fullmatch(r"[0-9a-f]{64}", oracle["fixture_sha256"]):
        raise ValueError("Name-reading fixture hash is invalid")
    for key in (
        "forbidden_recommendations",
        "lexical_meaning_patterns",
        "lexical_source_host_patterns",
        "kana_discrepancy_patterns",
        "rationale_patterns",
    ):
        value = oracle.get(key)
        if not isinstance(value, list) or not value or any(
            not isinstance(item, str) or not item for item in value
        ):
            raise ValueError(f"Name-reading oracle {key} must be a non-empty string list")
    return oracle


def validate_fixture(oracle: dict[str, Any], fixture_root: str | Path) -> Path:
    root = Path(fixture_root).resolve(strict=True)
    fixture = (root / oracle["fixture_file"]).resolve(strict=True)
    try:
        fixture.relative_to(root)
    except ValueError as exc:
        raise ValueError("Name-reading fixture escapes its root") from exc
    if not fixture.is_file() or fixture.is_symlink():
        raise ValueError("Name-reading fixture must be a regular file")
    if _sha256(fixture) != oracle["fixture_sha256"]:
        raise ValueError("Name-reading fixture hash mismatch")
    return fixture


def validate_result(result: Any) -> dict[str, str]:
    if not isinstance(result, dict):
        raise ValueError("Name-reading result must be an object")
    if set(result) != set(REQUIRED_RESULT_FIELDS):
        raise ValueError("Name-reading result has missing or unknown fields")
    if any(not isinstance(result[key], str) or not result[key].strip() for key in result):
        raise ValueError("Every name-reading result field must be a non-empty string")
    return {key: result[key].strip() for key in REQUIRED_RESULT_FIELDS}


def _matches(value: str, pattern: str) -> bool:
    return re.search(pattern, value, flags=re.IGNORECASE) is not None


def score_result(oracle: dict[str, Any], raw_result: Any) -> dict[str, Any]:
    result = validate_result(raw_result)
    parsed_url = urlparse(result["lexical_source_url"])
    normalized_subject = re.sub(
        r"^subject\s+", "", result["subject_id"], flags=re.IGNORECASE
    )
    checks = {
        "subject_id": normalized_subject.casefold() == oracle["subject_id"].casefold(),
        "recommendation": result["recommendation"].casefold()
        == oracle["recommendation"].casefold(),
        "forbidden_recommendation_absent": result["recommendation"].casefold()
        not in {item.casefold() for item in oracle["forbidden_recommendations"]},
        "lexical_language": _matches(
            result["lexical_language"], oracle["lexical_language_pattern"]
        ),
        "lexical_source_word": result["lexical_source_word"].casefold()
        == oracle["lexical_source_word"].casefold(),
        "lexical_meaning": all(
            _matches(result["lexical_meaning"], pattern)
            for pattern in oracle["lexical_meaning_patterns"]
        ),
        "lexical_source_url": parsed_url.scheme == "https"
        and any(
            _matches(parsed_url.hostname or "", pattern)
            for pattern in oracle["lexical_source_host_patterns"]
        ),
        "kana_discrepancy": all(
            _matches(result["kana_discrepancy"], pattern)
            for pattern in oracle["kana_discrepancy_patterns"]
        ),
        "rationale": all(
            _matches(result["rationale"], pattern)
            for pattern in oracle["rationale_patterns"]
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": oracle["benchmark_id"],
        "checks": checks,
        "failures": failures,
        "quality_pass": not failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("oracle", type=Path)
    parser.add_argument("result", type=Path)
    parser.add_argument("--fixture-root", type=Path, required=True)
    args = parser.parse_args()

    oracle = load_oracle(args.oracle)
    validate_fixture(oracle, args.fixture_root)
    score = score_result(oracle, _read_json(args.result))
    print(json.dumps(score, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if score["quality_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
