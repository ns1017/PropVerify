import sys
import os
import sqlite3
import requests
import config
from bs4 import BeautifulSoup
import ast

# Add parent directory to path to import app functions
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# Reuse fetch_data and calculate_score from app.py
def fetch_data(address):
    url = f"{config.NOMINATIM_API_URL}?q={address}&format=json"
    headers = {"User-Agent": config.NOMINATIM_USER_AGENT}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200 and response.json():
            return response.json()[0], "Nominatim"
    except requests.RequestException:
        pass

    if config.SCRAPING_ENABLED:
        scrape_url = f"https://www.zillow.com/homes/{address.replace(' ', '-')}_rb/"
        try:
            response = requests.get(scrape_url, headers=headers, timeout=5)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                price = soup.find('span', {'data-testid': 'price'})
                data = {'lat': 'N/A', 'lon': 'N/A', 'price': price.text if price else 'N/A'}
                return data, "Zillow"
        except requests.RequestException:
            pass
    
    return "No data found", "None"

def calculate_score(data):
    if isinstance(data, str):
        return 0.1, 10.0
    
    lat = float(data.get('lat', 0))
    if 25 <= lat <= 35:
        solar_score = 0.8
        confidence = 70.0
    elif 35 < lat <= 45:
        solar_score = 0.5
        confidence = 60.0
    else:
        solar_score = 0.3
        confidence = 50.0
    
    repair_score = 0.5
    score = (solar_score * 0.7 + repair_score * 0.3)
    return score, confidence

def get_or_cache(address):
    conn = sqlite3.connect(config.DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT data, score, confidence FROM properties WHERE address = ?", (address,))
    result = c.fetchone()
    if result:
        conn.close()
        data_str, score, confidence = result
        data = ast.literal_eval(data_str) if data_str.startswith("{") else data_str
        return data, score, confidence, "Cached"
    data, source = fetch_data(address)
    score, confidence = calculate_score(data)
    data_str = str(data) if isinstance(data, dict) else data
    c.execute("INSERT OR REPLACE INTO properties (address, data, score, confidence) VALUES (?, ?, ?, ?)",
              (address, data_str, score, confidence))
    conn.commit()
    conn.close()
    return data, score, confidence, source

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python run_leads.py <input_file>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    with open(input_file, 'r') as f:
        addresses = [line.strip() for line in f if line.strip()]
    
    for address in addresses[:config.MAX_SEARCHES]:  # Respect search limit
        data, score, confidence, source = get_or_cache(address)
        lat = data.get('lat', 'N/A') if isinstance(data, dict) else 'N/A'
        lon = data.get('lon', 'N/A') if isinstance(data, dict) else 'N/A'
        print(f"Address: {address}")
        print(f"Location: Lat: {lat}, Lon: {lon}")
        print(f"Source: {source}")
        print(f"Score: {score:.2f}, Confidence: {confidence:.1f}%")
        print("-" * 40)