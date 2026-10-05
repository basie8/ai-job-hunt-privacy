"""Append-only, hash-chained audit log.

Every model call, every deterministic check and every state transition in the
run lands here as one JSON line. Records are chained with SHA-256 over the
canonical serialisation of the record plus the previous record's hash, so a
later edit to any line invalidates every line after it -- ``verify_log`` walks
the chain and reports the first break.

The log is the artefact the reporter stage summarises, and the thing you hand
to whoever asks why a given order was sent.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

GENESIS_HASH = "0" * 64


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def sha256_of(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class AuditLog:
    """Writes one JSONL file per run and keeps the records in memory."""

    path: Optional[str] = None
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    records: List[Dict[str, Any]] = field(default_factory=list)
    _prev_hash: str = GENESIS_HASH

    def __post_init__(self) -> None:
        if self.path:
            directory = os.path.dirname(os.path.abspath(self.path))
            if directory:
                os.makedirs(directory, exist_ok=True)

    # -- writing ---------------------------------------------------------
    def record(self, stage: str, event: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        entry = {
            "seq": len(self.records),
            "run_id": self.run_id,
            "ts": _now(),
            "stage": stage,
            "event": event,
            "payload": payload,
            "prev_hash": self._prev_hash,
        }
        entry["hash"] = sha256_of(entry)
        self._prev_hash = entry["hash"]
        self.records.append(entry)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        return entry

    def llm_call(
        self,
        stage: str,
        *,
        model_id: str,
        effort: Optional[str],
        usage: Dict[str, int],
        cost_usd: float,
        latency_ms: int,
        request_id: Optional[str],
        stop_reason: Optional[str],
        prompt_sha256: str,
        response_sha256: str,
        attempt: int = 1,
    ) -> Dict[str, Any]:
        """One model round-trip. Prompts and responses are hashed, not copied.

        The hashes make a transcript verifiable against the log without the log
        itself becoming a second copy of everything the model saw.
        """
        return self.record(
            stage,
            "llm_call",
            {
                "model": model_id,
                "effort": effort,
                "attempt": attempt,
                "usage": {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
                    "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
                },
                "cost_usd": round(cost_usd, 6),
                "latency_ms": latency_ms,
                "request_id": request_id,
                "stop_reason": stop_reason,
                "prompt_sha256": prompt_sha256,
                "response_sha256": response_sha256,
            },
        )

    # -- reading ---------------------------------------------------------
    def events(self, event: str) -> List[Dict[str, Any]]:
        return [r for r in self.records if r["event"] == event]

    def total_cost_usd(self) -> float:
        return round(sum(r["payload"]["cost_usd"] for r in self.events("llm_call")), 6)

    def total_tokens(self) -> Dict[str, int]:
        totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        for r in self.events("llm_call"):
            for k in totals:
                totals[k] += r["payload"]["usage"].get(k, 0)
        return totals

    def cost_by_stage(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for r in self.events("llm_call"):
            out[r["stage"]] = round(out.get(r["stage"], 0.0) + r["payload"]["cost_usd"], 6)
        return out

    def summary(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "records": len(self.records),
            "total_cost_usd": self.total_cost_usd(),
            "tokens": self.total_tokens(),
            "cost_by_stage": self.cost_by_stage(),
            "head_hash": self._prev_hash,
        }

    def narrative(self, limit: int = 200) -> str:
        """Compact, model-readable rendering of the trail for the reporter."""
        lines = []
        for r in self.records[:limit]:
            payload = r["payload"]
            if r["event"] == "llm_call":
                detail = (
                    f"model={payload['model']} effort={payload['effort']} "
                    f"cost=${payload['cost_usd']:.4f} stop={payload['stop_reason']}"
                )
            else:
                detail = _canonical(payload)
                if len(detail) > 1200:
                    detail = detail[:1200] + "...(truncated)"
            lines.append(f"[{r['seq']:03d}] {r['stage']}/{r['event']}: {detail}")
        return "\n".join(lines)


def iter_log(path: str) -> Iterator[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def verify_records(records: Iterable[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
    """Re-walk the hash chain. Returns ``(ok, first_problem)``."""
    prev = GENESIS_HASH
    expected_seq = 0
    for record in records:
        if record.get("seq") != expected_seq:
            return False, f"seq {record.get('seq')!r} out of order (expected {expected_seq})"
        if record.get("prev_hash") != prev:
            return False, f"record {expected_seq} does not chain to its predecessor"
        stored = record.get("hash")
        recomputed = sha256_of({k: v for k, v in record.items() if k != "hash"})
        if stored != recomputed:
            return False, f"record {expected_seq} has been modified after it was written"
        prev = stored
        expected_seq += 1
    return True, None


def verify_log(path: str) -> Tuple[bool, Optional[str]]:
    """Verify a whole audit file, which holds one chain per run.

    Each run builds its own chain from GENESIS_HASH with its own sequence
    starting at zero, and the file accumulates them. Walking the file as a
    single chain therefore reports the second run as corruption -- it says
    "seq 0 out of order (expected 4)" against a log that is perfectly intact,
    which is what it did on 2026-09-21 with all ten chains verifying.

    A tamper check that cries wolf is worse than none: it is the one tool
    whose entire value is that you believe it when it fires.
    """
    runs: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
    for record in iter_log(path):
        runs.setdefault(str(record.get("run_id", "")), []).append(record)
    for run_id, records in runs.items():
        ok, problem = verify_records(records)
        if not ok:
            return False, f"run {run_id}: {problem}"
    return True, None


def verify_runs(path: str) -> Dict[str, Tuple[bool, Optional[str]]]:
    """Per-run verdicts, so a damaged run names itself rather than hiding
    behind the first failure."""
    runs: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
    for record in iter_log(path):
        runs.setdefault(str(record.get("run_id", "")), []).append(record)
    return {run_id: verify_records(records) for run_id, records in runs.items()}


class Timer:
    """Wall-clock helper so every stage reports latency the same way."""

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)
