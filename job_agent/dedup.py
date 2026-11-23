"""Cross-site deduplication and seen-job history persistence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .models import JobListing


def _norm(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def compute_fingerprint(job: JobListing) -> str:
    """Compute a stable cross-query fingerprint based on title, company, and primary city."""
    city = _norm((job.location or "").split(",")[0])
    key = f"{_norm(job.title)}|{_norm(job.company)}|{city}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def deduplicate_jobs(
    jobs: list[JobListing],
    seen_history_path: Path | None = None,
) -> list[JobListing]:
    """Deduplicate jobs by (source, job_id) and normalized fingerprint, keeping richest record."""
    seen_ids: set[tuple[str, str]] = set()
    by_fingerprint: dict[str, JobListing] = {}
    ordered_keys: list[str] = []

    previous_fingerprints: set[str] = set()
    if seen_history_path and seen_history_path.exists():
        try:
            payload = json.loads(seen_history_path.read_text(encoding="utf-8"))
            previous_fingerprints = set(payload.get("fingerprints", []))
        except (OSError, json.JSONDecodeError):
            previous_fingerprints = set()

    for job in jobs:
        fp = compute_fingerprint(job)
        job.fingerprint = fp
        id_key = (job.source, job.job_id)
        if job.job_id and id_key in seen_ids:
            continue
        if job.job_id:
            seen_ids.add(id_key)

        existing = by_fingerprint.get(fp)
        if existing is None:
            by_fingerprint[fp] = job
            ordered_keys.append(fp)
        else:
            # Prefer the entry with richer description / skill tags / salary.
            existing_richness = len(existing.description) + len(existing.raw_skills) * 40 + (20 if existing.salary else 0)
            candidate_richness = len(job.description) + len(job.raw_skills) * 40 + (20 if job.salary else 0)
            if candidate_richness > existing_richness:
                by_fingerprint[fp] = job

    deduped = [by_fingerprint[k] for k in ordered_keys]
    for job in deduped:
        job.is_new = job.fingerprint not in previous_fingerprints

    if seen_history_path:
        seen_history_path.parent.mkdir(parents=True, exist_ok=True)
        updated = sorted(previous_fingerprints | {j.fingerprint for j in deduped})
        seen_history_path.write_text(
            json.dumps({"fingerprints": updated}, indent=2),
            encoding="utf-8",
        )

    return deduped
