"""Versioned, model-blind paired review rules, scheduling and statistics.

No provider calls or run-file reads belong here. Repeated judgments and request
chunks are clustered within source content groups, never independent votes.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
import random
import re
from functools import lru_cache
from collections import Counter, defaultdict

VERSION = 3
EDITING = ("ready", "light_edits", "substantive_edits", "rewrite")
STATUSES = ("judged", "insufficient_context", "needs_human_review", "policy_conflict")
DECISIONS = ("left", "equivalent", "right")
STRENGTHS = ("slight", "clear")
POOLS = ("screening", "confirmation", "challenge", "calibration")
DEFAULT_POLICY = {
    "version": VERSION,
    "name": "Japanese game translation / paired editorial review",
    "screening_groups": 30, "confirmation_groups": 30, "challenge_groups": 20,
    "practical_margin": 0.05, "fidelity_margin": 0.05,
    "min_confirmation_groups": 20, "audit_fraction": 0.20,
    "minimum_audit_agreement": 0.80, "minimum_calibration_cases": 6,
    "minimum_calibration_agreement": 0.80,
    "mandatory_rules": ["honorifics", "glossary", "formatting"],
    "max_rule_violation_rate": 0.0, "max_runtime_failure_rate": 0.0,
    "max_major_fidelity_rate": 0.0,
    "collective_honorifics": "preserve_suffix",
    "glossary_inflections": "allow_grammatical_inflection",
    "explicit_source_gender": "source_resolves_unspecified_glossary",
    "stratum_weights": {},
    "instructions": "Preserve source-supported meaning, voice and ambiguity. "
                    "Judge whole scenes. Rule-only repairs are separate from linguistic preference. "
                    "Do not turn an unclear or conflicting rule into a translation error.",
}
PROTECTED_FIELDS = (
    "schema_version", "review_id", "record_id", "record_type", "pool", "sample_id",
    "content_group", "scene_id", "stratum", "line_count", "source", "context",
    "policy", "outputs", "output_status", "identical_candidates",
)
EDITABLE_FIELDS = (
    "status", "editing_requirement", "error_evidence", "rule_checks", "decision",
    "strength", "comparison_evidence", "notes",
)
FIELDS = (*PROTECTED_FIELDS, *EDITABLE_FIELDS)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_policy(value: dict | None) -> dict:
    policy = copy.deepcopy(DEFAULT_POLICY if value is None else value)
    if not isinstance(policy, dict) or set(policy) != set(DEFAULT_POLICY):
        raise ValueError("Review policy must contain exactly the documented v3 fields")
    if policy["version"] != VERSION:
        raise ValueError("Unsupported paired review policy version")
    for key in ("screening_groups", "confirmation_groups", "challenge_groups",
                "min_confirmation_groups", "minimum_calibration_cases"):
        if type(policy[key]) is not int or not 0 <= policy[key] <= 10000:
            raise ValueError(f"Invalid policy count: {key}")
    if policy["screening_groups"] < 1 or policy["min_confirmation_groups"] < 2:
        raise ValueError("Screening needs a group and confirmation needs at least two")
    for key in ("practical_margin", "fidelity_margin", "audit_fraction",
                "minimum_audit_agreement", "minimum_calibration_agreement",
                "max_rule_violation_rate", "max_runtime_failure_rate", "max_major_fidelity_rate"):
        if type(policy[key]) not in (int, float) or not math.isfinite(policy[key]) or not 0 <= policy[key] <= 1:
            raise ValueError(f"Invalid policy rate: {key}")
    if not policy["audit_fraction"] or not policy["minimum_calibration_cases"]:
        raise ValueError("Judge audits and calibration cannot be disabled")
    rules = policy["mandatory_rules"]
    if not isinstance(rules, list) or any(not isinstance(r, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", r) for r in rules) or len(rules) != len(set(rules)):
        raise ValueError("Mandatory rules must have unique stable identifiers")
    weights = policy["stratum_weights"]
    if not isinstance(weights, dict) or any(not isinstance(k, str) or type(v) not in (int, float)
            or not math.isfinite(v) or v <= 0 for k, v in weights.items()):
        raise ValueError("Stratum weights must be finite positive numbers")
    for key, choices in {
        "collective_honorifics": ("preserve_suffix", "preserve_politeness", "flag_conflict"),
        "glossary_inflections": ("allow_grammatical_inflection", "exact_forms"),
        "explicit_source_gender": ("source_resolves_unspecified_glossary", "flag_conflict"),
    }.items():
        if policy[key] not in choices:
            raise ValueError(f"Unsupported policy choice: {key}")
    for key in ("name", "instructions"):
        if not isinstance(policy[key], str) or not policy[key].strip():
            raise ValueError(f"Policy {key} is required")
    return policy


def content_groups(samples: list[dict]) -> dict[str, str]:
    """Keep event/page calls and exact duplicate blocks in the same split."""
    parents = {}
    def find(key):
        parents.setdefault(key, key)
        if parents[key] != key:
            parents[key] = find(parents[key])
        return parents[key]
    scenes, texts = {}, {}
    for sample in samples:
        sid = sample["id"]
        find(sid)
        scene = re.split(r":(?:call|chunk)-\d+", sample["scene_id"])[0]
        text = digest(sample["sources"])
        for table, key in ((scenes, scene), (texts, text)):
            if key in table:
                a, b = sorted((find(sid), find(table[key])))
                parents[b] = a
            else:
                table[key] = sid
    return {s["id"]: "group-" + digest(find(s["id"]))[:16] for s in samples}


def make_plan(samples: list[dict], policy: dict, seed: str,
              exposed_samples=(), challenge_samples=()) -> dict:
    """Split by source only; prior exported scenes never become fresh holdouts."""
    groups = content_groups(samples)
    grouped = defaultdict(list)
    for sample in samples:
        grouped[groups[sample["id"]]].append(sample)
    exposed = {groups[s] for s in exposed_samples if s in groups}
    challenge = {groups[s] for s in challenge_samples if s in groups}
    if any(s not in groups for s in challenge_samples):
        raise ValueError("Unknown challenge sample")
    assignment = {}
    # Explicit challenge groups have priority. Otherwise reserve a reproducible
    # source-code challenge subset, never selected by candidate performance.
    if not challenge:
        code = [g for g, rows in grouped.items() if any(
            re.search(r"\\(?:[A-Za-z]+\[|[.!|^{}])|__PROTECTED_", "\n".join(r["sources"])) for r in rows)]
        random.Random(seed + ":challenge").shuffle(code)
        challenge = set(code[:min(policy["challenge_groups"], len(grouped) // 4, len(code) // 3)])
    for group in challenge:
        assignment[group] = "challenge"
    by_stratum = defaultdict(list)
    for group, rows in grouped.items():
        if group not in challenge:
            by_stratum[rows[0]["stratum"]].append(group)
    ordered = []
    for stratum, values in sorted(by_stratum.items()):
        random.Random(seed + ":" + stratum).shuffle(values)
    while any(by_stratum.values()):
        for values in by_stratum.values():
            if values:
                ordered.append(values.pop())
    fresh = [g for g in ordered if g not in exposed]
    reserve = min(policy["confirmation_groups"], len(fresh) // 2)
    for group in fresh[:reserve]:
        assignment[group] = "confirmation"
    screening = [g for g in ordered if g not in assignment][:policy["screening_groups"]]
    for group in screening:
        assignment[group] = "screening"
    return {
        "seed": seed, "groups": groups,
        "pools": {s["id"]: assignment.get(groups[s["id"]], "reserve") for s in samples},
        "group_counts": dict(Counter(assignment.values())),
        "previously_exposed_groups": sorted(exposed),
        "confirmation_candidates": [],
    }


def scheduled_pairs(candidates: list[str], scene_index: int, *, complete=False) -> list[tuple[str, str]]:
    """Rotate two round-robin rounds per group, balancing opponent exposure."""
    if complete or len(candidates) <= 3:
        return list(itertools.combinations(candidates, 2))
    ring = list(candidates)
    if len(ring) % 2:
        ring.append(None)
    rounds = []
    for _ in range(len(ring) - 1):
        rounds.append([tuple(sorted((ring[i], ring[-1 - i])))
                       for i in range(len(ring) // 2)
                       if ring[i] is not None and ring[-1 - i] is not None])
        ring = [ring[0], ring[-1], *ring[1:-1]]
    return sorted(set(rounds[2 * scene_index % len(rounds)]
                      + rounds[(2 * scene_index + 1) % len(rounds)]))


def _quote(location: dict, source: list[str], outputs: dict, labels: list[str]) -> None:
    line = location.get("line")
    if type(line) is not int or not 1 <= line <= len(source):
        raise ValueError("Evidence line is outside the source block")
    quote = location.get("source_quote")
    if not isinstance(quote, str) or not quote or quote not in source[line - 1]:
        raise ValueError("Evidence source quote must match its exact source line")
    for label in labels:
        field = "translation_quote" if len(labels) == 1 else f"{label}_quote"
        quote = location.get(field)
        if not isinstance(quote, str) or not quote or quote not in outputs[label][line - 1]:
            raise ValueError(f"Evidence {field} must match its exact translation line")


def validate_assessment(row: dict, source: list[str], outputs: dict, policy: dict) -> dict:
    status = row.get("status", "").strip() or "unreviewed"
    if status not in (*STATUSES, "unreviewed", "unavailable"):
        raise ValueError("Unknown assessment status")
    editing = row.get("editing_requirement", "").strip()
    if row.get("decision") or row.get("strength") or row.get("comparison_evidence", "[]") not in ("", "[]"):
        raise ValueError("Assessment rows cannot contain comparative verdicts")
    errors = json.loads(row.get("error_evidence") or "{}")
    checks = json.loads(row.get("rule_checks") or "{}")
    if not isinstance(errors, dict) or set(errors) != set(outputs) or not isinstance(checks, dict) or set(checks) != set(outputs):
        raise ValueError("Assessment evidence and rule checks must cover every candidate label")
    notes = row.get("notes", "").strip()
    if status != "judged":
        if editing or any(errors.values()) or any(checks.values()):
            raise ValueError("Unjudged assessments must leave editing and findings blank")
        if status not in ("unreviewed", "unavailable") and not notes:
            raise ValueError("Abstention requires explanatory notes")
    elif editing not in EDITING:
        raise ValueError("Judged assessment requires an editing requirement")
    for label in outputs:
        if not isinstance(errors[label], list) or not isinstance(checks[label], list):
            raise ValueError("Candidate findings must be arrays")
        ids = set()
        for error in errors[label]:
            if not isinstance(error, dict) or not isinstance(error.get("id"), str) or not error["id"].strip() or error["id"] in ids:
                raise ValueError("Each underlying error needs a unique nonempty ID")
            ids.add(error["id"])
            if error.get("category") not in ("meaning", "omission", "addition", "terminology", "voice", "grammar", "runtime", "policy"):
                raise ValueError("Unknown error category")
            if error.get("severity") not in ("minor", "major", "critical"):
                raise ValueError("Unknown error severity")
            impacts = error.get("impacts")
            if not isinstance(impacts, list) or not impacts or len(set(impacts)) != len(impacts) or not set(impacts) <= {"linguistic", "compliance", "runtime"}:
                raise ValueError("Each error needs explicit unique impact tags")
            error_rules = error.get("rule_ids", [])
            if not isinstance(error_rules, list) or any(not isinstance(rule, str) for rule in error_rules) or not set(error_rules) <= set(policy["mandatory_rules"]):
                raise ValueError("Error rule IDs must refer to mandatory policy rules")
            if "compliance" in impacts and not error_rules:
                raise ValueError("Compliance errors must identify the violated rule_ids")
            if not isinstance(error.get("explanation"), str) or not error["explanation"].strip():
                raise ValueError("Error explanation is required")
            _quote(error, source, outputs, [label])
            occurrences = error.get("occurrences", [])
            if not isinstance(occurrences, list):
                raise ValueError("Error occurrences must be an array")
            for occurrence in occurrences:
                _quote(occurrence, source, outputs, [label])
        rule_ids = set()
        for check in checks[label]:
            if not isinstance(check, dict) or check.get("rule_id") not in policy["mandatory_rules"] or check["rule_id"] in rule_ids:
                raise ValueError("Rule checks require unique policy rule IDs")
            rule_ids.add(check["rule_id"])
            if not isinstance(check.get("opportunities"), list) or not isinstance(check.get("explanation"), str) or not check["explanation"].strip():
                raise ValueError("Each rule needs opportunities and an applicability explanation")
            seen = set()
            for opportunity in check["opportunities"]:
                _quote(opportunity, source, outputs, [label])
                if type(opportunity.get("passed")) is not bool:
                    raise ValueError("Rule opportunities require a boolean passed field")
                key = (opportunity["line"], opportunity["source_quote"])
                if key in seen:
                    raise ValueError("Duplicate rule opportunity")
                seen.add(key)
        if status == "judged" and rule_ids != set(policy["mandatory_rules"]):
            raise ValueError("Assess every mandatory rule, including non-applicable rules")
        failed_rules = {check["rule_id"] for check in checks[label] if any(not o["passed"] for o in check["opportunities"])}
        evidence_rules = {rule for error in errors[label] if "compliance" in error["impacts"] for rule in error["rule_ids"]}
        if failed_rules != evidence_rules:
            raise ValueError("Failed rule checks must match compliance error evidence")
        consequential = any(e["severity"] in ("major", "critical") and "linguistic" in e["impacts"] for e in errors[label])
        if status == "judged" and (consequential and editing in ("ready", "light_edits") or errors[label] and editing == "ready"):
            raise ValueError("Editing requirement contradicts recorded errors")
    return {"status": status, "editing": editing, "evidence": errors, "rules": checks, "notes": notes}


def validate_comparison(row: dict, source: list[str], outputs: dict) -> dict:
    status = row.get("status", "").strip() or "unreviewed"
    if status not in (*STATUSES, "unreviewed", "unavailable"):
        raise ValueError("Unknown comparison status")
    decision, strength = row.get("decision", "").strip(), row.get("strength", "").strip()
    notes = row.get("notes", "").strip()
    evidence = json.loads(row.get("comparison_evidence") or "[]")
    if not isinstance(evidence, list):
        raise ValueError("Comparison evidence must be an array")
    if row.get("editing_requirement") or row.get("error_evidence") not in ("", "{}") or row.get("rule_checks") not in ("", "{}"):
        raise ValueError("Comparison rows must keep assessment fields blank")
    if status != "judged":
        if decision or strength or evidence:
            raise ValueError("Unjudged comparisons must leave all verdict fields blank")
        if status not in ("unreviewed", "unavailable") and not notes:
            raise ValueError("Abstention requires explanatory notes")
    else:
        if decision not in DECISIONS or (decision != "equivalent" and strength not in STRENGTHS) or (decision == "equivalent" and strength):
            raise ValueError("Comparison requires left/right plus slight/clear, or equivalent without strength")
        if not notes:
            raise ValueError("Judged comparison requires a block-level rationale")
        if decision != "equivalent" and not evidence:
            raise ValueError("Preference requires positive source and candidate evidence")
        if outputs["A"] == outputs["B"] and decision != "equivalent":
            raise ValueError("Identical output blocks cannot have a preference")
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("explanation"), str) or not item["explanation"].strip():
            raise ValueError("Comparison evidence requires an explanation")
        _quote(item, source, outputs, ["A", "B"])
    return {"status": status, "decision": decision, "strength": strength, "notes": notes, "evidence": evidence}


def outcome(record: dict, candidate: str) -> int:
    if record["decision"] == "equivalent":
        return 0
    winner = record["left"] if record["decision"] == "left" else record["right"]
    return 1 if winner == candidate else -1


def assessment_signature(record: dict) -> tuple:
    return (record["editing"],
            any(e["severity"] in ("major", "critical") and "linguistic" in e["impacts"] for e in record["evidence"]),
            any(e["severity"] == "critical" for e in record["evidence"]),
            tuple(sorted((r["rule_id"], sum(not o["passed"] for o in r["opportunities"])) for r in record["rules"])))


def paired_interval(values: list[float], alpha: float = .05) -> list[float] | None:
    """Simultaneous exact marginal bounds for independent ternary outcomes.

    Fractional group averages use a bounded-mean Hoeffding fallback. Neither
    path invents zero uncertainty for a constant or all-equivalent sample.
    """
    if len(values) < 2:
        return None
    if all(v in (-1, 0, 1) for v in values):
        win = _binomial_bounds(values.count(1), len(values), alpha / 4)
        loss = _binomial_bounds(values.count(-1), len(values), alpha / 4)
        return [win[0] - loss[1], win[1] - loss[0]]
    mean = sum(values) / len(values)
    radius = math.sqrt(2 * math.log(2 / alpha) / len(values))
    return [max(-1.0, mean - radius), min(1.0, mean + radius)]


def _binomial_cdf(k, n, p):
    if k < 0:
        return 0.
    if k >= n or p <= 0:
        return 1.
    if p >= 1:
        return 0.
    if k > n // 2:
        return 1. - _binomial_cdf(n - k - 1, n, 1. - p)
    logs = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
            + i * math.log(p) + (n - i) * math.log1p(-p) for i in range(k + 1)]
    peak = max(logs)
    return min(1., math.exp(peak) * math.fsum(math.exp(x - peak) for x in logs))


@lru_cache(maxsize=512)
def _binomial_bounds(k, n, tail):
    """Clopper-Pearson limits by monotone binomial inversion; no scipy needed."""
    def invert(count, target):
        low, high = 0., 1.
        for _ in range(50):
            middle = (low + high) / 2
            if _binomial_cdf(count, n, middle) > target:
                low = middle
            else:
                high = middle
        return (low + high) / 2
    lower = 0. if k == 0 else math.exp(math.log(tail) / n) if k == n else invert(k - 1, 1 - tail)
    upper = 1. if k == n else -math.expm1(math.log(tail) / n) if k == 0 else invert(k, tail)
    return lower, upper


def _weighted_values(groups: dict, policy: dict) -> tuple[float, list[float], float]:
    """Return weighted mean and Hoeffding radius factor for fixed stratum weights."""
    strata = defaultdict(list)
    for entries in groups.values():
        strata[entries[0][1]].append(sum(x[0] for x in entries) / len(entries))
    requested = policy["stratum_weights"]
    if requested and set(strata) != set(requested):
        return float("nan"), [], 0.0
    total = sum(requested.values()) if requested else sum(map(len, strata.values()))
    weights, values = [], []
    for name, group_values in strata.items():
        mass = requested[name] / total if requested else len(group_values) / total
        weights.extend([mass / len(group_values)] * len(group_values))
        values.extend(group_values)
    mean = math.fsum(w * v for w, v in zip(weights, values))
    return 0. if abs(mean) < 1e-12 else mean, values, sum(w * w for w in weights)


def _summary_pairs(records: list[dict], candidates: list[str], policy: dict) -> list[dict]:
    pairs = []
    # Split the error budget between preference and fidelity claims, then
    # across the predeclared finalist pairs.
    alpha = .025 / max(1, len(candidates) * (len(candidates) - 1) // 2)
    for a, b in itertools.combinations(candidates, 2):
        selected = [r for r in records if {r["left"], r["right"]} == {a, b}]
        counted = [r for r in selected if r["status"] == "judged" and not r.get("disputed")]
        counts = Counter()
        groups = defaultdict(list)
        for r in counted:
            value = outcome(r, a)
            counts[("wins_" if value == 1 else "losses_") + r["strength"] if value else "equivalent"] += 1
            groups[r["content_group"]].append((value, r["stratum"]))
        mean, values, weight_squares = _weighted_values(groups, policy) if groups else (None, [], 0)
        if mean is not None and not math.isfinite(mean):
            mean = None
        interval = None
        if mean is not None and len(values) >= 2:
            if not policy["stratum_weights"]:
                interval = paired_interval(values, alpha)
            else:
                radius = math.sqrt(2 * math.log(2 / alpha) * weight_squares)
                interval = [max(-1., mean - radius), min(1., mean + radius)]
        pairs.append({"a": a, "b": b, **{k: counts[k] for k in (
            "wins_clear", "wins_slight", "equivalent", "losses_slight", "losses_clear")},
            "judged": len(counted), "groups": len(groups), "net_preference": mean,
            "interval": interval, "alpha": alpha,
            "abstentions": sum(r["status"] in STATUSES[1:] for r in selected),
            "unavailable": sum(r["status"] == "unavailable" for r in selected),
            "disputed": sum(bool(r.get("disputed")) for r in selected),
            "unreviewed": sum(r["status"] == "unreviewed" for r in selected)})
    return pairs


def summarize(campaign: dict) -> dict:
    """Aggregate v3 only; never turn legacy ranks into readiness or preferences."""
    policy = campaign["policy"]
    candidates = campaign["candidate_ids"]
    assessments = copy.deepcopy(list(campaign.get("assessments", {}).values()))
    comparisons = copy.deepcopy(list(campaign.get("comparisons", {}).values()))
    checks = defaultdict(list)
    for audit in campaign.get("audits", {}).values():
        for record in audit["records"]:
            if record["status"] == "judged":
                checks[record["baseline_task"]].append((audit["kind"], record))
    audit_counts = Counter()
    audited_tasks = defaultdict(set)
    audit_reviewers = set()
    for record in assessments:
        audits = [r for _, r in checks.get(record["task_key"], []) if r.get("type") == "assessment"]
        record["disputed"] = record["status"] == "judged" and any(
            assessment_signature(record) != assessment_signature(repeated) for repeated in audits)
        audit_reviewers.update(r.get("reviewer", "") for r in audits)
    disputed_outputs = {(r["sample_id"], r["output_digest"]) for r in assessments if r.get("disputed") and r.get("output_digest")}
    for record in assessments:
        if (record["sample_id"], record.get("output_digest")) in disputed_outputs:
            record["disputed"] = True
    for record in comparisons:
        record["disputed"] = False
        by_kind = defaultdict(list)
        for kind, repeated in checks.get(record["task_key"], []):
            if record["status"] != "judged":
                continue
            same = outcome(record, record["left"]) == outcome(repeated, record["left"])
            by_kind[kind].append(same)
            audit_reviewers.add(repeated.get("reviewer", ""))
            audited_tasks[(kind, record["pool"])].add(record["task_key"])
            record["disputed"] |= not same
        for kind, agreements in by_kind.items():
            audit_counts[kind + "_total"] += 1
            audit_counts[kind + "_agree"] += all(agreements)
    calibration = campaign.get("calibration_result") or {}
    calibration_results = campaign.get("calibration_results", {})
    required_reviewers = {r.get("reviewer", "") for r in comparisons if r["status"] == "judged"} | audit_reviewers
    calibrated = bool(required_reviewers) and all(
        (c := calibration_results.get(reviewer, {})).get("human_gold", False)
        and c.get("cases", 0) >= policy["minimum_calibration_cases"]
        and set(c.get("record_types", [])) == {"assessment", "comparison"}
        and all(c.get("by_type", {}).get(kind, {}).get("agreement", 0) >= policy["minimum_calibration_agreement"] for kind in ("assessment", "comparison"))
        and c.get("agreement", 0) >= policy["minimum_calibration_agreement"] for reviewer in required_reviewers)
    analysis = {"pools": {}, "audit": dict(audit_counts), "calibration": calibration,
                "calibrated": calibrated, "human_follow_up": [], "recommendations": {}}
    analysis["disputed_assessment_keys"] = [r["task_key"] for r in assessments if r.get("disputed")]
    for pool in POOLS[:3]:
        selected = [r for r in comparisons if r["pool"] == pool]
        scoped = [r for r in assessments if r["pool"] == pool]
        pool_ids = campaign["plan"].get("confirmation_candidates") if pool == "confirmation" else candidates
        pool_ids = pool_ids or candidates
        by_candidate = {}
        for candidate in candidates:
            rows = [r for r in scoped if r["candidate"] == candidate]
            judged = [r for r in rows if r["status"] == "judged" and not r.get("disputed")]
            editing = Counter(r["editing"] for r in judged)
            fidelity = [r for r in judged if any(e["severity"] in ("major", "critical") and "linguistic" in e["impacts"] and e["category"] in ("meaning", "omission", "addition", "voice", "terminology") for e in r["evidence"])]
            rules = {key: {"opportunities": 0, "violations": 0, "reviewed_blocks": 0} for key in policy["mandatory_rules"]}
            for row in judged:
                for check in row["rules"]:
                    metric = rules[check["rule_id"]]
                    metric["reviewed_blocks"] += 1
                    metric["opportunities"] += len(check["opportunities"])
                    metric["violations"] += sum(not o["passed"] for o in check["opportunities"])
            validity = campaign.get("coverage", {}).get(pool, {}).get(candidate, {})
            by_candidate[candidate] = {"judged": len(judged), "total": len(rows),
                "editing": {key: editing[key] for key in EDITING},
                "major_fidelity_blocks": len(fidelity), "rules": rules, "validity": validity,
                "disputed_assessments": sum(bool(r.get("disputed")) for r in rows),
                "unavailable_assessments": sum(r["status"] == "unavailable" for r in rows),
                "critical_blocks": sum(any(e["severity"] == "critical" for e in r["evidence"]) for r in judged)}
        analysis["pools"][pool] = {"pairs": _summary_pairs(selected, pool_ids, policy), "candidates": by_candidate}
    for row in assessments:
        if row.get("disputed") or row["status"] in STATUSES[1:] or (not row.get("adjudicated") and any(e["severity"] in ("major", "critical") for e in row.get("evidence", []))):
            analysis["human_follow_up"].append(row["sample_id"])
    analysis["human_follow_up"] += [r["sample_id"] for r in comparisons if r.get("disputed") or r["status"] in STATUSES[1:]]
    analysis["human_follow_up"] = sorted(set(analysis["human_follow_up"]))
    chosen_pool = "confirmation" if any(p["judged"] for p in analysis["pools"]["confirmation"]["pairs"]) else "screening"
    chosen = analysis["pools"][chosen_pool]
    required_audits = math.ceil(sum(r["pool"] == "confirmation" and r["status"] == "judged" and not r.get("identical") for r in comparisons) * policy["audit_fraction"])
    audited = not required_audits or all(len(audited_tasks[(kind, "confirmation")]) >= required_audits
                  and audit_counts[kind + "_agree"] / max(1, audit_counts[kind + "_total"]) >= policy["minimum_audit_agreement"] for kind in ("order_swap", "judge_check"))
    for candidate in candidates:
        pairs = [p for p in chosen["pairs"] if candidate in (p["a"], p["b"])]
        means = [p["net_preference"] * (1 if p["a"] == candidate else -1) for p in pairs if p["net_preference"] is not None]
        intervals = [(p["interval"] if p["a"] == candidate else [-p["interval"][1], -p["interval"][0]]) for p in pairs if p["interval"]]
        stats = chosen["candidates"][candidate]
        coverage = stats["validity"]
        production = "unassessed"
        if stats["total"] and stats["judged"] + stats["unavailable_assessments"] == stats["total"] and coverage.get("total", 0) and coverage.get("valid", 0):
            bad_rules = any(r["violations"] / max(1, r["opportunities"]) > policy["max_rule_violation_rate"] for r in stats["rules"].values())
            invalid = 1 - coverage.get("valid", 0) / coverage["total"]
            fidelity_rate = stats["major_fidelity_blocks"] / max(1, stats["judged"])
            production = "correction_required" if bad_rules or invalid > policy["max_runtime_failure_rate"] or stats["critical_blocks"] or fidelity_rate > policy["max_major_fidelity_rate"] else "eligible"
        elif coverage.get("total", 0) and (not coverage.get("valid", 0) or 1 - coverage.get("valid", 0) / coverage["total"] > policy["max_runtime_failure_rate"]):
            production = "correction_required"
        status = "no_demonstrated_difference"
        if any(p["disputed"] for p in pairs) or stats["disputed_assessments"]:
            status = "disputed"
        elif means and math.fsum(means) / len(means) > 1e-12:
            status = "provisional_leader"
        elif means and math.fsum(means) / len(means) < -1e-12:
            status = "lower_observed_preference"
        elif means and min(means) < 0 < max(means):
            status = "trade_off"
        sufficient = chosen_pool == "confirmation" and bool(pairs) and all(
            p["groups"] >= policy["min_confirmation_groups"] and not (p["abstentions"] or p["unreviewed"] or p["unavailable"] or p["disputed"]) for p in pairs)
        fidelity_safe = _fidelity_safe(candidate, pairs, assessments, policy)
        if sufficient and calibrated and audited and len(intervals) == len(pairs):
            if all(low > policy["practical_margin"] for low, _ in intervals) and fidelity_safe:
                status = "supported_quality_leader"
            elif all(low >= -policy["practical_margin"] and high <= policy["practical_margin"] for low, high in intervals) and fidelity_safe:
                status = "practically_equivalent"
        analysis["recommendations"][candidate] = {"status": status, "production": production,
            "pool": chosen_pool, "net_preference": sum(means) / len(means) if means else None,
            "fidelity_noninferiority": fidelity_safe}
    leaders = [c for c, result in analysis["recommendations"].items() if result["status"] == "provisional_leader"]
    if leaders:
        best = max(analysis["recommendations"][c]["net_preference"] for c in leaders)
        for candidate in leaders:
            if analysis["recommendations"][candidate]["net_preference"] < best:
                analysis["recommendations"][candidate]["status"] = "contender"
    eligible = [c for c, r in analysis["recommendations"].items() if r["production"] == "eligible"
                and r["status"] in ("supported_quality_leader", "practically_equivalent")]
    priced = [c for c in eligible if type(campaign.get("performance", {}).get(c, {}).get("cost_usd")) in (int, float)]
    analysis["value_recommendation"] = min(priced, key=lambda c: campaign["performance"][c]["cost_usd"]) if priced and len(priced) == len(eligible) else None
    analysis["production_status"] = "no_production_ready_candidate" if analysis["recommendations"] and all(
        r["production"] == "correction_required" for r in analysis["recommendations"].values()) else "see_candidate_requirements"
    analysis["interval_method"] = "simultaneous exact marginal bounds; bounded-mean fallback for fractional or weighted groups"
    return analysis


def _fidelity_safe(candidate, pairs, assessments, policy):
    """Require evidence of noninferiority, not merely a nonsignificant harm test."""
    if not pairs:
        return False
    for pair in pairs:
        rival = pair["b"] if pair["a"] == candidate else pair["a"]
        groups = defaultdict(lambda: defaultdict(list))
        strata = {}
        relevant = [r for r in assessments if r["pool"] == "confirmation" and r["candidate"] in (candidate, rival)]
        if not relevant or any(r["status"] != "judged" or r.get("disputed") for r in relevant):
            return False
        for row in assessments:
            if row["pool"] != "confirmation" or row["status"] != "judged" or row.get("disputed") or row["candidate"] not in (candidate, rival):
                continue
            bad = any(e["severity"] in ("major", "critical") and "linguistic" in e["impacts"] for e in row["evidence"])
            groups[row["content_group"]][row["candidate"]].append(int(bad))
            strata.setdefault(row["content_group"], row["stratum"])
        if any(candidate not in g or rival not in g for g in groups.values()):
            return False
        differences = {key: [(sum(g[candidate]) / len(g[candidate]) - sum(g[rival]) / len(g[rival]), strata[key])]
                       for key, g in groups.items()}
        mean, values, weight_squares = _weighted_values(differences, policy)
        if not values or not math.isfinite(mean):
            return False
        if policy["stratum_weights"] and len(values) >= 2:
            radius = math.sqrt(2 * math.log(2 / pair["alpha"]) * weight_squares)
            interval = [max(-1., mean - radius), min(1., mean + radius)]
        else:
            interval = paired_interval(values, pair["alpha"])
        if not interval or interval[1] > policy["fidelity_margin"]:
            return False
    return True


def suggested_contenders(campaign: dict) -> list[str]:
    report = summarize(campaign)
    eliminated = set()
    for pair in report["pools"]["screening"]["pairs"]:
        interval = pair["interval"]
        if interval and not pair["disputed"]:
            if interval[0] > campaign["policy"]["practical_margin"]:
                eliminated.add(pair["b"])
            elif interval[1] < -campaign["policy"]["practical_margin"]:
                eliminated.add(pair["a"])
    retained = [c for c in campaign["candidate_ids"] if c not in eliminated]
    return retained if len(retained) >= 2 else list(campaign["candidate_ids"])


def legacy_status(review: dict | None) -> str:
    if not review:
        return "Awaiting review"
    if review.get("status", "judged") != "judged":
        return review["status"].replace("_", " ").title()
    tiers = review.get("overall") or []
    if len(tiers) == 1 and len(tiers[0]) > 1:
        return "Reviewed · Full tie"
    if any(len(tier) > 1 for tier in tiers):
        return "Reviewed · Partial tie"
    return "Reviewed"


def sample_status(review: dict) -> str:
    comparisons = review.get("comparisons", [])
    if any(r.get("disputed") for r in [*comparisons, *review.get("assessments", [])]):
        return "Disputed"
    judged = [r for r in comparisons if r["status"] == "judged"]
    if judged and any(r["status"] == "unreviewed" for r in comparisons):
        return "Partially reviewed"
    if judged and any(r["status"] in STATUSES[1:] for r in comparisons):
        return "Partially judgeable"
    if not judged:
        return "Not judgeable" if any(r["status"] in (*STATUSES[1:], "unavailable") for r in comparisons) else "Awaiting review"
    if all(r.get("identical") for r in judged):
        return "Identical outputs"
    decisions = [r for r in judged if r["decision"] != "equivalent"]
    if not decisions:
        return "Equivalent quality"
    if len(judged) > 1:
        return "Mixed preferences"
    return "Clear preference" if decisions[0]["strength"] == "clear" else "Slight preference"


def comparison_sample_matches(sample: dict, selection="all", query="", *, mode="paired", scope=None) -> bool:
    """Shared comparison filters, without exposing reserved output in search."""
    scope = scope or {}
    paired = sample.get('paired_review') or {}
    comparisons = paired.get('comparisons', [])
    assessments = paired.get('assessments', [])
    if scope.get('candidate'):
        if scope.get('opponent'):
            if not any(r['pool'] == scope['pool'] and {r['left'], r['right']} == {scope['candidate'], scope['opponent']} for r in comparisons):
                return False
        elif not any(r['pool'] == scope['pool'] and r['candidate'] == scope['candidate'] for r in assessments):
            return False
    if selection == 'available' and sample.get('paired_holdout_locked'):
        return False
    review = sample.get('review')
    has_review = bool(review)
    if paired and mode == 'paired':
        has_review = any(r.get('status') == 'judged' for r in comparisons + assessments)
        if selection == 'reviewed' and not any(r['status'] == 'judged' for r in comparisons):
            return False
        if selection == 'ties' and sample_status(paired) not in ('Equivalent quality', 'Identical outputs'):
            return False
        review = {'notes': '\n'.join(r.get('notes', '') for r in comparisons),
                  'overall': [['equivalent', 'equivalent']]} if comparisons else None
    if selection == 'reviewed' and not review or selection == 'unreviewed' and has_review:
        return False
    if selection == 'follow_up' and not sample.get('human_follow_up'):
        return False
    if selection == 'ties' and not (review and any(len(tier) > 1 for tier in review.get('overall') or [])):
        return False
    if selection == 'notes' and not (review and str(review.get('notes') or '').strip()):
        return False
    if selection == 'problems' and not sample.get('has_problems'):
        return False
    if selection == 'disputed' and not any(r.get('disputed') for r in comparisons + assessments):
        return False
    query = query.strip().casefold()
    if not query:
        return True
    values = [sample.get('id', ''), sample.get('scene_id', ''), sample.get('stratum', ''),
              *(sample.get('sources') or []), str((review or {}).get('notes') or '')]
    if not sample.get('paired_holdout_locked'):
        for line in sample.get('lines') or []:
            values.extend(output.get('translation', '') for output in (line.get('outputs') or {}).values())
    return query in '\n'.join(str(value) for value in values).casefold()


def format_summary(campaign: dict, labels: dict[str, str]) -> str:
    report = campaign.get("analysis") or summarize(campaign)
    name = lambda c: labels.get(c, c)
    lines = ["Paired editorial review v3", f"Policy: {campaign['policy']['name']}",
             "Editing requirements, linguistic preference and production compliance are separate.",
             "Intervals cover source-content sampling, not judge bias. Pilot thresholds require calibration."]
    for candidate, recommendation in report["recommendations"].items():
        lines.append(f"{name(candidate)}: {recommendation['status'].replace('_', ' ')}; {recommendation['production'].replace('_', ' ')}")
    value = report.get("value_recommendation")
    lines.append("Value recommendation: " + (name(value) if value else "not established by the quality and production evidence"))
    for pool, data in report["pools"].items():
        lines.extend(["", pool.title()])
        for candidate, info in data["candidates"].items():
            if not info["total"] and not info["validity"]:
                continue
            editing = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in info["editing"].items())
            validity = info["validity"]
            lines.append(f"{name(candidate)}: {editing}; major fidelity {info['major_fidelity_blocks']}/{info['judged']} reviewed blocks; "
                         f"valid {validity.get('valid', 0)}/{validity.get('total', 0)} blocks.")
            for rule, values in info["rules"].items():
                lines.append(f"  {rule}: {values['violations']}/{values['opportunities']} violations; {values['reviewed_blocks']} blocks checked.")
        for pair in data["pairs"]:
            if not any(pair[k] for k in ("judged", "unavailable", "unreviewed", "abstentions", "disputed")):
                continue
            wins, losses = pair["wins_clear"] + pair["wins_slight"], pair["losses_clear"] + pair["losses_slight"]
            net = f"{pair['net_preference']:+.1%}" if pair["net_preference"] is not None else "unavailable"
            interval = "unavailable" if pair["interval"] is None else f"{pair['interval'][0]:+.1%} to {pair['interval'][1]:+.1%}"
            lines.append(f"{name(pair['a'])} vs {name(pair['b'])}: {wins} preferred ({pair['wins_clear']} clear, {pair['wins_slight']} slight), "
                         f"{pair['equivalent']} equivalent, {losses} other preferred ({pair['losses_clear']} clear, {pair['losses_slight']} slight); "
                         f"net {net}, simultaneous interval {interval}, {pair['groups']} content groups. "
                         f"Abstentions {pair['abstentions']}; disputed {pair['disputed']}; unavailable {pair['unavailable']}; pending {pair['unreviewed']}.")
    lines.extend(["", f"Intervals: {report['interval_method']}", f"Judge audit: {report['audit'] or 'not completed'}",
                  f"Human-gold calibration: {report['calibration'] or 'not supplied / not completed'}",
                  "Human follow-up: " + (", ".join(report["human_follow_up"]) or "none flagged"),
                  "Cost and latency cover observed generation, including retries; they do not establish translation quality."])
    return "\n".join(lines)
