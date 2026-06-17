<img width="1536" height="1024" alt="image" src="https://github.com/user-attachments/assets/5695f7b3-4692-460d-bd71-8fd1a7409c3e" />

# 📈 Automated Option Selling Strategy — NIFTY & SENSEX

> **Non-directional ATM Straddle | 0DTE | AngelOne API | AWS EC2 | ML Data Collection**

---

## Overview

A fully automated intraday option selling system that executes a **non-directional ATM straddle strategy** on Indian markets (NIFTY and SENSEX) via the AngelOne SmartAPI. The system sells both CE and PE at the ATM strike at 9:19 AM IST and exits at 2:59 PM IST, with intelligent stop-loss management throughout the day.

The system is also actively **collecting labeled trade data** to train a Machine Learning model that predicts the probability of a **double-sided Stop Loss hit** on any given trading day — the primary risk event for this strategy.

---

## 🆕 Latest Version — v2.0 (June 2026)

### ML Data Collection Layer Added

The most significant addition in this version is a dedicated **trade data logging module** (`trade_data_logger.py`) that runs silently alongside the trading strategy every day, building a structured dataset for future ML model training.

**Why ML?**

The biggest risk in option selling is a **double-sided SL hit** — when both CE and PE stop losses execute on the same day due to the market whipsawing in both directions. This results in maximum loss on both legs simultaneously. The goal is to build a model that **predicts the probability of this happening before or during the trading day**, enabling early protective action.

**Data collection started: June 8, 2026.**

Every trading day, one new labeled row is automatically appended to `options_trade_log.csv` with 39 columns covering the full trade lifecycle — from pre-market VIX and gap data through intraday SL upgrade timings to the final `double_sl_hit = Y/N` outcome label.

### Bug Fixes & Improvements in v2.0

- **Sensex prev_close bug fixed** — Previously fetching NIFTY 50 previous close for SENSEX trades, resulting in a 220% gap calculation error. Now dynamically selects `S&P BSE SENSEX` or `NIFTY 50` from NSE based on instrument. Yahoo Finance (`^BSESN`) used as fallback when NSE drops Sensex data after market hours.
- **First candle via Yahoo Finance** — Replaced unreliable AngelOne `getCandleData` for spot index tokens (`26000`, `99919000`) with Yahoo Finance intraday chart API (`^NSEI`, `^BSESN`), which works reliably during and after market hours.
- **SL race condition fix** — Before upgrading from 30% → 40% SL, system now checks if the 30% SL already executed on exchange (handles single-minute spike scenarios where price blows past both trigger levels before next LTP poll).
- **EOD square-off protection** — Uses `ce_sl_logged` / `pe_sl_logged` flags to skip square-off on legs already closed by SL during the day — preventing a dangerous scenario where the code cancels an orphan SL order and places an unintended fresh buy on a position that was already closed, creating a naked long option at market close.

---

## Architecture

```
Amazon EventBridge (Scheduled Trigger)
        │
        ▼
AWS Lambda (Start EC2)
        │
        ▼
┌─────────────────────────────────┐
│         EC2 Instance            │
│                                 │
│  Option Selling Code            │
│       → Strategy Engine         │◄──── AngelOne API
│       → Option Selling Strategy │────► (Market Data / Orders)
│                                 │
│  Logs → CloudWatch → S3         │────► Telegram
└─────────────────────────────────┘      (Live Alerts)
        │
        ▼
  Automation
  Start EC2 (Before Market Open)
  Stop EC2  (After Market Close)
```

**Flow:**
1. EventBridge triggers Lambda on schedule (pre-market)
2. Lambda starts the EC2 instance
3. EC2 runs the option selling strategy
4. Connects with AngelOne API to place and monitor orders
5. Notifications sent to Telegram (order confirmations, SL alerts, errors)
6. Logs stored in CloudWatch and S3
7. Trade data saved to CSV for ML training

---

## Strategy Details

### Instrument Schedule

| Day | Instrument | Exchange | Expiry |
|-----|-----------|----------|--------|
| Monday | NIFTY | NFO | Tuesday |
| Tuesday | SENSEX | BFO | Thursday |
| Wednesday | SENSEX | BFO | Thursday |
| Thursday | NIFTY | NFO | Tuesday |
| Friday | NIFTY | NFO | Tuesday |

> Expiry override: If today is NIFTY expiry (Tuesday) → run SENSEX. If SENSEX expiry (Thursday) → run NIFTY.

### Entry Logic
- **Wait until 9:18:56 AM IST**
- Fetch ATM strike (NIFTY: round to 50, SENSEX: round to 100)
- SELL CE + PE at ATM strike via MARKET order
- Place STOPLOSS_LIMIT orders at **30% above entry** for both legs
- Quantities: NIFTY = 455, SENSEX = 140

### Stop Loss Management

```
Initial SL  = entry × 1.30   (placed immediately at entry)
Upgraded SL = entry × 1.40   (placed when LTP crosses entry × 1.20)
```

**Upgrade Logic:** If either leg's LTP crosses +20% above entry price, the 30% SL is cancelled and replaced with a 40% SL. This locks in a controlled loss before the move accelerates.

**Race Condition Protection:** Before attempting an upgrade, the system checks if the 30% SL has already executed on the exchange. If yes — logs it, skips the upgrade, sends Telegram alert.

### Exit Logic

| Exit Type | Trigger | Action |
|-----------|---------|--------|
| Normal | 14:59 IST | Square off open positions (skips already-closed legs) |
| Double SL | Both CE + PE SL executed | Early exit, log EOD |

> **Important:** Square off at 14:59 uses `ce_sl_logged` / `pe_sl_logged` flags to skip any leg already closed by SL during the day — preventing accidental fresh option buys on closed positions.

---

## Risk Signal

Computed pre-entry (~8:50 AM) using India VIX and overnight gap:

| Condition | Points |
|-----------|--------|
| VIX > 17 | +3 |
| 13 < VIX ≤ 17 | +1 |
| \|Gap\| > 0.8% | +3 |
| 0.3% < \|Gap\| ≤ 0.8% | +1 |

| Score | Signal |
|-------|--------|
| 0–1 | 🟢 LOW |
| 2–4 | 🟡 MEDIUM |
| 5–6 | 🔴 HIGH |

---

## ML Data Collection — Predicting Double SL

### Objective

Build a binary classifier to predict **double_sl_hit (Y/N)** — whether both CE and PE stop losses will be hit on a given trading day.

### Target Variable
```
double_sl_hit = Y  →  Both CE and PE SL executed (loss day)
double_sl_hit = N  →  Normal exit or single SL only
```

### How Data Is Captured

The `trade_data_logger.py` module runs inside every strategy execution. It captures data in 5 phases throughout the trading day and saves to CSV **immediately after each phase** — so even if the EC2 instance is stopped mid-day, all data captured so far is preserved on disk.

```
Phase 1 — Pre-market (~8:50 AM)
  VIX, spot, prev_close, gap_pct, risk_signal, risk_score
  → Saved to CSV immediately

Phase 2 — Entry (9:19 AM)
  ATM strike, CE/PE premiums, straddle price, SL levels
  → Saved to CSV immediately

Phase 3 — First Candle (9:25 AM)
  9:15 candle open/high/low/size_pct via Yahoo Finance
  → Saved to CSV immediately

Phase 4 — Intraday (dynamic, when triggered)
  SL upgrade timings, which side first, gap between upgrades
  SL hit timings, which side first, gap between hits
  → Saved to CSV immediately on each event

Phase 5 — EOD (14:59 or early exit)
  ce_sl_hit, pe_sl_hit, double_sl_hit (THE LABEL), exit_time, notes
  → Saved to CSV immediately
```

### Feature Phases

**Phase 1 — Available at 9:20 AM (entry)**
- `vix_open` — India VIX
- `gap_pct` — Overnight gap %
- `straddle_price` — Combined CE + PE premium
- `day_of_week` — Trading day

**Phase 2 — Available at 9:25 AM**
- `first_candle_size_pct` — (High - Low) / Open × 100 of 9:15 candle

**Phase 3 — Dynamic intraday**
- `ce_upgrade_mins_from_entry` / `pe_upgrade_mins_from_entry`
- `which_side_upgraded_first`
- `both_sides_upgraded`
- `gap_between_upgrades_mins`
- `ce_sl_hit_mins_from_entry` / `pe_sl_hit_mins_from_entry`

### Model Roadmap

| Data Rows | Model | Status |
|-----------|-------|--------|
| < 50 | Too few — collect only | 🔄 Active |
| 50–100 | Logistic Regression (Phase 1+2 features) | ⏳ Planned |
| 100–200 | Random Forest (all features) | ⏳ Planned |
| 200+ | Full confidence — dynamic intraday model | 🔮 Future |

> **Metric:** F1 Score (not accuracy — double SL is minority class)

### Key Hypothesis

> When the **first side upgrades early** (< 30 mins from entry) AND **gap % is high**, the probability of a double SL is significantly elevated. The prediction trigger fires at the moment of first upgrade — giving hours of warning before the second side moves.

### Production Alert Flow (Future)

Once sufficient data is collected and model is trained, Telegram alerts will look like:

```
9:20 AM  → "Entry risk: 42% — VIX=15.6, Gap=+1.08%"
9:25 AM  → "Post-candle risk: 58% — Candle size 0.20%"
Dynamic  → "PE upgraded in 24 mins. Double SL probability: 78% — consider early exit"
```

### Data Collected So Far

```
Start date    : June 8, 2026
Rows          : 5 (as of June 16, 2026)
Double SL days: 1 (June 12, 2026)
Normal days   : 3
Single SL days: 1
Target        : ~125 rows by Dec 2026
```

| Date | Instrument | Gap% | Risk | Straddle | Candle% | double_sl_hit |
|------|-----------|------|------|----------|---------|---------------|
| 2026-06-08 | NIFTY | -1.224 | MEDIUM(4) | 244.98 | — | N |
| 2026-06-09 | SENSEX | +0.695 | MEDIUM(2) | 893.12 | — | N |
| 2026-06-10 | SENSEX | -0.481 | MEDIUM(2) | 743.27 | — | N |
| 2026-06-11 | NIFTY | -0.476 | MEDIUM(2) | 331.32 | 0.221% | N |
| 2026-06-12 | NIFTY | +1.083 | MEDIUM(4) | 275.85 | 0.202% | **Y** |

---

## CSV Schema

> 📁 File on EC2: `/home/ec2-user/AlgoTrading/common/options_trade_log.csv`
>
> 📁 GitHub: [AlgoTrading/common](https://github.com/kanisgar/AlgoTrading/tree/main/common)

39 columns covering 5 phases of trade lifecycle:

| Phase | Columns |
|-------|---------|
| Identity | date, instrument, day_of_week |
| Pre-entry | vix_open, spot_at_entry, prev_close, gap_pct, risk_signal, risk_score |
| Entry | atm_strike, ce/pe_premium_entry, straddle_price, ce/pe_sl_30/40_level |
| First Candle | first_candle_open/high/low/size_pct |
| SL Upgrade | ce/pe_upgrade_time, mins_from_entry, which_side_first, both_upgraded, gap_mins |
| SL Hit | ce/pe_sl_hit_time, mins_from_entry, which_side_first, gap_between_hits |
| EOD | ce_sl_hit, pe_sl_hit, **double_sl_hit**, exit_time, notes |

---

## File Structure

```
/home/ec2-user/
├── AlgoTrading/
│   ├── common/                             # 👉 https://github.com/kanisgar/AlgoTrading/tree/main/common
│   │   ├── trade_data_logger.py            # ML data capture module (39 columns)
│   │   ├── options_trade_log.csv           # ML training data (grows daily)
│   │   └── get_cached_order_book.py        # Shared order book cache utility
│   ├── nifty_expiry_holidays.txt
│   └── job_logs/
│       ├── job_option_selling_vikas_nifty_YYYY-MM-DD.txt
│       ├── job_option_selling_vikas_YYYY-MM-DD.txt
│       └── trade_data_logger_YYYY-MM-DD.txt
└── Option_Selling_Vikas/
    ├── run_trading.py                      # Entry point — decides NIFTY or SENSEX
    ├── option_selling_vikas_nifty.py       # NIFTY strategy
    └── option_selling_vikas.py             # SENSEX strategy
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Cloud | AWS EC2, Lambda, EventBridge, CloudWatch, S3 |
| Broker API | AngelOne SmartAPI |
| Language | Python 3.9+ |
| Alerts | Telegram Bot API |
| Market Data | AngelOne API + Yahoo Finance (fallback) |
| Auth | pyotp (TOTP) |
| Timezone | pytz / zoneinfo (IST) |

### Dependencies
```bash
pip install smartapi-python pyotp pytz requests boto3 twilio
```

---

## Key Design Decisions

**Kill-safe CSV writes** — Every `log_*()` call saves to CSV immediately. If EC2 is stopped mid-day, all captured data is preserved on disk.

**Yahoo Finance fallback** — NSE drops Sensex from `allIndices` after market close. Yahoo Finance (`^BSESN`) is used as fallback for `prev_close` and first candle OHLC.

**SL logged flag** — `ce_sl_logged` / `pe_sl_logged` boolean flags track whether each leg was closed by SL during the day. Used to prevent dangerous fresh buys at EOD square-off on already-closed positions.

**Race condition protection** — Before upgrading SL from 30% to 40%, the system checks if the 30% SL already executed on the exchange — preventing orphan SL orders on closed positions.

---

## Telegram Alerts

| Alert | When |
|-------|------|
| 📊 Risk Signal | Pre-entry with VIX, Gap, Signal level |
| ✅ Orders Placed | After CE + PE entry with SL levels |
| 🚀 SL Upgraded | When 30% → 40% upgrade triggers |
| ⚠️ SL Hit Before Upgrade | When spike executes SL before upgrade |
| ❌ SL Placement Failed | When 40% SL placement fails — manual action required |
| ✅ All Positions Squared Off | EOD normal exit |

---

## Disclaimer

This system is for personal use only. Options trading involves substantial risk. Past performance does not guarantee future results. This is not financial advice.

---

*Built and maintained by Kanisgar | EC2: i-0bc461a1bc178f190 | Running since April 2025*
