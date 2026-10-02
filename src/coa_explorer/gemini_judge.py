"""The evaluation judge: Gemini Pro in Vertex AI batch mode.

A batch job reads its requests from, and writes its replies to, Cloud Storage, so this uploads one
JSONL file, waits for the job, and reads the replies back. Credentials are Application Default
Credentials locally and the CI service account in GitHub Actions; there are no keys. The model name
comes from configuration. Batch jobs run asynchronously (usually minutes) at a lower price than
online calls, which suits an evaluation nobody is waiting on interactively.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from urllib.parse import quote, urlparse

import google.auth
from google import genai
from google.auth.transport.requests import AuthorizedSession
from google.genai import types

STORAGE_API = "https://storage.googleapis.com"
POLL_SECONDS = 30
TIMEOUT_SECONDS = 4 * 60 * 60
FINISHED = {
    types.JobState.JOB_STATE_SUCCEEDED,
    types.JobState.JOB_STATE_PARTIALLY_SUCCEEDED,
    types.JobState.JOB_STATE_FAILED,
    types.JobState.JOB_STATE_CANCELLED,
    types.JobState.JOB_STATE_EXPIRED,
}
USABLE = {types.JobState.JOB_STATE_SUCCEEDED, types.JobState.JOB_STATE_PARTIALLY_SUCCEEDED}


class GeminiBatchJudge:
    def __init__(
        self,
        *,
        project: str,
        location: str,
        model: str,
        bucket: str,
        log: Callable[[str], None] = lambda message: print(message, flush=True),
    ):
        self._client = genai.Client(vertexai=True, project=project, location=location)
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        self._http = AuthorizedSession(credentials)
        self._model = model
        self._bucket = bucket
        self._log = log

    def generate_batch(self, system: str, prompts: list[str]) -> list[str | None]:
        run = f"eval/{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
        source = f"gs://{self._bucket}/{run}/input.jsonl"
        self._upload(f"{run}/input.jsonl", batch_input(system, prompts))
        job = self._client.batches.create(
            model=self._model,
            src=source,
            config=types.CreateBatchJobConfig(
                display_name=f"coa-eval-{run.rsplit('/', 1)[-1]}",
                dest=f"gs://{self._bucket}/{run}/output",
            ),
        )
        self._log(f"judge batch job {job.name} submitted ({len(prompts)} prompts)")
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while job.state not in FINISHED:
            if time.monotonic() > deadline:
                raise TimeoutError(f"judge batch job {job.name} did not finish in time")
            time.sleep(POLL_SECONDS)
            job = self._client.batches.get(name=job.name)
            self._log(f"judge batch job state: {job.state}")
        if job.state not in USABLE:
            raise RuntimeError(f"judge batch job {job.name} ended {job.state}: {job.error}")
        directory = job.dest.gcs_uri if job.dest and job.dest.gcs_uri else None
        directory = directory or (job.output_info.gcs_output_directory if job.output_info else None)
        if not directory:
            raise RuntimeError(f"judge batch job {job.name} reported no output location")
        return parse_output(prompts, self._read_outputs(directory))

    def _upload(self, name: str, text: str) -> None:
        response = self._http.post(
            f"{STORAGE_API}/upload/storage/v1/b/{self._bucket}/o",
            params={"uploadType": "media", "name": name},
            data=text.encode("utf-8"),
            headers={"Content-Type": "application/jsonl"},
        )
        response.raise_for_status()

    def _read_outputs(self, directory: str) -> list[str]:
        """The text of every `predictions.jsonl` the job wrote under `directory`."""
        parsed = urlparse(directory)
        prefix = parsed.path.lstrip("/")
        names: list[str] = []
        token = None
        while True:  # the listing is paged
            listing = self._http.get(
                f"{STORAGE_API}/storage/v1/b/{parsed.netloc}/o",
                params={"prefix": prefix, **({"pageToken": token} if token else {})},
            )
            listing.raise_for_status()
            body = listing.json()
            names += [i["name"] for i in body.get("items", []) if i["name"].endswith(".jsonl")]
            token = body.get("nextPageToken")
            if not token:
                break
        texts = []
        for name in names:
            response = self._http.get(
                f"{STORAGE_API}/storage/v1/b/{parsed.netloc}/o/{quote(name, safe='')}",
                params={"alt": "media"},
            )
            response.raise_for_status()
            texts.append(response.content.decode("utf-8"))
        return texts


def batch_input(system: str, prompts: list[str]) -> str:
    """The JSONL a Vertex batch job reads: one request per prompt, asking for JSON back."""
    return "".join(
        json.dumps(
            {
                "request": {
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "systemInstruction": {"parts": [{"text": system}]},
                    "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
                }
            }
        )
        + "\n"
        for prompt in prompts
    )


def parse_output(prompts: list[str], outputs: list[str]) -> list[str | None]:
    """Each prompt's reply text. Batch replies come back in no promised order but echo their
    request, so they are matched on the prompt text; a prompt with no usable reply gets None."""
    waiting: dict[str, list[int]] = {}
    for position, prompt in enumerate(prompts):
        waiting.setdefault(prompt, []).append(position)
    replies: list[str | None] = [None] * len(prompts)
    for output in outputs:
        for line in output.splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            try:
                prompt = record["request"]["contents"][0]["parts"][0]["text"]
                parts = record["response"]["candidates"][0]["content"]["parts"]
            except (KeyError, IndexError, TypeError):
                continue  # a failed request echoes itself with a status and no response
            text = "".join(p["text"] for p in parts if p.get("text") and not p.get("thought"))
            if text and waiting.get(prompt):
                replies[waiting[prompt].pop(0)] = text
    return replies
