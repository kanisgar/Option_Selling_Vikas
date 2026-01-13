#!/usr/bin/env python3

import os
import sys
import platform
import subprocess
from datetime import datetime
import getpass
import logging

# ----------------------------------
# PLATFORM & PATH RESOLUTION (AS GIVEN)
# ----------------------------------
system_platform = platform.system()
current_user = getpass.getuser()

if system_platform == "Windows":
    holiday_location = "C:\\Kani_Personal\\Automate_Trading\\Option_Selling_Vikas\\"
    base_script_path = "C:/Kani_Personal/Automate_Trading/Option_Selling_Vikas"
    log_path = f"C:/Kani_Personal/Automate_Trading/Option_Selling_Vikas/job_logs/job_run_trading_{datetime.now().strftime('%Y-%m-%d')}.txt"
    PYTHON = "python"

elif system_platform == "Darwin":
    holiday_location = "/Users/kanisgar/Documents/Option_Selling_Vikas/"
    base_script_path = "/Users/kanisgar/Documents/Option_Selling_Vikas"
    log_path = f"/Users/kanisgar/Documents/Option_Selling_Vikas/job_logs/job_run_trading_{datetime.now().strftime('%Y-%m-%d')}.txt"
    PYTHON = "/usr/bin/python3"

elif system_platform == "Linux":
    if current_user == "ec2-user":
        holiday_location = "/home/ec2-user/Option_Selling_Vikas/"
        base_script_path = "/home/ec2-user/Option_Selling_Vikas"
        log_path = f"/home/ec2-user/Option_Selling_Vikas/job_logs/job_run_trading_{datetime.now().strftime('%Y-%m-%d')}.txt"
        PYTHON = "/usr/bin/python3"
    else:
        print("Unsupported Linux user")
        sys.exit(1)

else:
    print(f"Unsupported platform: {system_platform}")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    filename=log_path,
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO
)

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

# ----------------------------------
# SCRIPT PATHS
# ----------------------------------
NIFTY_SCRIPT = os.path.join(base_script_path, "option_selling_vikas_nifty.py")
SENSEX_SCRIPT = os.path.join(base_script_path, "option_selling_vikas.py")

# ----------------------------------
# IMPORT EXPIRY LOGIC FROM SCRIPTS
# ----------------------------------
sys.path.append(base_script_path)

from option_selling_vikas_nifty import is_expiry_day as is_nifty_expiry
from option_selling_vikas import is_expiry_day as is_sensex_expiry


def run(script_path):
    log_and_print(f"🚀 Running: {script_path}")
    subprocess.run([PYTHON, script_path], check=True)


def main():
    weekday = datetime.today().weekday()  # MON=0 ... SUN=6

    nifty_expiry = is_nifty_expiry()
    sensex_expiry = is_sensex_expiry()

    # ----------------------------------
    # DEFAULT DAY MAPPING
    # ----------------------------------
    if weekday in [0, 3, 4]:        # MON, THU, FRI
        default = "NIFTY"
    elif weekday in [1, 2]:         # TUE, WED
        default = "SENSEX"
    else:
        log_and_print("Weekend. No trades.")
        return

    # ----------------------------------
    # EXPIRY OVERRIDE LOGIC
    # ----------------------------------
    if default == "NIFTY" and nifty_expiry:
        log_and_print("⚠️ NIFTY expiry today → Switching to SENSEX")
        run(SENSEX_SCRIPT)
        return

    if default == "SENSEX" and sensex_expiry:
        log_and_print("⚠️ SENSEX expiry today → Switching to NIFTY")
        run(NIFTY_SCRIPT)
        return

    # ----------------------------------
    # NORMAL EXECUTION
    # ----------------------------------
    if default == "NIFTY":
        run(NIFTY_SCRIPT)
    else:
        run(SENSEX_SCRIPT)


if __name__ == "__main__":
    main()
