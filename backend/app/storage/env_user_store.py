"""Single user defined in .env (APP_USERNAME / APP_PASSWORD_HASH).

Phase 1 has no user database; sign-up and multiple users come later.
"""

import hmac
import re

from app.core.config import Settings
from app.core.security import verify_password
from app.schemas import User
from app.storage.base import UserStore


def _user_id_for(username: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]", "-", username.strip().lower())[:50] or "user"
    return f"u-{slug}"


class EnvUserStore(UserStore):
    def __init__(self, settings: Settings) -> None:
        self._user = User(
            id=_user_id_for(settings.app_username),
            username=settings.app_username,
            display_name=settings.app_display_name,
        )
        self._password_hash = settings.app_password_hash

    def authenticate(self, username: str, password: str) -> User | None:
        username_ok = hmac.compare_digest(username.strip().lower(), self._user.username.lower())
        # Always run bcrypt so a wrong username takes as long as a wrong password.
        password_ok = verify_password(password, self._password_hash)
        return self._user if (username_ok and password_ok) else None

    def get_user(self, user_id: str) -> User | None:
        return self._user if user_id == self._user.id else None
