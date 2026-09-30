"""Line-delimited JSON RPC over private child-process pipes (no HTTP port)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .service import WorkspaceService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--production-providers", action="store_true")
    args = parser.parse_args()
    service = WorkspaceService(args.workspace, allow_live=args.allow_live, allow_providers=args.production_providers)
    methods = {name: getattr(service, name) for name in (
        "state", "import_project", "save_guidance", "preview", "start", "stop", "resume", "review", "export",
        "context", "save_context", "get_drafts", "save_drafts", "native_preview", "start_native", "review_page", "apply_reviewed", "engine_log",
        "asset_state", "asset_open", "asset_thumbnails", "asset_action",
        "image_list", "image_import", "image_get", "image_save", "image_render", "image_approve", "image_review", "image_export",
        "instruction_catalog", "instruction_get", "instruction_save", "instruction_draft", "instruction_import",
        "guide_catalog", "guide_page", "settings_transfer",
        "settings_get", "settings_save", "settings_draft", "settings_key", "settings_import", "settings_models",
        "manual_state", "manual_inspect", "manual_start", "manual_resume", "manual_answer", "manual_stop", "manual_log", "manual_export",
        "batch_state", "batch_register", "batch_action", "batch_resume",
        "evaluation_state", "evaluation_action", "evaluation_draft", "evaluation_reasoning",
        "workflow_state", "workflow_open", "workflow_update", "workflow_preview", "workflow_execute", "workflow_stop",
        "version_state", "version_open", "version_save", "version_action",
        "len_state", "len_open", "len_save", "len_action", "len_documents", "len_document_save",
        "workflow_documents", "workflow_document_save", "workflow_skill", "workflow_phase", "workflow_draft"
    )}
    try:
        for line in sys.stdin:
            request = {}
            try:
                request = json.loads(line)
                if request.get("method") not in methods:
                    raise ValueError("Unknown desktop operation.")
                result = methods[request["method"]](**request.get("params", {}))
                response = {"id": request.get("id"), "result": result}
            except Exception as exc:
                response = {"id": request.get("id"), "error": str(exc) if isinstance(exc, ValueError) else f"{type(exc).__name__}: operation failed."}
            print(json.dumps(response, ensure_ascii=False), flush=True)
            # Do not retain a large image data URL while waiting for the next RPC.
            request = response = result = line = None
    finally:
        service.close()


if __name__ == "__main__":
    main()
