from pymongo import MongoClient
import config

if config.MONGO_URI:
    try:
        client = MongoClient(config.MONGO_URI)
        db = client[config.DB_NAME]
    except Exception as e:
        client = None
        db = None
        print(f"❌ ERROR: Failed to initialize MongoDB client: {e}")
else:

    client = None
    db = None
    print("❌ ERROR: MONGO_URI is missing. Database connection will fail.")


# Collections
users_collection = db["users"] if db is not None else None
courses_collection = db["courses"] if db is not None else None
quizzes_collection = db["quizzes"] if db is not None else None
quiz_results_collection = db["quiz_results"] if db is not None else None
enrollments_collection = db["enrollments"] if db is not None else None
submissions_collection = db["submissions"] if db is not None else None

