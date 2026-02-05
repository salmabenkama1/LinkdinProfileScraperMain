import os
import logging
import time
from collections import deque
from selenium import webdriver
from dotenv import load_dotenv

# ----------------------------
# 1️⃣ Load .env first
# ----------------------------
dotenv_path = os.path.join(os.getcwd(), 'environment', '.env')
print("Loading .env from:", dotenv_path)
load_dotenv(dotenv_path)

# Debug: print Mongo credentials
print("After load_dotenv:")
print("MONGO_URI:", os.getenv("MONGO_URI"))
print("MONGO_DB:", os.getenv("MONGO_DB"))
print("MONGO_COLLECTION:", os.getenv("MONGO_COLLECTION"))

# ----------------------------
# 2️⃣ Import helper functions after .env is loaded
# ----------------------------
from src.helper import (
    add_random_delay,
    init_db,
    load_profile_list,
    login,
    save_profile_list,
    start_chrome_with_debug,
    save_to_json,
    save_to_mongo,
    mimic_human_interaction,
    load_profiles_from_csv,
    load_profiles_from_json,
    load_profiles_from_txt
)
from src.scrape import scrape_profile, extract_more_profiles

# ----------------------------
# 3️⃣ Logging
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("./log/scraping.log")]
)

# ----------------------------
# 4️⃣ Chrome setup
# ----------------------------
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROMEDRIVER_PATH = r"C:\Users\Salma.BENKAMA\Desktop\linkedin-profile-scraper-master\drivers\chromedriver.exe"
PROFILE_PATH = r"C:\Users\Salma.BENKAMA\chrome_debug"

# ----------------------------
# 5️⃣ Main function
# ----------------------------
def main():
    max_profiles_per_hour = 25
    scraped_count = 0

    root_profiles_file = os.getenv("ROOT")
    db_path = os.getenv("DB_PATH")

    # Mongo check
    mongo_enabled = all([
        os.getenv("MONGO_URI"),
        os.getenv("MONGO_DB"),
        os.getenv("MONGO_COLLECTION")
    ])
    if mongo_enabled:
        logging.info("MongoDB enabled ")
    else:
        logging.warning("MongoDB not configured — JSON only ⚠️")

    # Load root profiles
    if root_profiles_file.endswith('.json'):
        list_profile = load_profiles_from_json(root_profiles_file)
    elif root_profiles_file.endswith('.txt'):
        list_profile = load_profiles_from_txt(root_profiles_file)
    elif root_profiles_file.endswith('.csv'):
        list_profile = load_profiles_from_csv(root_profiles_file)
    else:
        logging.error("Unsupported file format for root profiles.")
        return

    if not list_profile:
        logging.warning("No root profiles found, starting empty.")

    try:
        # Start Chrome
        driver = start_chrome_with_debug(CHROME_PATH, CHROMEDRIVER_PATH, PROFILE_PATH)
        driver.get("https://www.linkedin.com/feed/")
        time.sleep(3)

        # Initialize local DB
        init_db(db_path)
        queue = deque(list_profile)
        list_profile = load_profile_list(db_path)

        while queue:
            if scraped_count >= max_profiles_per_hour:
                logging.info("Reached hourly limit. Sleeping 1h...")
                time.sleep(3600)
                scraped_count = 0

            add_random_delay(20, 60)
            current_profile = queue.popleft()

            if current_profile not in list_profile:
                try:
                    profile_info = scrape_profile(driver, current_profile, visited_profiles=list_profile)

                    if profile_info:
                        list_profile.add(current_profile)
                        save_to_json(profile_info)

                        # 🔹 Save to Mongo dynamically
                        if mongo_enabled:
                            print(f"Saving {current_profile} to Mongo...")
                            save_to_mongo(profile_info)

                        logging.info(f"Profile saved: {current_profile}")
                    else:
                        logging.warning(f"Failed to scrape: {current_profile}")

                    # Discover more profiles
                    new_links = extract_more_profiles(driver)
                    new_links = [l for l in new_links if l not in list_profile]
                    queue.extend(new_links)

                    save_profile_list(db_path, current_profile)
                    scraped_count += 1

                except Exception as e:
                    logging.error(f"Error scraping {current_profile}: {e}")
                    continue

    except Exception as e:
        logging.error(f"Fatal error: {e}")

    finally:
        if 'driver' in locals():
            driver.quit()
        logging.info("Driver closed.")

# ----------------------------
# 6️⃣ Entry point
# ----------------------------
if __name__ == "__main__":
    main()
