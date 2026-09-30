"""Prepare one private engine process from its frozen manual-run plan."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]


def prepare(root):
    root = Path(root).resolve()
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    os.chdir(root)
    os.environ.update({"PYTHON_DOTENV_DISABLED": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                       "TIKTOKEN_CACHE_DIR": str(ROOT / "data/tokenizers"),
                       "DAZED_GAME_ROOT": str(root / "game"), "DAZED_GLOSSARY_PATH": str(root / "game/.dazedtl/glossary.txt"),
                       "DAZED_INCLUDE_GLOSSARY_BASE": "true", "TRANSLATION_RUN_LOG": str(root / "log/translation.txt")})
    import util.paths as paths
    paths.PROMPT_PATH = root / "context/system.md"
    paths.GLOSSARY_BASE_PATH = root / "context/base-glossary.txt"
    paths.TRANSLATION_CONTEXTS_PATH = root / "context/translation_contexts.json"
    paths.SFX_REFERENCE_PATH = root / "context/sfx.json"
    from util import api_keys
    # Batch history resolves stored credential names through the same vault.
    # A run keeps its selected name even if the UI chooses another credential.
    api_keys.API_KEYS_PATH = root.parents[2] / "settings/api_keys.json"
    if plan["mode"] not in {"estimate", "offline"}:
        load_vault = api_keys.load_vault
        def pinned_vault(path=None):
            value = load_vault(path)
            if path is None and plan["key_name"] in value["keys"]:
                value["active"] = plan["key_name"]
            return value
        api_keys.load_vault = pinned_vault
    if plan["mode"] in {"estimate", "offline"}:
        api_keys.API_KEYS_PATH = root / "unused-local-vault.json"
        # Local estimation and synthetic tests cannot turn into paid requests,
        # including a provider-specific fallback or a tokenizer download.
        os.environ["DAZEDTL_TEST_OFFLINE"] = "1"
    if os.getenv('DAZEDTL_TEST_OFFLINE') == '1':
        import socket
        def blocked(*_args, **_kwargs):
            raise RuntimeError("Network access is disabled for this local run.")
        socket.create_connection = socket.socket.connect = socket.socket.connect_ex = blocked
    if plan.get("workflow"):
        os.environ.update(plan["workflow"].get("environment", {}))
    import util.speakers as speakers
    if (root / "context/wolf_speakers.json").is_file():
        speakers.CONFIG_PATH = root / "context/wolf_speakers.json"
    import util.translation as translation
    if plan.get('batch_link'):
        from .batches import batch_root
        linked = batch_root(root, plan)
        for name, filename in {'BATCH_QUEUE_FILE': 'batch_requests.json', 'BATCH_STATE_FILE': 'batch_state.json',
                               'BATCH_RESULTS_FILE': 'batch_results.json', 'BATCH_LOCK_FILE': 'batch_files.lock',
                               'BATCH_SUBMIT_LOCK_FILE': 'batch_submit.lock'}.items():
            setattr(translation, name, linked / 'log' / filename)
        translation.BATCH_QUEUE_EXPECTED = plan['batch_link']
        from util import batch_history
        batch_history.BATCH_HISTORY_FILE = linked / 'log/batch_history.json'
        for name in ('BATCH_QUEUE_FILE', 'BATCH_STATE_FILE', 'BATCH_RESULTS_FILE'):
            setattr(batch_history, name, getattr(translation, name))
    if plan["mode"] == "offline":
        from .rpgmaker import offline_completion
        def complete(**params):
            result = offline_completion(params)
            return SimpleNamespace(choices=[SimpleNamespace(index=0, finish_reason="stop", message=SimpleNamespace(content=result["text"]))],
                                   usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0))
        translation.openai.chat = SimpleNamespace(completions=SimpleNamespace(create=complete))
    from importlib import import_module
    from util.engine_options import apply_engine_options
    from util.translation_task import TRANSLATION_MODULE_SPECS
    module_path = next(item[2] for item in TRANSLATION_MODULE_SPECS if item[0] == plan["engine"])
    module = import_module(module_path)
    apply_engine_options(module, plan["engines"])
    return plan
