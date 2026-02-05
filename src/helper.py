import os
import time
import json
import random
import logging
from functools import wraps
from pymongo import MongoClient
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support import expected_conditions as EC

# ----------------------------
# Load environment variables
# ----------------------------
load_dotenv(dotenv_path='./environment/.env')

TIMEOUT = int(os.getenv("TIMEOUT", 10))
TRIES = int(os.getenv("TRIES", 3))
DELAY = float(os.getenv("DELAY", 2))

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")

# ----------------------------
# Setup Logging
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("./log/scraping.log")]
)

# ----------------------------
# Retry Decorator
# ----------------------------
def retry(ExceptionToCheck, tries=TRIES, delay=DELAY):
    def deco_retry(f):
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 0:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    logging.warning(f"Retrying after exception: {type(e).__name__}")
                    time.sleep(mdelay)
                    mtries -= 1
            logging.error(f"Failed after {tries} attempts.")
            return None
        return f_retry
    return deco_retry

# ----------------------------
# Selenium Utilities
# ----------------------------
@retry((NoSuchElementException, TimeoutException))
def wait_element(driver, by, element, timeout=TIMEOUT):
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, element))
    )

@retry((NoSuchElementException, TimeoutException))
def get_object(driver, by, element, timeout=TIMEOUT):
    wait_element(driver, by, element, timeout)
    return driver.find_element(by, element)

@retry((NoSuchElementException, TimeoutException))
def get_objects(driver, by, element, timeout=TIMEOUT):
    wait_element(driver, by, element, timeout)
    return driver.find_elements(by, element)

@retry((NoSuchElementException, TimeoutException))
def extract_elements(driver, by, element, multiple=False, attribute=None, timeout=TIMEOUT):
    elems = get_objects(driver, by, element, timeout) if multiple else [get_object(driver, by, element, timeout)]
    if attribute:
        return [el.get_attribute(attribute) for el in elems] if multiple else elems[0].get_attribute(attribute)
    return [el.text.strip() for el in elems] if multiple else elems[0].text.strip()

# ----------------------------
# Browser / Login
# ----------------------------
@retry((NoSuchElementException, TimeoutException))
def login(driver):
    driver.get("https://www.linkedin.com/login")
    get_object(driver, By.ID, "username").send_keys(EMAIL)
    get_object(driver, By.ID, "password").send_keys(PASSWORD)
    get_object(driver, By.CLASS_NAME, "btn__primary--large").click()
    logging.info("Login submitted.")

    captcha = driver.find_elements(By.XPATH, "//input[@id='captcha']")
    if captcha:
        input("Solve CAPTCHA manually and press Enter...")

    logging.info("Login completed.")

@retry((NoSuchElementException, TimeoutException))
def scroll_and_load(driver, wait_time=2, max_scrolls=None):
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_count = 0

    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(wait_time)

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height or (max_scrolls and scroll_count >= max_scrolls):
            break

        last_height = new_height
        scroll_count += 1

# ----------------------------
# Data Storage (JSON + Mongo) with debug
# ----------------------------
def save_to_json(profile_info, file_path='./data/scraped_profiles.json'):
    if not os.path.exists(file_path):
        with open(file_path, 'w') as f:
            json.dump([profile_info], f, indent=4)
    else:
        with open(file_path, 'r+') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
            data.append(profile_info)
            f.seek(0)
            json.dump(data, f, indent=4)

    logging.info("Profile saved to JSON.")

def save_to_mongo(data):
    mongo_uri = os.getenv("MONGO_URI")
    mongo_db = os.getenv("MONGO_DB")
    mongo_collection = os.getenv("MONGO_COLLECTION")
    mongo_enabled = all([mongo_uri, mongo_db, mongo_collection])

    if not mongo_enabled:
        logging.warning("MongoDB not configured — skipping save.")
        return

    try:
        with MongoClient(mongo_uri, serverSelectionTimeoutMS=5000) as client:
            # Test connection
            client.server_info()
            db = client[mongo_db]
            collection = db[mongo_collection]

            if isinstance(data, list):
                res = collection.insert_many(data)
                logging.info(f"Inserted {len(res.inserted_ids)} documents into MongoDB.")
            else:
                res = collection.insert_one(data)
                logging.info(f"Inserted document with _id={res.inserted_id} into MongoDB.")

    except Exception as e:
        logging.error(f"MongoDB save failed: {e}")

def is_profile_scraped_mongo(profile_url):
    mongo_uri = os.getenv("MONGO_URI")
    mongo_db = os.getenv("MONGO_DB")
    mongo_collection = os.getenv("MONGO_COLLECTION")
    mongo_enabled = all([mongo_uri, mongo_db, mongo_collection])
    if not mongo_enabled:
        return False

    try:
        with MongoClient(mongo_uri, serverSelectionTimeoutMS=3000) as client:
            db = client[mongo_db]
            collection = db[mongo_collection]
            return collection.count_documents({"profile_url": profile_url}, limit=1) > 0
    except Exception as e:
        logging.error(f"Mongo check failed: {e}")
        return False

# ----------------------------
# Root Profiles Loading
# ----------------------------
def load_profiles_from_json(file_path='./data/root_profiles.json'):
    try:
        with open(file_path, 'r') as f:
            profiles = json.load(f)
            logging.info(f"Loaded {len(profiles)} root profiles.")
            return set(profiles)
    except Exception as e:
        logging.error(f"Failed to load root profiles: {e}")
        return set()

def load_profiles_from_txt(file_path):
    try:
        with open(file_path, 'r') as f:
            return {line.strip() for line in f if line.strip()}
    except Exception as e:
        logging.error(f"TXT load failed: {e}")
        return set()

def load_profiles_from_csv(file_path):
    import csv
    profiles = set()
    try:
        with open(file_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if row:
                    profiles.add(row[0].strip())
    except Exception as e:
        logging.error(f"CSV load failed: {e}")
    return profiles

# ----------------------------
# Human-like Interaction
# ----------------------------
def add_random_delay(min_time=5, max_time=30):
    time.sleep(random.uniform(min_time, max_time))

def mimic_human_interaction(driver):
    scroll_distance = random.randint(50, 100)
    driver.execute_script(f"window.scrollBy(0, {scroll_distance});")
    add_random_delay()

# ----------------------------
# Chrome Debug Helper
# ----------------------------
def start_chrome_with_debug(chrome_path, chromedriver_path, profile_path):
    import subprocess
    import requests

    try:
        requests.get("http://127.0.0.1:9222/json", timeout=1)
        logging.info("Chrome debug already running.")
    except:
        subprocess.Popen([
            chrome_path,
            "--remote-debugging-port=9222",
            f"--user-data-dir={profile_path}",
            "--no-first-run",
            "--no-default-browser-check"
        ])
        time.sleep(5)

    options = Options()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
    service = Service(chromedriver_path)

    return webdriver.Chrome(service=service, options=options)

# ----------------------------
# Simple DB (visited profiles)
# ----------------------------
def init_db(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if not os.path.exists(db_path):
        with open(db_path, "w") as f:
            json.dump([], f)

def load_profile_list(db_path):
    try:
        with open(db_path, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_profile_list(db_path, profile_url):
    profiles = load_profile_list(db_path)
    profiles.add(profile_url)
    with open(db_path, "w") as f:
        json.dump(list(profiles), f, indent=2)
