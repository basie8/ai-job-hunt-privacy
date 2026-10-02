# Synthetic sample data

These three CSVs are **generated random walks**, not real gold prices. They exist
so `python -m gold_trader signal --csv-dir gold_trader/examples/data` runs
end-to-end without a feed, and so the CSV parser has something to parse in a
demo. Any signal produced from them is meaningless.

Replace them with real exports before trusting anything:

- **MT4/MT5**: open the XAUUSD chart at the timeframe you want, then
  *File -> Save As* (or *Tools -> History Center -> Export*). Save as
  `XAUUSD_h1.csv`, `XAUUSD_h4.csv`, `XAUUSD_m15.csv`.
- **TradingView**: chart menu -> *Export chart data* -> CSV.
- **Dukascopy**: the historical data feed exports the same shape.

Column names do not need editing - the parser aliases the usual spellings
(`<DATE>`, `time`, `datetime`, `<CLOSE>`, `close`, `tickvol`, ...).
