"""Pure validation and scene-level statistics for blinded block reviews."""

from __future__ import annotations

import itertools
import random
from collections import Counter, defaultdict


REVIEW_STATUSES = ("judged", "insufficient_context", "needs_human_review")
ERROR_CATEGORIES = (
    "meaning", "omission", "addition", "terminology", "voice", "grammar", "runtime",
)
ERROR_SEVERITIES = ("minor", "major", "critical")


def sample_context(request: dict) -> dict:
    """Keep request boundaries and entry grouping; never merge context lines."""
    return {
        "history": list(request.get("history") or []),
        "system": str(request.get("system") or ""),
        "glossary": str(request.get("glossary") or ""),
        "sfx_reference": str(request.get("sfx_reference") or ""),
    }


def identical_groups(outputs: dict[str, list[str]]) -> list[list[str]]:
    groups = defaultdict(list)
    for label, block in outputs.items():
        groups[tuple(block)].append(label)
    return [labels for labels in groups.values() if len(labels) > 1]


def validate_evidence(value: object, sources: list[str], outputs: dict) -> dict:
    """Require attributable, exact quotations without imposing line-level scores."""
    if not isinstance(value, dict) or set(value) != set(outputs):
        raise ValueError("Error evidence must contain an array for every candidate label")
    for label, errors in value.items():
        if not isinstance(errors, list):
            raise ValueError(f"Error evidence for {label} must be an array")
        for error in errors:
            if not isinstance(error, dict):
                raise ValueError("Each error must be an object")
            if error.get("category") not in ERROR_CATEGORIES:
                raise ValueError("Unknown error category")
            if error.get("severity") not in ERROR_SEVERITIES:
                raise ValueError("Unknown error severity")
            line = error.get("line")
            if type(line) is not int or not 1 <= line <= len(sources):
                raise ValueError("Error evidence line is outside the source block")
            for field, block in (("source_quote", sources), ("translation_quote", outputs[label])):
                quote = error.get(field)
                if not isinstance(quote, str) or not quote or quote not in block[line - 1]:
                    raise ValueError(f"Error {field} must quote its indicated line exactly")
            if not isinstance(error.get("explanation"), str) or not error["explanation"].strip():
                raise ValueError("Error evidence requires an explanation")
    return value


def ranking_points(tiers: list[list[str]]) -> dict[str, float]:
    count = sum(map(len, tiers))
    points, position = {}, 0
    for tier in tiers:
        award = sum(count - 1 - i for i in range(position, position + len(tier))) / len(tier)
        points.update((candidate, award) for candidate in tier)
        position += len(tier)
    return points


def _relation(tiers: list[list[str]], a: str, b: str) -> int:
    ranks = {candidate: rank for rank, tier in enumerate(tiers) for candidate in tier}
    return (ranks[a] < ranks[b]) - (ranks[a] > ranks[b])


def _interval(values: list[float]) -> list[float] | None:
    if not values:
        return None
    values = sorted(values)
    return [round(values[int((len(values) - 1) * p)], 2) for p in (0.025, 0.975)]


def summarize_reviews(rows: list[dict], candidates: list[str], *, repetitions: int = 500) -> dict:
    """Bootstrap independent scenes, retaining every row within each scene.

    Primary rankings remain line-weighted for compatibility. These supplemental
    scores average normalized block ranks within a scene, then across scenes.
    A paired resample is shared by all candidates. Abstentions never earn points.
    """
    judged = [row for row in rows if row["status"] == "judged"]
    coverage = Counter(row["status"] for row in rows)
    by_stratum = {}
    for stratum in sorted({row["stratum"] for row in rows}):
        subset = [row for row in judged if row["stratum"] == stratum]
        points = {c: 0.0 for c in candidates}
        quality = {}
        for row in subset:
            for metric, tiers in row["rankings"].items():
                scores = points if metric == "overall" else quality.setdefault(metric, {c: 0.0 for c in candidates})
                for candidate, award in ranking_points(tiers).items():
                    scores[candidate] += award * row["line_count"]
        by_stratum[stratum] = {
            "samples": len(subset), "lines": sum(r["line_count"] for r in subset),
            "scenes": len({r["scene_id"] for r in subset}),
            "abstentions": sum(r["status"] != "judged" and r["stratum"] == stratum for r in rows),
            "points": points, "quality_points": quality,
        }

    metrics = sorted({metric for row in judged for metric in row["rankings"]})
    scene_statistics = {}
    overall_draws = {}
    for metric in metrics:
        scene_rows = defaultdict(list)
        for row in judged:
            if metric in row["rankings"]:
                scene_rows[row["scene_id"]].append(row)
        scenes = sorted(scene_rows)
        scores = {c: [] for c in candidates}
        for scene in scenes:
            scene_points = [ranking_points(row["rankings"][metric]) for row in scene_rows[scene]]
            for candidate in candidates:
                scores[candidate].append(
                    100 * sum(p[candidate] / (len(candidates) - 1) for p in scene_points) / len(scene_points)
                )
        means = {c: sum(v) / len(v) for c, v in scores.items()}
        draws = {c: [] for c in candidates}
        if len(scenes) >= 2:
            rng = random.Random("scene-review-bootstrap-v1")
            for _ in range(repetitions):
                indices = [rng.randrange(len(scenes)) for _ in scenes]
                for candidate in candidates:
                    draws[candidate].append(sum(scores[candidate][i] for i in indices) / len(indices))
        scene_statistics[metric] = {
            c: {"score": round(means[c], 2), "ci95": _interval(draws[c])}
            for c in candidates
        }
        if metric == "overall":
            overall_draws = draws

    pairwise = []
    for a, b in itertools.combinations(candidates, 2):
        relations = Counter(_relation(r["rankings"]["overall"], a, b) for r in judged)
        differences = [x - y for x, y in zip(overall_draws.get(a, []), overall_draws.get(b, []))]
        pairwise.append({
            "a": a, "b": b, "wins": relations[1], "ties": relations[0], "losses": relations[-1],
            "scene_difference_ci95": _interval(differences),
        })
    errors = {c: dict.fromkeys(ERROR_SEVERITIES, 0) for c in candidates}
    follow_up = []
    for row in rows:
        consequential = False
        for candidate, evidence in row.get("evidence", {}).items():
            for error in evidence:
                errors[candidate][error["severity"]] += 1
                consequential |= error["severity"] in ("major", "critical")
        if consequential or row["status"] in ("insufficient_context", "needs_human_review"):
            follow_up.append(row["sample_id"])
    return {
        "coverage": dict(coverage), "by_stratum": by_stratum,
        "scene_count": len({r["scene_id"] for r in judged}),
        "scene_scores": scene_statistics, "pairwise": pairwise, "errors": errors,
        "human_follow_up": follow_up,
        "bootstrap": {"unit": "scene", "repetitions": repetitions, "confidence": 0.95},
    }


def judge_agreement(baseline: list[dict], repeated: list[dict]) -> dict:
    """Compare mapped preferences, never randomized letters or translation strings."""
    previous = {r["sample_id"]: r for r in baseline}
    compared = agreed = 0
    disputed, exact, samples = [], 0, 0
    metrics = defaultdict(lambda: {"comparisons": 0, "agreements": 0})
    for row in repeated:
        old = previous.get(row["sample_id"])
        if not old or old["status"] != "judged" or row["status"] != "judged":
            continue
        candidates = sorted(c for tier in row["rankings"]["overall"] for c in tier)
        if set(candidates) != {c for tier in old["rankings"]["overall"] for c in tier}:
            continue
        samples += 1
        same = True
        for metric in set(row["rankings"]) & set(old["rankings"]):
            for a, b in itertools.combinations(candidates, 2):
                match = _relation(row["rankings"][metric], a, b) == _relation(old["rankings"][metric], a, b)
                metrics[metric]["comparisons"] += 1
                metrics[metric]["agreements"] += match
                if metric == "overall":
                    compared += 1
                    agreed += match
                    same &= match
        exact += same
        if not same:
            disputed.append(row["sample_id"])
    return {
        "samples": samples, "exact_rank_agreements": exact,
        "pair_comparisons": compared, "pair_agreements": agreed,
        "pair_agreement_rate": agreed / compared if compared else None,
        "by_metric": dict(metrics), "disputed_samples": disputed,
    }


def sampling_summary(segments: list[dict]) -> dict:
    by_scene = Counter(s["scene_id"] for s in segments)
    strata = {}
    for stratum in sorted({s["stratum"] for s in segments}):
        subset = [s for s in segments if s["stratum"] == stratum]
        scenes = Counter(s["scene_id"] for s in subset)
        strata[stratum] = {"lines": len(subset), "scenes": len(scenes), "largest_scene_lines": max(scenes.values())}
    return {
        "scenes": len(by_scene), "largest_scene_lines": max(by_scene.values(), default=0),
        "largest_scene_share": max(by_scene.values(), default=0) / len(segments) if segments else 0,
        "by_stratum": strata,
    }


def format_review_summary(review: dict, labels: dict[str, str]) -> str:
    """Plain report shared by the UI and exported review summary."""
    analysis = review.get("analysis") or {}
    if not analysis:
        return "Import a new review to see scene statistics, error severity and judge agreement."
    coverage = analysis["coverage"]
    lines = [
        f"Reviewer: {review.get('reviewer') or 'unspecified'} ({review.get('reviewer_kind') or 'unspecified'}).",
        f"Judged: {coverage.get('judged', 0)} samples across {analysis['scene_count']} scenes. "
        f"Insufficient context: {coverage.get('insufficient_context', 0)}. "
        f"Needs human review: {coverage.get('needs_human_review', 0)}. "
        f"Not yet reviewed: {coverage.get('unreviewed', 0)}.",
        f"Export coverage: {review.get('export_coverage', {}).get('eligible_samples', '?')}/"
        f"{review.get('export_coverage', {}).get('total_samples', '?')} complete samples. "
        "Quality scores cover successful outputs; keep Valid and cost in the comparison.",
        "", "Scene-balanced scores (0–100; 95% scene-bootstrap intervals):",
    ]
    for metric, scores in analysis["scene_scores"].items():
        lines.append(metric.replace('_', ' ').title())
        for candidate, values in scores.items():
            ci = values["ci95"]
            interval = f"{ci[0]:g}–{ci[1]:g}" if ci else "unavailable: fewer than two scenes"
            lines.append(f"  {labels.get(candidate, candidate)}: {values['score']:g} ({interval})")
    lines.extend(["", "By content category (line-weighted overall points):"])
    for stratum, values in analysis["by_stratum"].items():
        points = "; ".join(f"{labels.get(c, c)} {p:g}" for c, p in values["points"].items())
        lines.append(f"{stratum}: {values['samples']} samples, {values['scenes']} scenes, {values['lines']} lines; {points}")
        for metric, scores in values["quality_points"].items():
            lines.append(f"  {metric}: " + "; ".join(f"{labels.get(c, c)} {p:g}" for c, p in scores.items()))
    lines.extend(["", "Pairwise wins / ties / losses (whole samples):"])
    for pair in analysis["pairwise"]:
        ci = pair['scene_difference_ci95']
        lines.append(f"{labels.get(pair['a'], pair['a'])} vs {labels.get(pair['b'], pair['b'])}: "
                     f"{pair['wins']} / {pair['ties']} / {pair['losses']}; scene-score difference 95% interval: {ci or 'unavailable'}")
    lines.extend(["", "Recorded errors (not independent line scores):"])
    for candidate, counts in analysis["errors"].items():
        lines.append(f"{labels.get(candidate, candidate)}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    agreement = review.get("judge_agreement")
    if agreement:
        rate = agreement['pair_agreement_rate']
        lines.append("")
        if rate is None:
            lines.append("Judge check: no overlapping judged samples.")
        else:
            lines.append(f"Judge check: {agreement['samples']} overlapping judged samples; pairwise agreement {rate:.1%}.")
        lines.append("Disagreements: " + (", ".join(agreement['disputed_samples']) or "none"))
    lines.extend(["", "Qualified human follow-up: " + (", ".join(analysis['human_follow_up']) or "none flagged"),
                  "Intervals describe scene sampling only, not judge bias. Small scene counts remain weak evidence."])
    return "\n".join(lines)
