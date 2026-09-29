import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "lgu.db")

SECRET_KEY = "lgu-convocation-demo-key-change-in-production"
HMAC_SECRET = b"lgu-convocation-hmac-secret-change-in-production"

ID_VERSION = "LGU1"
ID_LENGTH = 8
ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I to avoid misreads

DISPLAY_TZ = "Asia/Karachi"

APP_NAME = "LGU Smart Convocation System"
UNIVERSITY = "Lahore Garrison University"
MOTTO = "Nurturing the Future of Pakistan in an Excellent Environment"
