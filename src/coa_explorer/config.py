"""Settings from the environment, with a git-ignored `.env` (see `.env.example`) as a fallback."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX = REPO_ROOT / "build" / "coa.sqlite"
DEFAULT_SAVED_ANSWERS = REPO_ROOT / "data" / "saved-answers.json"


@dataclass(frozen=True)
class Settings:
    gcp_project_id: str
    gemini_location: str
    gemini_answer_model: str
    gemini_extraction_model: str  # reads the scanned AAPSI and APMT tables
    gemini_embedding_model: str
    index_path: Path
    # The public demo's guard rails. With no `firestore_database` the app runs without them.
    firestore_database: str | None = None
    firestore_log_collection: str = "questions"
    firestore_limits_collection: str = "limits"
    firestore_ttl_field: str = "expire_at"
    hourly_limit_per_ip: int = 10
    daily_question_cap: int = 300
    # Keys the hashed IP in the rate-limit counters. Set it so every instance hashes the same way;
    # left unset, each process picks its own and the hourly limit applies per instance.
    ip_hash_salt: str = ""


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
        gemini_extraction_model=env.get("GEMINI_EXTRACTION_MODEL") or env["GEMINI_ANSWER_MODEL"],
        gemini_embedding_model=env.get("GEMINI_EMBEDDING_MODEL") or "gemini-embedding-001",
        index_path=Path(env.get("COA_INDEX_PATH") or DEFAULT_INDEX),
        firestore_database=env.get("FIRESTORE_DATABASE") or None,
        firestore_log_collection=env.get("FIRESTORE_LOG_COLLECTION") or "questions",
        firestore_limits_collection=env.get("FIRESTORE_LIMITS_COLLECTION") or "limits",
        firestore_ttl_field=env.get("FIRESTORE_TTL_FIELD") or "expire_at",
        hourly_limit_per_ip=int(env.get("HOURLY_LIMIT_PER_IP") or 10),
        daily_question_cap=int(env.get("DAILY_QUESTION_CAP") or 300),
        ip_hash_salt=env.get("IP_HASH_SALT") or secrets.token_hex(16),
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
