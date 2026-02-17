-- Crypto price bars from Alpaca (5-min candles)
CREATE TABLE IF NOT EXISTS crypto_bars_5min (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    vwap DOUBLE PRECISION,
    trade_count INTEGER,
    PRIMARY KEY (symbol, ts)
);

CREATE INDEX IF NOT EXISTS idx_crypto_bars_ts ON crypto_bars_5min (ts);
CREATE INDEX IF NOT EXISTS idx_crypto_bars_symbol_ts ON crypto_bars_5min (symbol, ts DESC);
