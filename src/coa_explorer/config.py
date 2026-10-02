"""Settings from the environment, with a git-ignored `.env` (see `.env.example`) as a fallback."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX = REPO_ROOT / "build" / "coa.sqlite"
DEFAULT_REVIEWED = REPO_ROOT / "data" / "reviewed"


@dataclass(frozen=True)
class Settings:
    gcp_project_id: str
    gemini_location: str
    gemini_answer_model: str
    gemini_embedding_model: str
    index_path: Path


def load_settings(env_file: Path = REPO_ROOT / ".env") -> Settings:
    env = {**read_env_file(env_file), **os.environ}
    missing = [k for k in ("GCP_PROJECT_ID", "GEMINI_ANSWER_MODEL") if not env.get(k)]
    if missing:
        raise SystemExit(
            f"missing setting(s): {', '.join(missing)}. Run scripts/setup-gcp.sh or copy"
            " .env.example to .env and fill them in."
        )
    return Settings(
        gcp_project_id=env["GCP_PROJECT_ID"],
        gemini_location=env.get("GEMINI_LOCATION") or "global",
        gemini_answer_model=env["GEMINI_ANSWER_MODEL"],
        gemini_embedding_model=env.get("GEMINI_EMBEDDING_MODEL") or "gemini-embedding-001",
        index_path=Path(env.get("COA_INDEX_PATH") or DEFAULT_INDEX),
    )


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("\"'")
    return values
