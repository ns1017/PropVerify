from flask import Flask, render_template, request
import sqlite3
from functools import wraps
import config
import requests
from redfin import Redfin
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException, WebDriverException
import ast
import logging
import time
import os
import re

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config.from_object(config)

logging.basicConfig(filename='scrape.log', level=logging.DEBUG, 
                    format='%(asctime)s %(levelname)s: %(message)s')

def init_db():
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS properties
                 (address TEXT PRIMARY KEY, data TEXT, score REAL, confidence REAL, feedback TEXT)''')
    try:
        c.execute("ALTER TABLE properties ADD COLUMN feedback TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

init_db()

active_searches = 0

def limit_searches(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        global active_searches
        if active_searches >= app.config['MAX_SEARCHES']:
            return "Too many searches, please wait.", 429
        active_searches += 1
        try:
            return f(*args, **kwargs)
        finally:
            active_searches -= 1
    return decorated

def fetch_data(street, city, state, zip_code):
    address = f"{street}, {city}, {state} {zip_code}"
    headers = {"User-Agent": app.config['NOMINATIM_USER_AGENT']}
    
    # Nominatim API for lat/lon
    url = f"{app.config['NOMINATIM_API_URL']}?q={address}&format=json"
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200 and response.json():
            nominatim_data = response.json()[0]
            logging.info(f"Nominatim success for {address}: {nominatim_data}")
        else:
            nominatim_data = None
            logging.warning(f"Nominatim returned {response.status_code} for {address}")
    except requests.RequestException as e:
        nominatim_data = None
        logging.error(f"Nominatim failed for {address}: {str(e)}")

    if app.config['SCRAPING_ENABLED']:
        # Redfin API via reteps/redfin
        redfin_data = {'price': 'N/A', 'year_built': 'N/A', 'acreage': 'N/A', 'solar_info': 'N/A'}
        if Redfin:
            try:
                redfin_client = Redfin()
                response = redfin_client.search(address)
                time.sleep(5)  # Rate limit precaution
                if 'payload' in response and 'exactMatch' in response['payload']:
                    url = response['payload']['exactMatch']['url']
                    initial_info = redfin_client.initial_info(url)
                    property_id = initial_info['payload']['propertyId']
                    mls_data = redfin_client.below_the_fold(property_id)
                    
                    # Extract data (adjust keys based on actual response)
                    redfin_data['price'] = mls_data['payload'].get('price', {}).get('value', 'N/A')
                    redfin_data['year_built'] = mls_data['payload'].get('yearBuilt', 'N/A')
                    redfin_data['acreage'] = mls_data['payload'].get('lotSize', {}).get('value', 'N/A')
                    solar_info = mls_data['payload'].get('utilityInfo', {}).get('solarDetails', 'N/A')
                    redfin_data['solar_info'] = solar_info if solar_info != 'N/A' else 'N/A'
                    logging.info(f"Redfin API success for {address}: {redfin_data}")
                    logging.debug(f"Full Redfin mls_data: {mls_data}")
                else:
                    logging.warning(f"Redfin API no exact match for {address}")
            except Exception as e:
                logging.error(f"Redfin API failed for {address}: {str(e)}")

        # Fallback to Selenium for Redfin if API fails or Redfin not installed
        if all(value == 'N/A' for value in redfin_data.values()) or not Redfin:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument(f"user-agent={app.config['NOMINATIM_USER_AGENT']}")
            driver_path = os.path.join(os.path.dirname(__file__), "chromedriver.exe")
            service = Service(executable_path=driver_path)
            try:
                driver = webdriver.Chrome(service=service, options=chrome_options)
                addr_part = street.replace(' ', '-')
                redfin_url = f"https://www.redfin.com/{state}/{city}/{addr_part}"
                driver.get(redfin_url)
                time.sleep(3)
                price_elem = driver.find_element(By.CSS_SELECTOR, 'div[class*="home-main-stats"] span')
                year_elem = driver.find_element(By.XPATH, "//span[contains(text(), 'Built')]")
                acreage_elem = driver.find_element(By.XPATH, "//span[contains(text(), 'Lot size')]")
                solar_elem = driver.find_element(By.XPATH, "//div[contains(., 'Electricity and solar')]//following-sibling::p[contains(., 'Est.')]")
                
                redfin_data['price'] = price_elem.text.strip() if price_elem else 'N/A'
                redfin_data['year_built'] = year_elem.text.split()[-1] if year_elem else 'N/A'
                redfin_data['acreage'] = re.search(r'[\d.]+', acreage_elem.text).group() if acreage_elem and re.search(r'[\d.]+', acreage_elem.text) else 'N/A'
                redfin_data['solar_info'] = solar_elem.text.strip() if solar_elem else 'N/A'
                logging.info(f"Redfin Selenium fallback success for {address}: {redfin_data}")
            except (NoSuchElementException, WebDriverException) as e:
                logging.error(f"Redfin Selenium fallback failed for {address}: {str(e)}")
            finally:
                if 'driver' in locals():
                    driver.quit()

        # Zillow scraping (Selenium)
        zillow_data = {'price': 'N/A', 'year_built': 'N/A', 'acreage': 'N/A', 'home_type': 'N/A'}
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument(f"user-agent={app.config['NOMINATIM_USER_AGENT']}")
        driver_path = os.path.join(os.path.dirname(__file__), "chromedriver.exe")
        service = Service(executable_path=driver_path)
        try:
            driver = webdriver.Chrome(service=service, options=chrome_options)
            zillow_url = f"https://www.zillow.com/homes/{street.replace(' ', '-')}-{city}-{state}-{zip_code}_rb/"
            driver.get(zillow_url)
            time.sleep(3)
            price_elem = driver.find_element(By.CSS_SELECTOR, 'span[data-testid="price"]')
            year_elem = driver.find_element(By.XPATH, '//span[contains(@class, "dFxMdJ") and contains(text(), "Built in")]')
            acreage_elem = driver.find_element(By.XPATH, '//span[contains(@class, "dFxMdJ") and contains(text(), "Lot size") or contains(text(), "Acres")]')
            type_elem = driver.find_element(By.XPATH, '//span[contains(@class, "dFxMdJ") and (contains(text(), "Single Family") or contains(text(), "Condo") or contains(text(), "Townhouse"))]')
            
            zillow_data['price'] = price_elem.text.strip() if price_elem else 'N/A'
            zillow_data['year_built'] = year_elem.text.replace("Built in ", "").strip() if year_elem else 'N/A'
            zillow_data['acreage'] = acreage_elem.text.split(" ")[0] if acreage_elem else 'N/A'
            zillow_data['home_type'] = type_elem.text.strip() if type_elem else 'N/A'
            logging.info(f"Zillow scraped for {address}: {zillow_data}")
        except (NoSuchElementException, WebDriverException) as e:
            logging.error(f"Zillow failed for {address}: {str(e)}")
        finally:
            driver.quit()

        # Combine data
        combined_data = {
            'lat': nominatim_data.get('lat', 'N/A') if nominatim_data else 'N/A',
            'lon': nominatim_data.get('lon', 'N/A') if nominatim_data else 'N/A',
            'price': redfin_data['price'] if redfin_data['price'] != 'N/A' else zillow_data['price'],
            'year_built': redfin_data['year_built'] if redfin_data['year_built'] != 'N/A' else zillow_data['year_built'],
            'acreage': redfin_data['acreage'] if redfin_data['acreage'] != 'N/A' else zillow_data['acreage'],
            'home_type': zillow_data['home_type'],
            'solar_info': redfin_data['solar_info'],
            'sources': []
        }
        if nominatim_data:
            combined_data['sources'].append("Nominatim")
        if any(redfin_data[k] != 'N/A' for k in redfin_data.keys()):
            combined_data['sources'].append("Redfin")
        if any(zillow_data[k] != 'N/A' for k in zillow_data.keys()):
            combined_data['sources'].append("Zillow")
        source_str = " + ".join(combined_data['sources']) if combined_data['sources'] else "None"
        return combined_data, source_str
    
    return nominatim_data or "No data found", "Nominatim" if nominatim_data else "None"

def calculate_score(data):
    if isinstance(data, str):
        return 0.1, 10.0
    
    try:
        lat = float(data.get('lat', 0))
    except (ValueError, TypeError):
        lat = 0
    
    solar_score = 0.5
    confidence = 60.0
    if 25 <= lat <= 35:
        solar_score = 0.8
        confidence = 70.0
    elif 35 < lat <= 45:
        solar_score = 0.5
        confidence = 60.0
    
    if 'solar_info' in data and data['solar_info'] != 'N/A':
        if 'save' in data['solar_info'].lower():
            solar_score += 0.2
            confidence += 10.0
        if 'rooftop solar' in data['solar_info'].lower():
            solar_score += 0.1
            confidence += 5.0
    
    repair_score = 0.5
    if 'year_built' in data and data['year_built'] != 'N/A':
        try:
            year = int(data['year_built'])
            age = 2025 - year
            if age > 30:
                repair_score = 0.3
                confidence += 10.0
            elif age < 10:
                repair_score = 0.7
                confidence += 10.0
        except ValueError:
            pass
    
    acreage_score = 0.5
    if 'acreage' in data and data['acreage'] != 'N/A':
        try:
            acreage = float(data['acreage'])
            if acreage > 1.0:
                acreage_score = 0.8
                confidence += 10.0
            elif acreage < 0.1:
                acreage_score = 0.2
        except ValueError:
            pass
    
    score = (solar_score * 0.5 + repair_score * 0.3 + acreage_score * 0.2)
    return score, min(confidence, 100.0)

def get_or_cache(street, city, state, zip_code):
    address = f"{street}, {city}, {state} {zip_code}"
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    c = conn.cursor()
    c.execute("SELECT data, score, confidence, feedback FROM properties WHERE address = ?", (address,))
    result = c.fetchone()
    if result:
        conn.close()
        data_str, score, confidence, feedback = result
        data = ast.literal_eval(data_str) if data_str.startswith("{") else data_str
        source = "Cached"
        return data, score, confidence, source, feedback
    data, source = fetch_data(street, city, state, zip_code)
    score, confidence = calculate_score(data)
    data_str = str(data) if isinstance(data, dict) else data
    c.execute("INSERT OR REPLACE INTO properties (address, data, score, confidence, feedback) VALUES (?, ?, ?, ?, ?)",
              (address, data_str, score, confidence, None))
    conn.commit()
    conn.close()
    return data, score, confidence, source, None

@app.route('/', methods=['GET', 'POST'])
@limit_searches
def home():
    if request.method == 'POST':
        street = request.form['street']
        city = request.form['city']
        state = request.form['state'].upper()
        zip_code = request.form['zip']
        address = f"{street}, {city}, {state} {zip_code}"
        try:
            data, score, confidence, source, feedback = get_or_cache(street, city, state, zip_code)
            if isinstance(data, dict):
                result = {
                    'address': address,
                    'lat': data.get('lat', 'N/A'),
                    'lon': data.get('lon', 'N/A'),
                    'price': data.get('price', 'N/A'),
                    'year_built': data.get('year_built', 'N/A'),
                    'acreage': data.get('acreage', 'N/A'),
                    'home_type': data.get('home_type', 'N/A'),
                    'solar_info': data.get('solar_info', 'N/A'),
                    'source': source,
                    'score': f"{score:.2f}",
                    'confidence': f"{confidence:.1f}"
                }
            else:
                result = {
                    'address': address,
                    'lat': 'N/A',
                    'lon': 'N/A',
                    'price': 'N/A',
                    'year_built': 'N/A',
                    'acreage': 'N/A',
                    'home_type': 'N/A',
                    'solar_info': 'N/A',
                    'source': source,
                    'score': f"{score:.2f}",
                    'confidence': f"{confidence:.1f}"
                }
            return render_template('index.html', result=result)
        except Exception as e:
            logging.error(f"Error processing {address}: {str(e)}")
            return "Internal server error", 500
    return render_template('index.html')

@app.route('/feedback', methods=['POST'])
@limit_searches
def feedback():
    address = request.form['address']
    solar = request.form['solar']
    repairs = request.form['repairs']
    feedback_data = f"solar:{solar},repairs:{repairs}"
    
    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    c = conn.cursor()
    c.execute("UPDATE properties SET feedback = ? WHERE address = ?", (feedback_data, address))
    conn.commit()
    conn.close()
    
    street, city, state_zip = address.split(',', 2)
    state, zip_code = state_zip.strip().split(' ', 1)
    data, score, confidence, source, _ = get_or_cache(street.strip(), city.strip(), state.strip(), zip_code.strip())
    if isinstance(data, dict):
        result = {
            'address': address,
            'lat': data.get('lat', 'N/A'),
            'lon': data.get('lon', 'N/A'),
            'price': data.get('price', 'N/A'),
            'year_built': data.get('year_built', 'N/A'),
            'acreage': data.get('acreage', 'N/A'),
            'home_type': data.get('home_type', 'N/A'),
            'solar_info': data.get('solar_info', 'N/A'),
            'source': source,
            'score': f"{score:.2f}",
            'confidence': f"{confidence:.1f}"
        }
    else:
        result = {
            'address': address,
            'lat': 'N/A',
            'lon': 'N/A',
            'price': 'N/A',
            'year_built': 'N/A',
            'acreage': 'N/A',
            'home_type': 'N/A',
            'solar_info': 'N/A',
            'source': source,
            'score': f"{score:.2f}",
            'confidence': f"{confidence:.1f}"
        }
    return render_template('index.html', result=result)

if __name__ == '__main__':
    app.run(debug=app.config['DEBUG'])