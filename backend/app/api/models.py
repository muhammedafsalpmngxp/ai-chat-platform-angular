from fastapi import APIRouter

from app.api.deps import CatalogDep, CurrentUser, SettingsDep
from app.schemas import ModelCatalogResponse

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=ModelCatalogResponse)
def list_models(_: CurrentUser, catalog: CatalogDep, settings: SettingsDep) -> ModelCatalogResponse:
    return ModelCatalogResponse(
        default_model=catalog.default_id,
        prices_as_of=catalog.prices_as_of,
        premium_unlock_minutes=settings.premium_unlock_minutes,
        models=list(catalog.models),
    )
