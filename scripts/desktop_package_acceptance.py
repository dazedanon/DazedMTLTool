#!/usr/bin/env python3
"""Offline package relocation check on Linux with disposable user state.

Moves a generated desktop/out package, launches it before and after the move,
and checks that its writable Python environment and settings survive. The
package is restored to its original location even when validation fails.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    package = args.package.resolve()
    if not sys.platform.startswith("linux") or not package.is_relative_to((ROOT / "desktop/out/packages").resolve()) or not (package / "dazedtl").is_file():
        parser.error("Choose a generated Linux package under desktop/out/packages/.")
    moved = package.with_name(package.name + " 移動した build")
    if moved.exists():
        parser.error("The relocation destination already exists.")
    evidence = ROOT / ".tmp-ui/desktop-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    reports = []
    with tempfile.TemporaryDirectory(prefix="dazedtl-package-") as temporary:
        profile = Path(temporary) / "Profile 日本語"
        workspace = Path(temporary) / "workspace"
        def launch(folder):
            subprocess.run([sys.executable, str(ROOT / "scripts/benchmark_desktop.py"), "--runs", "1", "--packaged", str(folder / "dazedtl"),
                            "--profile", str(profile), "--workspace", str(workspace)], check=True)
            report = json.loads((evidence / "electron-performance-packaged-loaded.json").read_text())
            reports.append(report["runs"][0])
        try:
            launch(package)
            settings = profile / "tool/.env"
            settings.write_text("PACKAGE_RELOCATION_FIXTURE=preserved\n", encoding="utf-8")
            interpreter = profile / "python-env/bin/python"
            env = {**os.environ, "PYTHON_DOTENV_DISABLED": "1", "PYTHONNOUSERSITE": "1"}
            script = "import json,sysconfig; print(json.dumps(sysconfig.get_path('purelib')))"
            site = Path(json.loads(subprocess.check_output([str(interpreter), "-I", "-c", script], env=env)))
            (site / "relocation_fixture.py").write_text("VALUE = 'preserved'\n")
            package.rename(moved)
            launch(moved)
            probe = "import json,sys,cv2,numpy,openai,relocation_fixture; print(json.dumps({'base':sys.base_prefix,'extra':relocation_fixture.VALUE,'python':sys.version.split()[0]}))"
            result = json.loads(subprocess.check_output([str(interpreter), "-I", "-c", probe], env=env))
            assert Path(result["base"]).is_relative_to(moved)
            assert result["extra"] == "preserved"
            assert settings.read_text() == "PACKAGE_RELOCATION_FIXTURE=preserved\n"
            subprocess.run([str(interpreter), str(profile / "tool/scripts/len_translation.py"), "--help"], cwd=profile / "tool", env=env,
                           check=True, stdout=subprocess.DEVNULL)
            output = {"package": package.name, "python": result["python"], "first_launch": reports[0], "relocated_launch": reports[1],
                      "settings_preserved": True, "optional_dependency_preserved": True, "len_cli_available": True, "api_requests": 0}
            (evidence / "electron-package-relocation.json").write_text(json.dumps(output, indent=2))
            print(json.dumps({key:value for key,value in output.items() if key not in {"first_launch","relocated_launch"}}, indent=2))
        finally:
            if moved.exists():
                moved.rename(package)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
