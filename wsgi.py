"""WSGI entry point.

PythonAnywhere: in your WSGI configuration file add

    import sys
    sys.path.insert(0, "/home/<username>/JazzClubAdmin")
    from wsgi import application

Flask CLI (migrations etc.):  flask --app wsgi db upgrade
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import create_app  # noqa: E402

application = create_app()
