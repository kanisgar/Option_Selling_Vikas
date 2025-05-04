import time
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
QTY = 20  # Adjust based on your margin/lot

# Initialize SmartConnect
smart_api = SmartConnect(api_key=API_KEY)

#Intialize Twilio
client = Client(account_sid, auth_token)

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
    log_path = f"C:/Kani_Personal/Automate_Trading/Option_Selling_Vikas/job_logs/job_option_selling_vikas_{datetime.now().strftime('%Y-%m-%d')}.txt"

elif system_platform == "Darwin":  # Mac
    holiday_location = "/Users/kanisgar/Documents/AlgoTrading/"
    log_path = f"/Users/kanisgar/Documents/Option_Selling_Vikas/job_logs/job_option_selling_vikas_{datetime.now().strftime('%Y-%m-%d')}.txt"

elif system_platform == "Linux":
    if current_user == "ec2-user":
        holiday_location = "/home/ec2-user/AlgoTrading/"
        log_path = f"/home/ec2-user/Option_Selling_Vikas/job_logs/job_option_selling_vikas_{datetime.now().strftime('%Y-%m-%d')}.txt"
        should_stop_ec2_on_exit = True
os.makedirs(os.path.dirname(log_path), exist_ok=True)

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

def is_market_holiday():
    holiday_file = holiday_location + "nifty_expiry_holidays.txt"  
    try:
        with open(holiday_file, "r") as f:
            holidays = [line.strip() for line in f.readlines()]
    except FileNotFoundError:
        log_and_print(f"Warning: {holiday_file} not found. Assuming no holidays.")
        return False
    today = datetime.today().strftime("%d%b%y")  # Format like 26Feb25
    return today in holidays
    
def get_current_ist_time():
    return datetime.now(finland_tz).astimezone(india_tz)

def wait_until_ist(target_time):
    while True:
        now = get_current_ist_time()
        if now.strftime("%H:%M") >= target_time:
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
            log_and_print("✅ Login successful!")
        else:
            send_whatsapp_message("❌ Login failed:")
            log_and_print(f"❌ Login failed: {session.get('message', 'Unknown error')}")
            raise Exception(f"❌ Login failed: {session.get('message', 'Unknown error')}")
    except Exception as e:
        log_and_print(f"🔒 Inside Login() and exception is {e}")

def send_whatsapp_message(message_body):
    """
    Sends a WhatsApp message using Twilio API.
    :param message_body: The message content to send.
    """
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
        log_and_print(f"WhatsApp Message Sent: {message_body}")
    except Exception as e:
        log_and_print(f"Failed to send message: {e}")

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
        log_and_print(f"🔒 Session not active or error occurred: {e}")
        return False

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
        # Find next Tuesday (weekday = 3)
        days_ahead = (1 - today.weekday() + 7) % 7
        expiry_day = today + timedelta(days=days_ahead)
        # Adjust expiry_day if it's a holiday or falls on weekend
        while expiry_day.strftime("%d%b%y") in holidays or expiry_day.weekday() in [5, 6]:
            expiry_day -= timedelta(days=1)
    return expiry_day

def get_nifty_atm():
    spot_data = smart_api.ltpData("NSE", "NIFTY", "26000")
    if spot_data.get("status"):
        spot = float(spot_data["data"]["ltp"])
        return round(spot / 50) * 50
    raise Exception("❌ Failed to fetch NIFTY LTP")

def get_sensex_atm():
    spot_data = smart_api.ltpData("BSE", "SENSEX", "99919000")  # "1" is usually the token for SENSEX
    if spot_data.get("status"):
        spot = float(spot_data["data"]["ltp"])
        return round(spot / 100) * 100
    raise Exception("❌ Failed to fetch SENSEX LTP")

def build_symbols(atm, expiry):
    yy = expiry.strftime("%y")               # '25'
    m = str(int(expiry.strftime("%m")))      # '5' (no leading zero)
    dd = expiry.strftime("%d")               # '06'
    strike_str = str(atm)                    # e.g., '82000'
    base = f"SENSEX{yy}{m}{dd}{strike_str}"
    print(f"{base}CE", f"{base}PE")
    return f"{base}CE", f"{base}PE"
    
def get_token(symbol):
    res = smart_api.searchScrip("BFO", symbol)
    if res.get("status"):
        return res["data"][0]["symboltoken"]
    raise Exception(f"❌ Token not found for {symbol}")

def get_ltp(symbol, symbol_token):
    """Fetches the LTP (Last Traded Price) for the given symbol using symbol token."""
    global last_logged_time
    
    try:
        #if not is_logged_in(refresh_token):
         #   log_and_print("Session expired, re-authenticating before square-off...")
         #   smart_api.terminateSession(CLIENT_CODE)
         #   login()
        current_time = time.time()
        ltp_call_timestamps.append(current_time)
        while ltp_call_timestamps and current_time - ltp_call_timestamps[0] > 60:
            ltp_call_timestamps.popleft()
        if current_time - last_logged_time >= 60:
            log_and_print(f"🕒 LTP calls in last 60 seconds: {len(ltp_call_timestamps)}")
            last_logged_time = current_time
        time.sleep(0.5)
        ltp_data = smart_api.ltpData("BFO", symbol, symbol_token)
        if ltp_data.get("status") is True:
            return float(ltp_data["data"]["ltp"])
        return None
    except Exception as e:
        log_and_print(f"❌ Failed to get LTP for Symbol:{symbol} and Symbol Token:{symbol_token} and exception is {e} ")

def place_market_order(symbol, token):
        try:
            order = {
                "variety": "NORMAL",
                "tradingsymbol": symbol,
                "symboltoken": token,
                "transactiontype": "SELL",
                "exchange": "BFO",
                "ordertype": "MARKET",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "quantity": QTY
            }
            res = smart_api.placeOrder(order)
            if res.get("status"):
                return res["data"]["orderid"]
        except Exception as e:
            log_and_print(f"❌ Order failed for {symbol}: {e}")
            send_whatsapp_message(f"❌ OPTION SELLING VIKAS: Order failed for {symbol}: {e}")
        return None

def place_sl_order(symbol, token, sl_price):
    try:
        order = {
            "variety": "STOPLOSS",
            "tradingsymbol": symbol,
            "symboltoken": token,
            "transactiontype": "BUY",
            "exchange": "BFO",
            "ordertype": "STOPLOSS_LIMIT",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": sl_price,
            "triggerprice": sl_price,
            "quantity": QTY
        }
        smart_api.placeOrder(order)
        log_and_print(f"🔐 SL order placed for {symbol} at {sl_price}")
    except Exception as e:
        log_and_print(f"❌ SL order failed for {symbol}: {e}")
        send_whatsapp_message(f"❌ OPTION SELLING VIKAS:(PLACE SL QUICKLY) SL order failed for {symbol} and SL PRICE IS : {slprice} and Exception is: {e}")

def cancel_order(order_id):
    """Cancel the order by its order ID."""
    try:
        cancel_response = smart_api.cancelOrder(str(order_id), "STOPLOSS")
        return cancel_response
    except Exception as e:
        #send_whatsapp_message(f"❌ DO MANUALLY; Failed to cancel order {order_id}: {e}")
        log_and_print(f"❌ Failed to cancel order {order_id}: {e}")
        return None

def square_off(symbol, token, order_id):
    try:
        order_status = smart_api.orderBook()
        sl_hit = any(order.get("orderid") == order_id and order.get("status") == "complete"
                     for order in order_status.get("data", []))

        if not sl_hit:
            # Place BUY to square off
            cancel_order(smart_api, order_id)
            order = {
                "variety": "NORMAL",
                "tradingsymbol": symbol,
                "symboltoken": token,
                "transactiontype": "BUY",
                "exchange": "BFO",
                "ordertype": "MARKET",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "quantity": QTY
            }
            smart_api.placeOrder(order)
            log_and_print(f"✅ Squared off {symbol}")
        else:
            log_and_print(f"🛑 SL already hit for {symbol}, skipping square off")
    except Exception as e:
        log_and_print(f"❌ Error while squaring off {symbol}: {e}")
        send_whatsapp_message(f"❌ OPTION SELLING VIKAS :(DO MANUALLY!) : Error while squaring off {symbol}: {e}")

def get_order_entry_price(order_id):
    """Fetch the exact executed price for a specific order ID."""
    try:
        all_orders = smart_api.orderBook()  # Get the list of all today's orders
        if all_orders.get("status"):
            orders = all_orders["data"]
            for order in orders:
                if order.get("orderid") == order_id:
                    if order.get("orderstatus").lower() == "complete":
                        executed_price = float(order.get("averageprice"))
                        return executed_price
                    else:
                        log_and_print(f"⚠️ Order ID {order_id} is not fully complete yet. Status: {order.get('orderstatus')}")
                        return None
        else:
            log_and_print("⚠️ No order data received from orderBook()")
    except Exception as e:
        log_and_print(f"❌ Failed to fetch executed price for order ID {order_id}: {e}")
        send_whatsapp_message(f"❌OPTION SELLING VIKAS: Failed to fetch executed price for order ID {order_id}: {e}")
    return None

def is_order_executed(order_id):
    try:
        order_details = smart_api.orderBook()
        for order in order_details.get("data", []):
            if order["orderid"] == order_id and order["status"].lower() == "complete":
                return True
    except Exception as e:
        log_and_print(f"❌ Failed to check order status for {order_id}: {e}")
    return False



def execute_trade_block(ce_symbol, pe_symbol, ce_token, pe_token, risk_pct):

    ce_order_id = place_market_order(ce_symbol, ce_token)
    pe_order_id = place_market_order(pe_symbol, pe_token)

    ce_ltp = get_order_entry_price(ce_order_id)
    pe_ltp = get_order_entry_price(pe_order_id)
    
    if ce_entry_price is None or pe_entry_price is None:
        log_and_print("❌ Failed to get entry prices. Exiting...")
        return

    ce_sl = round(ce_ltp * (1 + risk_pct), 1)
    pe_sl = round(pe_ltp * (1 + risk_pct), 1)

    ce_sl_order_id = place_sl_order(ce_symbol, ce_token, ce_sl)
    pe_sl_order_id = place_sl_order(pe_symbol, pe_token, pe_sl)

    return ce_sl_order_id, pe_sl_order_id

def execute_expiry_trade_block(ce_symbol, pe_symbol, ce_token, pe_token, risk_pct):

    # Place ATM CE and PE orders
    ce_order_id = place_market_order(ce_symbol, ce_token)
    pe_order_id = place_market_order(pe_symbol, pe_token)

    # Fetch entry prices for the placed orders
    ce_entry_price = get_order_entry_price(ce_order_id)
    pe_entry_price = get_order_entry_price(pe_order_id)

    if ce_entry_price is None or pe_entry_price is None:
        log_and_print("❌ Failed to get entry prices. Exiting...")
        return

    # Calculate stop-loss based on the entry price
    ce_sl = round(ce_entry_price * (1 + risk_pct), 1)
    pe_sl = round(pe_entry_price * (1 + risk_pct), 1)

    # Place stop-loss orders for the ATM CE and PE
    ce_sl_order_id = place_sl_order(ce_symbol, ce_token, ce_sl)
    pe_sl_order_id = place_sl_order(pe_symbol, pe_token, pe_sl)
    return ce_sl_order_id, pe_sl_order_id

# ---------- STRATEGY WRAPPER ----------
def run_os_strategy():
    try:
        login()
        expiry = get_expiry_day()
        print(expiry)
        #wait_until_ist("09:18")
        atm_strike = get_sensex_atm()
        print(atm_strike)
        ce_symbol, pe_symbol = build_symbols(atm_strike, expiry)
        ce_token = get_token(ce_symbol)
        time.sleep(1)
        pe_token = get_token(pe_symbol)
        log_and_print("Now we have to wait till 09.19 AM")
        wait_until_ist("09:19")
        ce_sl_order_1043, pe_sl_order_1043 = execute_trade_block(ce_symbol, pe_symbol, ce_token, pe_token, RISK_1043)
        send_whatsapp_message("OPTION SELLING VIKAS: STRATEGY ORDER PLACED")
        ce_sl_order_1430, pe_sl_order_1430 = None
        reentered = False
        while get_current_ist_time().strftime("%H:%M") < "14:59":
            tim = get_current_ist_time().strftime("%H:%M")
            time.sleep(30)
            #RE-ENTER THE TRADE IF BOTH SIDE SL HIT
            if not reentered and is_order_executed(ce_sl_order_1043) and is_order_executed(pe_sl_order_1043):
                if get_current_ist_time().strftime("%H:%M") < "14:15":
                    log_and_print("⚠️ Both SL hit, re-entering trade before 14:15...")
                    atm_strike = get_sensex_atm()
                    ce_symbol, pe_symbol = build_symbols(atm_strike, expiry)
                    ce_token = get_token(ce_symbol)
                    time.sleep(1)
                    pe_token = get_token(pe_symbol)
                    ce_sl_order_1430, pe_sl_order_1430 = execute_trade_block(ce_symbol, pe_symbol, ce_token, pe_token, RISK_1043)
                    reentered = True
                    log_and_print(f"OPTION SELLING VIKAS: STRATEGY RE-ENTRY AT {tim}")
                    send_whatsapp_message(f"OPTION SELLING VIKAS: STRATEGY RE-ENTRY PLACED AT {tim}")
        if not is_logged_in(refresh_token, smart_api):
            log_and_print("Session expired, re-authenticating before square-off...")
            smart_api = login()  
        square_off(ce_symbol, ce_token, ce_sl_order_1043)
        square_off(pe_symbol, pe_token, pe_sl_order_1043)
        if reentered:
            square_off(ce_symbol, ce_token, ce_sl_order_1430)
            square_off(pe_symbol, pe_token, pe_sl_order_1430)        
        log_and_print("✅ All positions checked and squared off (if needed)")
        send_whatsapp_message("✅Option Selling Vikas: All positions checked and squared off (if needed)")

    except Exception as e:
        log_and_print(f"❌ Error: {e}")
        send_whatsapp_message(f"Option Selling Vikas:❌ Error: {e}")

# To run it directly:
if __name__ == "__main__":
    try:
        log_and_print(f"job is running on {system_platform}")
        if is_market_holiday():
            send_whatsapp_message(f"🔔:Option Selling Vikas: Market holiday on {current_date}. Exiting script.")
            log_and_print("Market holiday today. Exiting script.")
        else:
            log_and_print("📈Running regular strategy...")
            run_os_strategy()  # Call the normal strategy
    except Exception as e:
        log_and_print(f"❌ Exception in trading script: {str(e)}")
        send_whatsapp_message(f"❌ Option Selling Vikas: Exception in trading script: {str(e)}")
    finally:
        log_and_print ("OS:Logging out inside finally")
        smart_api.terminateSession(CLIENT_CODE)
