# NHL Goalie Saves Betting System — Deployment Guide

## Architecture

```
Daily Pipeline Flow:
┌─────────┐    ┌──────────────┐    ┌─────────────────┐    ┌────────┐    ┌─────────┐
│ NHL API │───▶│ data_pipeline│───▶│ strategy_engine  │───▶│ notify │───▶│ Discord │
│ Odds API│    │  (features)  │    │  (MF3/MF2/MF5)  │    │        │    │#nhl-bet │
└─────────┘    └──────────────┘    └─────────────────┘    └────────┘    └─────────┘
                     │                      │
                     ▼                      ▼
              data/daily_slate.csv    picks/picks_DATE.json
                                            │
                                            ▼ (next day)
                                     ┌──────────────┐
                                     │track_results │───▶ logs/paper_trades.csv
                                     └──────────────┘
```

## Components

| File | Purpose |
|---|---|
| `config.yaml` | All configuration (bankroll, strategies, schedule) |
| `data_pipeline.py` | Pulls NHL schedule, starting goalies, odds, builds features, runs model |
| `strategy_engine.py` | Applies MF3a/MF3b/MF5/MF2/PF1 filters, sizes bets via Kelly |
| `kelly_sizer.py` | Quarter-Kelly bet sizing with strategy-specific win probability estimates |
| `notify.py` | Formats and queues Discord notifications |
| `track_results.py` | Matches picks to actual results, tracks P&L |
| `scheduler.py` | Orchestrates daily runs (daemon mode or one-shot phases) |
| `test_system.py` | End-to-end test suite |

## Data Sources

- **NHL API** (`api-web.nhle.com/v1`): Schedule, starting goalies, no auth needed
- **The Odds API** (`the-odds-api.com`): Goalie saves lines, requires API key (500 req/month free)
- **PostgreSQL** (`nhl_betting`): Historical stats for rolling features (goalie_stats, game_team_stats)

## Model

- **LightGBM regressor** trained on all available data (2022-2026)
- 15 features including Corsi, save %, shots against, rest days
- Serialized at `model/lightgbm_model.pkl` with metadata at `model/model_metadata.json`
- Corsi quantile thresholds baked into metadata for strategy filters

## Setup

```bash
cd nhl-betting/deploy
pip install -r requirements.txt

# Get The Odds API key
# 1. Sign up at https://the-odds-api.com/
# 2. Copy your API key

# Create .env
cp .env.example .env
# Edit .env and add your ODDS_API_KEY

# Run tests
python test_system.py

# Run once (pick a phase)
python scheduler.py --phase morning    # Pull schedule + odds
python scheduler.py --phase picks      # Generate picks

# Or run as daemon
python scheduler.py --daemon
```

## Daily Schedule (all times ET)

| Time | Phase | What happens |
|---|---|---|
| 8:00 AM | Morning | Pull schedule, initial odds, build features |
| 11:00 AM | Starters | Re-check goalie starter confirmations |
| 2:00 PM | Picks | Final pull, run strategies, send picks to Discord |
| 9:00 AM+1 | Results | Track yesterday's results, send summary |

## OpenClaw Integration

The scheduler can also be triggered via OpenClaw cron jobs:

```
# In OpenClaw, create cron jobs for each phase:
# 8:00 AM ET: "Run NHL morning pipeline: python ~/nhc-capital/nhl-betting/deploy/scheduler.py --phase morning"
# 2:00 PM ET: "Run NHL picks pipeline: python ~/nhc-capital/nhl-betting/deploy/scheduler.py --phase picks"
# 9:00 AM ET: "Run NHL results tracking: python ~/nhc-capital/nhl-betting/deploy/scheduler.py --phase results"
```

Notifications are queued to `deploy/pending_notification.json` — OpenClaw picks these up and sends to Discord.

## Strategies

| Strategy | Filter | Side | Validated WR | p-value |
|---|---|---|---|---|
| MF3a | Gap [1.0-1.5) + Corsi bottom 25% | UNDER | 70.5% | <0.01 |
| MF3b | Gap ≥2.5 + Corsi bottom 25% | UNDER | 58.0% | <0.05 |
| MF5 | Gap ≥1.0 + Corsi bottom 30% | UNDER | 62.1% | <0.01 |
| MF2 | Gap ≥2.0 + B2B (rest ≤1d) | UNDER | 62.2% | <0.05 |
| PF1 | Triple Corsi top 25% | OVER | 59.2% | paper only |

## Paper Trading Mode

`config.yaml` has `paper_trading: true` by default. All bets are logged to `logs/paper_trades.csv` but no real money is at risk. Set to `false` only after reviewing at least 30 days of paper results.

## Monitoring

- **Logs**: `logs/scheduler_DATE.log` — full pipeline output
- **Errors**: `logs/errors_DATE.log` — errors only
- **Picks**: `picks/picks_DATE.json` — daily picks
- **Paper trades**: `logs/paper_trades.csv` — running P&L tracker
- **API cache**: `data/api_cache/` — raw API responses for debugging

## Error Handling

- **Odds API rate limit**: 500 req/month ≈ 16/day. System uses ~5-8 per run. If limit hit, skips odds and logs error.
- **NHL API down**: 3 retries with exponential backoff.
- **Goalie not confirmed**: Flagged in picks but not auto-excluded (may need manual decision by 2PM).
- **Model file missing**: Critical failure, logged immediately.
- **Database down**: Critical failure, all features require DB access.

## Retraining

To retrain the model (e.g., after adding new seasons of data):

```bash
cd nhl-betting
python model/build_features.py    # Rebuild feature matrix from DB
python model/serialize_model.py   # Retrain and serialize
python deploy/test_system.py      # Verify everything still works
```
