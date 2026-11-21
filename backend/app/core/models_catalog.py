"""Model catalog loaded from config/models.yaml, plus cost maths."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.schemas import ModelInfo

PER_MILLION = 1_000_000


@dataclass(frozen=True)
class ModelCatalog:
    models: tuple[ModelInfo, ...]
    default_id: str
    prices_as_of: str | None

    def get(self, model_id: str) -> ModelInfo | None:
        return next((m for m in self.models if m.id == model_id), None)

    @property
    def default(self) -> ModelInfo:
        model = self.get(self.default_id)
        assert model is not None
        return model

    def cost_usd(
        self, model_id: str, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0
    ) -> float:
        """Price of one request. Cached input tokens are billed at the cached rate."""
        model = self.get(model_id)
        if model is None:
            return 0.0
        cached = min(cached_input_tokens, input_tokens)
        cached_price = model.cached_input_price if model.cached_input_price is not None else model.input_price
        return (
            (input_tokens - cached) * model.input_price
            + cached * cached_price
            + output_tokens * model.output_price
        ) / PER_MILLION


def _relative_cost(model: ModelInfo, base: ModelInfo) -> float:
    """How many times the default model's price (average of input and output ratios)."""
    ratios = []
    if base.input_price:
        ratios.append(model.input_price / base.input_price)
    if base.output_price:
        ratios.append(model.output_price / base.output_price)
    return round(sum(ratios) / len(ratios), 1) if ratios else 1.0


@lru_cache
def load_catalog(path: Path) -> ModelCatalog:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    default_id = raw.get("default_model")
    models = [ModelInfo.model_validate(item) for item in raw.get("models", [])]
    base = next((m for m in models if m.id == default_id), None)
    if base is None:
        raise ValueError(f"default_model '{default_id}' is not in {path}")
    for model in models:
        model.is_default = model.id == default_id
        model.relative_cost = _relative_cost(model, base)
    as_of = raw.get("prices_as_of")
    return ModelCatalog(tuple(models), default_id, str(as_of) if as_of else None)


def load_models(path: Path) -> list[ModelInfo]:
    return list(load_catalog(path).models)
