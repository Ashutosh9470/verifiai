# app/firebase.py
import os
import firebase_admin
from firebase_admin import credentials, firestore

_DB = None

def init_firebase():
    global _DB
    if _DB is not None:
        return _DB

    # Prefer explicit path; fall back to env var; finally raise helpful error
    explicit_path = r"C:\Users\sharm\OneDrive\Desktop\verifiai\serviceAccountKey.json"
    cred_path = explicit_path if os.path.exists(explicit_path) else os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    if not cred_path or not os.path.exists(cred_path):
        raise FileNotFoundError(
            f"Firebase service account key not found. Checked: "
            f"'{explicit_path}' and GOOGLE_APPLICATION_CREDENTIALS='{os.getenv('GOOGLE_APPLICATION_CREDENTIALS')}'."
        )

    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        # If your project id differs, put it here explicitly:
        firebase_admin.initialize_app(cred)  # project inferred from key

    _DB = firestore.client()
    return _DB

def get_db():
    return init_firebase()
