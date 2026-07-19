import os
from urllib.parse import quote_plus

from dotenv import load_dotenv


load_dotenv()


# -------------------------------------------------------------------
# Chatbot 
# -------------------------------------------------------------------
CHATBOT_API_KEY = os.getenv("CHATBOT_API_KEY")

# -------------------------------------------------------------------
# Forecast API
# -------------------------------------------------------------------
FORECAST_API_URL = os.getenv("FORECAST_API_URL")


# Read-only forecast database
# -------------------------------------------------------------------

ADK_DB_USER = os.getenv("ADK_DB_USER")
ADK_DB_PASSWORD = os.getenv("ADK_DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB")


required_vars = {
    "ADK_DB_USER": ADK_DB_USER,
    "ADK_DB_PASSWORD": ADK_DB_PASSWORD,
    "DB_HOST": DB_HOST,
    "DB_PORT": DB_PORT,
    "POSTGRES_DB": POSTGRES_DB,
    "FORECAST_API_URL": FORECAST_API_URL,
}

missing_vars = [
    name
    for name, value in required_vars.items()
    if not value
]

if missing_vars:
    raise ValueError(
        "Missing required environment variables: "
        + ", ".join(missing_vars)
    )


# Encode special characters that may appear in database credentials.
encoded_user = quote_plus(ADK_DB_USER)
encoded_password = quote_plus(ADK_DB_PASSWORD)

ADK_DB_CONN = (
    f"postgresql://{encoded_user}:{encoded_password}"
    f"@{DB_HOST}:{DB_PORT}/{POSTGRES_DB}"
)