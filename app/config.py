import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "lgu.db")

SECRET_KEY = os.environ.get("LGU_SECRET_KEY", "lgu-convocation-demo-key-change-in-production")
# QR signing secret (bytes). Set LGU_HMAC_SECRET in the environment on the
# real server; the committed value is a demo default. Changing it
# invalidates previously issued QR codes, so set it once before cards
# are printed.
HMAC_SECRET = os.environ.get("LGU_HMAC_SECRET", "lgu-convocation-hmac-secret-change-in-production").encode("utf-8")

ID_VERSION = "LGU1"
ID_LENGTH = 8
ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I to avoid misreads

DISPLAY_TZ = "Asia/Karachi"

APP_NAME = "LGU Smart Convocation System"
UNIVERSITY = "Lahore Garrison University"
MOTTO = "Nurturing the Future of Pakistan in an Excellent Environment"
