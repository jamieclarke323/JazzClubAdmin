"""Local development server.  Usage:  python run.py"""
import os

os.environ.setdefault("SESSION_COOKIE_SECURE", "0")

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))
