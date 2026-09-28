"""Paired variants of the existing review contract/statistics regression cases.

Called by the matching test_evaluation cases to exercise both formats with the
same safety expectations, without constructing a GUI or contacting providers.
"""
import copy
import csv
import json
from collections import Counter
from pathlib import Path

from util import evaluation
from util import evaluation_pairwise as paired


def fixture(parent, name, groups=8, candidates=3):
    root = Path(parent) / name
    root.mkdir()
    manifest = {"segments": [], "logical_requests": [], "executions": []}
    state = {"run_id": name, "status": "completed", "candidates": []}
    for i in range(groups):
        sid, rid = f"segment-{i}", f"sample-{i}"
        scene = f"Map{i:03d}:event-1:page-1:call-1"
        source = f"猫が{i}匹います。"
        manifest["segments"].append(dict(id=sid, source=source, scene_id=scene, stratum="dialogue"))
        manifest["logical_requests"].append(dict(id=rid, sources=[source], segment_ids=[sid],
            scene_id=scene, stratum="dialogue", system="Translate the complete scene.", history=[], glossary="", sfx_reference=""))
        manifest["executions"].append(dict(id=f"rep-1:{rid}", logical_request_id=rid, repetition=1))
    for j in range(candidates):
        cid = f"candidate-{j}"
        path = f"results/{cid}.json"
        result = {"executions": {f"rep-1:sample-{i}": {"repetition": 1, "logical_request_id": f"sample-{i}",
            "lines": [{"segment_id": f"segment-{i}", "translation": f"There are {i} cats. Variant {j}.", "valid": True}]}
            for i in range(groups)}}
        evaluation._atomic_write_json(root / path, result)
        state["candidates"].append(dict(id=cid, model=f"private-model-{j}", status="completed", result_file=path,
            summary={"actual_cost_usd": float(j + 1)}))
    evaluation._atomic_write_json(root / "manifest.json", manifest)
    evaluation._atomic_write_json(root / "state.json", state)
    return root


def read(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, rows):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=paired.FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def fill(rows):
    rows = copy.deepcopy(rows)
    for row in rows:
        if row["record_type"] == "sample" or row["status"] == "unavailable":
            continue
        row.update(status="judged", notes="Generated fixture judgment with exact evidence.")
        outputs, source = json.loads(row["outputs"]), json.loads(row["source"])
        if row["record_type"] == "assessment":
            row["editing_requirement"] = "ready"
            row["rule_checks"] = json.dumps({"A": [{"rule_id": key, "opportunities": [],
                "explanation": "No matching requirement in this generated fixture."}
                for key in json.loads(row["policy"])["mandatory_rules"]]})
        elif outputs["A"] == outputs["B"]:
            row["decision"] = "equivalent"
        else:
            row.update(decision="left", strength="slight", comparison_evidence=json.dumps([{
                "line": 1, "source_quote": source[0], "A_quote": outputs["A"][0], "B_quote": outputs["B"][0],
                "explanation": "Source-grounded comparative fixture, not an error allegation."}]))
    return rows


def check_contract(test):
    root = fixture(test.run_dir, "paired-contract")
    state = evaluation._read_json(root / "state.json")
    state["human_review"] = {"points": {"candidate-0": 123}, "rows": []}
    evaluation._atomic_write_json(root / "state.json", state)
    path = evaluation.export_paired_review(root)
    original = path.read_bytes()
    test.assertNotIn(b"private-model", original)
    test.assertNotIn(b"candidate-0", original)
    rows = fill(read(path))
    test.assertEqual(set(r["record_type"] for r in rows), {"sample", "assessment", "comparison"})
    compared = next(r for r in rows if r["record_type"] == "comparison")
    compared.update(status="policy_conflict", notes="Conflicting source instructions.", decision="", strength="", comparison_evidence="[]")
    reviewed = root / "reviewed.csv"
    write(reviewed, rows)
    result = evaluation.import_blind_review(root, reviewed, reviewer="judge-1", reviewer_kind="ai")
    test.assertEqual(result["version"], 3)
    test.assertTrue(all(r["editing"] == "ready" and not r["evidence"] for r in result["assessments"].values()))
    test.assertTrue(any(r["strength"] == "slight" for r in result["comparisons"].values()))
    test.assertTrue(any(r["status"] == "policy_conflict" for r in result["comparisons"].values()))
    test.assertEqual(evaluation._read_json(root / "state.json")["human_review"], state["human_review"])
    test.assertEqual(path.read_bytes(), original)
    again = evaluation.import_blind_review(root, reviewed, reviewer="judge-1", reviewer_kind="ai")
    test.assertEqual(result["analysis"], again["analysis"])
    payload = evaluation.load_comparison_data(root)
    test.assertTrue(any(s.get("paired_review", {}).get("comparisons") for s in payload["samples"]))
    test.assertEqual(sum(p["wins_slight"] + p["losses_slight"] for p in result["analysis"]["pools"]["screening"]["pairs"]),
                     sum(r["status"] == "judged" for r in result["comparisons"].values()))
    duplicates = fixture(test.run_dir, "paired-duplicates", groups=2)
    duplicate_state = evaluation._read_json(duplicates / "state.json")
    first = duplicates / duplicate_state["candidates"][0]["result_file"]
    second = duplicates / duplicate_state["candidates"][1]["result_file"]
    evaluation._atomic_write_json(second, evaluation._read_json(first))
    duplicate_csv = evaluation.export_paired_review(duplicates)
    duplicate_rows = fill(read(duplicate_csv))
    test.assertEqual(sum(r["record_type"] == "assessment" for r in duplicate_rows), 2)
    duplicate_pair = next(r for r in duplicate_rows if r["record_type"] == "comparison" and json.loads(r["outputs"])["A"] == json.loads(r["outputs"])["B"])
    output = json.loads(duplicate_pair["outputs"])
    duplicate_pair.update(decision="left", strength="slight", comparison_evidence=json.dumps([dict(line=1,
        source_quote=json.loads(duplicate_pair["source"])[0], A_quote=output["A"][0], B_quote=output["B"][0], explanation="Invalid preference fixture.")]))
    write(duplicate_csv, duplicate_rows)
    with test.assertRaisesRegex(ValueError, "Identical"):
        evaluation.import_blind_review(duplicates, duplicate_csv, reviewer="judge")
    duplicate_pair.update(decision="equivalent", strength="", comparison_evidence="[]")
    write(duplicate_csv, duplicate_rows)
    identical_review = evaluation.import_blind_review(duplicates, duplicate_csv, reviewer="judge")
    test.assertEqual(len(identical_review["assessments"]), 3)


def check_protection(test):
    root = fixture(test.run_dir, "paired-protection", groups=2)
    path = evaluation.export_paired_review(root)
    rows = fill(read(path))
    state_before = (root / "state.json").read_bytes()
    for field in ("source", "outputs", "context", "policy", "content_group", "output_status", "identical_candidates"):
        with test.subTest(paired_protected=field):
            changed = copy.deepcopy(rows)
            changed[0][field] = "changed"
            write(path, changed)
            with test.assertRaisesRegex(ValueError, "Protected"):
                evaluation.import_blind_review(root, path, reviewer="judge")
            test.assertEqual((root / "state.json").read_bytes(), state_before)
    for changed in (rows[:-1], list(reversed(rows)), rows + [rows[0]]):
        write(path, changed)
        with test.assertRaisesRegex(ValueError, "every row"):
            evaluation.import_blind_review(root, path, reviewer="judge")
    mutations = (
        ("comparison", {"comparison_evidence": '[{"line":1,"source_quote":"not in source","A_quote":"x","B_quote":"y","explanation":"bad"}]'}),
        ("comparison", {"status": "needs_human_review"}),
        ("comparison", {"status": "unavailable"}),
        ("assessment", {"rule_checks": '{"A":[]}'}),
        ("sample", {"notes": "forbidden"}),
    )
    for kind, mutation in mutations:
        with test.subTest(paired_invalid=mutation):
            changed = copy.deepcopy(rows)
            next(r for r in changed if r["record_type"] == kind).update(mutation)
            write(path, changed)
            with test.assertRaises(ValueError):
                evaluation.import_blind_review(root, path, reviewer="judge")
            test.assertEqual((root / "state.json").read_bytes(), state_before)
    # A local compliance defect remains distinct from a meaning error and must
    # agree with readiness and opportunity evidence.
    assessment = next(r for r in rows if r["record_type"] == "assessment")
    source, outputs = json.loads(assessment["source"]), json.loads(assessment["outputs"])
    error = {"id": "one", "category": "policy", "severity": "minor", "impacts": ["compliance"],
             "rule_ids": ["honorifics"],
             "line": 1, "source_quote": source[0], "translation_quote": outputs["A"][0], "explanation": "Local repair."}
    assessment["error_evidence"] = json.dumps({"A": [error]})
    checks = json.loads(assessment["rule_checks"])
    checks["A"][0]["opportunities"] = [{"line": 1, "source_quote": source[0], "translation_quote": outputs["A"][0], "passed": False}]
    assessment["rule_checks"] = json.dumps(checks)
    write(path, rows)
    with test.assertRaisesRegex(ValueError, "Editing requirement"):
        evaluation.import_blind_review(root, path, reviewer="judge")
    assessment["editing_requirement"] = "light_edits"
    write(path, rows)
    result = evaluation.import_blind_review(root, path, reviewer="judge")
    test.assertEqual(sum(c["major_fidelity_blocks"] for c in result["analysis"]["pools"]["screening"]["candidates"].values()), 0)
    error.update(category="meaning", severity="major", impacts=["linguistic"])
    checks["A"][0]["opportunities"] = []
    assessment["rule_checks"] = json.dumps(checks)
    assessment.update(editing_requirement="substantive_edits", error_evidence=json.dumps({"A": [error]}))
    write(path, rows)
    result = evaluation.import_blind_review(root, path, reviewer="judge")
    test.assertEqual(sum(c["major_fidelity_blocks"] for c in result["analysis"]["pools"]["screening"]["candidates"].values()), 1)


def check_coverage(test):
    root = fixture(test.run_dir, "paired-coverage", groups=2)
    state = evaluation._read_json(root / "state.json")
    state["candidates"][0]["result_file"] = ""
    state["candidates"][0]["status"] = "failed"
    evaluation._atomic_write_json(root / "state.json", state)
    test.assertTrue(evaluation.blind_review_candidates(root, include_unavailable=True)[0]["available"])
    path = evaluation.export_paired_review(root)
    rows = fill(read(path))
    test.assertTrue(any(r["status"] == "unavailable" for r in rows))
    write(path, rows)
    result = evaluation.import_blind_review(root, path, reviewer="judge")
    info = result["analysis"]["pools"]["screening"]["candidates"]["candidate-0"]
    test.assertEqual(info["validity"], {"total": 1, "valid": 0, "source_lines": 1})
    test.assertEqual(info["judged"], 0)
    for pair in result["analysis"]["pools"]["screening"]["pairs"]:
        if "candidate-0" in (pair["a"], pair["b"]):
            test.assertEqual(pair["judged"], 0)
            test.assertIsNone(pair["net_preference"])
            test.assertEqual(pair["unavailable"], 1)


def synthetic_campaign(count=6):
    policy = paired.validate_policy(None)
    campaign = dict(candidate_ids=["a", "b"], policy=policy,
        plan={"confirmation_candidates": ["a", "b"]}, assessments={}, comparisons={}, audits={}, coverage={})
    for i in range(count):
        key = f"pair-{i}"
        campaign["comparisons"][key] = dict(task_key=key, sample_id=f"sample-{i}", content_group=f"scene-{i}",
            stratum="dialogue", pool="confirmation", status="judged", type="comparison", left="a", right="b",
            decision=("left", "equivalent", "right")[i % 3], strength="slight" if i % 3 != 1 else "",
            notes="Generated outcome", evidence=[], reviewer="judge")
    return campaign


def check_statistics(test):
    campaign = synthetic_campaign()
    report = paired.summarize(campaign)
    pair = report["pools"]["confirmation"]["pairs"][0]
    test.assertEqual((pair["wins_slight"], pair["equivalent"], pair["losses_slight"]), (2, 2, 2))
    test.assertEqual(pair["net_preference"], 0)
    test.assertLess(pair["interval"][0], 0)
    test.assertGreater(pair["interval"][1], 0)
    split = copy.deepcopy(campaign)
    split["comparisons"]["split"] = dict(split["comparisons"]["pair-0"], task_key="split")
    split_pair = paired.summarize(split)["pools"]["confirmation"]["pairs"][0]
    test.assertEqual((split_pair["net_preference"], split_pair["groups"], split_pair["interval"]),
                     (pair["net_preference"], pair["groups"], pair["interval"]))
    expanded = copy.deepcopy(campaign)
    expanded["candidate_ids"].append("c")
    expanded["plan"]["confirmation_candidates"].append("c")
    test.assertEqual(paired.summarize(expanded)["pools"]["confirmation"]["pairs"][0]["net_preference"], pair["net_preference"])
    campaign["comparisons"]["pair-0"].update(status="insufficient_context", decision="", strength="")
    pair = paired.summarize(campaign)["pools"]["confirmation"]["pairs"][0]
    test.assertEqual(pair["abstentions"], 1)
    test.assertAlmostEqual(pair["net_preference"], -.2)
    for r in campaign["comparisons"].values():
        r.update(status="judged", decision="equivalent", strength="")
    report = paired.summarize(campaign)
    test.assertTrue(all(r["status"] == "no_demonstrated_difference" for r in report["recommendations"].values()))
    test.assertGreater(report["pools"]["confirmation"]["pairs"][0]["interval"][1], 0)
    test.assertIsNone(report["value_recommendation"])
    low, high = paired._binomial_bounds(0, 10, .025)
    test.assertEqual(low, 0)
    test.assertAlmostEqual(high, 1 - .025 ** .1)
    test.assertEqual(paired.legacy_status({"overall": [["a", "b"]]}), "Reviewed · Full tie")
    test.assertEqual(paired.legacy_status({"overall": [["a"], ["b", "c"]]}), "Reviewed · Partial tie")
    # Confirmation, calibrated judges and adequate audit coverage are required
    # before an observed advantage can become a supported recommendation.
    confirmed = synthetic_campaign(100)
    for r in confirmed["comparisons"].values():
        r.update(decision="left", strength="clear")
    for candidate in ("a", "b"):
        for i in range(100):
            key = f"assessment-{candidate}-{i}"
            confirmed["assessments"][key] = dict(task_key=key, sample_id=f"sample-{i}", content_group=f"scene-{i}",
                stratum="dialogue", pool="confirmation", type="assessment", status="judged", candidate=candidate,
                editing="ready", evidence=[], rules=[dict(rule_id=k, opportunities=[], explanation="Fixture.")
                    for k in confirmed["policy"]["mandatory_rules"]], reviewer="judge")
    confirmed["coverage"] = {"confirmation": {c: {"total": 100, "valid": 100} for c in ("a", "b")}}
    confirmed["performance"] = {"a": {"cost_usd": 2.}, "b": {"cost_usd": 1.}}
    for kind, reviewer in (("order_swap", "judge"), ("judge_check", "second")):
        confirmed["audits"][kind] = {"kind": kind, "records": [dict(r, baseline_task=r["task_key"], reviewer=reviewer)
            for r in list(confirmed["comparisons"].values())[:20]]}
    for reviewer in ("judge", "second"):
        confirmed.setdefault("calibration_results", {})[reviewer] = {"human_gold": True, "cases": 6, "agreement": 1.,
            "record_types": ["assessment", "comparison"], "by_type": {k: {"agreement": 1.} for k in ("assessment", "comparison")}}
    supported = paired.summarize(confirmed)
    test.assertEqual(supported["recommendations"]["a"]["status"], "supported_quality_leader")
    test.assertEqual(supported["value_recommendation"], "a")
    for r in confirmed["comparisons"].values():
        r.update(decision="equivalent", strength="")
    for audit in confirmed["audits"].values():
        for r in audit["records"]:
            r.update(decision="equivalent", strength="")
    equivalent = paired.summarize(confirmed)
    test.assertEqual(equivalent["recommendations"]["a"]["status"], "practically_equivalent")
    test.assertEqual(equivalent["value_recommendation"], "b")
    for row in confirmed["assessments"].values():
        row.update(editing="substantive_edits", evidence=[{"category": "meaning", "severity": "major", "impacts": ["linguistic"]}])
    flawed = paired.summarize(confirmed)
    test.assertEqual(flawed["production_status"], "no_production_ready_candidate")
    test.assertIsNone(flawed["value_recommendation"])
    test.assertEqual(flawed["pools"]["confirmation"]["candidates"]["a"]["editing"]["substantive_edits"], 100)


def check_stages_and_audits(test):
    root = fixture(test.run_dir, "paired-stages")
    policy = paired.validate_policy(None)
    samples = [dict(id=f"s-{i}", scene_id=f"Map{i}:event-1:page-1:call-1", sources=[f"文{i}"], stratum="dialogue") for i in range(10)]
    samples.append(dict(samples[0], id="s-10", scene_id="Map0:event-1:page-1:call-2", sources=["別の文"]))
    samples.append(dict(samples[1], id="s-11", scene_id="Map11:event-1:page-1:call-1"))
    plan = paired.make_plan(samples, policy, "seed")
    test.assertEqual(plan["pools"]["s-0"], plan["pools"]["s-10"])
    test.assertEqual(plan["pools"]["s-1"], plan["pools"]["s-11"])
    contaminated = paired.make_plan(samples, policy, "seed", exposed_samples=[s["id"] for s in samples])
    test.assertNotIn("confirmation", contaminated["pools"].values())
    counts = Counter(pair for i in range(7) for pair in paired.scheduled_pairs(list("abcdefgh"), i))
    test.assertEqual(len(counts), 28)
    test.assertEqual(set(counts.values()), {2})
    with test.assertRaisesRegex(ValueError, "screening"):
        evaluation.paired_review_preview(root, stage="confirmation")
    screening = evaluation.export_paired_review(root, challenge_samples=["sample-0"])
    screening_rows = fill(read(screening)); write(screening, screening_rows)
    baseline = evaluation.import_blind_review(root, screening, reviewer="first")
    held_out = [s for s in evaluation.load_comparison_data(root)["samples"] if s.get("paired_holdout_locked")]
    test.assertEqual(len(held_out), 3)
    confirmation = evaluation.export_paired_review(root, stage="confirmation")
    confirmation_rows = fill(read(confirmation)); write(confirmation, confirmation_rows)
    test.assertTrue({r["content_group"] for r in screening_rows}.isdisjoint({r["content_group"] for r in confirmation_rows}))
    baseline = evaluation.import_blind_review(root, confirmation, reviewer="first")
    test.assertFalse(any(s.get("paired_holdout_locked") for s in evaluation.load_comparison_data(root)["samples"]))
    challenge = evaluation.export_paired_review(root, stage="challenge")
    challenge_rows = fill(read(challenge)); write(challenge, challenge_rows)
    test.assertTrue({r["content_group"] for r in challenge_rows}.isdisjoint({r["content_group"] for r in screening_rows + confirmation_rows}))
    baseline = evaluation.import_blind_review(root, challenge, reviewer="first")
    audit = evaluation.export_paired_review(root, stage="order_swap")
    rows = fill(read(audit))
    state = evaluation._read_json(root / "state.json")
    export = state["paired_exports"][rows[0]["review_id"]]
    for row in rows:
        binding = export["bindings"][row["record_id"]]
        previous = baseline["comparisons"][binding["baseline_task"]]
        test.assertEqual(binding["mapping"]["A"], previous["right"])
        # First judge chose left; reversing positions means an agreeing audit
        # chooses right. One deliberate disagreement must be flagged.
        row["decision"] = "right"
    rows[0]["decision"] = "left"
    write(audit, rows)
    checked = evaluation.import_blind_review(root, audit, reviewer="first")
    test.assertTrue(checked["analysis"]["human_follow_up"])
    test.assertTrue(any(p["disputed"] for d in checked["analysis"]["pools"].values() for p in d["pairs"]))
    test.assertEqual(len(checked["comparisons"]), len(baseline["comparisons"]))
    independent = evaluation.export_paired_review(root, stage="judge_check")
    write(independent, fill(read(independent)))
    with test.assertRaisesRegex(ValueError, "different reviewer"):
        evaluation.import_blind_review(root, independent, reviewer="first")
    evaluation.import_blind_review(root, independent, reviewer="second")
    adjudication = evaluation.export_paired_review(root, stage="adjudication")
    write(adjudication, fill(read(adjudication)))
    with test.assertRaisesRegex(ValueError, "qualified human"):
        evaluation.import_blind_review(root, adjudication, reviewer="ai", reviewer_kind="ai")
    resolved = evaluation.import_blind_review(root, adjudication, reviewer="Human fixture", reviewer_kind="human")
    test.assertTrue(resolved["adjudication_history"])
    test.assertTrue(any(r.get("adjudicated") for r in resolved["comparisons"].values()))
    test.assertFalse(any(p["disputed"] for d in resolved["analysis"]["pools"].values() for p in d["pairs"]))
    test.assertEqual(len(resolved["comparisons"]), len(baseline["comparisons"]))
    suite = {"version": 1, "author": "Synthetic human-gold fixture", "author_kind": "human", "cases": [
        {"id": f"gold-{i}", "source": [f"猫が{i}匹です。"],
         "context": {"history": [], "system": "Translate.", "glossary": "", "sfx_reference": ""},
         "left": [f"There are {i} cats."], "right": [f"There are {i} dogs."], "decision": "left"} for i in range(6)]}
    suite["cases"].append({"id": "gold-assessment", "type": "assessment", "source": ["猫です。"],
        "context": suite["cases"][0]["context"], "output": ["It's a cat."],
        "expected": {"editing": "ready", "major_linguistic": False, "critical": False, "violated_rules": []}})
    suite_path = root / "calibration-fixture.json"
    suite_path.write_text(json.dumps(suite), encoding="utf-8")
    evaluation.load_review_calibration(root, suite_path)
    invalid = copy.deepcopy(suite)
    invalid["cases"].append(dict(invalid["cases"][0], id="duplicate-input"))
    suite_path.write_text(json.dumps(invalid), encoding="utf-8")
    with test.assertRaisesRegex(ValueError, "Duplicate calibration"):
        evaluation.load_review_calibration(root, suite_path)
    suite_path.write_text(json.dumps(suite), encoding="utf-8")
    calibration = evaluation.export_paired_review(root, stage="calibration")
    gold_rows = fill(read(calibration))
    test.assertNotIn("Synthetic human-gold fixture", calibration.read_text(encoding="utf-8"))
    state = evaluation._read_json(root / "state.json")
    gold_export = state["paired_exports"][gold_rows[0]["review_id"]]
    for row in gold_rows:
        if row["record_type"] == "assessment":
            continue
        binding = gold_export["bindings"][row["record_id"]]
        row["decision"] = "left" if binding["mapping"]["A"] == "gold-left" else "right"
    write(calibration, gold_rows)
    calibrated = evaluation.import_blind_review(root, calibration, reviewer="first")
    test.assertEqual(calibrated["calibration_result"]["agreement"], 1)
    test.assertEqual(set(calibrated["calibration_result"]["record_types"]), {"assessment", "comparison"})
    test.assertEqual(len(calibrated["comparisons"]), len(baseline["comparisons"]))
    archive = evaluation.export_run_archive(root, root / "portable.dazedeval")
    restored = evaluation.import_run_archive(root / "destination", archive)
    saved, _ = evaluation.load_run(restored)
    test.assertEqual(saved["paired_review"], calibrated)
    test.assertTrue(all((restored / e["file"]).is_file() for e in saved["paired_exports"].values()))
