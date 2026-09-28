"""Protected CSV and persisted campaign boundaries for paired reviews.

Candidate mappings and calibration answers stay in private run state. Exports
contain only source context, anonymous outputs, policy, and review forms.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import math
import random
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from util import evaluation_pairwise as paired


def _engine():
    # The legacy evaluator exposes this workflow without importing it during
    # unrelated translation startup or introducing an import cycle.
    from util import evaluation
    return evaluation


def _source_data(root, state, manifest):
    engine = _engine()
    results = engine._candidate_results(root, state, manifest)
    primary = defaultdict(dict)
    for candidate, result in results.items():
        for execution in result.get("executions", {}).values():
            if execution.get("repetition") != 1:
                continue
            for line in execution.get("lines", []):
                primary[line["segment_id"]][candidate] = line
    segments = {s["id"]: s for s in manifest.get("segments", [])}
    requests = manifest.get("logical_requests") or [dict(id=s["id"], segment_ids=[s["id"]]) for s in segments.values()]
    samples = []
    for request in requests:
        ids = request.get("segment_ids") or []
        if not ids:
            continue
        first = segments[ids[0]]
        sample = {"id": request["id"], "scene_id": request.get("scene_id") or first.get("scene_id", request["id"]),
                  "stratum": request.get("stratum") or first.get("stratum", "unknown"),
                  "sources": request.get("sources") or [segments[s]["source"] for s in ids],
                  "context": engine.review_stats.sample_context(request), "outputs": {}, "output_status": {}}
        for candidate in state["candidates"]:
            cid = candidate["id"]
            lines = [primary[s].get(cid) for s in ids]
            sample["outputs"][cid] = [str((line or {}).get("translation") or "") for line in lines]
            sample["output_status"][cid] = "missing" if any(line is None for line in lines) else "invalid" if any(
                not line.get("valid", True) for line in lines) else "valid"
        samples.append(sample)
    return samples


def _exposed(state):
    seen = set()
    for export in state.get("review_exports", {}).values():
        seen.update(export.get("key", {}))
    for export in state.get("paired_exports", {}).values():
        seen.update(export.get("sample_ids", []))
    return seen


def _campaign(state, samples, candidate_ids=None, policy=None, *, new=False, challenge_samples=()):
    current = state.get("paired_review")
    if current and not new:
        if policy is not None and paired.validate_policy(policy) != current["policy"]:
            raise ValueError("Policy is frozen. Start a new campaign to change it.")
        if paired.digest(samples) != current["source_digest"]:
            raise ValueError("Frozen campaign source or outputs changed; start a new campaign")
        saved = copy.deepcopy(current)
        if not saved["plan"]["confirmation_candidates"]:
            exposed_elsewhere = {sid for export in state.get("review_exports", {}).values() for sid in export.get("key", {})}
            exposed_elsewhere.update(sid for export in state.get("paired_exports", {}).values()
                                     if export["campaign_id"] != saved["campaign_id"] for sid in export.get("sample_ids", []))
            saved["plan"]["contaminated_confirmation"] = sorted(sid for sid in exposed_elsewhere
                if saved["plan"]["pools"].get(sid) == "confirmation")
        return saved
    ids = candidate_ids or [c["id"] for c in state["candidates"]]
    available = {c["id"] for c in state["candidates"]}
    if len(ids) < 2 or len(set(ids)) != len(ids) or not set(ids) <= available:
        raise ValueError("Select at least two distinct evaluation candidates")
    policy = paired.validate_policy(policy)
    cid = uuid.uuid4().hex
    plan = paired.make_plan(samples, policy, paired.digest([(s["id"], s["sources"]) for s in samples]),
                            _exposed(state), challenge_samples)
    return {"version": paired.VERSION, "campaign_id": cid, "candidate_ids": list(ids),
            "policy": policy, "source_digest": paired.digest(samples), "plan": plan,
            "assessments": {}, "comparisons": {}, "audits": {}, "coverage": {},
            "created_at": _engine()._utc_now()}


def preview(run_dir, *, stage="screening", candidate_ids=None, policy=None, new_campaign=False,
            challenge_samples=()) -> dict:
    engine = _engine()
    root = Path(run_dir)
    state, manifest = engine.load_run(root)
    if state.get("status") not in ("completed", "failed"):
        raise ValueError("Finish generation before exporting paired reviews")
    samples = _source_data(root, state, manifest)
    campaign = _campaign(state, samples, candidate_ids, policy, new=new_campaign, challenge_samples=challenge_samples)
    records, metadata = _records(campaign, samples, stage, candidate_ids)
    return {"campaign_id": campaign["campaign_id"], "stage": stage,
            "records": len(records), "counts": dict(Counter(r["record_type"] for r in records)),
            "groups": campaign["plan"]["group_counts"], "metadata": metadata,
            "suggested_contenders": paired.suggested_contenders(campaign),
            "policy": campaign["policy"], "has_existing_campaign": bool(state.get("paired_review"))}


def _base_row(campaign, sample, record_type, pool, mapping):
    dump = lambda value: json.dumps(value, ensure_ascii=False)
    outputs = {label: sample["outputs"][cid] for label, cid in mapping.items()}
    groups = _engine().review_stats.identical_groups(outputs)
    row = dict.fromkeys(paired.FIELDS, "")
    row.update({"schema_version": "3", "record_id": uuid.uuid4().hex,
        "record_type": record_type, "pool": pool, "sample_id": sample["id"],
        "content_group": campaign["plan"]["groups"].get(sample["id"], sample["id"]),
        "scene_id": sample["scene_id"], "stratum": sample["stratum"],
        "line_count": str(len(sample["sources"])), "source": dump(sample["sources"]),
        "context": dump(sample["context"]), "policy": dump(campaign["policy"]),
        "outputs": dump(outputs), "output_status": dump({k: sample["output_status"][c] for k, c in mapping.items()}),
        "identical_candidates": dump(groups)})
    if record_type == "assessment":
        row["error_evidence"] = dump({label: [] for label in mapping})
        row["rule_checks"] = dump({label: [] for label in mapping})
    elif record_type == "comparison":
        row["comparison_evidence"] = "[]"
    if record_type != "sample" and any(sample["output_status"][c] != "valid" for c in mapping.values()):
        row["status"] = "unavailable"
        row["notes"] = "Missing or invalid output; retained in production reliability coverage."
    return row


def _task_key(kind, sample_id, candidates):
    return kind + ":" + paired.digest([sample_id, sorted(candidates)])[:24]


def _records(campaign, samples, stage, selected_candidates=None):
    ids = campaign["candidate_ids"]
    by_id = {s["id"]: s for s in samples}
    rows, bindings = [], {}
    def add(sample, kind, mapping, pool, **extra):
        row = _base_row(campaign, sample, kind, pool, mapping)
        rows.append(row)
        bindings[row["record_id"]] = {"mapping": mapping, "task_key": _task_key(kind, sample["id"], mapping.values()), **extra}
        return row
    if stage in ("order_swap", "judge_check", "adjudication"):
        follow_up = set(paired.summarize(campaign)["human_follow_up"])
        candidates = [r for r in campaign["comparisons"].values() if r["status"] in (paired.STATUSES if stage == "adjudication" else ("judged",))
                      and (not r.get("identical") or r["sample_id"] in follow_up)]
        random.Random(campaign["campaign_id"] + ":" + stage).shuffle(candidates)
        selected = []
        for pool in paired.POOLS[:3]:
            pool_rows = [r for r in candidates if r["pool"] == pool]
            selected.extend(pool_rows[:math.ceil(len(pool_rows) * campaign["policy"]["audit_fraction"])])
        tasks = {r["task_key"] for r in selected}
        selected += [r for r in candidates if r["sample_id"] in follow_up and r["task_key"] not in tasks]
        if stage == "adjudication":
            selected = [r for r in candidates if r["sample_id"] in follow_up]
        for record in selected:
            mapping = {"A": record["right"], "B": record["left"]}
            add(by_id[record["sample_id"]], "comparison", mapping, record["pool"],
                baseline_task=record["task_key"], baseline_digest=paired.digest(record), baseline_reviewer=record.get("reviewer", ""))
        if stage in ("judge_check", "adjudication"):
            assessed = [r for r in campaign["assessments"].values() if r["status"] in (paired.STATUSES if stage == "adjudication" else ("judged",))]
            random.Random(campaign["campaign_id"] + ":assessments").shuffle(assessed)
            selected_assessments = assessed[:max(1, math.ceil(len(assessed) * campaign["policy"]["audit_fraction"]))]
            selected_keys = {r["task_key"] for r in selected_assessments}
            selected_assessments += [r for r in assessed if r["sample_id"] in follow_up and r["task_key"] not in selected_keys]
            if stage == "adjudication":
                selected_assessments = [r for r in assessed if r["sample_id"] in follow_up]
            for record in selected_assessments:
                add(by_id[record["sample_id"]], "assessment", {"A": record["candidate"]}, record["pool"],
                    duplicate_candidates=[record["candidate"]], baseline_task=record["task_key"],
                    baseline_digest=paired.digest(record), baseline_reviewer=record.get("reviewer", ""))
        if not rows:
            raise ValueError("Import judgeable comparisons or assessments before exporting this audit")
        return rows, {"bindings": bindings, "audit_kind": stage}
    if stage == "calibration":
        suite = campaign.get("calibration_suite")
        if not suite:
            raise ValueError("Load a human-authored calibration suite before calibration export")
        for case in suite["cases"]:
            if case.get("type", "comparison") == "assessment":
                sample = {"id": case["id"], "scene_id": case["id"], "stratum": "calibration",
                    "sources": case["source"], "context": case["context"],
                    "outputs": {"gold": case["output"]}, "output_status": {"gold": "valid"}}
                add(sample, "assessment", {"A": "gold"}, "calibration", duplicate_candidates=["gold"],
                    gold=case["expected"])
                continue
            sample = {"id": case["id"], "scene_id": case["id"], "stratum": "calibration",
                "sources": case["source"], "context": case["context"],
                "outputs": {"gold-left": case["left"], "gold-right": case["right"]},
                "output_status": {"gold-left": "valid", "gold-right": "valid"}}
            order = ["gold-left", "gold-right"]
            random.SystemRandom().shuffle(order)
            add(sample, "comparison", dict(zip(("A", "B"), order)), "calibration", gold=case["decision"])
        return rows, {"bindings": bindings, "calibration_digest": paired.digest(suite)}
    if stage not in paired.POOLS[:3]:
        raise ValueError("Unknown paired review stage")
    if stage == "confirmation":
        if campaign["plan"].get("contaminated_confirmation"):
            raise ValueError("Reserved confirmation sources were exposed by another review export; use fresh source groups")
        screening = [r for r in campaign["comparisons"].values() if r["pool"] == "screening"]
        if not screening or not any(r["status"] == "judged" for r in screening) or any(r["status"] == "unreviewed" for r in screening):
            raise ValueError("Complete the screening review before confirmation")
        ids = selected_candidates or paired.suggested_contenders(campaign)
        plausible = set(paired.suggested_contenders(campaign))
        if not plausible <= set(ids):
            raise ValueError("Confirmation must retain all statistically plausible contenders")
        frozen = campaign["plan"]["confirmation_candidates"]
        if frozen and list(ids) != frozen:
            raise ValueError("Confirmation contenders are frozen for this campaign")
        if len(ids) < 2 or not set(ids) <= set(campaign["candidate_ids"]):
            raise ValueError("Invalid confirmation candidate selection")
        campaign["plan"]["confirmation_candidates"] = list(ids)
    elif selected_candidates is not None and set(selected_candidates) != set(ids):
        raise ValueError("Candidate selection is frozen; start a new campaign to change it")
    selected = [s for s in samples if campaign["plan"]["pools"][s["id"]] == stage]
    if not selected:
        raise ValueError(f"No {stage} groups are available. Confirmation needs unexposed source groups; challenge groups need source codes or explicit selection.")
    group_order = {g: i for i, g in enumerate(dict.fromkeys(campaign["plan"]["groups"][s["id"]] for s in selected))}
    for sample in selected:
        shuffled = list(ids)
        random.SystemRandom().shuffle(shuffled)
        add(sample, "sample", {_engine()._blind_label(i): c for i, c in enumerate(shuffled)}, stage)
        unique = defaultdict(list)
        for cid in ids:
            unique[(tuple(sample["outputs"][cid]), sample["output_status"][cid])].append(cid)
        for duplicate_ids in unique.values():
            add(sample, "assessment", {"A": duplicate_ids[0]}, stage, duplicate_candidates=duplicate_ids)
        group = campaign["plan"]["groups"][sample["id"]]
        for a, b in paired.scheduled_pairs(ids, group_order[group], complete=stage != "screening"):
            order = [a, b]
            random.SystemRandom().shuffle(order)
            add(sample, "comparison", dict(zip(("A", "B"), order)), stage)
    return rows, {"bindings": bindings, "audit_kind": ""}


def export_review(run_dir, output_path=None, *, stage="screening", candidate_ids=None,
                  policy=None, new_campaign=False, challenge_samples=()) -> Path:
    engine = _engine()
    root = Path(run_dir)
    with engine._evaluation_submit_lock(root):
        state, manifest = engine.load_run(root)
        if state.get("status") not in ("completed", "failed"):
            raise ValueError("Finish generation before exporting paired reviews")
        samples = _source_data(root, state, manifest)
        old = state.get("paired_review")
        campaign = _campaign(state, samples, candidate_ids, policy, new=new_campaign, challenge_samples=challenge_samples)
        rows, metadata = _records(campaign, samples, stage, candidate_ids)
        review_id = uuid.uuid4().hex
        for row in rows:
            row["review_id"] = review_id
            metadata["bindings"][row["record_id"]]["protected_digest"] = paired.digest({key: row[key] for key in paired.PROTECTED_FIELDS})
        # Source snapshot records are covered by the same import protection but
        # are not extra scored judgments. They retain all candidate failures.
        for pool in paired.POOLS[:3]:
            scoped = [s for s in samples if campaign["plan"]["pools"][s["id"]] == pool]
            campaign["coverage"][pool] = {cid: {"total": len(scoped),
                "valid": sum(s["output_status"][cid] == "valid" for s in scoped),
                "source_lines": sum(len(s["sources"]) for s in scoped)} for cid in campaign["candidate_ids"]}
        archive_name = f"paired_review.{stage}.{review_id[:8]}.csv"
        export = {"campaign_id": campaign["campaign_id"], "stage": stage, "file": archive_name,
            "sample_ids": sorted({r["sample_id"] for r in rows if r["pool"] != "calibration"}),
            "record_order": [r["record_id"] for r in rows], "created_at": engine._utc_now(), **metadata}
        campaign["performance"] = {c["id"]: {"cost_usd": (c.get("summary") or {}).get("actual_cost_usd"),
            "live_latency": (c.get("summary") or {}).get("live_latency")} for c in state["candidates"] if c["id"] in campaign["candidate_ids"]}
        output = Path(output_path) if output_path else root / f"paired_review.{stage}.{review_id[:8]}.csv"
        if output.suffix.lower() != ".csv":
            raise ValueError("Paired reviews must be saved as CSV files")
        protected_paths = {root / "state.json", root / "manifest.json", root / "blind_key.json", root / "blind_review.csv"}
        if output.resolve() in {p.resolve() for p in protected_paths}:
            raise ValueError("Choose a new paired CSV path; protected or legacy files cannot be overwritten")
        with io.StringIO(newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=paired.FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            text = "\ufeff" + stream.getvalue()
            engine._atomic_write_text_exact(output, text)
            if output.resolve() != (root / archive_name).resolve():
                engine._atomic_write_text_exact(root / archive_name, text)
        if old and new_campaign:
            state.setdefault("paired_review_history", {})[old["campaign_id"]] = old
        campaign["last_export_path"] = str(output.resolve())
        state["paired_review"] = campaign
        state.setdefault("paired_exports", {})[review_id] = export
        state["updated_at"] = engine._utc_now()
        engine._atomic_write_json(root / "state.json", state)
        return output.resolve()


def is_paired_csv(path) -> bool:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return "schema_version" in next(csv.reader(stream), [])


def import_review(run_dir, review_path, *, reviewer="", reviewer_kind="unspecified") -> dict:
    if reviewer_kind not in ("unspecified", "ai", "human"):
        raise ValueError("Unknown reviewer kind")
    if not reviewer.strip():
        raise ValueError("Paired review requires a reviewer name/session for audit provenance")
    engine = _engine()
    root = Path(run_dir)
    with engine._evaluation_submit_lock(root):
        state, manifest = engine.load_run(root)
        with Path(review_path).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != list(paired.FIELDS):
                raise ValueError("Paired CSV must preserve its exact columns and order")
            rows = list(reader)
        if any(set(row) != set(paired.FIELDS) or any(value is None for value in row.values()) for row in rows):
            raise ValueError("Paired CSV rows must have exactly the declared field count")
        ids = {r.get("review_id") for r in rows}
        if len(ids) != 1:
            raise ValueError("Paired CSV must belong to one known export")
        export_id = next(iter(ids))
        export = state.get("paired_exports", {}).get(export_id)
        campaign = copy.deepcopy(state.get("paired_review"))
        if not export or not campaign or export["campaign_id"] != campaign["campaign_id"]:
            raise ValueError("Unknown or inactive paired review export")
        if export["stage"] == "adjudication" and reviewer_kind != "human":
            raise ValueError("Adjudication must be imported as a qualified human review")
        samples = _source_data(root, state, manifest)
        if paired.digest(samples) != campaign["source_digest"]:
            raise ValueError("Frozen evaluation source or outputs changed")
        if [r.get("record_id") for r in rows] != export["record_order"]:
            raise ValueError("Paired CSV must preserve every row and its order")
        parsed = []
        try:
            for row in rows:
                binding = export["bindings"][row["record_id"]]
                if paired.digest({key: row.get(key) for key in paired.PROTECTED_FIELDS}) != binding["protected_digest"]:
                    raise ValueError("Protected paired review input changed")
                mapping = binding["mapping"]
                if row["record_type"] == "sample":
                    if any(row[key] for key in paired.EDITABLE_FIELDS):
                        raise ValueError("Sample snapshot rows cannot be edited")
                    continue
                source, outputs = json.loads(row["source"]), json.loads(row["outputs"])
                unavailable = any(v != "valid" for v in json.loads(row["output_status"]).values())
                if unavailable != (row["status"] == "unavailable"):
                    raise ValueError("Missing/invalid output must remain unavailable; valid output cannot be hidden")
                if row["record_type"] == "assessment":
                    result = paired.validate_assessment(row, source, outputs, campaign["policy"])
                else:
                    result = paired.validate_comparison(row, source, outputs)
                record = {"sample_id": row["sample_id"], "scene_id": row["scene_id"],
                    "content_group": row["content_group"], "stratum": row["stratum"], "pool": row["pool"],
                    "type": row["record_type"], "task_key": binding["task_key"],
                    "reviewer": reviewer.strip(), "reviewer_kind": reviewer_kind,
                    "export_id": export_id, **result}
                if export["stage"] in ("order_swap", "judge_check", "adjudication"):
                    collection = campaign["assessments" if row["record_type"] == "assessment" else "comparisons"]
                    baseline = collection.get(binding["baseline_task"])
                    revising_own_adjudication = baseline and export["stage"] == "adjudication" and baseline["export_id"] == export_id
                    if not baseline or (not revising_own_adjudication and paired.digest(baseline) != binding["baseline_digest"]):
                        raise ValueError("Baseline comparison or assessment changed; export a fresh audit")
                    if export["stage"] == "judge_check" and reviewer.strip().casefold() == binding["baseline_reviewer"].casefold():
                        raise ValueError("Independent judge check requires a different reviewer/session")
                    record["baseline_task"] = binding["baseline_task"]
                if row["record_type"] == "assessment":
                    record.update(candidate=mapping["A"], output_digest=paired.digest(outputs["A"]),
                                  evidence=result["evidence"]["A"], rules=result["rules"]["A"])
                    if export["stage"] == "calibration":
                        record["gold"] = binding["gold"]
                    for candidate in binding["duplicate_candidates"]:
                        copied = copy.deepcopy(record)
                        copied["candidate"] = candidate
                        copied["task_key"] = _task_key("assessment", row["sample_id"], [candidate])
                        parsed.append(copied)
                else:
                    record.update(left=mapping["A"], right=mapping["B"], identical=outputs["A"] == outputs["B"])
                    if export["stage"] == "calibration":
                        record["gold"] = binding["gold"]
                    parsed.append(record)
        except (TypeError, KeyError, AttributeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid paired review record: {exc}") from exc
        if not any(r["status"] in paired.STATUSES for r in parsed):
            raise ValueError("Paired CSV contains no completed judgments or abstentions")
        stage = export["stage"]
        if stage == "adjudication":
            signatures = {}
            for record in parsed:
                if record["type"] != "assessment" or record["status"] == "unreviewed":
                    continue
                key = (record["sample_id"], record["output_digest"])
                signature = (record["status"], paired.assessment_signature(record) if record["status"] == "judged" else None)
                if key in signatures and signatures[key] != signature:
                    raise ValueError("Identical outputs must receive consistent human adjudication")
                signatures[key] = signature
        if stage in ("order_swap", "judge_check"):
            campaign["audits"][export_id] = {"kind": stage, "records": parsed, "reviewer": reviewer}
        elif stage == "calibration":
            suite = campaign.get("calibration_suite")
            if not suite or paired.digest(suite) != export["calibration_digest"]:
                raise ValueError("Calibration gold changed; export a fresh calibration review")
            judged = [r for r in parsed if r["status"] == "judged"]
            expected = {"left": 1, "equivalent": 0, "right": -1}
            def matches_gold(record):
                if record["type"] == "comparison":
                    return paired.outcome(record, "gold-left") == expected[record["gold"]]
                gold = record["gold"]
                signature = paired.assessment_signature(record)
                return (signature[:3] == (gold["editing"], gold["major_linguistic"], gold["critical"])
                        and {rule for rule, count in signature[3] if count} == set(gold["violated_rules"]))
            matches = sum(matches_gold(r) for r in judged)
            campaign["calibration_result"] = {"cases": len(parsed), "judged": len(judged),
                "agreement": matches / len(parsed), "human_gold": True,
                "record_types": sorted({r["type"] for r in parsed}),
                "by_type": {kind: {"cases": sum(r["type"] == kind for r in parsed),
                    "agreement": sum(r["type"] == kind and r["status"] == "judged" and matches_gold(r) for r in parsed)
                    / max(1, sum(r["type"] == kind for r in parsed))} for kind in ("assessment", "comparison")},
                "reviewer": reviewer, "reviewer_kind": reviewer_kind, "suite_digest": paired.digest(suite),
                "gold_author": suite["author"], "export_id": export_id}
            campaign.setdefault("calibration_results", {})[reviewer] = copy.deepcopy(campaign["calibration_result"])
        else:
            if stage == "adjudication":
                history = campaign.setdefault("adjudication_history", {}).setdefault(export_id, {"before": {}, "reviewer": reviewer})
            for record in parsed:
                if stage == "adjudication" and record["status"] == "unreviewed":
                    continue
                container = campaign["assessments" if record["type"] == "assessment" else "comparisons"]
                previous = container.get(record["task_key"])
                if previous and previous["export_id"] != export_id and stage != "adjudication":
                    raise ValueError("This task already has a review from another export; use an audit or a new campaign")
                if stage == "adjudication":
                    history["before"].setdefault(record["task_key"], copy.deepcopy(previous))
                    record["adjudicated"] = True
                    if record["type"] == "assessment":
                        for key, duplicate in list(container.items()):
                            if duplicate["sample_id"] == record["sample_id"] and duplicate.get("output_digest") == record["output_digest"]:
                                history["before"].setdefault(key, copy.deepcopy(duplicate))
                                container[key] = dict(copy.deepcopy(record), task_key=key, candidate=duplicate["candidate"])
                container[record["task_key"]] = record
            # Updated baselines invalidate their old audit results rather than
            # letting stale judgments affect the new conclusion.
            for audit_id in list(campaign["audits"]):
                audit_export = state["paired_exports"][audit_id]
                stale = {b["baseline_task"] for b in audit_export["bindings"].values()
                         if paired.digest(campaign["comparisons"].get(b["baseline_task"], campaign["assessments"].get(b["baseline_task"], {}))) != b["baseline_digest"]}
                if stale:
                    records = campaign["audits"][audit_id]["records"]
                    campaign.setdefault("superseded_audits", []).append({"export_id": audit_id,
                        "records": [r for r in records if r["baseline_task"] in stale]})
                    campaign["audits"][audit_id]["records"] = [r for r in records if r["baseline_task"] not in stale]
                    if not campaign["audits"][audit_id]["records"]:
                        del campaign["audits"][audit_id]
        campaign["analysis"] = paired.summarize(campaign)
        campaign["last_import_path"] = str(Path(review_path).resolve())
        campaign["updated_at"] = engine._utc_now()
        state["paired_review"] = campaign
        state.setdefault("paired_imports", {})[export_id] = {"reviewer": reviewer, "reviewer_kind": reviewer_kind,
            "csv_sha256": engine._sha256(Path(review_path).read_bytes()), "imported_at": engine._utc_now()}
        state["updated_at"] = engine._utc_now()
        engine._atomic_write_json(root / "state.json", state)
        return campaign


def load_calibration_suite(run_dir, suite_path) -> dict:
    """Load user-supplied human gold; never manufacture a human calibration set."""
    suite = json.loads(Path(suite_path).read_text(encoding="utf-8-sig"))
    if not isinstance(suite, dict) or suite.get("version") != 1 or suite.get("author_kind") != "human" or not isinstance(suite.get("author"), str) or not suite["author"].strip():
        raise ValueError("Calibration requires version 1, a human author, and author_kind=human")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Calibration suite requires cases")
    seen, input_signatures = set(), set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"].strip() or case["id"] in seen:
            raise ValueError("Calibration case IDs must be unique")
        seen.add(case["id"])
        kind = case.get("type", "comparison")
        if kind not in ("assessment", "comparison"):
            raise ValueError("Calibration type must be assessment or comparison")
        output_fields = ("left", "right") if kind == "comparison" else ("output",)
        for key in ("source", *output_fields):
            if not isinstance(case.get(key), list) or not case[key] or not all(isinstance(x, str) for x in case[key]):
                raise ValueError("Calibration source and outputs must be nonempty string arrays")
        if any(len(case["source"]) != len(case[key]) for key in output_fields):
            raise ValueError("Calibration lines must align")
        if not isinstance(case.get("context"), dict) or set(case["context"]) != {"history", "system", "glossary", "sfx_reference"}:
            raise ValueError("Calibration requires complete model-blind context")
        if not isinstance(case["context"]["history"], list) or not all(isinstance(x, str) for x in case["context"]["history"]) or not all(
                isinstance(case["context"][key], str) for key in ("system", "glossary", "sfx_reference")):
            raise ValueError("Calibration context has invalid field types")
        signature = paired.digest([kind, case["source"], case["context"], *[case[key] for key in output_fields]])
        if signature in input_signatures:
            raise ValueError("Duplicate calibration inputs cannot inflate case coverage")
        input_signatures.add(signature)
        if kind == "comparison" and case.get("decision") not in paired.DECISIONS:
            raise ValueError("Calibration gold decision must be left, right, or equivalent")
        if kind == "comparison" and case["left"] == case["right"] and case["decision"] != "equivalent":
            raise ValueError("Identical calibration outputs must have equivalent gold")
        if kind == "assessment":
            expected = case.get("expected")
            if not isinstance(expected, dict) or set(expected) != {"editing", "major_linguistic", "critical", "violated_rules"} or expected["editing"] not in paired.EDITING or any(
                    type(expected[key]) is not bool for key in ("major_linguistic", "critical")) or not isinstance(expected["violated_rules"], list) or not all(isinstance(r, str) for r in expected["violated_rules"]):
                raise ValueError("Assessment calibration needs editing, major_linguistic, critical and violated_rules gold")
    engine = _engine()
    root = Path(run_dir)
    with engine._evaluation_submit_lock(root):
        state, _ = engine.load_run(root)
        campaign = state.get("paired_review")
        if not campaign:
            raise ValueError("Export screening to start a campaign before loading calibration")
        if any(not set(case.get("expected", {}).get("violated_rules", [])) <= set(campaign["policy"]["mandatory_rules"]) for case in cases):
            raise ValueError("Calibration refers to rules outside this campaign's policy")
        campaign["calibration_suite"] = suite
        campaign.pop("calibration_result", None)
        campaign.pop("calibration_results", None)
        campaign["analysis"] = paired.summarize(campaign)
        engine._atomic_write_json(root / "state.json", state)
    return {"cases": len(cases), "author": suite["author"], "digest": paired.digest(suite)}


def enrich_comparison(samples: list[dict], campaign: dict) -> None:
    """Attach v3 evidence without replacing legacy verdicts or their scores."""
    assessments = defaultdict(list)
    comparisons = defaultdict(list)
    report = campaign.get("analysis") or paired.summarize(campaign)
    audit_rows = defaultdict(list)
    for audit in campaign.get("audits", {}).values():
        for row in audit["records"]:
            audit_rows[row["baseline_task"]].append(row)
    for row in campaign.get("assessments", {}).values():
        copied = copy.deepcopy(row)
        copied["disputed"] = row["task_key"] in report.get("disputed_assessment_keys", [])
        assessments[row["sample_id"]].append(copied)
    for row in campaign.get("comparisons", {}).values():
        copied = copy.deepcopy(row)
        copied["disputed"] = row["status"] == "judged" and any(
            r["status"] == "judged" and paired.outcome(row, row["left"]) != paired.outcome(r, row["left"])
            for r in audit_rows[row["task_key"]])
        comparisons[row["sample_id"]].append(copied)
    for sample in samples:
        sid = sample["id"]
        sample["paired_review"] = {"assessments": assessments[sid], "comparisons": comparisons[sid],
            "pool": campaign["plan"]["pools"].get(sid, "reserve"),
            "content_group": campaign["plan"]["groups"].get(sid, "")}
        sample["paired_holdout_locked"] = (sample["paired_review"]["pool"] == "confirmation"
                                           and not campaign["plan"]["confirmation_candidates"])
        if sid in report["human_follow_up"]:
            sample["human_follow_up"] = True
