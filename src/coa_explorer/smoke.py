"""Post-deploy smoke check: ask a running app a real question and look at what comes back."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

QUESTION = "What did COA observe about cash advances in Manila?"
TIMEOUT_SECONDS = 120


def check(base_url: str, question: str = QUESTION, timeout: float = TIMEOUT_SECONDS) -> list[str]:
    """Return what is wrong with the app at `base_url`; an empty list means it works end to end."""
    base = base_url.rstrip("/")
    try:
        with urllib.request.urlopen(base + "/", timeout=timeout) as page:
            if page.status != 200:
                return [f"{base}/ returned HTTP {page.status}"]
        request = urllib.request.Request(
            base + "/api/ask",
            data=json.dumps({"question": question}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            events = [json.loads(line) for line in response.read().decode().splitlines() if line]
    except (urllib.error.URLError, OSError, ValueError) as error:
        return [f"could not reach {base}: {error}"]

    last = events[-1] if events else {}
    if last.get("type") != "answer":
        return [f"expected an answer, got {last.get('type', 'no event')}: {last}"]
    uncited = [p for p in last.get("key_points", []) if not p.get("citations")]
    if not last.get("key_points") or uncited:
        return [f"the answer has no cited key points: {last}"]
    return []
