"""
Bootstrap script to create first admin user.
Run this ONCE, then delete it.
"""

from datetime import datetime
from app.services.firebase_service import db
from app.services.auth_service import hash_password

USERNAME = "admin"
EMAIL = "admin@greenhouse.local"
PASSWORD = "admin123"

# Check if admin already exists by EMAIL (important!)
query = db.collection("users") \
          .where("email", "==", EMAIL) \
          .limit(1) \
          .stream()

if next(query, None):
    print("Admin already exists.")
else:
    db.collection("users").add({
        "username": USERNAME,
        "email": EMAIL,
        "password_hash": hash_password(PASSWORD),
        "role": "admin",
        "is_active": True,
        "created_at": datetime.utcnow(),
        "last_login_at": None
    })
    print("Admin created successfully.")
