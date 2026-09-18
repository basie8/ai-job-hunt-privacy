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


#: Where to look for the key, in order. AURUM_ANTHROPIC_API_KEY comes first
#: because ANTHROPIC_API_KEY is *reserved* inside a Claude Code session: the
#: platform authenticates the session through the account and refuses to pass
#: that name through to the sandbox, warning "won't be used to authenticate
#: requests". The pipeline is a separate API consumer running inside that
#: session, so it needs a name the platform does not claim.
#:
#: The reserved names are still read, because they work fine outside a Claude
#: Code session -- a local shell, CI, a plain container.
CREDENTIAL_ENV_VARS = (
    "AURUM_ANTHROPIC_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
)


def resolve_api_key() -> str:
    """The first credential found, or "" so the SDK can try its own resolution."""
    import os

    for name in CREDENTIAL_ENV_VARS:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def credential_source() -> str:
    """Which variable supplied the key, for reporting. Never the key itself."""
    import os

    for name in CREDENTIAL_ENV_VARS:
        if (os.environ.get(name) or "").strip():
            return name
    return ""


class AnthropicStageClient(StageClient):
    """Real client. Requires the ``anthropic`` package and credentials.

    Credentials resolve the SDK's own way: ``ANTHROPIC_API_KEY``, then
    ``ANTHROPIC_AUTH_TOKEN``, then an ``ant auth login`` profile. Nothing is
    read or logged from the environment here.
    """

    def __init__(self, client: Any = None, max_attempts: int = 2) -> None:
        if client is None:
            import anthropic  # imported lazily so the rest of the package has no hard dep

            key = resolve_api_key()
            client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
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


#: What a credential check can conclude. Each is a different problem with a
#: different remedy, and collapsing any two of them sends the reader to the
#: wrong place -- which is exactly what cost an evening on 2026-09-17, when a
#: key that was present but revoked was reported as "no credentials".
ABSENT = "absent"        # no variable is set
VALID = "valid"          # the API accepted it
REFUSED = "refused"      # the API rejected the value (401)
UNREACHABLE = "unreachable"  # the request never got an answer
UNCHECKED = "unchecked"  # a key is set but nothing asked the API


@dataclass(frozen=True)
class CredentialCheck:
    """The result of asking whether the pipeline can authenticate.

    Deliberately carries the variable *name* and the key's *length*, never the
    value. A diagnostic that echoes a secret turns a support question into a
    rotation, and that has already happened once in this project.
    """

    status: str
    source: str = ""
    key_length: int = 0
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == VALID

    def render(self) -> str:
        where = self.source or "(none set)"
        head = f"credential: {where}"
        if self.key_length:
            head += f" ({self.key_length} characters)"
        return f"{head}\nstatus: {self.status}\n{self.detail}".rstrip()


def verify_key(client: Any = None, probe: bool = True) -> CredentialCheck:
    """Ask the API whether the configured key works, without spending anything.

    The check is ``models.list``: authenticated, free, and independent of which
    models the account may call. A messages request would work too, but it
    bills, and a diagnostic that costs money is a diagnostic people avoid
    running.

    ``probe=False`` reports only what is set locally, for when the network is
    not available or not wanted.
    """
    import os

    source = credential_source()
    if not source:
        return CredentialCheck(
            status=ABSENT,
            detail="No credential variable is set: " + "/".join(CREDENTIAL_ENV_VARS),
        )
    length = len((os.environ.get(source) or "").strip())

    if not probe:
        return CredentialCheck(
            status=UNCHECKED, source=source, key_length=length,
            detail="A key is set. Not verified against the API (probe disabled).",
        )

    if client is None:
        import anthropic

        client = anthropic.Anthropic(api_key=resolve_api_key())

    try:
        client.models.list(limit=1)
    except Exception as exc:  # noqa: BLE001 - the SDK's exception tree varies by version
        text = str(exc)
        if _looks_like_auth_failure(exc, text):
            return CredentialCheck(
                status=REFUSED, source=source, key_length=length,
                detail=("The API refused the value (401). The variable is set and was "
                        "sent, so this is not a missing-variable problem: the key "
                        "itself is revoked, mistyped, or from another organisation."),
            )
        return CredentialCheck(
            status=UNREACHABLE, source=source, key_length=length,
            detail=f"The request did not get an answer, so the key is unjudged: {text}",
        )

    return CredentialCheck(
        status=VALID, source=source, key_length=length,
        detail="The API accepted the key. The four stages can authenticate.",
    )


def _looks_like_auth_failure(exc: Exception, text: str) -> bool:
    """Is this a rejected key, or something else entirely?

    Checked by status code first and prose second: the SDK's exception class
    names have changed between versions, and a check that matches on the class
    would start reporting a revoked key as a network fault after an upgrade.
    """
    status = getattr(exc, "status_code", None)
    if status == 401:
        return True
    if status is not None:
        return False
    lowered = text.lower()
    return "authentication_error" in lowered or "401" in lowered
