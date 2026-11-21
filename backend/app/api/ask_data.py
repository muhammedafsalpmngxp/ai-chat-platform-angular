"""Connect / disconnect the user's company account for Ask Data.

The password is sent once to the company auth service and never stored;
only the returned tokens are kept, in memory, for this backend process.
"""

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentUser, LimiterDep, SettingsDep
from app.api.auth import _check_lockout
from app.schemas import AskDataConnect, AskDataStatus
from app.services.ask_data import AskDataAuthError, AskDataError, AskDataGateway

router = APIRouter(prefix="/ask-data", tags=["ask-data"])


def _gateway(request: Request) -> AskDataGateway | None:
    return request.app.state.ask_data


def _status(gateway: AskDataGateway | None, user_id: str) -> AskDataStatus:
    session = gateway.session(user_id) if gateway else None
    return AskDataStatus(enabled=gateway is not None, connected=session is not None, email=session.email if session else None)


@router.get("/status", response_model=AskDataStatus)
def get_status(request: Request, user: CurrentUser) -> AskDataStatus:
    return _status(_gateway(request), user.id)


@router.post("/connect", response_model=AskDataStatus)
async def connect(
    body: AskDataConnect, request: Request, user: CurrentUser, settings: SettingsDep, limiter: LimiterDep
) -> AskDataStatus:
    gateway = _gateway(request)
    if gateway is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Ask Data is not configured on this server.")
    key = f"ask-data:{user.id}"
    _check_lockout(limiter, key)
    try:
        await gateway.connect(user.id, body.email.strip(), body.password)
    except AskDataAuthError as exc:
        limiter.failed(key)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    except AskDataError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from None
    limiter.reset(key)
    return _status(gateway, user.id)


@router.post("/disconnect", response_model=AskDataStatus)
def disconnect(request: Request, user: CurrentUser) -> AskDataStatus:
    gateway = _gateway(request)
    if gateway is not None:
        gateway.disconnect(user.id)
    return _status(gateway, user.id)
