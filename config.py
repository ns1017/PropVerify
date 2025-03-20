import os

# Base directory for relative paths
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Flask settings
DEBUG = True  # Enable debug mode for development
SECRET_KEY = "f091bf9d22a8db35a74cb98884c4167b"  # For form security: python -c "import secrets; print(secrets.token_hex(16))"

# Database settings
DATABASE_PATH = os.path.join(BASE_DIR, "ailead.db")

# API settings
NOMINATIM_API_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "AILeadQualifier"
MAX_SEARCHES = 1  # Limit to 1 search at a time (adjustable to #<~3)

# AI model settings
MODEL_PATH = os.path.join(BASE_DIR, "data", "model.pkl")
SAMPLE_DATA_PATH = os.path.join(BASE_DIR, "data", "sample_data.csv")

# Optional Toggles
SCRAPING_ENABLED = True  # Toggle scraping if implemented
FEEDBACK_ENABLED = True   # For user feedback loop