from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


REPO = Path(__file__).resolve().parents[1]
BUNDLE_ROOT = REPO.parent / "release-bundles"
OUTPUT = BUNDLE_ROOT / "concern-production-20260913.zip"
FILES = [
    "package.json",
    "src/agency_protocol.mjs",
    "src/db.mjs",
    "src/enterprise_context.mjs",
    "src/initiative.mjs",
    "src/proactive.mjs",
    "src/bot.mjs",
    "src/playground.mjs",
    "config/agency-prompts.v1.json",
    "config/prompts/work-context-router-v1.json",
    "config/prompts/work-response-v1.json",
    "scripts/agency_online_shadow_smoke.mjs",
    "scripts/agency_release_static_closure.mjs",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(REPO), *args], text=True).strip()


def main() -> None:
    BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xiyu-concern-bundle-") as raw:
        stage = Path(raw)
        payload = stage / "payload"
        for relative in FILES:
            destination = payload / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / relative, destination)
        apply_script = stage / "apply-concern-production.sh"
        shutil.copy2(REPO / "scripts/agency_production_apply.sh", apply_script)
        manifest = {
            "schemaVersion": "xiyu-concern-production-bundle-v1",
            "releaseId": "concern-production-20260913",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "sourceRepository": str(REPO),
            "sourceBranch": git("branch", "--show-current"),
            "sourceRevision": git("rev-parse", "HEAD"),
            "payloadRoot": "payload",
            "files": {relative: sha256(payload / relative) for relative in FILES},
            "applyScriptSha256": sha256(apply_script),
            "workbenchFilesIncluded": False,
            "featureFlag": {"name": "XIYU_AGENCY_MODE", "shadowBeforeEnabled": True, "enabledAfterShadow": True},
            "safety": {"credentialsIncluded": False, "databaseIncluded": False, "realBotDelivery": False, "realModelCalls": 0, "productionWritesBeforeApply": False},
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary_output = stage / OUTPUT.name
        with ZipFile(temporary_output, "w", ZIP_DEFLATED) as archive:
            for path in sorted(p for p in stage.rglob("*") if p.is_file() and p != temporary_output):
                archive.write(path, path.relative_to(stage).as_posix())
        shutil.copy2(temporary_output, OUTPUT)
    print(json.dumps({"path": str(OUTPUT), "sha256": sha256(OUTPUT), "bytes": OUTPUT.stat().st_size, "payloadCount": len(FILES)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
