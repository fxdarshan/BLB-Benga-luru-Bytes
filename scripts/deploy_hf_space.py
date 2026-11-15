"""Deploy the API to a Hugging Face Space, creating the Space the first time.

Run by .github/workflows/deploy-hf.yml after CI passes on main. It needs HF_TOKEN, a Hugging Face
token with write access. Uploads only the files the image is built from, plus the Space's README;
Hugging Face then builds the Dockerfile. A deploy whose files haven't changed makes no commit, so
the Space isn't rebuilt or restarted.

The Groq key is never handled here: add GROQ_API_KEY as a secret in the Space's settings.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
SPACE_NAME = os.environ.get("HF_SPACE_NAME", "blb-api")
# What the image is built from (as Railway's watch paths), and the Space's own README.
FILES = ["Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock", "Doc/problemStatement.md"]
FOLDERS = ["src"]
# Settings that aren't secret. They match Railway's, apart from the state directory.
VARIABLES = {
    "LLM_PROVIDER": "groq",
    "LLM_EFFORT": "low",
    "LLM_DAILY_TOKEN_LIMIT": "400000",
    "ALLOWED_ORIGINS": "https://blb-frontend.vercel.app",
    "RATE_LIMIT_PER_MINUTE": "10",
    "TRUSTED_PROXY_HOPS": "1",
}


def space_url(repo_id: str) -> str:
    """The address the Space's app is served at, such as https://user-blb-api.hf.space."""
    host = repo_id.replace("/", "-").replace("_", "-").replace(".", "-").lower()
    return f"https://{host}.hf.space"


def bundle(target: Path) -> None:
    for name in FILES:
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target / name)
    for name in FOLDERS:
        shutil.copytree(ROOT / name, target / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "deploy" / "huggingface" / "README.md", target / "README.md")


def main() -> int:
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("HF_TOKEN isn't set. Add it as a repository secret.", file=sys.stderr)
        return 1
    api = HfApi(token=token)
    repo_id = f"{api.whoami()['name']}/{SPACE_NAME}"
    # Public, so the web page can call it without signing in.
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", private=False, exist_ok=True)

    current = {name: v.value for name, v in api.get_space_variables(repo_id).items()}
    for name, value in VARIABLES.items():
        if current.get(name) != value:
            api.add_space_variable(repo_id, name, value)
            print(f"Set {name}")

    commit = os.environ.get("GITHUB_SHA", "local")[:7]
    with tempfile.TemporaryDirectory() as folder:
        bundle(Path(folder))
        api.upload_folder(
            folder_path=folder,
            repo_id=repo_id,
            repo_type="space",
            delete_patterns="*",  # files no longer in the bundle are removed
            commit_message=f"Deploy {commit} from GitHub",
        )

    runtime = api.get_space_runtime(repo_id)
    print(f"Space: https://huggingface.co/spaces/{repo_id} ({runtime.stage})")
    print(f"API:   {space_url(repo_id)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
