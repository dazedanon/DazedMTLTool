#!/usr/bin/env python3
"""Score an offline RPG Maker QA run against a committed oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def _read_json(path: str | Path) -> Any:
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _json_pointer(value: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {pointer!r}")
    current = value
    for encoded in pointer[1:].split("/"):
        key = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", key):
                raise ValueError(f"Invalid JSON pointer array index: {key!r}")
            current = current[int(key)]
        elif isinstance(current, dict):
            current = current[key]
        else:
            raise ValueError(f"JSON pointer traverses a scalar: {pointer!r}")
    return current


def load_oracle(path: str | Path) -> dict[str, Any]:
    """Load and validate the benchmark oracle schema."""
    oracle_path = Path(path)
    oracle = _read_json(oracle_path)
    if not isinstance(oracle, dict):
        raise ValueError(f"Expected a JSON object in {oracle_path}")
    if type(oracle.get("schema_version")) is not int or oracle["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported RPG Maker QA oracle schema")
    if not isinstance(oracle.get("benchmark_id"), str):
        raise ValueError("Oracle benchmark_id must be a string")
    artifacts = oracle.get("artifact_sha256")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("Oracle artifact_sha256 must be a non-empty object")
    for relative, digest in artifacts.items():
        artifact_relative = Path(str(relative))
        if (
            not isinstance(relative, str)
            or artifact_relative.is_absolute()
            or ".." in artifact_relative.parts
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError(f"Oracle has an unsafe artifact entry: {relative!r}")
    cases = oracle.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Oracle cases must be a non-empty list")

    case_ids: set[str] = set()
    locators: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Every oracle case must be an object")
        required = ("id", "cluster_id", "focus", "file", "live_path", "source_path")
        if any(not isinstance(case.get(key), str) for key in required):
            raise ValueError(f"Oracle case has invalid identity fields: {case!r}")
        expected_locator = f"{case['file']}#{case['live_path']}"
        if case.get("locator") != expected_locator:
            raise ValueError(f"Oracle locator is not canonical: {case.get('id')}")
        if case["id"] in case_ids or case["locator"] in locators:
            raise ValueError(f"Duplicate oracle case or locator: {case['id']}")
        if case["file"] not in artifacts:
            raise ValueError(f"Oracle case file is not hash-bound: {case['id']}")
        case_ids.add(case["id"])
        locators.add(case["locator"])
        if not isinstance(case.get("actionable"), bool):
            raise ValueError(f"Oracle actionable must be boolean: {case['id']}")
        if case["actionable"]:
            for key in ("family_id", "severity", "correction"):
                if not isinstance(case.get(key), str) or not case[key]:
                    raise ValueError(f"Actionable case lacks {key}: {case['id']}")
        elif case.get("family_id") is not None or case.get("correction") is not None:
            raise ValueError(f"Non-actionable case defines a fix: {case['id']}")
    oracle["oracle_sha256"] = _sha256(oracle_path)
    return oracle


def validate_fixture(oracle: dict[str, Any], fixture_root: str | Path) -> None:
    """Prove every oracle source/live value exists at its declared JSON pointer."""
    root = Path(fixture_root).resolve(strict=True)
    artifact_paths: dict[str, Path] = {}
    for relative, expected_hash in oracle["artifact_sha256"].items():
        unresolved = root / relative
        resolved = unresolved.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Fixture artifact escapes its root: {relative}") from exc
        if not resolved.is_file() or unresolved.is_symlink():
            raise ValueError(f"Fixture artifact is not a regular file: {relative}")
        if _sha256(resolved) != expected_hash:
            raise ValueError(f"Fixture artifact hash mismatch: {relative}")
        artifact_paths[relative] = resolved

    loaded: dict[str, Any] = {}
    for case in oracle["cases"]:
        relative = case["file"]
        if relative not in loaded:
            loaded[relative] = _read_json(artifact_paths[relative])
        document = loaded[relative]
        if _json_pointer(document, case["source_path"]) != case["source"]:
            raise ValueError(f"Oracle source mismatch: {case['id']}")
        if _json_pointer(document, case["live_path"]) != case["current"]:
            raise ValueError(f"Oracle live-value mismatch: {case['id']}")


def validate_run_artifact(run: dict[str, Any], oracle: dict[str, Any]) -> None:
    """Validate a model/agent-produced benchmark result before scoring it."""
    if type(run.get("schema_version")) is not int or run["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported RPG Maker QA run schema")
    if run.get("benchmark_id") != oracle["benchmark_id"]:
        raise ValueError("Run benchmark_id does not match the oracle")
    if run.get("oracle_sha256") != oracle["oracle_sha256"]:
        raise ValueError("Run oracle_sha256 does not match the oracle")
    if run.get("artifact_sha256") != oracle["artifact_sha256"]:
        raise ValueError("Run artifact hashes do not match the oracle")

    known_clusters_by_focus: dict[str, set[str]] = {}
    for case in oracle["cases"]:
        known_clusters_by_focus.setdefault(case["focus"], set()).add(case["cluster_id"])
    reviewed_by_focus = run.get("reviewed_clusters_by_focus")
    if not isinstance(reviewed_by_focus, dict):
        raise ValueError("reviewed_clusters_by_focus must be an object")
    if not set(reviewed_by_focus) <= set(known_clusters_by_focus):
        raise ValueError("reviewed_clusters_by_focus contains an unknown focus")
    for focus, reviewed in reviewed_by_focus.items():
        if not isinstance(reviewed, list) or any(
            not isinstance(item, str) for item in reviewed
        ):
            raise ValueError(f"Reviewed clusters for {focus} must be a string list")
        if (
            len(reviewed) != len(set(reviewed))
            or not set(reviewed) <= known_clusters_by_focus[focus]
        ):
            raise ValueError(f"Reviewed clusters for {focus} are duplicate or unknown")

    known_locators = {case["locator"] for case in oracle["cases"]}
    findings = run.get("findings")
    if not isinstance(findings, list):
        raise ValueError("findings must be a list")
    finding_locators: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("Every finding must be an object")
        locator = finding.get("locator")
        if locator not in known_locators or locator in finding_locators:
            raise ValueError("findings contains a duplicate or unknown locator")
        finding_locators.add(locator)
        if finding.get("focus") not in known_clusters_by_focus:
            raise ValueError(f"Finding focus is unknown: {locator}")
        if not isinstance(finding.get("family_id"), str):
            raise ValueError(f"Finding family_id must be a string: {locator}")
        if finding.get("severity") not in {"Critical", "High", "Medium"}:
            raise ValueError(f"Finding severity is invalid: {locator}")
        if not isinstance(finding.get("correction"), str):
            raise ValueError(f"Finding correction must be a string: {locator}")

    metadata = run.get("run_metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("run_metadata must be an object")
    elapsed = metadata.get("elapsed_seconds")
    if (
        isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(elapsed)
        or elapsed <= 0
    ):
        raise ValueError("run_metadata.elapsed_seconds must be finite and positive")
    for key in ("input_tokens", "output_tokens"):
        value = metadata.get(key)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise ValueError(f"run_metadata.{key} must be a non-negative integer")


def score_run(oracle: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """Return accuracy, propagation, coverage, and work-rate metrics."""
    validate_run_artifact(run, oracle)
    cases = {case["locator"]: case for case in oracle["cases"]}
    expected = {locator for locator, case in cases.items() if case["actionable"]}
    predicted = {finding["locator"] for finding in run["findings"]}
    findings = {finding["locator"]: finding for finding in run["findings"]}

    true_positive = expected & predicted
    false_positive = predicted - expected
    false_negative = expected - predicted
    family_correct = {
        locator for locator in true_positive
        if findings[locator]["family_id"] == cases[locator]["family_id"]
    }
    correction_correct = {
        locator for locator in true_positive
        if findings[locator]["correction"] == cases[locator]["correction"]
    }
    focus_correct = {
        locator for locator in true_positive
        if findings[locator]["focus"] == cases[locator]["focus"]
    }
    severity_correct = {
        locator for locator in true_positive
        if findings[locator]["severity"] == cases[locator]["severity"]
    }

    expected_families: dict[str, set[str]] = {}
    for locator in expected:
        expected_families.setdefault(cases[locator]["family_id"], set()).add(locator)
    complete_families = sum(
        1 for family_id, locators in expected_families.items()
        if all(
            locator in findings and findings[locator]["family_id"] == family_id
            for locator in locators
        )
    )
    expected_family_ids = set(expected_families)
    predicted_family_ids = {finding["family_id"] for finding in run["findings"]}
    matched_family_ids = expected_family_ids & predicted_family_ids

    all_clusters_by_focus: dict[str, set[str]] = {}
    for case in cases.values():
        all_clusters_by_focus.setdefault(case["focus"], set()).add(case["cluster_id"])
    reviewed_by_focus = {
        focus: set(clusters)
        for focus, clusters in run["reviewed_clusters_by_focus"].items()
    }
    reviewed_count = sum(len(clusters) for clusters in reviewed_by_focus.values())
    all_cluster_count = sum(len(clusters) for clusters in all_clusters_by_focus.values())
    focus_coverage = {
        focus: _ratio(len(reviewed_by_focus.get(focus, set())), len(clusters))
        for focus, clusters in sorted(all_clusters_by_focus.items())
    }
    metadata = run.get("run_metadata", {})
    elapsed = float(metadata.get("elapsed_seconds", 0) or 0)
    threshold_false_positives = sum(
        1 for locator in false_positive
        if "threshold-only" in cases[locator].get("tags", [])
    )
    precision = _ratio(len(true_positive), len(predicted))
    recall = _ratio(len(true_positive), len(expected))
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": oracle["benchmark_id"],
        "oracle_sha256": oracle.get("oracle_sha256"),
        "locator_precision": precision,
        "locator_recall": recall,
        "locator_f1": f1,
        "family_precision": _ratio(len(matched_family_ids), len(predicted_family_ids)),
        "family_recall": _ratio(len(matched_family_ids), len(expected_family_ids)),
        "locator_family_label_accuracy": _ratio(len(family_correct), len(true_positive)),
        "locator_family_label_completeness": _ratio(len(family_correct), len(expected)),
        "focus_accuracy": _ratio(len(focus_correct), len(true_positive)),
        "focus_completeness": _ratio(len(focus_correct), len(expected)),
        "severity_accuracy": _ratio(len(severity_correct), len(true_positive)),
        "severity_completeness": _ratio(len(severity_correct), len(expected)),
        "propagation_completeness": _ratio(complete_families, len(expected_families)),
        "correction_exactness": _ratio(len(correction_correct), len(true_positive)),
        "correction_completeness": _ratio(len(correction_correct), len(expected)),
        "coverage": _ratio(reviewed_count, all_cluster_count),
        "focus_coverage": focus_coverage,
        "true_positive_count": len(true_positive),
        "false_positive_count": len(false_positive),
        "false_negative_count": len(false_negative),
        "threshold_only_false_positive_count": threshold_false_positives,
        "reviewed_cluster_count": reviewed_count,
        "expected_cluster_count": all_cluster_count,
        "elapsed_seconds": elapsed,
        "clusters_per_hour": reviewed_count * 3600 / elapsed if elapsed else None,
        "input_tokens": metadata.get("input_tokens"),
        "output_tokens": metadata.get("output_tokens"),
        "quality_pass": all((
            precision == 1.0,
            recall == 1.0,
            len(family_correct) == len(expected),
            len(correction_correct) == len(expected),
            len(focus_correct) == len(expected),
            len(severity_correct) == len(expected),
            reviewed_count == all_cluster_count,
            all(value == 1.0 for value in focus_coverage.values()),
        )),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("oracle", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("--fixture-root", type=Path)
    args = parser.parse_args()

    oracle = load_oracle(args.oracle)
    validate_fixture(oracle, args.fixture_root or args.oracle.parent)
    run = _read_json(args.run)
    if not isinstance(run, dict):
        raise ValueError(f"Expected a JSON object in {args.run}")
    score = score_run(oracle, run)
    print(json.dumps(score, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if score["quality_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
