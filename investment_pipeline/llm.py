"""Thin, audited wrapper around the Anthropic Messages API.

One call site for every stage, so that model choice, effort, schema
enforcement, error handling and audit capture happen exactly once and in the
same way regardless of which tier a stage runs on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, TypeVar

from .audit import AuditLog, Timer, sha256_of
from .config import ModelSpec

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from pydantic import BaseModel

T = TypeVar("T")


class StageError(RuntimeError):
    """A stage could not produce a usable, schema-valid result."""


@dataclass
class StageCall:
    """Everything the audit log needs to know about one model round-trip."""

    parsed: Any
    model_id: str
    effort: Optional[str]
    usage: Dict[str, int]
    cost_usd: float
    latency_ms: int
    request_id: Optional[str]
    stop_reason: Optional[str]
    prompt_sha256: str
    response_sha256: str


class StageClient:
    """Interface the pipeline depends on. Swap it out to test without network."""

    def call(
        self,
        *,
        stage: str,
        spec: ModelSpec,
        system: str,
        user: str,
        output_format: "Type[BaseModel]",
    ) -> StageCall:
        raise NotImplementedError


class AnthropicStageClient(StageClient):
    """Real client. Requires the ``anthropic`` package and credentials.

    Credentials resolve the SDK's own way: ``ANTHROPIC_API_KEY``, then
    ``ANTHROPIC_AUTH_TOKEN``, then an ``ant auth login`` profile. Nothing is
    read or logged from the environment here.
    """

    def __init__(self, client: Any = None, max_attempts: int = 2) -> None:
        if client is None:
            import anthropic  # imported lazily so the rest of the package has no hard dep

            client = anthropic.Anthropic()
        self._client = client
        self._max_attempts = max(1, max_attempts)

    def call(
        self,
        *,
        stage: str,
        spec: ModelSpec,
        system: str,
        user: str,
        output_format: "Type[BaseModel]",
    ) -> StageCall:
        import anthropic

        # The system prompt is the stable prefix; cache it and let the volatile
        # per-run context sit after the breakpoint in the user message.
        system_blocks: List[Dict[str, Any]] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        kwargs: Dict[str, Any] = {
            "model": spec.model_id,
            "max_tokens": spec.max_tokens,
            "system": system_blocks,
            "messages": [{"role": "user", "content": user}],
            "output_format": output_format,
        }
        output_config = spec.output_config()
        if output_config:
            kwargs["output_config"] = output_config
        if spec.thinking:
            kwargs["thinking"] = spec.thinking

        prompt_hash = sha256_of({"system": system, "user": user, "model": spec.model_id})
        last_error: Optional[Exception] = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                with Timer() as timer:
                    response = self._client.messages.parse(**kwargs)
            except anthropic.BadRequestError as exc:
                # Not retryable: a malformed request stays malformed.
                raise StageError(f"{stage}: bad request to {spec.model_id}: {exc}") from exc
            except anthropic.AuthenticationError as exc:
                raise StageError(f"{stage}: authentication failed: {exc}") from exc
            except anthropic.PermissionDeniedError as exc:
                raise StageError(f"{stage}: credentials lack access to {spec.model_id}") from exc
            except anthropic.NotFoundError as exc:
                raise StageError(f"{stage}: unknown model {spec.model_id!r}") from exc
            except anthropic.RateLimitError as exc:
                # The SDK already retried with backoff; surface it rather than spin.
                raise StageError(f"{stage}: rate limited on {spec.model_id}: {exc}") from exc
            except anthropic.APIStatusError as exc:
                raise StageError(
                    f"{stage}: API error {exc.status_code} on {spec.model_id}: {exc}"
                ) from exc
            except anthropic.APIConnectionError as exc:
                raise StageError(f"{stage}: could not reach the API: {exc}") from exc

            stop_reason = getattr(response, "stop_reason", None)
            if stop_reason == "refusal":
                details = getattr(response, "stop_details", None)
                category = getattr(details, "category", None)
                raise StageError(f"{stage}: model declined the request (category={category!r})")
            if stop_reason == "max_tokens":
                last_error = StageError(
                    f"{stage}: response hit max_tokens ({spec.max_tokens}); output truncated"
                )
                if attempt < self._max_attempts:
                    continue
                raise last_error

            parsed = getattr(response, "parsed_output", None)
            if parsed is None:
                last_error = StageError(f"{stage}: model returned no schema-valid output")
                if attempt < self._max_attempts:
                    continue
                raise last_error

            usage = _usage_dict(response)
            return StageCall(
                parsed=parsed,
                model_id=spec.model_id,
                effort=spec.effort,
                usage=usage,
                cost_usd=spec.cost_usd(usage),
                latency_ms=getattr(timer, "elapsed_ms", 0),
                request_id=getattr(response, "_request_id", None),
                stop_reason=stop_reason,
                prompt_sha256=prompt_hash,
                response_sha256=sha256_of(json.loads(parsed.model_dump_json())),
            )

        raise last_error or StageError(f"{stage}: call failed")


def _usage_dict(response: Any) -> Dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
    }


def run_stage(
    client: StageClient,
    log: AuditLog,
    *,
    stage: str,
    spec: ModelSpec,
    system: str,
    user: str,
    output_format: "Type[BaseModel]",
) -> Any:
    """Call one stage and write its round-trip to the audit log."""
    call = client.call(
        stage=stage, spec=spec, system=system, user=user, output_format=output_format
    )
    log.llm_call(
        stage,
        model_id=call.model_id,
        effort=call.effort,
        usage=call.usage,
        cost_usd=call.cost_usd,
        latency_ms=call.latency_ms,
        request_id=call.request_id,
        stop_reason=call.stop_reason,
        prompt_sha256=call.prompt_sha256,
        response_sha256=call.response_sha256,
    )
    return call.parsed
