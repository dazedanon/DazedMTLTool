"""Len request plans and preflight quotes. No translation/provider calls or keys."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from util.len_translation import LenProject, request_contexts, shared_context, _reference_subset
from util.paths import DATA_DIR


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


def api_settings() -> dict:
    """Read the same saved configuration as the API GUI without exporting keys."""
    from dotenv import dotenv_values
    values = dotenv_values(DATA_DIR.parent / ".env")
    # Do not copy the complete environment, key vault, or raw URL into a prompt.
    return {key: str(values.get(key) or default).strip() for key, default in
            (("model", ""), ("api", ""), ("API_PROVIDER", "openai"))}


def settings_fingerprint(settings):
    return _hash(_canonical({key: settings.get(key, "") for key in ("model", "api", "API_PROVIDER")}))


def _evidence(project, paths):
    from util.len_progress import _read_artifact
    if not isinstance(paths, list) or not paths:
        raise ValueError("The request plan needs source/guidance input paths, relative to the game.")
    evidence = {}
    for path in paths:
        _read_artifact(project.game_root, path, evidence)
    return [{"path": key, "sha256": evidence[key]["sha256"]} for key in sorted(evidence)]


def _compiler_fingerprint():
    # Request fingerprints cannot detect a changed compiler/template by themselves.
    root = DATA_DIR.parent
    paths = ("util/len_api.py", "util/len_translation.py", "util/translation.py",
             "util/skills/__init__.py", "util/skills/contexts.py", "util/skills/system.py",
             "util/sfx_reference.py", "util/vocab.py", "util/reference_games.py",
             "data/translation_contexts.json",
             "data/sfx_reference/j_ono.json")
    return _hash(_canonical({name: _hash((root / name).read_bytes())
                            if (root / name).is_file() else None for name in paths}))


def compile_plan(project: LenProject, plan: dict) -> dict:
    if (not isinstance(plan, dict) or set(plan) != {"complete", "inputs", "batches"}
            or type(plan["complete"]) is not bool):
        raise ValueError("A request plan requires complete, inputs and batches.")
    compiler = _compiler_fingerprint()
    inputs = _evidence(project, plan["inputs"])
    requests = request_contexts(project, plan["batches"])
    if compiler != _compiler_fingerprint() or inputs != _evidence(project, plan["inputs"]):
        raise ValueError("Source inputs changed during compilation; retry the plan.")
    for request in requests:
        request["sources_sha256"] = _hash(_canonical(request["sources"]))
    return {"schema": 1, "complete": plan["complete"], "compiler_sha256": compiler,
            "inputs": inputs, "batches": requests,
            "scope_sha256": _scope(project)}


def _scope(project):
    return _hash(_canonical({"images": project.include_images, "instructions": project.instructions,
                             "base_glossary": project.include_glossary_base}))


def _read_plan(project, path):
    from util.len_progress import _artifact
    path = _artifact(project.game_root, path)
    raw = path.read_bytes()
    plan = json.loads(raw)
    if (not isinstance(plan, dict) or plan.get("schema") != 1 or plan.get("complete") is not True
            or not isinstance(plan.get("batches"), list) or not plan["batches"]):
        raise ValueError("Prepare the complete request plan first; a partial corpus cannot be quoted as the whole API job.")
    if plan.get("compiler_sha256") != _compiler_fingerprint():
        raise ValueError("Request compiler or templates changed. Recompile the request plan.")
    if plan.get("scope_sha256") != _scope(project):
        raise ValueError("Project scope changed. Recompile the request plan.")
    inputs = plan.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("The request plan has no source evidence.")
    if _evidence(project, [item["path"] for item in inputs]) != inputs:
        raise ValueError("Source inputs changed. Recompile the request plan before estimating.")
    shared = shared_context(project)["content_sha256"]
    seen = set()
    for batch in plan["batches"]:
        identity, context = batch.get("id"), batch.get("context")
        if not isinstance(identity, str) or not identity or identity in seen or not isinstance(context, dict):
            raise ValueError("Invalid or duplicate compiled request.")
        seen.add(identity)
        signature = _hash(_canonical({key: value for key, value in context.items() if key != "request_sha256"}))
        if context.get("request_sha256") != signature or context.get("context_sha256") != shared:
            raise ValueError("Compiled requests changed or use old guidance. Recompile the plan.")
        sources = batch.get("sources")
        if batch.get("sources_sha256") != _hash(_canonical(sources)):
            raise ValueError("Compiled source payload changed. Recompile the request plan.")
        values = list(sources.values()) if isinstance(sources, dict) else sources
        if not isinstance(values, list) or not values or not all(isinstance(v, str) and v for v in values):
            raise ValueError("Each compiled request needs its source payload for output estimation.")
    # Reference content may change even when its registry and local guidance do not.
    from util.reference_games import reference_context
    all_sources = [source for batch in plan["batches"]
                   for source in (batch["sources"].values() if isinstance(batch["sources"], dict) else batch["sources"])]
    references = reference_context(project.game_root, all_sources)
    for batch in plan["batches"]:
        current = _reference_subset(references, batch["sources"])
        if current != batch["context"].get("reference_translations"):
            raise ValueError("Reference translations changed. Recompile the request plan.")
    return plan, _hash(raw)


def create_estimate(project, relative=".dazedtl/len-method/api-requests.json", *, settings=None):
    """Price the saved complete context set using Workflow's token/pricing rules."""
    from util.translation import estimateCostComparison, getPricingConfig
    from util.batch_providers import detect_batch_provider
    import tiktoken

    settings = api_settings() if settings is None else settings
    model = settings.get("model", "").strip()
    if not model:
        raise ValueError("Choose and save a model in API Settings first.")
    provider = detect_batch_provider(model, api_url=settings.get("api", ""), api_provider=settings.get("API_PROVIDER", "openai"))
    if provider is None:
        raise ValueError("This API route does not support Batch Translation. Choose a supported route in API Settings.")
    plan, signature = _read_plan(project, relative)
    encoder = tiktoken.encoding_for_model("gpt-4")
    input_tokens = output_tokens = units = 0
    for batch in plan["batches"]:
        context = batch["context"]
        # Count every context field the adapter must send, including references,
        # per-field instructions and the complete speaker-bearing user payload.
        fields = [context[key] for key in ("system", "glossary", "sfx_reference", "request_instructions", "preceding_japanese_source_context", "user")]
        fields.append(json.dumps(context["reference_translations"], ensure_ascii=False))
        input_tokens += sum(len(encoder.encode(field if isinstance(field, str) else json.dumps(field, ensure_ascii=False))) for field in fields) + 8
        payload = json.dumps(batch["sources"], ensure_ascii=False)
        output_tokens += round(len(encoder.encode(payload)) * 2.5)
        units += len(batch["sources"])
    comparison = estimateCostComparison(input_tokens, output_tokens, model, batch_provider=provider)
    pricing = getPricingConfig(model)
    if any(not math.isfinite(comparison[key]) or comparison[key] < 0 for key in ("live_cost", "batch_cost")):
        raise ValueError("API pricing must be finite and nonnegative.")
    return {"schema": 1, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "request_file": relative, "request_sha256": signature,
            "settings_sha256": settings_fingerprint(settings), "scope_sha256": _scope(project),
            "model": model, "provider": provider, "requests": len(plan["batches"]), "units": units,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "batch_cost": comparison["batch_cost"], "live_cost": comparison["live_cost"],
            "input_rate": pricing["inputAPICost"], "output_rate": pricing["outputAPICost"],
            "unestimated_thinking_tokens": comparison["unestimated_thinking_tokens"],
            "approved": False}


def validate_estimate(project, estimate, *, settings=None):
    if not isinstance(estimate, dict) or estimate.get("schema") != 1 or estimate.get("approved") is not True:
        raise ValueError("Review and accept the API estimate before copying the translation prompt, or choose preparation only.")
    if estimate.get("scope_sha256") != _scope(project):
        raise ValueError("Project scope changed. Review a new API estimate.")
    settings = api_settings() if settings is None else settings
    if estimate.get("settings_sha256") != settings_fingerprint(settings):
        raise ValueError("API settings changed. Review a new estimate.")
    _plan, signature = _read_plan(project, estimate["request_file"])
    if signature != estimate.get("request_sha256"):
        raise ValueError("The request plan changed. Review a new API estimate.")
    for key in ("batch_cost", "live_cost", "input_rate", "output_rate"):
        value = estimate.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("Invalid saved estimate.")


def estimate_summary(estimate):
    return (f"{estimate['provider']} / {estimate['model']}: {estimate['requests']:,} requests, {estimate['units']:,} source units.\\n"
            f"Estimated Batch cost: ${estimate['batch_cost']:.4f}; Live comparison: ${estimate['live_cost']:.4f}.\\n"
            f"Estimated tokens: {estimate['input_tokens']:,} input / {estimate['output_tokens']:,} output. "
            f"Standard rates per million: ${estimate['input_rate']:g} input / ${estimate['output_rate']:g} output.\\n"
            "Uses the application's pricing table/configured fallback rates and a 2.5× source-token output allowance; no cache savings assumed. Verify displayed rates for the selected model. "
            "An estimate, not a spending cap. Provider wait time, retries, billed reasoning, image work, assistant work and QA are excluded. "
            "Final submission must review the adapter's collected request estimate. Request plan: " + estimate["request_file"]).replace("\\n", "\n")
