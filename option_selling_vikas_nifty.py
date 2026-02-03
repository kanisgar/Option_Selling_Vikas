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
API_KEY = 'I39xpH90'
CLIENT_CODE = 'AAAI570791'
PASSWORD = '1611'
TOTP_SECRET = 'ZXI5JF7SKHJND6W2XCBHYPLEJU'
refresh_token = None

#For EC2 False by Default
should_stop_ec2_on_exit = False

#-----------Twilio Config -----------
account_sid = 'AC6ef902b81d63731c13b746613aadb2aa'
auth_token = '06c408e1a82a20ae2b839f2cceac4705'  # Replace with actual token

# --------- Risk Config ---------
RISK_1043 = 0.40
RISK_1113 = 0.34
producttype="INTRADAY"
#producttype='CARRYFORWARD"
QTY = 455 #7 Lots , 715 -> 14 lots
EXP_QTY = 455 #7 Lots , 715 -> 14 lots
auto_reentry = False #Make it False incase if no re-entry is required
# Initialize SmartConnect
smart_api = SmartConnect(api_key=API_KEY)

#Intialize Twilio
client = Client(account_sid, auth_token)

#For Telegram Bot
BOT_TOKEN = "8313800040:AAFbD8M5e6g8OF2SlGJzgfM9c9oyfZyah6c"
# List of Telegram Chat IDs (Replace with actual chat IDs of your recipients)
RECIPIENT_CHAT_IDS = [
    "632084234",  # Recipient 1
]

# --------- Timezone Setup ---------
current_date = datetime.now().strftime("%Y-%m-%d")
india_tz = pytz.timezone("Asia/Kolkata")
finland_tz = pytz.timezone("Europe/Helsinki")
system_platform = platform.system()
current_user = getpass.getuser()

#holiday_location="C:\Kani_Personal\Automate_Trading\AlgoTrading\\"
#log_path = f"C:/Kani_Personal/Automate_Trading/AlgoTrading/job_logs/job_optionSellingVikas_{datetime.now().strftime('%Y-%m-%d')}.txt"
if system_platform == "Windows":
    holiday_location = "C:\\Kani_Personal\\Automate_Trading\\AlgoTrading\\"
    log_path = f"C:/Kani_Personal/Automate_Trading/Option_Selling_Vikas/job_logs/job_option_selling_vikas_nifty_{datetime.now().strftime('%Y-%m-%d')}.txt"

elif system_platform == "Darwin":  # Mac
    holiday_location = "/Users/kanisgar/Documents/AlgoTrading/"
    log_path = f"/Users/kanisgar/Documents/Option_Selling_Vikas/job_logs/job_option_selling_vikas_nifty_{datetime.now().strftime('%Y-%m-%d')}.txt"

elif system_platform == "Linux":
    if current_user == "ec2-user":
        holiday_location = "/home/ec2-user/AlgoTrading/"
        log_path = f"/home/ec2-user/Option_Selling_Vikas/job_logs/job_option_selling_vikas_nifty_{datetime.now().strftime('%Y-%m-%d')}.txt"
        should_stop_ec2_on_exit = False
os.makedirs(os.path.dirname(log_path), exist_ok=True)

# 🔁 Use the holiday_location to build shared path
shared_utils_path = os.path.join(holiday_location, "common")
sys.path.append(shared_utils_path)
from get_cached_order_book import get_order_book
CACHE_FILE = os.path.join(shared_utils_path, "orderbook_cache.json")
LOCK_FILE = os.path.join(shared_utils_path, "orderbook_cache.lock")

# Configure logging
logging.basicConfig(
    filename=log_path,
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO
)
last_logged_time = 0
ltp_call_timestamps = deque()

#THE BELOW METHOD IS NOT USED ANYWHERE IN THE CODE, NEED TO CALL SUPPOSE EC2 EXIT REQD.
def trigger_ec2_shutdown_lambda():
    FUNCTION_NAME = "stopEC2Instance"
    INSTANCE_ID = "i-0bc461a1bc178f190"
    
    payload = {
        "instance_id": INSTANCE_ID
    }

    try:
        lambda_client = boto3.client("lambda", region_name="us-east-1")  # Adjust your region
        response = lambda_client.invoke(
            FunctionName=FUNCTION_NAME,
            InvocationType="Event",  # Async execution
            Payload=json.dumps(payload).encode('utf-8')
        )
        print("🛑 EC2 shutdown Lambda triggered successfully.")
    except Exception as e:
        print(f"⚠️ Failed to trigger Lambda: {e}")

def log_and_print(message, level="info"):
    print(message)
    if level == "info":
        logging.info(message)
    elif level == "error":
        logging.error(message)
    elif level == "warning":
        logging.warning(message)
    elif level == "debug":
        logging.debug(message)

def is_expiry_day():
    today = datetime.today()
    expiry_day = get_expiry_day()
    return today.date() == expiry_day.date()

def is_market_holiday(date_obj):
    holiday_file = holiday_location + "nifty_expiry_holidays.txt"
    try:
        with open(holiday_file, "r") as f:
            holidays = [line.strip() for line in f.readlines()]
    except FileNotFoundError:
        log_and_print(f"OPTION SELLING VIKAS NIFTY: Warning: {holiday_file} not found. Assuming no holidays.")
        return False
    date_str = date_obj.strftime("%d%b%y")
    return date_str in holidays or date_obj.weekday() in [5, 6]
    
def get_current_ist_time():
    return datetime.now(finland_tz).astimezone(india_tz)

def wait_until_ist(target_time):
    while True:
        now = get_current_ist_time()
        if now.strftime("%H:%M:%S") >= target_time:
            break
        time.sleep(1)

def login():
    """Logs in and generates authentication tokens."""
    try:
        global smart_api
        totp = pyotp.TOTP(TOTP_SECRET).now()
        session = smart_api.generateSession(CLIENT_CODE, PASSWORD, totp)
        if session.get("status") is True:
            refresh_token = session["data"]["refreshToken"]
            log_and_print("OPTION SELLING VIKAS NIFTY:✅ Login successful!")
        else:
            send_whatsapp_message("❌OPTION SELLING VIKAS NIFTY: Login failed:")
            log_and_print(f"OPTION SELLING VIKAS NIFTY:❌ Login failed: {session.get('message', 'Unknown error')}")
            raise Exception(f"❌ Login failed: {session.get('message', 'Unknown error')}")
    except Exception as e:
        log_and_print(f"OPTION SELLING VIKAS NIFTY:🔒 Inside Login() and exception is {e}")

"""
def send_whatsapp_message(message_body):
    recipients = [
        'whatsapp:+919042528367',  # Recipient 1
        'whatsapp:+918012991200'   # Recipient 2 (add as many as needed)
    ]
    try:
        message = client.messages.create(
            from_='whatsapp:+14155238886',  # Twilio sandbox number
            #to='whatsapp:+919042528367',
            to=recipients,  
            body=message_body
        )
        log_and_print(f"OPTION SELLING VIKAS NIFTY:WhatsApp Message Sent: {message_body}")
    except Exception as e:
        log_and_print(f"OPTION SELLING VIKAS NIFTY:Failed to send message: {e}")
"""
def send_whatsapp_message(message_body):
    """
    Sends a message using Telegram Bot API to multiple recipients.
    :param message_body: The message content to send.
    """
    try:
        for chat_id in RECIPIENT_CHAT_IDS:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message_body
            }
            response = requests.post(url, data=payload)
            if response.status_code == 200:
                log_and_print(f"Telegram Message Sent to {chat_id}: {message_body}")
            else:
                log_and_print(f"Failed to send Telegram message to {chat_id}: {response.text}")
    except Exception as e:
        log_and_print(f"Error sending Telegram message: {e}")

def is_logged_in(refresh_token):
    try:
        time.sleep(1)
        response = smart_api.getProfile(refresh_token)
        # If it returns data, assume logged in
        stat = response.get("status")
        #Disabling the below log and log_and_print to avoid multiple log_and_print statment in logs
        #log_and_print(f"Inside is_logged_in method and response is {stat}")
        return response.get("status") == True
    except Exception as e:
        log_and_print(f"OPTION SELLING VIKAS NIFTY:🔒 Session not active or error occurred: {e}")
        return False
"""
def get_expiry_day():
    today = datetime.today()
    holiday_file = holiday_location + "nifty_expiry_holidays.txt"
    holidays = []
    if os.path.exists(holiday_file):
        with open(holiday_file, "r") as file:
            holidays = [line.strip() for line in file.readlines()]
    # Find next Thursday (weekday = 3)
    days_ahead = (3 - today.weekday() + 7) % 7  # Thursday = 3
    expiry_day = today + timedelta(days=days_ahead)
    # Adjust expiry_day if it's a holiday or weekend
    while expiry_day.strftime("%d%b%y") in holidays or expiry_day.weekday() in [5, 6]:
        expiry_day -= timedelta(days=1)
    # Hardcoded skip: if expiry is 28-Aug-2025, replace with 04-Sep-2025
    if expiry_day.strftime("%d%b%y") == "28Aug25":
        expiry_day = datetime.strptime("04Sep25", "%d%b%y")
    return expiry_day
"""

def get_expiry_day():
    today = datetime.today()
    holiday_file = holiday_location + "nifty_expiry_holidays.txt"
    holidays = []
    if os.path.exists(holiday_file):
        with open(holiday_file, "r") as file:
            holidays = [line.strip() for line in file.readlines()]
    if today.weekday() == 1 and today.strftime("%d%b%y") not in holidays:
        expiry_day = today
    else:
        # Find next Tuesday (weekday = 1)
        days_ahead = (1 - today.weekday() + 7) % 7
        expiry_day = today + timedelta(days=days_ahead)
        # Adjust expiry_day if it's a holiday or falls on weekend
        while expiry_day.strftime("%d%b%y") in holidays or expiry_day.weekday() in [5, 6]:
            expiry_day -= timedelta(days=1)
    return expiry_day

def get_last_valid_expiry_of_month(expiry):
    year = expiry.year
    month = expiry.month
    last_day = calendar.monthrange(year, month)[1]
    thursdays = []
    skip_dates = ["28Aug25"]  # Explicitly skip this date
    for day in range(1, last_day + 1):
        date_obj = datetime(year, month, day)
        if date_obj.weekday() == 3:  # Thursday
            # Adjust if it's a holiday, weekend, or in skip_dates
            while is_market_holiday(date_obj) or date_obj.strftime("%d%b%y") in skip_dates or date_obj.weekday() in [5, 6]:
                date_obj -= timedelta(days=1)
            thursdays.append(date_obj)
    unique_expiries = sorted(set(thursdays))
    return unique_expiries[-1] if unique_expiries else expiry

def get_nifty_atm():
    """Fetches the nearest ATM strike price for NIFTY."""
    spot_data = smart_api.ltpData("NSE", "NIFTY", "26000")
    if spot_data.get("status") is True:
        return round(float(spot_data["data"]["ltp"]) / 50) * 50  # Round to nearest 50
    raise Exception("❌ Failed to get NIFTY ATM price!")

def get_sensex_atm():
    spot_data = smart_api.ltpData("BSE", "SENSEX", "99919000")  # "1" is usually the token for SENSEX
    if spot_data.get("status"):
        spot = float(spot_data["data"]["ltp"])
        return round(spot / 100) * 100
    raise Exception("❌ Failed to fetch SENSEX LTP")
"""
def build_symbols(atm, expiry):
    yy = expiry.strftime("%y")               # '25'
    dd = expiry.strftime("%d")               # '06'
    strike_str = str(atm)                    # '81300'
    last_expiry = get_last_valid_expiry_of_month(expiry)
    # AngelOne month code mapping (short form)
    month_map = {
        1:"J", 2:"F", 3:"M", 4:"A", 5:"Y", 6:"U",
        7:"L", 8:"G", 9:"S", 10:"O", 11:"N", 12:"D"
    }
    if expiry.date() == last_expiry.date():
        # Monthly format (still 3-letter month string)
        mon_str = expiry.strftime("%b").upper()  # 'MAY'
        base = f"SENSEX{yy}{mon_str}{strike_str}"
    else:
        # Weekly format → YY + MonthCode + DD
        month_code = month_map[int(expiry.strftime("%m"))]
        base = f"SENSEX{yy}{month_code}{dd}{strike_str}"
    print(f"{base}CE", f"{base}PE")
    return f"{base}CE", f"{base}PE"
"""

def build_symbols(strike_price, expiry_date):
    """Generate the symbol for NIFTY options based on the strike price and expiry date."""
    expiry_str = expiry_date.strftime("%d%b%y").upper()
    strike_str = str(strike_price).zfill(5)
    return f"NIFTY{expiry_str}{strike_str}CE", f"NIFTY{expiry_str}{strike_str}PE"

"""  
def get_token(symbol):
    res = smart_api.searchScrip("BFO", symbol)
    if res.get("status"):
        return res["data"][0]["symboltoken"]
    raise Exception(f"❌ Token not found for {symbol}")
"""

def get_token(symbol):
    """Fetches the symbol token for a given symbol."""
    try:
        search_response = smart_api.searchScrip("NFO", symbol)
        if search_response.get("status") is True:
            return search_response["data"][0]["symboltoken"]
        else:
         log_and_print(f"❌ Failed to get symbol token for {symbol} and exception is {e}")
         send_whatsapp_message(f"❌ Failed to get symbol token for {symbol} and exception is {e}")
         raise Exception(f"❌ Failed to get symbol token for {symbol} and exception is {e}")
    except Exception as e:
        log_and_print(f"❌ Failed to get symbol token for {symbol} and exception is {e}")
        send_whatsapp_message(f"❌ Failed to get symbol token for {symbol} and exception is {e}")
        raise Exception(f"❌ Failed to get symbol token for {symbol} and exception is {e}")

def get_ltp(symbol, symbol_token):
    """Fetches the LTP (Last Traded Price) for the given symbol using symbol token."""
    global last_logged_time
    
    try:
        #if not is_logged_in(refresh_token):
         #   log_and_print("Session expired, re-authenticating before square_off...")
         #   smart_api.terminateSession(CLIENT_CODE)
         #   login()
        current_time = time.time()
        ltp_call_timestamps.append(current_time)
        while ltp_call_timestamps and current_time - ltp_call_timestamps[0] > 60:
            ltp_call_timestamps.popleft()
        if current_time - last_logged_time >= 60:
            log_and_print(f"OPTION SELLING VIKAS NIFTY:🕒 LTP calls in last 60 seconds: {len(ltp_call_timestamps)}")
            last_logged_time = current_time
        time.sleep(0.5)
        #ltp_data = smart_api.ltpData("BFO", symbol, symbol_token)
        ltp_data = smart_api.ltpData("NFO", symbol, symbol_token)
        if ltp_data.get("status") is True:
            return float(ltp_data["data"]["ltp"])
        return None
    except Exception as e:
        log_and_print(f"OPTION SELLING VIKAS NIFTY:❌ Failed to get LTP for Symbol:{symbol} and Symbol Token:{symbol_token} and exception is {e} ")

def place_market_order(symbol, token):
        try:
            order = {
                "variety": "NORMAL",
                "tradingsymbol": symbol,
                "symboltoken": token,
                "transactiontype": "SELL",
                #"exchange": "BFO",
                "exchange": "NFO",
                "ordertype": "MARKET",
                "producttype": producttype,
                "duration": "DAY",
                "quantity": QTY
            }
            res = smart_api.placeOrder(order)
            if res:
                return res
        except Exception as e:
            log_and_print(f"OPTION SELLING VIKAS NIFTY:❌ Order failed for {symbol}: {e}")
            send_whatsapp_message(f"❌ OPTION SELLING VIKAS NIFTY: Order failed for {symbol}: {e}")
        return None

def emergency_exit(symbol, token):
        try:
            order = {
                "variety": "NORMAL",
                "tradingsymbol": symbol,
                "symboltoken": token,
                "transactiontype": "BUY",
                #"exchange": "BFO",
                "exchange": "NFO",
                "ordertype": "MARKET",
                "producttype": producttype,
                "duration": "DAY",
                "quantity": QTY
            }
            smart_api.placeOrder(order)
        except Exception as e:
            log_and_print(f"❌OPTION SELLING VIKAS NIFTY: Emergency Exit Order failed for {symbol}: {e}")
            send_whatsapp_message(f"❌ OPTION SELLING VIKAS NIFTY:Emergency Exit Order failed for {symbol}: {e}")
        return None

def place_sl_order(symbol, token, sl_price):
    try:
        order = {
            "variety": "STOPLOSS",
            "tradingsymbol": symbol,
            "symboltoken": token,
            "transactiontype": "BUY",
            #"exchange": "BFO",
            "exchange": "NFO",
            "ordertype": "STOPLOSS_LIMIT",
            "producttype": producttype,
            "duration": "DAY",
            "price": sl_price,
            "triggerprice": sl_price,
            "quantity": QTY
        }
        order_response = smart_api.placeOrder(order)
        log_and_print(f"OPTION SELLING VIKAS NIFTY:🔐 SL order placed for {symbol} at {sl_price} and the SL order number is {order_response}")
        return order_response
    except Exception as e:
        log_and_print(f"OPTION SELLING VIKAS NIFTY:❌ SL order failed for {symbol}: {e}")
        send_whatsapp_message(f"❌ OPTION SELLING VIKAS NIFTY:(PLACE SL QUICKLY) SL order failed for {symbol} and SL PRICE IS : {sl_price} and Exception is: {e}")
        return None

def cancel_order(order_id):
    """Cancel the order by its order ID with retries and status checking."""
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        log_and_print(f"OPTION SELLING VIKAS NIFTY:🔁 Attempt {attempt} to cancel order {order_id}")
        try:
            cancel_response = smart_api.cancelOrder(str(order_id), "STOPLOSS")
            log_and_print(f"OPTION SELLING VIKAS NIFTY:❌ Cancel attempt {attempt} made for order {order_id}")
        except Exception as e:
            log_and_print(f"OPTION SELLING VIKAS NIFTY:⚠️ Attempt {attempt} failed to cancel order {order_id}: {e}")
            cancel_response = None
        # Check if cancellation succeeded
        time.sleep(1)
        current_status = get_order_status_from_book(order_id)
        log_and_print(f"OPTION SELLING VIKAS NIFTY:📘 Order {order_id} status after attempt {attempt}: {current_status}")
        if current_status.upper() in ["CANCELLED", "REJECTED", "COMPLETE"]:
            log_and_print(f"OPTION SELLING VIKAS NIFTY:✅ Order {order_id} is in final state: {current_status}. Stopping attempts.")
            return cancel_response
        # Optional: wait briefly before next retry
        time.sleep(1)
    log_and_print(f"OPTION SELLING VIKAS NIFTY:❌ Failed to cancel order {order_id} after {max_attempts} attempts.")
    return None

def square_off(symbol, token, order_id):
    try:
        time.sleep(1)
        order_status = get_order_book(smart_api,CACHE_FILE,LOCK_FILE)
        sl_hit = is_order_executed(order_id)
        log_and_print(f"KANI:The sl_hit for {symbol} token:{token} and {order_id}is {sl_hit}")
        if not sl_hit:
            # Place BUY to square off
            cancel_order(order_id)
            log_and_print(f"KANI:Looks like we cancelled the order id : {order_id}. Here is the status : {get_order_status_from_book(order_id)}")
            time.sleep(1)
            order = {
                "variety": "NORMAL",
                "tradingsymbol": symbol,
                "symboltoken": token,
                "transactiontype": "BUY",
                #"exchange": "BFO",
                "exchange": "NFO",
                "ordertype": "MARKET",
                "producttype": producttype,
                "duration": "DAY",
                "quantity": QTY
            }
            square_order = smart_api.placeOrder(order)
            log_and_print(f"OPTION SELLING VIKAS NIFTY:✅ Squared off {symbol} and square off order :{square_order} status is {get_order_status_from_book(square_order)}")
        else:
            log_and_print(f"OPTION SELLING VIKAS NIFTY:🛑 SL already hit for {symbol}, skipping square off")
    except Exception as e:
        log_and_print(f"OPTION SELLING VIKAS NIFTY:❌ Error while squaring off {symbol}: {e}")
        send_whatsapp_message(f"❌ OPTION SELLING VIKAS NIFTY :(DO MANUALLY!) : Error while squaring off {symbol}: {e}")

def get_order_entry_price(order_id):
    """Fetch the exact executed price for a specific order ID."""
    try:
        time.sleep(1)
        all_orders = get_order_book(smart_api, CACHE_FILE, LOCK_FILE)  # Get the list of all today's orders
        if all_orders.get("status"):
            orders = all_orders["data"]
            for order in orders:
                if str(order.get("orderid")) == str(order_id):
                    status = order.get("orderstatus", "").strip().lower()
                    if status == "complete":
                        executed_price = float(order.get("averageprice"))
                        return executed_price
                    else:
                        log_and_print(f"OPTION SELLING VIKAS NIFTY:⚠️ Order ID {order_id} is not fully complete yet. Status: {order.get('orderstatus')}")
                        return None
            log_and_print(f"OPTION SELLING VIKAS NIFTY:⚠️ Order ID {order_id} not found in order book.")
        else:
            log_and_print("OPTION SELLING VIKAS NIFTY:⚠️ No order data received from orderBook()")
    except Exception as e:
        log_and_print(f"OPTION SELLING VIKAS NIFTY:❌ Failed to fetch executed price for order ID {order_id}: {e}")
        send_whatsapp_message(f"❌OPTION SELLING VIKAS NIFTY: Failed to fetch executed price for order ID {order_id}: {e}")
    return None


def is_order_executed(order_id):
    try:
        order_details = get_order_book(smart_api, CACHE_FILE, LOCK_FILE)
        log_and_print(f"OPTION SELLING VIKAS NIFTY:Checking if Order ID:{order_id} got executed")
        for order in order_details.get("data", []):
            if str(order.get("orderid")) == str(order_id):
                status = order.get("orderstatus", "").strip().lower()
                return status == "complete"
        log_and_print(f"OPTION SELLING VIKAS NIFTY: Order ID {order_id} not found in order book.")
        return False
    except Exception as e:
        log_and_print(f"❌OPTION SELLING VIKAS NIFTY:Exception in is_order_executed: {e}")
        return False

def get_order_status_from_book(order_id):
    """
    Fetch order status from Angel One order book.
    Returns the order status as a string or "UNKNOWN" if not found.
    """
    try:
        order_book = get_order_book(smart_api, CACHE_FILE, LOCK_FILE)  # Fetch all orders     
        if order_book and order_book.get("data"):  # Ensure we have valid data
            for order in order_book["data"]:  # Loop through orders
                if str(order.get("orderid")) == str(order_id):
                    return order.get("status", "UNKNOWN")  # Return status if found                
        log_and_print(f"⚠️ Order ID {order_id} not found in order book.")
    except Exception as e:
        log_and_print(f"❌ Error fetching status for order ID {order_id}: {e}")
        send_whatsapp_message(f"Error fetching status for order ID {order_id}: {e}")
    return "UNKNOWN"  # Default if order is not found or exception occurs


def execute_trade_block(ce_symbol, pe_symbol, ce_token, pe_token, risk_pct):

    ce_order_id = place_market_order(ce_symbol, ce_token)
    #log_and_print(f"OPTION SELLING VIKAS NIFTY:ce_order_id is {ce_order_id}")
    time.sleep(5)
    pe_order_id = place_market_order(pe_symbol, pe_token)
    #log_and_print(f"OPTION SELLING VIKAS NIFTY:pe_order_id is {pe_order_id}")
    time.sleep(5)
    if is_order_executed(ce_order_id) and is_order_executed(pe_order_id):

        ce_entry_price = get_order_entry_price(ce_order_id)
        pe_entry_price = get_order_entry_price(pe_order_id)
        
        if ce_entry_price is None or pe_entry_price is None:
            log_and_print("OPTION SELLING VIKAS NIFTY:❌ Failed to get entry prices. Exiting...")
            return
        
        ce_sl = round(ce_entry_price * (1 + risk_pct), 1)
        pe_sl = round(pe_entry_price * (1 + risk_pct), 1)
        
        ce_sl_order_id = place_sl_order(ce_symbol, ce_token, ce_sl)
        pe_sl_order_id = place_sl_order(pe_symbol, pe_token, pe_sl)
        
        return ce_sl_order_id, pe_sl_order_id
    
    else:
        if ce_order_id:
            if is_order_executed(ce_order_id):
                emergency_exit(ce_symbol,ce_token)
            else:
                cancel_order(ce_order_id)
        if pe_order_id:
            if is_order_executed(pe_order_id):
                emergency_exit(pe_symbol,pe_token)
            else:
                cancel_order(pe_order_id)
        send_whatsapp_message(f"OPTION SELLING VIKAS NIFTY: UNABLE TO PLACE MARKET ORDER and TRIGGERED EMERGENCY EXIT")
        raise Exception(f"OPTION SELLING VIKAS NIFTY: UNABLE TO PLACE MARKET ORDER AND TRIGGERED EMERGENCY EXIT")
        return None 

# ---------- STRATEGY WRAPPER ----------
def run_os_strategy():
    try:
        ce_sl_order_1430 = None
        pe_sl_order_1430 = None
        ce_sl_order_1043 = None
        pe_sl_order_1043 = None
        reentered = False
        login()
        expiry = get_expiry_day()
        log_and_print(expiry)
        global QTY
        if is_expiry_day():
            QTY = EXP_QTY
            log_and_print(f"OPTION SELLING VIKAS NIFTY:📉 Today is expiry. Quantity set to EXP_QTY: {QTY}")
            log_and_print("Exiting the NIFTY script since today is expiry")
            sys.exit(0)
        else:
            log_and_print(f"OPTION SELLING VIKAS NIFTY:📈 Today is not expiry. Quantity remains as QTY: {QTY}")
        log_and_print("OPTION SELLING VIKAS NIFTY:Now we have to wait till 09.18:56 AM")
        wait_until_ist("09:18:56")
        #atm_strike = get_sensex_atm()
        atm_strike = get_nifty_atm()
        log_and_print(atm_strike)
        ce_symbol, pe_symbol = build_symbols(atm_strike, expiry)
        ce_token = get_token(ce_symbol)
        time.sleep(1)
        pe_token = get_token(pe_symbol)
        ce_sl_order_1043, pe_sl_order_1043 = execute_trade_block(ce_symbol, pe_symbol, ce_token, pe_token, RISK_1043)
        log_and_print(f"KANI:The CE sl order id is {ce_sl_order_1043} and PE sl order id is {pe_sl_order_1043}")
        send_whatsapp_message("OPTION SELLING VIKAS NIFTY: STRATEGY ORDER PLACED ALONG WITH SL. PLEASE CHECK ONCE MANUALLY IF SL ORDER IS IN PENDING STATE")
        while get_current_ist_time().strftime("%H:%M") < "14:59":
            tim = get_current_ist_time().strftime("%H:%M")
            time.sleep(30)
            #RE-ENTER THE TRADE IF BOTH SIDE SL HIT
            if is_order_executed(ce_sl_order_1043) and is_order_executed(pe_sl_order_1043):
                if not reentered and auto_reentry:
                    if get_current_ist_time().strftime("%H:%M") < "13:00":
                        log_and_print("OPTION SELLING VIKAS NIFTY:⚠️ Both SL hit, Re-logging & re-entering trade before 13:00...")
                        login()
                        #atm_strike = get_sensex_atm()
                        atm_strike = get_nifty_atm()
                        ce_symbol_reentry, pe_symbol_reentry = build_symbols(atm_strike, expiry)
                        ce_token_reentry = get_token(ce_symbol_reentry)
                        time.sleep(1)
                        pe_token_reentry = get_token(pe_symbol_reentry)
                        ce_sl_order_1430, pe_sl_order_1430 = execute_trade_block(ce_symbol_reentry, pe_symbol_reentry, ce_token_reentry, pe_token_reentry, RISK_1043)
                        reentered = True
                        log_and_print(f"OPTION SELLING VIKAS NIFTY: STRATEGY RE-ENTRY AT {tim}")
                        send_whatsapp_message(f"OPTION SELLING VIKAS NIFTY: STRATEGY RE-ENTRY PLACED AT {tim}")
                elif not auto_reentry:
                    log_and_print(f"OPTION SELLING VIKAS NIFTY:🚫 EARLY EXIT at {tim} :Double Side SL hit. Re-entry not allowed.Do Manual action incase required.")
                    send_whatsapp_message(f"OPTION SELLING VIKAS NIFTY:🚫 EARLY EXIT at {tim} ->  Double Side SL hit. Re-entry not allowed.Do Manual action incase required.")
                    return
                elif reentered:
                    if is_order_executed(ce_sl_order_1430) and is_order_executed(pe_sl_order_1430):
                        log_and_print(f"OPTION SELLING VIKAS NIFTY:🚫 Exiting early at {tim}... 4 side SL hit even after re-entry. No more trades.")
                        send_whatsapp_message(f"OPTION SELLING VIKAS NIFTY:🚫 EARLY EXIT at {tim} -> 4 side SL hit even after re-entry. No more trades.")
                        return
        log_and_print("OPTION SELLING VIKAS NIFTY:Session might have expired, re-logging before square_off...")
        login()
        log_and_print(f"KANI:Trying to square of CE SL order:{ce_sl_order_1043}")
        square_off(ce_symbol, ce_token, ce_sl_order_1043)
        log_and_print(f"KANI:Trying to square of PE SL order:{pe_sl_order_1043}")
        square_off(pe_symbol, pe_token, pe_sl_order_1043)
        if reentered:
            square_off(ce_symbol_reentry, ce_token_reentry, ce_sl_order_1430)
            square_off(pe_symbol_reentry, pe_token_reentry, pe_sl_order_1430)        
        log_and_print("OPTION SELLING VIKAS NIFTY:✅ All positions checked and squared off (if needed)")
        send_whatsapp_message("✅OPTION SELLING VIKAS NIFTY: All positions checked and squared off (if needed)")

    except Exception as e:
        log_and_print(f"OPTION SELLING VIKAS NIFTY:❌ Error: {e}")
        send_whatsapp_message(f"OPTION SELLING VIKAS NIFTY:❌ Error: {e}")

# To run it directly:
if __name__ == "__main__":
    try:
        log_and_print(f"OPTION SELLING VIKAS NIFTY:job is running on {system_platform}")
        current_date = datetime.today()
        if is_market_holiday(current_date):
            send_whatsapp_message(f"🔔:OPTION SELLING VIKAS NIFTY: Market holiday on {current_date}. Exiting script.")
            log_and_print("OPTION SELLING VIKAS NIFTY:Market holiday today. Exiting script.")
        else:
            log_and_print("OPTION SELLING VIKAS NIFTY:📈Running regular strategy...")
            run_os_strategy()  # Call the normal strategy
    except Exception as e:
        log_and_print(f"OPTION SELLING VIKAS NIFTY:❌ Exception in trading script: {str(e)}")
        send_whatsapp_message(f"❌ OPTION SELLING VIKAS NIFTY: Exception in trading script: {str(e)}")
    finally:
        log_and_print ("❌ OPTION SELLING VIKAS NIFTY:Logging out inside finally")
        send_whatsapp_message(f"❌ OPTION SELLING VIKAS NIFTY:Executing Finally Block")
        smart_api.terminateSession(CLIENT_CODE)
