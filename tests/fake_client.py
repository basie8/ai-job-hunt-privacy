"""A StageClient that replays canned stage outputs, so tests never hit the API."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from investment_pipeline.audit import sha256_of
from investment_pipeline.llm import StageCall, StageClient


class FakeStageClient(StageClient):
    def __init__(self, outputs: Dict[str, Any], usage: Dict[str, int] | None = None) -> None:
        self.outputs = outputs
        self.usage = usage or {
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        self.calls: List[Dict[str, Any]] = []

    def call(self, *, stage, spec, system, user, output_format) -> StageCall:
        if stage not in self.outputs:
            raise AssertionError(f"FakeStageClient has no canned output for stage {stage!r}")
        parsed = self.outputs[stage]
        if not isinstance(parsed, output_format):
            parsed = output_format.model_validate(parsed)
        self.calls.append(
            {"stage": stage, "model": spec.model_id, "effort": spec.effort, "user": user}
        )
        return StageCall(
            parsed=parsed,
            model_id=spec.model_id,
            effort=spec.effort,
            usage=dict(self.usage),
            cost_usd=spec.cost_usd(self.usage),
            latency_ms=7,
            request_id=f"req_fake_{stage}",
            stop_reason="end_turn",
            prompt_sha256=sha256_of({"system": system, "user": user}),
            response_sha256=sha256_of(json.loads(parsed.model_dump_json())),
        )

    def user_message_for(self, stage: str) -> str:
        for call in self.calls:
            if call["stage"] == stage:
                return call["user"]
        raise AssertionError(f"stage {stage!r} was never called")

    def stages_called(self) -> List[str]:
        return [c["stage"] for c in self.calls]
