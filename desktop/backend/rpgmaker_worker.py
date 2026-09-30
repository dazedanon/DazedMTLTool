"""Isolated production RPG Maker adapter process.

The actual parser, context builder, validation, glossary, wrapping and cache run
unchanged in this process. Only the SDK transport is delegated over private
pipes to the desktop service, which owns credentials, receipts and the budget.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PROTOCOL_OUT = sys.stdout
PROTOCOL_IN = sys.stdin


class WorkerStopped(BaseException):
    pass


def exchange(kind, **payload):
    PROTOCOL_OUT.write(json.dumps({"event": kind, **payload}, ensure_ascii=False) + "\n")
    PROTOCOL_OUT.flush()
    line = PROTOCOL_IN.readline()
    if not line:
        raise WorkerStopped("The controller disconnected; saved work can be resumed.")
    response = json.loads(line)
    if response.get("stop"):
        raise WorkerStopped(response.get("message") or "Stopped after the current request.")
    if response.get("error"):
        raise WorkerStopped(response["error"])
    return response


def configure_environment(root, settings):
    # This process never receives API credentials or inherits the user's .env.
    for key in list(os.environ):
        if any(token in key.lower() for token in ("api_key", "secret", "token")) or key in {"key", "api", "organization", "org"}:
            os.environ.pop(key, None)
    os.environ.update({
        "PYTHON_DOTENV_DISABLED": "1", "DAZEDTL_TEST_OFFLINE": "1", "model": "gpt-6-luna", "API_PROVIDER": "openai",
        "key": "desktop-broker-only", "api": "https://api.openai.com/v1", "language": "English", "timeout": "45",
        "width": str(settings["width"]), "faceWidth": str(settings["faceWidth"]),
        "listWidth": str(settings["listWidth"]), "noteWidth": str(settings["noteWidth"]), "batchsize": str(settings["batchsize"]),
        "DAZED_GAME_ROOT": str(root / "game"), "DAZED_GLOSSARY_PATH": str(root / "game/.dazedtl/glossary.txt"),
        "DAZED_INCLUDE_GLOSSARY_BASE": "true", "convertQuotes": "true", "useSfxReference": "true",
        "TRANSLATION_RUN_LOG": str(root / "log/translation.txt"),
        "TIKTOKEN_CACHE_DIR": str(ROOT / "data/tokenizers"),
    })
    for key in ("BATCH_PHASE", "BATCH_PROVIDER", "TRANSLATION_LOG_REQUESTS", "API_KEY_OPTIONAL"):
        os.environ.pop(key, None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    plan = json.loads(args.manifest.read_text(encoding="utf-8"))
    root = args.manifest.parent.resolve()
    os.chdir(root)
    configure_environment(root, plan["settings"])
    # Keep parser output out of the RPC stream. Logs stay inside this run.
    (root / "log").mkdir(exist_ok=True)
    log = (root / "log/engine.txt").open("a", encoding="utf-8", buffering=1)
    original_error = sys.stderr
    sys.stdout = log
    sys.stderr = log

    import util.paths as paths
    paths.PROMPT_PATH = root / "context/system.md"
    paths.GLOSSARY_BASE_PATH = root / "context/base-glossary.txt"
    paths.TRANSLATION_CONTEXTS_PATH = root / "context/translation_contexts.json"
    paths.SFX_REFERENCE_PATH = root / "context/sfx.json"

    import util.translation as translation
    translation._load_litellm_pricing = lambda: {}
    translation._lookup_model_price = lambda _model: (0.10, 0.50)
    translation.DEBUG = False

    # A network call in this worker is always a programming error: the parent
    # is the sole provider transport. Block accidental model/pricing fallbacks.
    import socket
    def no_network(*_args, **_kwargs):
        raise WorkerStopped("The engine attempted direct network access; the budgeted broker is required.")
    socket.create_connection = no_network
    socket.socket.connect = socket.socket.connect_ex = no_network

    from modules import rpgmakermvmz as engine
    from util.runtime_profile import apply_batch_runtime_profile
    apply_batch_runtime_profile(engine, plan["profile"])
    engine.TRANSLATION_CONFIG.validationRetries = 0
    engine.PROGRESS_SAVE_INTERVAL_SECONDS = 0
    engine.resetSpeakerState()

    current_file = ""
    def completion(**params):
        result = exchange("request", file=current_file, params=params)["response"]
        return SimpleNamespace(choices=[SimpleNamespace(index=0, finish_reason="stop", message=SimpleNamespace(content=result["text"]))],
                               usage=SimpleNamespace(prompt_tokens=result.get("prompt_tokens", 0), completion_tokens=result.get("completion_tokens", 0)))
    translation.openai.chat = SimpleNamespace(completions=SimpleNamespace(create=completion))

    class Progress:
        def __init__(self, total=0, **_kwargs):
            self.total, self.n, self.last = total, 0, 0
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def update(self, amount=1):
            self.n += amount
            if time.monotonic() - self.last >= .15:
                self.last = time.monotonic()
                exchange("progress", file=current_file, current=self.n, total=self.total)
        def refresh(self):
            pass
        @staticmethod
        def write(message, **_kwargs):
            print(message)
    engine.tqdm = Progress

    try:
        if plan["phase"] != "database" and not plan.get("speakers_done"):
            engine.setSpeakerParseMode(True)
            for filename in plan["files"]:
                from desktop.backend.rpgmaker import file_phase
                if file_phase(filename) != "dialogue":
                    continue
                current_file = filename
                exchange("scanning_speakers", file=filename)
                engine.handleMVMZ(filename, False)
            current_file = "speakers"
            exchange("speaker_scope", names=engine.pendingSpeakerNames())
            if engine.finalizeSpeakerParse() is False:
                exchange("file_error", file="speakers", message="Speaker translations could not be validated. Review the glossary before resuming.")
                raise WorkerStopped("Speaker translations could not be validated. Review the glossary before resuming.")
            engine.setSpeakerParseMode(False)
            exchange("speakers_done")

        for filename in plan["files"]:
            if filename in plan.get("completed_files", []):
                continue
            current_file = filename
            exchange("file_start", file=filename)
            engine.resetActorMapCache()
            result = engine.handleMVMZ(filename, False)
            if result == "Fail" or engine.MISMATCH:
                exchange("file_error", file=filename, message="The production adapter preserved source text for invalid results. Review or retry this file.")
                raise WorkerStopped("A file needs attention before continuing.")
            output = root / "translated" / filename
            if not output.is_file():
                raise WorkerStopped("The production adapter did not write its expected output.")
            exchange("file_done", file=filename)
        exchange("complete")
    except WorkerStopped as exc:
        PROTOCOL_OUT.write(json.dumps({"event": "stopped", "message": str(exc)}, ensure_ascii=False) + "\n")
        PROTOCOL_OUT.flush()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        PROTOCOL_OUT.write(json.dumps({"event": "failed", "message": f"{type(exc).__name__}: production adapter failed. See this run's engine log."}) + "\n")
        PROTOCOL_OUT.flush()
        return 1
    finally:
        sys.stdout, sys.stderr = PROTOCOL_OUT, original_error
        log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
