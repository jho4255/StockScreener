# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

StockAlarm is a Python stock screener that identifies oversold buying opportunities in US (S&P 500, NASDAQ 100) and Korean (KOSPI, KOSDAQ) markets using a two-stage filtering pipeline.

## How to Run

```bash
# US market screening (default)
python runScreening.py US

# Korean market screening
python runScreening.py KR
```

## Dependencies

- `yfinance` — market data (daily + 15m intraday)
- `pandas_ta` — RSI, Stochastic calculations
- `pandas`, `numpy` — data manipulation
- `requests` — fetching ticker lists from Wikipedia and Naver API
- `tqdm` — progress bars

## Architecture

The screener runs a two-step pipeline in `runScreening.py`:

1. **Step 1 — Condition D (Daily):** Screen all tickers on daily bars for FearZone + RSI ≤ 31 + Stochastic %K ≤ 21
2. **Step 2 — Condition M (15-min Intraday):** Re-screen Condition D candidates on 15-minute bars with the same thresholds

### Key Technical Indicators

- **FearZone** (`get_fearzone_condition`): Custom contrarian indicator based on Zeiierman's Pine Script. Detects panic selling using two sub-conditions:
  - `FZ1`: Drawdown from 30-bar high, triggers when > WMA mean + 1 stdev (50-bar)
  - `FZ2`: 30-bar WMA of price, triggers when < WMA mean - 1 stdev (50-bar)
  - FearZone = both FZ1 and FZ2 active simultaneously
- **RSI(14):** Standard, oversold threshold at 31
- **Slow Stochastic (40, 10, 10):** %K line, oversold threshold at 21

### Ticker Universe

- **US:** Hardcoded growth/momentum tickers + S&P 500 (Wikipedia) + NASDAQ 100 (Wikipedia), deduplicated
- **KR:** Top 300 KOSPI + 300 KOSDAQ by market cap from Naver mobile API, suffixed `.KS`/`.KQ`

## Reference Documents

- `raw_plan.txt` — Original screening conditions and implementation plan (Korean)
- `understand_feargread.md` — Detailed analysis of the GreedZone/FearZone indicator logic (Korean)
