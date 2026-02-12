from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
import config
from routes.auth_routes import auth_bp
from routes.quiz_routes import quiz_bp
import os

app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = config.JWT_SECRET_KEY

CORS(
    app,
    origins=["http://localhost:3000"],  
    supports_credentials=True,
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"]
)

jwt = JWTManager(app)

app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(quiz_bp)

@app.route("/")
def home():
    return "✅ Flask server with JWT Auth is running!"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
