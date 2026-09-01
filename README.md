# ai-job-hunt-privacy

Privacy policy page for AI Job Hunt (`index.html`), plus the MetaTrader 5 trading
agent described below.

---

## SMC AI Agent — MT5 expert advisor for XAUUSD (FTMO 2-step)

An MQL5 expert advisor that trades gold from Smart Money Concepts **without fixed
technical parameters**. On every bar close it re-reads the raw candles, calibrates
itself to the volatility and rhythm it can actually see, rebuilds the full SMC map
(market structure, BOS/CHoCH, order blocks, fair value gaps, equal highs/lows,
session and daily liquidity, premium/discount), proposes a direction from one of
three researched playbooks, scores 16 confluence factors, converts them into a
probability with an online model that keeps learning, and trades only when the
reward on the table pays for that probability — inside a layered FTMO envelope that
cannot lose 5% in a day.

```
MQL5/
  Experts/SMCAgent/SMC_AI_Agent.mq5     the agent
  Include/SMCAgent/
    Defs.mqh          shared types and the statistics helpers
    MarketState.mqh   live chart read + self-calibration
    SmcEngine.mqh     structure, order blocks, imbalances, liquidity, sweeps
    Confluence.mqh    playbooks and the 16-factor reasoning layer
    Learner.mqh       online logistic regression with prior anchoring
    RiskManager.mqh   FTMO 2-step envelope and position sizing
    TradeManager.mqh  execution, management, real and paper feedback books
    NewsFilter.mqh    MT5 economic calendar with CSV fallback
    Visuals.mqh       chart drawing and the live decision panel
    Logger.mqh        structured console/journal logging
docs/
  RESEARCH.md   what the design is based on, with sources
  STRATEGY.md   the full decision specification
  USER_GUIDE.md install, inputs, panel legend, backtesting, limitations
```

**Start here:** [docs/USER_GUIDE.md](docs/USER_GUIDE.md) ·
[docs/STRATEGY.md](docs/STRATEGY.md) · [docs/RESEARCH.md](docs/RESEARCH.md)

Trading a leveraged instrument carries risk; this repository is not investment
advice.
