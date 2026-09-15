"""One-time bootstrap: create the first admin user directly in the database
(there is no admin yet to authorize POST /auth/register). After this, use
POST /auth/register with the resulting admin's token to add more users.

Usage: python -m scripts.create_admin you@example.com "a-strong-password"
"""
import sys
from sqlalchemy import select
from app import auth
from app.db import SessionLocal
from app.models import User


def main():
    if len(sys.argv) != 3:
        print("Usage: python -m scripts.create_admin <email> <password>")
        raise SystemExit(1)
    email, password = sys.argv[1], sys.argv[2]
    with SessionLocal.begin() as db:
        if db.scalar(select(User).where(User.email == email)):
            print(f"User {email} already exists.")
            return
        db.add(User(email=email, role="admin", password_hash=auth.hash_password(password)))
    print(f"Created admin user {email}. Log in via POST /auth/login to get a token.")


if __name__ == "__main__":
    main()
