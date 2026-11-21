from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, LimiterDep, SettingsDep, UserStoreDep
from app.core.rate_limit import AttemptLimiter
from app.core.security import create_access_token, create_premium_unlock_token
from app.schemas import LoginRequest, ReauthRequest, ReauthResponse, TokenResponse, User

router = APIRouter(prefix="/auth", tags=["auth"])


def _check_lockout(limiter: AttemptLimiter, key: str) -> None:
    wait = limiter.retry_after(key)
    if wait:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many wrong passwords. Try again in {max(1, round(wait / 60))} min.",
            headers={"Retry-After": str(wait)},
        )


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest, settings: SettingsDep, users: UserStoreDep, limiter: LimiterDep
) -> TokenResponse:
    key = f"login:{body.username.strip().lower()}"
    _check_lockout(limiter, key)
    user = users.authenticate(body.username, body.password)
    if user is None:
        limiter.failed(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    limiter.reset(key)
    token, expires_in = create_access_token(user.id, settings)
    return TokenResponse(access_token=token, expires_in=expires_in, user=user)


@router.get("/me", response_model=User)
def me(user: CurrentUser) -> User:
    return user


@router.post("/reauth", response_model=ReauthResponse)
def reauth(
    body: ReauthRequest,
    user: CurrentUser,
    settings: SettingsDep,
    users: UserStoreDep,
    limiter: LimiterDep,
) -> ReauthResponse:
    """Re-enter the password to unlock premium models for a short time."""
    key = f"reauth:{user.id}"
    _check_lockout(limiter, key)
    if users.authenticate(user.username, body.password) is None:
        limiter.failed(key)
        # 403, not 401: the session is still valid, only the password was wrong.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Incorrect password")
    limiter.reset(key)
    token, expires_in = create_premium_unlock_token(user.id, settings)
    return ReauthResponse(unlock_token=token, expires_in=expires_in)
