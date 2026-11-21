"""Generate values for backend/.env.

Usage (from backend/):
    python scripts/hash_password.py            -> prompts for a password, prints APP_PASSWORD_HASH
    python scripts/hash_password.py --secret   -> also prints a random JWT_SECRET
"""

import getpass
import secrets
import sys

import bcrypt


def main() -> None:
    password = getpass.getpass("New password: ")
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters.")
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    print("\nPaste into backend/.env (keep the single quotes):\n")
    print(f"APP_PASSWORD_HASH='{password_hash}'")
    if "--secret" in sys.argv:
        print(f"JWT_SECRET='{secrets.token_urlsafe(48)}'")


if __name__ == "__main__":
    main()
