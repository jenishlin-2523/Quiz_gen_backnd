import os
from dotenv import load_dotenv

# Load local .env file if it exists
load_dotenv()

# Essential Environment Variables
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "super-secret-key")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "quiz_app")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

# Validation Check
missing_vars = []
if not MONGO_URI: missing_vars.append("MONGO_URI")
if not GROQ_API_KEY: missing_vars.append("GROQ_API_KEY")

if missing_vars:
    print(f"⚠️  WARNING: Missing environment variables: {', '.join(missing_vars)}")
    print("Please set these variables in your deployment environment (e.g., Render Dashboard).")
