# Four-stage LLM investment pipeline

Turns market signals into risk-checked order intents through four model stages,
with the exposure controls enforced in code and every step written to a
tamper-evident audit log.

```
  signals + portfolio
          |
          v
  [1] Analyst        claude-opus-5   effort=high   -> sized trade ideas
          |
          v
  deterministic limit engine (no model)            -> per-idea ceilings
          |
          v
  [2] Risk Manager   claude-opus-5   effort=max    -> verdict + adjustments
          |
      enforcement: min(risk manager, engine ceiling)
          |
          v
  [3] Executor       claude-sonnet-5 effort=low    -> order intents
          |
      post-check: approved symbol? within notional? (no model)
          |
          v
  [4] Reporter       claude-haiku-4-5              -> the written record
```

## Why the tiers are where they are

| Stage | Model | Effort | Input/Output $ per MTok | Why |
|---|---|---|---|---|
| Analyst | `claude-opus-5` | `high` | 5.00 / 25.00 | Open-ended synthesis over messy, partial signals. A weak thesis here is expensive and hard to spot downstream. |
| Risk Manager | `claude-opus-5` | `max` | 5.00 / 25.00 | The veto gate. It is the one stage where correctness matters more than cost, so it gets the most reasoning the model offers. |
| Executor | `claude-sonnet-5` | `low` | 2.00 / 10.00 | A mechanical transform of an already-approved decision into order mechanics. Low effort means fewer tokens and less preamble. |
| Reporter | `claude-haiku-4-5` | n/a | 1.00 / 5.00 | Summarising an audit trail that is already facts. Haiku 4.5 rejects `output_config.effort`, so the field is omitted for this tier. |

Prices are Anthropic first-party API rates. Every call's real usage, cost and
request id lands in the audit log, so the tiering can be re-argued from measured
spend rather than from this table (`AuditLog.cost_by_stage()`).

Promote or demote a stage without touching code:

```bash
PIPELINE_MODEL_EXECUTOR=claude-opus-5 python -m investment_pipeline run --input my_input.json
```

The stage's effort *intent* survives the swap; promoting into a model that
rejects `effort` drops the field instead of sending an invalid request.

## The part that is deliberately not a model

`risk.py` contains the exposure controls, and nothing in it calls an LLM:

| Control | Default | Behaviour on breach |
|---|---|---|
| Restricted symbols | empty | Hard block |
| Permitted asset classes | equity, etf, fx, rates, credit, commodity | Hard block |
| Drawdown kill switch | 15% | Hard block on risk-adding trades; risk-reducing trades still pass |
| Single position weight | 5% of NAV | Clamp, net of what is already held |
| Sector weight | 25% of NAV | Pro-rata scale-down of that sector's additions |
| Gross exposure | 120% of NAV | Pro-rata scale-down of additions |
| Net exposure | 100% of NAV | Pro-rata scale-down of the offending side |
| Cash floor | 2% of NAV | Pro-rata scale-down of buys |
| New positions per run | 8 | Drop the lowest-conviction names |
| Daily turnover | 20% of NAV | Pro-rata scale-down of additions |
| Conviction floor | 0.55 | Not actionable |
| Per-order notional | $25m | Order rejected at the post-execution check |

The risk-manager stage sees this engine's output as part of its prompt and is
told the weights are ceilings. Then `pipeline._enforce` takes
`min(risk_manager_weight, engine_ceiling)` regardless of what the model asked
for, drops anything the engine blocked, and drops anything the risk manager did
not explicitly address — silence is not approval. A model asking for more than
the ceiling does not get it; it gets an `override_attempt` record in the log.

The executor's output is re-checked the same way: an order for a symbol that was
never approved, one above the approved notional, one above the per-order cap, or
a limit order with no limit price is dropped before it appears in the result.

## Audit log

One JSONL file per run. Each record carries `prev_hash` and a SHA-256 `hash` over
its own canonical serialisation, so editing or removing any line invalidates
every line after it.

```jsonl
{"seq":0,"run_id":"…","ts":"…","stage":"pipeline","event":"run_started","payload":{…},"prev_hash":"000…","hash":"a3f…"}
{"seq":1,…,"stage":"analyst","event":"llm_call","payload":{"model":"claude-opus-5","effort":"high","usage":{…},"cost_usd":0.0712,"latency_ms":8431,"request_id":"req_…","prompt_sha256":"…","response_sha256":"…"}}
```

Prompts and responses are hashed, not copied: the log stays verifiable against a
transcript without becoming a second copy of everything the models saw.

Events written per run: `run_started`, `llm_call` (×4), `stage_output` (×4),
`deterministic_screen`, `override_attempt`, `unreviewed_ideas`, `enforcement`,
`order_check` or `stage_skipped`, `run_completed`.

```bash
python -m investment_pipeline verify --log audit/pipeline.jsonl
# audit/pipeline.jsonl: audit chain intact      (exit 0; exit 1 and a reason if not)
```

## Usage

```bash
pip install -r investment_pipeline/requirements.txt
export ANTHROPIC_API_KEY=...        # or `ant auth login`

# Full run
python -m investment_pipeline run \
  --input investment_pipeline/examples/sample_input.json \
  --audit-log audit/pipeline.jsonl

# Exposure controls only — no model calls, no credentials needed
python -m investment_pipeline screen \
  --input investment_pipeline/examples/sample_input.json \
  --ideas investment_pipeline/examples/sample_ideas.json
```

As a library:

```python
from investment_pipeline import AuditLog, PipelineConfig, PipelineInput, RiskLimits, run
from investment_pipeline.llm import AnthropicStageClient

config = PipelineConfig(limits=RiskLimits(max_position_weight_pct=3.0))
log = AuditLog(path="audit/run.jsonl")
result = run(PipelineInput.model_validate(payload), AnthropicStageClient(), config, log)

for trade in result.approved:
    print(trade.symbol, trade.weight_pct, trade.binding_constraint)
print(result.report.executive_summary, log.total_cost_usd())
```

`pipeline.run` takes any `StageClient`, so `tests/fake_client.py` replays canned
stage outputs and the whole orchestration is testable without network access.

## Prompting and API notes

- Every stage is schema-constrained via `output_config.format` (through the
  SDK's `messages.parse` with a Pydantic `output_format`), so stages consume
  data, not prose. Schemas are in `schemas.py`.
- System prompts are module-level constants in `prompts.py` and carry the cache
  breakpoint; all per-run context goes in the user message after it, which keeps
  the cached prefix stable across runs. `AuditLog.total_tokens()` reports
  `cache_read_input_tokens` so you can check the cache is actually hitting.
- Adaptive thinking is on for the Opus and Sonnet stages (`{"type": "adaptive"}`);
  the analyst asks for `display: "summarized"`. The Haiku reporter sends no
  `thinking` field at all.
- `llm.py` catches the SDK's typed exceptions in a most-specific-first chain and
  treats a `refusal` or `max_tokens` stop reason as a stage failure rather than
  parsing a truncated result.

## Cost

The four calls are small — the bulk of each prompt is a portfolio and a handful
of signals. At the rates above, a run with roughly 4k/2k tokens for the analyst,
6k/8k for the risk manager at `max` effort, 2k/1.5k for the executor and 4k/1k
for the reporter comes to about **$0.33**, dominated by the risk stage's output
tokens. That is an estimate from the published rates, not a measurement — the
log's `cost_by_stage()` gives you the real number once you have run it, and a
warm prompt cache takes the input side down substantially.

## What this is not

- **There is no broker connectivity.** Stage 3 produces order *intents*. Nothing
  is sent anywhere; wiring an OMS or an execution venue is left to the caller,
  deliberately, so the pipeline cannot trade by accident.
- **There is no market data adapter.** `PipelineInput` is whatever you hand it.
- **There is no backtest harness**, so the prompts and limits here are a starting
  configuration, not a validated strategy.
- The limit engine models shorts as cash-neutral and margin is governed only by
  the gross-exposure cap; a book where financing matters needs a real margin
  model in `risk.py`.
