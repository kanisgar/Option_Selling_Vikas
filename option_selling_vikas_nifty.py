import os
from datetime import datetime, timedelta
import pyotp
from SmartApi import SmartConnect
import pytz
import time
from collections import deque
import logging
import boto3
import json
import platform
import getpass
from twilio.rest import Client
import sys
import calendar
import requests

# --------- Account Config ---------
API_KEY     = 'xgMtWyMS'
CLIENT_CODE = 'AAAI570791'
PASSWORD    = '1611'
TOTP_SECRET = 'ZXI5JF7SKHJND6W2XCBHYPLEJU'
refresh_token = None

should_stop_ec2_on_exit = False

account_sid = 'AC6ef902b81d63731c13b746613aadb2aa'
auth_token  = '06c408e1a82a20ae2b839f2cceac4705'

# --------- Risk Config ---------
RISK_1043    = 0.30
RISK_1113    = 0.40
producttype  = "INTRADAY"
QTY          = 455
EXP_QTY      = 455
auto_reentry = False

smart_api = SmartConnect(api_key=API_KEY)
client    = Client(account_sid, auth_token)

BOT_TOKEN          = "8313800040:AAFbD8M5e6g8OF2SlGJzgfM9c9oyfZyah6c"
RECIPIENT_CHAT_IDS = ["632084234"]

current_date    = datetime.now().strftime("%Y-%m-%d")
india_tz        = pytz.timezone("Asia/Kolkata")
finland_tz      = pytz.timezone("Europe/Helsinki")
system_platform = platform.system()
current_user    = getpass.getuser()

if system_platform == "Windows":
    holiday_location = "C:\\Kani_Personal\\Automate_Trading\\AlgoTrading\\"
    log_path = f"C:/Kani_Personal/Automate_Trading/Option_Selling_Vikas/job_logs/job_option_selling_vikas_nifty_{datetime.now().strftime('%Y-%m-%d')}.txt"
elif system_platform == "Darwin":
    holiday_location = "/Users/kanisgar/Documents/AlgoTrading/"
    log_path = f"/Users/kanisgar/Documents/Option_Selling_Vikas/job_logs/job_option_selling_vikas_nifty_{datetime.now().strftime('%Y-%m-%d')}.txt"
elif system_platform == "Linux":
    if current_user == "ec2-user":
        holiday_location = "/home/ec2-user/AlgoTrading/"
        log_path = f"/home/ec2-user/Option_Selling_Vikas/job_logs/job_option_selling_vikas_nifty_{datetime.now().strftime('%Y-%m-%d')}.txt"
        should_stop_ec2_on_exit = False

os.makedirs(os.path.dirname(log_path), exist_ok=True)

shared_utils_path = os.path.join(holiday_location, "common")
sys.path.append(shared_utils_path)
from get_cached_order_book import get_order_book
from trade_data_logger import TradeDataLogger

CACHE_FILE = os.path.join(shared_utils_path, "orderbook_cache.json")
LOCK_FILE  = os.path.join(shared_utils_path, "orderbook_cache.lock")

logging.basicConfig(
    filename=log_path, filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S', level=logging.INFO
)
last_logged_time    = 0
ltp_call_timestamps = deque()


def trigger_ec2_shutdown_lambda():
    FUNCTION_NAME = "stopEC2Instance"
    INSTANCE_ID   = "i-0bc461a1bc178f190"
    try:
        lambda_client = boto3.client("lambda", region_name="us-east-1")
        lambda_client.invoke(
            FunctionName=FUNCTION_NAME, InvocationType="Event",
            Payload=json.dumps({"instance_id": INSTANCE_ID}).encode()
        )
        print("🛑 EC2 shutdown Lambda triggered.")
    except Exception as e:
        print(f"⚠️ Lambda trigger failed: {e}")


def log_and_print(message, level="info"):
    print(message)
    if level == "info":      logging.info(message)
    elif level == "error":   logging.error(message)
    elif level == "warning": logging.warning(message)
    elif level == "debug":   logging.debug(message)


def is_expiry_day():
    return datetime.today().date() == get_expiry_day().date()


def is_market_holiday(date_obj):
    holiday_file = holiday_location + "nifty_expiry_holidays.txt"
    try:
        with open(holiday_file, "r") as f:
            holidays = [line.strip() for line in f.readlines()]
    except FileNotFoundError:
        log_and_print(f"NIFTY: Warning: {holiday_file} not found. Assuming no holidays.")
        return False
    return date_obj.strftime("%d%b%y") in holidays or date_obj.weekday() in [5, 6]


def get_current_ist_time():
    return datetime.now(finland_tz).astimezone(india_tz)


def wait_until_ist(target_time):
    while True:
        now = get_current_ist_time()
        if now.strftime("%H:%M:%S") >= target_time:
            break
        time.sleep(1)


def login():
    try:
        global smart_api
        totp    = pyotp.TOTP(TOTP_SECRET).now()
        session = smart_api.generateSession(CLIENT_CODE, PASSWORD, totp)
        if session.get("status") is True:
            refresh_token = session["data"]["refreshToken"]
            log_and_print("NIFTY:✅ Login successful!")
        else:
            send_telegram(f"❌ NIFTY: Login failed: {session.get('message', 'Unknown')}")
            log_and_print(f"NIFTY:❌ Login failed: {session.get('message', 'Unknown')}")
            raise Exception(f"Login failed: {session.get('message')}")
    except Exception as e:
        log_and_print(f"NIFTY:🔒 Login exception: {e}")


def send_telegram(message_body):
    try:
        for chat_id in RECIPIENT_CHAT_IDS:
            url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            resp = requests.post(url, data={"chat_id": chat_id, "text": message_body})
            if resp.status_code == 200:
                log_and_print(f"Telegram sent to {chat_id}: {message_body}")
            else:
                log_and_print(f"Telegram failed to {chat_id}: {resp.text}")
    except Exception as e:
        log_and_print(f"Telegram error: {e}")


def is_logged_in(refresh_token):
    try:
        time.sleep(1)
        response = smart_api.getProfile(refresh_token)
        return response.get("status") == True
    except Exception as e:
        log_and_print(f"NIFTY:🔒 Session check error: {e}")
        return False


def get_expiry_day():
    today        = datetime.today()
    holiday_file = holiday_location + "nifty_expiry_holidays.txt"
    holidays     = []
    if os.path.exists(holiday_file):
        with open(holiday_file, "r") as file:
            holidays = [line.strip() for line in file.readlines()]
    if today.weekday() == 1 and today.strftime("%d%b%y") not in holidays:
        expiry_day = today
    else:
        days_ahead = (1 - today.weekday() + 7) % 7
        expiry_day = today + timedelta(days=days_ahead)
        while expiry_day.strftime("%d%b%y") in holidays or expiry_day.weekday() in [5, 6]:
            expiry_day -= timedelta(days=1)
    return expiry_day


def get_last_valid_expiry_of_month(expiry):
    year, month = expiry.year, expiry.month
    last_day    = calendar.monthrange(year, month)[1]
    skip_dates  = ["28Aug25"]
    thursdays   = []
    for day in range(1, last_day + 1):
        date_obj = datetime(year, month, day)
        if date_obj.weekday() == 3:
            while (is_market_holiday(date_obj) or
                   date_obj.strftime("%d%b%y") in skip_dates or
                   date_obj.weekday() in [5, 6]):
                date_obj -= timedelta(days=1)
            thursdays.append(date_obj)
    unique_expiries = sorted(set(thursdays))
    return unique_expiries[-1] if unique_expiries else expiry


def get_nifty_atm():
    spot_data = smart_api.ltpData("NSE", "NIFTY", "26000")
    if spot_data.get("status") is True:
        return round(float(spot_data["data"]["ltp"]) / 50) * 50
    raise Exception("❌ Failed to get NIFTY ATM price!")


def get_nifty_spot():
    spot_data = smart_api.ltpData("NSE", "NIFTY", "26000")
    if spot_data.get("status") is True:
        return float(spot_data["data"]["ltp"])
    return None


def get_915_candle_nifty():
    """
    Fetch 9:15 candle OHLC for Nifty from NSE public chart API.
    Uses same NSE session as VIX fetch — reliable, no AngelOne token needed.
    Call at 9:25 AM so the 9:15 candle is fully formed.
    """
    try:
        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":     "application/json",
            "Referer":    "https://www.nseindia.com"
        }
        session.get("https://www.nseindia.com", headers=headers, timeout=8)
        resp = session.get(
            "https://www.nseindia.com/api/chart-databyindex?index=NIFTY 50&indices=true",
            headers=headers, timeout=8
        )
        resp.raise_for_status()
        data  = resp.json()
        graph = data.get("grapData") or data.get("graphData") or []
        if not graph:
            log_and_print("NIFTY: 9:15 candle — empty graph data from NSE")
            return None

        # Filter price points between 09:15 and 09:19 IST
        candle_points = []
        for point in graph:
            ts_ms = point[0]
            price = float(point[1])
            dt    = datetime.fromtimestamp(ts_ms / 1000, tz=india_tz)
            if "09:15" <= dt.strftime("%H:%M") <= "09:19":
                candle_points.append(price)

        if not candle_points:
            # Fallback: use very first available point
            log_and_print("NIFTY: 9:15 candle — no 09:15-09:19 points, using first available")
            first = float(graph[0][1])
            return {"open": first, "high": first, "low": first, "close": first}

        result = {
            "open":  candle_points[0],
            "high":  max(candle_points),
            "low":   min(candle_points),
            "close": candle_points[-1]
        }
        log_and_print(f"NIFTY: 9:15 candle → O={result['open']} H={result['high']} L={result['low']}")
        return result

    except Exception as e:
        log_and_print(f"NIFTY: 9:15 candle fetch failed: {e}")
    return None


def build_symbols(strike_price, expiry_date):
    expiry_str = expiry_date.strftime("%d%b%y").upper()
    strike_str = str(strike_price).zfill(5)
    return f"NIFTY{expiry_str}{strike_str}CE", f"NIFTY{expiry_str}{strike_str}PE"


def get_token(symbol):
    try:
        search_response = smart_api.searchScrip("NFO", symbol)
        if search_response.get("status") is True:
            return search_response["data"][0]["symboltoken"]
        raise Exception(f"Token not found for {symbol}")
    except Exception as e:
        log_and_print(f"❌ get_token failed for {symbol}: {e}")
        send_telegram(f"❌ NIFTY: get_token failed for {symbol}: {e}")
        raise


def get_ltp(symbol, symbol_token):
    global last_logged_time
    try:
        current_time = time.time()
        ltp_call_timestamps.append(current_time)
        while ltp_call_timestamps and current_time - ltp_call_timestamps[0] > 60:
            ltp_call_timestamps.popleft()
        if current_time - last_logged_time >= 60:
            log_and_print(f"NIFTY:🕒 LTP calls last 60s: {len(ltp_call_timestamps)}")
            last_logged_time = current_time
        time.sleep(0.5)
        ltp_data = smart_api.ltpData("NFO", symbol, symbol_token)
        if ltp_data.get("status") is True:
            return float(ltp_data["data"]["ltp"])
        return None
    except Exception as e:
        log_and_print(f"NIFTY:❌ LTP failed {symbol}: {e}")


def place_market_order(symbol, token):
    try:
        order = {
            "variety": "NORMAL", "tradingsymbol": symbol,
            "symboltoken": token, "transactiontype": "SELL",
            "exchange": "NFO", "ordertype": "MARKET",
            "producttype": producttype, "duration": "DAY", "quantity": QTY
        }
        res = smart_api.placeOrder(order)
        if res:
            return res
    except Exception as e:
        log_and_print(f"NIFTY:❌ Order failed {symbol}: {e}")
        send_telegram(f"❌ NIFTY: Order failed {symbol}: {e}")
    return None


def emergency_exit(symbol, token):
    try:
        order = {
            "variety": "NORMAL", "tradingsymbol": symbol,
            "symboltoken": token, "transactiontype": "BUY",
            "exchange": "NFO", "ordertype": "MARKET",
            "producttype": producttype, "duration": "DAY", "quantity": QTY
        }
        smart_api.placeOrder(order)
    except Exception as e:
        log_and_print(f"NIFTY:❌ Emergency exit failed {symbol}: {e}")
        send_telegram(f"❌ NIFTY: Emergency exit failed {symbol}: {e}")
    return None


def place_sl_order(symbol, token, sl_price):
    try:
        order = {
            "variety": "STOPLOSS", "tradingsymbol": symbol,
            "symboltoken": token, "transactiontype": "BUY",
            "exchange": "NFO", "ordertype": "STOPLOSS_LIMIT",
            "producttype": producttype, "duration": "DAY",
            "price": sl_price, "triggerprice": sl_price, "quantity": QTY
        }
        order_response = smart_api.placeOrder(order)
        log_and_print(f"NIFTY:🔐 SL placed {symbol} @ {sl_price} → {order_response}")
        return order_response
    except Exception as e:
        log_and_print(f"NIFTY:❌ SL failed {symbol}: {e}")
        send_telegram(f"❌ NIFTY: (PLACE SL MANUALLY!) SL failed {symbol} @ {sl_price}: {e}")
        return None


def cancel_order(order_id):
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        log_and_print(f"NIFTY:🔁 Cancel attempt {attempt} for {order_id}")
        try:
            cancel_response = smart_api.cancelOrder(str(order_id), "STOPLOSS")
            log_and_print(f"NIFTY: Cancel attempt {attempt} made for {order_id}")
        except Exception as e:
            log_and_print(f"NIFTY:⚠️ Cancel attempt {attempt} failed: {e}")
            cancel_response = None
        time.sleep(1)
        current_status = get_order_status_from_book(order_id)
        log_and_print(f"NIFTY:📘 Order {order_id} status after attempt {attempt}: {current_status}")
        if current_status.upper() in ["CANCELLED", "REJECTED", "COMPLETE"]:
            log_and_print(f"NIFTY:✅ Order {order_id} in final state: {current_status}")
            return cancel_response
        time.sleep(1)
    log_and_print(f"NIFTY:❌ Failed to cancel {order_id} after {max_attempts} attempts.")
    return None


def square_off(symbol, token, order_id):
    try:
        time.sleep(1)
        get_order_book(smart_api, CACHE_FILE, LOCK_FILE)
        sl_hit = is_order_executed(order_id)
        log_and_print(f"NIFTY: sl_hit for {symbol} order {order_id}: {sl_hit}")
        if not sl_hit:
            cancel_order(order_id)
            log_and_print(f"NIFTY: Cancelled {order_id}. Status: {get_order_status_from_book(order_id)}")
            time.sleep(1)
            order = {
                "variety": "NORMAL", "tradingsymbol": symbol,
                "symboltoken": token, "transactiontype": "BUY",
                "exchange": "NFO", "ordertype": "MARKET",
                "producttype": producttype, "duration": "DAY", "quantity": QTY
            }
            square_order = smart_api.placeOrder(order)
            log_and_print(f"NIFTY:✅ Squared off {symbol}: {square_order}")
        else:
            log_and_print(f"NIFTY:🛑 SL already hit {symbol}, skip square off")
    except Exception as e:
        log_and_print(f"NIFTY:❌ Square off error {symbol}: {e}")
        send_telegram(f"❌ NIFTY: (DO MANUALLY!) Square off error {symbol}: {e}")


def get_order_entry_price(order_id):
    try:
        time.sleep(1)
        all_orders = get_order_book(smart_api, CACHE_FILE, LOCK_FILE)
        if all_orders.get("status"):
            for order in all_orders["data"]:
                if str(order.get("orderid")) == str(order_id):
                    if order.get("orderstatus", "").strip().lower() == "complete":
                        return float(order.get("averageprice"))
                    else:
                        log_and_print(f"NIFTY:⚠️ Order {order_id} not complete yet.")
                        return None
            log_and_print(f"NIFTY:⚠️ Order {order_id} not found.")
        else:
            log_and_print("NIFTY:⚠️ No order data from orderBook()")
    except Exception as e:
        log_and_print(f"NIFTY:❌ get_order_entry_price failed {order_id}: {e}")
        send_telegram(f"❌ NIFTY: get_order_entry_price failed {order_id}: {e}")
    return None


def is_order_executed(order_id):
    try:
        order_details = get_order_book(smart_api, CACHE_FILE, LOCK_FILE)
        log_and_print(f"NIFTY: Checking order {order_id}")
        for order in order_details.get("data", []):
            if str(order.get("orderid")) == str(order_id):
                return order.get("orderstatus", "").strip().lower() == "complete"
        log_and_print(f"NIFTY: Order {order_id} not found in order book.")
        return False
    except Exception as e:
        log_and_print(f"NIFTY:❌ is_order_executed exception: {e}")
        return False


def get_order_status_from_book(order_id):
    try:
        order_book = get_order_book(smart_api, CACHE_FILE, LOCK_FILE)
        if order_book and order_book.get("data"):
            for order in order_book["data"]:
                if str(order.get("orderid")) == str(order_id):
                    return order.get("status", "UNKNOWN")
        log_and_print(f"NIFTY:⚠️ Order {order_id} not found in book.")
    except Exception as e:
        log_and_print(f"NIFTY:❌ get_order_status_from_book error {order_id}: {e}")
        send_telegram(f"NIFTY: Error fetching status for {order_id}: {e}")
    return "UNKNOWN"


def execute_trade_block(ce_symbol, pe_symbol, ce_token, pe_token, risk_pct, risk_pct_40):
    ce_order_id = place_market_order(ce_symbol, ce_token)
    time.sleep(5)
    pe_order_id = place_market_order(pe_symbol, pe_token)
    time.sleep(5)
    if is_order_executed(ce_order_id) and is_order_executed(pe_order_id):
        ce_entry_price = get_order_entry_price(ce_order_id)
        pe_entry_price = get_order_entry_price(pe_order_id)
        if ce_entry_price is None or pe_entry_price is None:
            log_and_print("NIFTY:❌ Failed to get entry prices. Exiting...")
            return
        ce_sl    = round(ce_entry_price * (1 + risk_pct),    1)
        pe_sl    = round(pe_entry_price * (1 + risk_pct),    1)
        ce_sl_40 = round(ce_entry_price * (1 + risk_pct_40), 1)
        pe_sl_40 = round(pe_entry_price * (1 + risk_pct_40), 1)
        ce_sl_order_id = place_sl_order(ce_symbol, ce_token, ce_sl)
        pe_sl_order_id = place_sl_order(pe_symbol, pe_token, pe_sl)
        return ce_sl_order_id, pe_sl_order_id, ce_entry_price, pe_entry_price, ce_sl_40, pe_sl_40
    else:
        if ce_order_id:
            emergency_exit(ce_symbol, ce_token) if is_order_executed(ce_order_id) else cancel_order(ce_order_id)
        if pe_order_id:
            emergency_exit(pe_symbol, pe_token) if is_order_executed(pe_order_id) else cancel_order(pe_order_id)
        send_telegram("NIFTY: UNABLE TO PLACE MARKET ORDER → EMERGENCY EXIT")
        raise Exception("NIFTY: UNABLE TO PLACE MARKET ORDER AND TRIGGERED EMERGENCY EXIT")


def run_os_strategy():
    trade_logger = TradeDataLogger(instrument="NIFTY")

    try:
        ce_sl_order_1430  = None
        pe_sl_order_1430  = None
        ce_sl_order_1043  = None
        pe_sl_order_1043  = None
        ce_entry_price    = None
        pe_entry_price    = None
        ce_sl_40          = None
        pe_sl_40          = None
        ce_updated        = False
        pe_updated        = False
        reentered         = False
        ltp_miss_count    = 0
        first_candle_done = False
        ce_sl_logged      = False  # tracks if CE SL hit has been logged
        pe_sl_logged      = False  # tracks if PE SL hit has been logged

        login()
        expiry = get_expiry_day()
        log_and_print(f"NIFTY: Expiry → {expiry}")

        global QTY
        if is_expiry_day():
            QTY = EXP_QTY
            log_and_print(f"NIFTY:📉 Expiry day. QTY={QTY}. Exiting.")
            sys.exit(0)
        else:
            log_and_print(f"NIFTY:📈 Not expiry. QTY={QTY}")

        # Pre-entry: fetch spot + VIX, send risk signal via Telegram
        log_and_print("NIFTY: Fetching spot and VIX...")
        spot_now    = get_nifty_spot()
        risk_signal = trade_logger.log_pre_entry(spot_now)
        send_telegram(f"📊 NIFTY Risk Signal: {risk_signal}\n"
                      f"VIX={trade_logger._row['vix_open']} | "
                      f"Gap={trade_logger._row['gap_pct']}%")

        log_and_print("NIFTY: Waiting till 09:18:56...")
        wait_until_ist("09:18:56")

        atm_strike = get_nifty_atm()
        log_and_print(f"NIFTY: ATM={atm_strike}")
        ce_symbol, pe_symbol = build_symbols(atm_strike, expiry)
        ce_token = get_token(ce_symbol)
        time.sleep(1)
        pe_token = get_token(pe_symbol)

        (ce_sl_order_1043, pe_sl_order_1043,
         ce_entry_price, pe_entry_price,
         ce_sl_40, pe_sl_40) = execute_trade_block(
            ce_symbol, pe_symbol, ce_token, pe_token, RISK_1043, RISK_1113)

        log_and_print(f"NIFTY: CE SL order={ce_sl_order_1043}, PE SL order={pe_sl_order_1043}")

        ce_sl_30_level = round(ce_entry_price * (1 + RISK_1043), 1)
        pe_sl_30_level = round(pe_entry_price * (1 + RISK_1043), 1)
        trade_logger.log_entry(
            ce_entry=ce_entry_price, pe_entry=pe_entry_price,
            atm_strike=atm_strike,
            ce_sl_30=ce_sl_30_level, pe_sl_30=pe_sl_30_level,
            ce_sl_40=ce_sl_40,       pe_sl_40=pe_sl_40
        )

        send_telegram(
            f"NIFTY: ORDERS PLACED. SL pending.\n"
            f"CE entry={ce_entry_price} SL30={ce_sl_30_level} SL40={ce_sl_40}\n"
            f"PE entry={pe_entry_price} SL30={pe_sl_30_level} SL40={pe_sl_40}"
        )

        # ── Main loop ─────────────────────────────────────────────────────
        while get_current_ist_time().strftime("%H:%M") < "14:59":
            tim = get_current_ist_time().strftime("%H:%M")
            time.sleep(3)

            if not ce_updated:
                ce_ltp = get_ltp(ce_symbol, ce_token)
            time.sleep(1)
            if not pe_updated:
                pe_ltp = get_ltp(pe_symbol, pe_token)

            if (not ce_updated and ce_ltp is None) or (not pe_updated and pe_ltp is None):
                ltp_miss_count += 1
                log_and_print(f"NIFTY:⚠️ LTP missing: {ltp_miss_count}")
                if ltp_miss_count >= 7:
                    log_and_print("NIFTY:❌ LTP missing 7 times.")
                    send_telegram("NIFTY:❌ LTP missing continuously. Check system!")
                    ltp_miss_count = 0
                time.sleep(2)
                continue

            # Capture real 9:15 candle OHLC once after 9:25
            if not first_candle_done and tim >= "09:25":
                try:
                    candle = get_915_candle_nifty()
                    if candle:
                        trade_logger.log_first_candle(
                            open_=candle["open"],
                            high=candle["high"],
                            low=candle["low"]
                        )
                    else:
                        log_and_print("NIFTY: 9:15 candle returned None, skipping")
                except Exception as e:
                    log_and_print(f"NIFTY: First candle capture failed: {e}")
                first_candle_done = True

            # CE SL hit detection — catch the exact moment it executes
            if not ce_sl_logged and ce_sl_order_1043 and is_order_executed(ce_sl_order_1043):
                trade_logger.log_sl_hit("CE")
                ce_sl_logged = True
                log_and_print(f"NIFTY: CE SL hit detected at {tim}")

            # PE SL hit detection — catch the exact moment it executes
            if not pe_sl_logged and pe_sl_order_1043 and is_order_executed(pe_sl_order_1043):
                trade_logger.log_sl_hit("PE")
                pe_sl_logged = True
                log_and_print(f"NIFTY: PE SL hit detected at {tim}")

            # CE premium crossed +20% → upgrade SL from 30% to 40%
            if not ce_updated and ce_ltp >= ce_entry_price * 1.20:
                log_and_print("NIFTY:🚀 CE +20% → upgrade SL to 40%")
                cancel_order(ce_sl_order_1043)
                time.sleep(1)
                ce_sl_order_1043 = place_sl_order(ce_symbol, ce_token, ce_sl_40)
                log_and_print(f"NIFTY: CE SL modified → {ce_sl_order_1043}")
                ce_updated = True
                trade_logger.log_sl_upgrade("CE")
                send_telegram("NIFTY: CE SL upgraded to 40%. PLEASE VERIFY.")

            # PE premium crossed +20% → upgrade SL from 30% to 40%
            if not pe_updated and pe_ltp >= pe_entry_price * 1.20:
                log_and_print("NIFTY:🚀 PE +20% → upgrade SL to 40%")
                cancel_order(pe_sl_order_1043)
                time.sleep(1)
                pe_sl_order_1043 = place_sl_order(pe_symbol, pe_token, pe_sl_40)
                log_and_print(f"NIFTY: PE SL modified → {pe_sl_order_1043}")
                pe_updated = True
                trade_logger.log_sl_upgrade("PE")
                send_telegram("NIFTY: PE SL upgraded to 40%. PLEASE VERIFY.")

            # Both SL hit check
            if is_order_executed(ce_sl_order_1043) and is_order_executed(pe_sl_order_1043):
                if not reentered and auto_reentry:
                    if get_current_ist_time().strftime("%H:%M") < "13:00":
                        log_and_print("NIFTY:⚠️ Both SL hit → re-entering...")
                        login()
                        atm_strike = get_nifty_atm()
                        ce_symbol_reentry, pe_symbol_reentry = build_symbols(atm_strike, expiry)
                        ce_token_reentry = get_token(ce_symbol_reentry)
                        time.sleep(1)
                        pe_token_reentry = get_token(pe_symbol_reentry)
                        ce_sl_order_1430, pe_sl_order_1430 = execute_trade_block(
                            ce_symbol_reentry, pe_symbol_reentry,
                            ce_token_reentry, pe_token_reentry, RISK_1043, RISK_1113)
                        reentered = True
                        send_telegram(f"NIFTY: RE-ENTRY at {tim}")
                elif not auto_reentry:
                    trade_logger.log_eod(
                        ce_sl_hit=True, pe_sl_hit=True,
                        notes=f"Double SL early exit at {tim}"
                    )
                    log_and_print(f"NIFTY:🚫 EARLY EXIT at {tim}: Double SL hit.")
                    send_telegram(f"NIFTY:🚫 EARLY EXIT at {tim} → Double SL. No re-entry.")
                    return
                elif reentered:
                    if is_order_executed(ce_sl_order_1430) and is_order_executed(pe_sl_order_1430):
                        trade_logger.log_eod(
                            ce_sl_hit=True, pe_sl_hit=True,
                            notes=f"4-side SL hit at {tim}"
                        )
                        log_and_print(f"NIFTY:🚫 4-side SL hit at {tim}. Exiting.")
                        send_telegram(f"NIFTY:🚫 4-side SL at {tim}. No more trades.")
                        return

        # ── Normal EOD ────────────────────────────────────────────────────
        log_and_print("NIFTY: Re-logging before square off...")
        login()

        ce_final_hit = is_order_executed(ce_sl_order_1043)
        pe_final_hit = is_order_executed(pe_sl_order_1043)
        trade_logger.log_eod(
            ce_sl_hit=ce_final_hit, pe_sl_hit=pe_final_hit,
            notes="Normal exit at 14:59"
        )

        square_off(ce_symbol, ce_token, ce_sl_order_1043)
        square_off(pe_symbol, pe_token, pe_sl_order_1043)
        if reentered:
            square_off(ce_symbol_reentry, ce_token_reentry, ce_sl_order_1430)
            square_off(pe_symbol_reentry, pe_token_reentry, pe_sl_order_1430)

        log_and_print("NIFTY:✅ All positions squared off.")
        send_telegram("NIFTY:✅ All positions squared off.")

    except Exception as e:
        log_and_print(f"NIFTY:❌ Error: {e}")
        send_telegram(f"NIFTY:❌ Error: {e}")

    finally:
        try:
            trade_logger.save()
        except Exception as e:
            log_and_print(f"NIFTY: TradeDataLogger save failed in finally: {e}")


if __name__ == "__main__":
    try:
        log_and_print(f"NIFTY: Running on {system_platform}")
        current_date = datetime.today()
        if is_market_holiday(current_date):
            send_telegram(f"NIFTY: Market holiday {current_date}. Exiting.")
            log_and_print("NIFTY: Market holiday. Exiting.")
        else:
            log_and_print("NIFTY:📈 Running strategy...")
            run_os_strategy()
    except Exception as e:
        log_and_print(f"NIFTY:❌ Exception: {e}")
        send_telegram(f"NIFTY:❌ Exception: {e}")
    finally:
        log_and_print("NIFTY: Logging out...")
        send_telegram("NIFTY: Finally block executing. Logging out.")
        smart_api.terminateSession(CLIENT_CODE)
