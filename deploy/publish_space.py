"""Publish the committed code (HEAD) as a Hugging Face Docker Space, for the judges.

    hf auth login                                         # once, with a write token
    uv run --with huggingface_hub python deploy/publish_space.py STAGING_DIR [--name valio-aimo-trade]

What it does:
- copies HEAD (git archive) into STAGING_DIR, with a Space README header on README.md,
- packs data/raw/ (git-ignored Valio Aimo files) into deploy/data.enc, encrypted with a fresh
  Fernet key, so the public Space files never hold readable event data,
- sets the Space secrets DATA_KEY, GEMINI_API_KEY and VALIO_API_KEY (read from .env, never printed),
- uploads STAGING_DIR. The Space then builds the Dockerfile and starts deploy/start.sh.
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import tarfile
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
HEADER = """---
title: Valio Aimo Trusted Trade Agents
emoji: 🥛
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
short_description: AI agents buy from Valio Aimo; plain code decides.
---

"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("staging", type=Path, help="An empty folder outside the repo.")
    ap.add_argument("--name", default="valio-aimo-trade")
    args = ap.parse_args()

    api = HfApi()
    repo_id = f"{api.whoami()['name']}/{args.name}"
    env = dotenv_values(ROOT / ".env")
    missing = [k for k in ("GEMINI_API_KEY", "VALIO_API_KEY") if not env.get(k)]
    if missing:
        raise SystemExit(f"Missing in .env: {', '.join(missing)}")

    staging = args.staging.resolve()
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    archive = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, check=True,
                             capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(staging, filter="data")
    readme = staging / "README.md"
    readme.write_text(HEADER + readme.read_text(encoding="utf-8"), encoding="utf-8")

    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w:gz") as tar:
        for f in sorted((ROOT / "data" / "raw").iterdir()):
            tar.add(f, arcname=f.name)
    key = Fernet.generate_key()
    (staging / "deploy" / "data.enc").write_bytes(Fernet(key).encrypt(packed.getvalue()))

    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
    api.add_space_secret(repo_id, "DATA_KEY", key.decode())
    for name in ("GEMINI_API_KEY", "VALIO_API_KEY"):
        api.add_space_secret(repo_id, name, env[name])
    api.upload_folder(repo_id=repo_id, repo_type="space", folder_path=staging,
                      commit_message="Deploy " + subprocess.run(
                          ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip())
    host = repo_id.replace("/", "-").replace("_", "-").replace(".", "-").lower()
    print(f"Space:  https://huggingface.co/spaces/{repo_id}")
    print(f"App:    https://{host}.hf.space/app/")


if __name__ == "__main__":
    main()
