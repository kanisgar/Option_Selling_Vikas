
<img width="1536" height="1024" alt="image" src="https://github.com/user-attachments/assets/5695f7b3-4692-460d-bd71-8fd1a7409c3e" />

# 📈 Automated Option Selling Strategy — NIFTY & SENSEX

> **Non-directional ATM Straddle | 0DTE | AngelOne API | AWS EC2 | ML Data Collection**

---

## Overview

A fully automated intraday option selling system that executes a **non-directional ATM straddle strategy** on Indian markets (NIFTY and SENSEX) via the AngelOne SmartAPI. The system sells both CE and PE at the ATM strike at 9:19 AM IST and exits at 2:59 PM IST, with intelligent stop-loss management throughout the day.

The system is also actively **collecting labeled trade data** to train a Machine Learning model that predicts the probability of a **double-sided Stop Loss hit** on any given trading day — the primary risk event for this strategy.

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
| < 50 | Too few | Collecting |
| 50–100 | Logistic Regression | Planned |
| 100–200 | Random Forest | Planned |
| 200+ | Full confidence | Future |

> **Metric:** F1 Score (not accuracy — double SL is minority class)

### Key Hypothesis

> When the **first side upgrades early** (< 30 mins from entry) AND **gap % is high**, the probability of a double SL is significantly elevated. The prediction trigger fires at the moment of first upgrade — giving hours of warning before the second side moves.

### Data Collected So Far

```
Start date : June 8, 2026
Rows       : 5 (as of June 16, 2026)
Target     : ~125 rows by Dec 2026
```

---

## CSV Schema

File: `/home/ec2-user/AlgoTrading/common/options_trade_log.csv`

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
│   ├── common/
│   │   ├── trade_data_logger.py        # ML data capture module
│   │   ├── options_trade_log.csv       # ML training data
│   │   └── get_cached_order_book.py
│   ├── nifty_expiry_holidays.txt
│   └── job_logs/
│       ├── job_option_selling_vikas_nifty_YYYY-MM-DD.txt
│       ├── job_option_selling_vikas_YYYY-MM-DD.txt
│       └── trade_data_logger_YYYY-MM-DD.txt
└── Option_Selling_Vikas/
    ├── run_trading.py                  # Entry point
    ├── option_selling_vikas_nifty.py   # NIFTY strategy
    └── option_selling_vikas.py         # SENSEX strategy
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

*Built and maintained by Kanisgar | EC2: i-0bc461a1bc178f190 | Running since June 2026*
