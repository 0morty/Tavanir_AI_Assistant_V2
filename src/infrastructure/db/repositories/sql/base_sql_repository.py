from __future__ import annotations

import dataclasses
from typing import Any, Generic, TypeVar, cast

from sqlalchemy.ext.asyncio import AsyncSession

EntityT = TypeVar("EntityT")
ModelT = TypeVar("ModelT")


class BaseSqlRepository(Generic[EntityT, ModelT]):
    """
    Generic base class for all PostgreSQL repositories.
    Provides session encapsulation and default mapper hooks between
    pure domain entities and SQLAlchemy ORM models.
    """

    def __init__(
        self,
        session: AsyncSession,
        entity_class: type[EntityT] | None = None,
        model_class: type[ModelT] | None = None,
    ) -> None:
        self._session = session
        self._entity_class = entity_class
        self._model_class = model_class

    @property
    def session(self) -> AsyncSession:
        """Direct access to the underlying AsyncSession."""
        return self._session

    def _to_entity(self, model: ModelT) -> EntityT:
        """
        Default mapper: maps an ORM model instance -> domain entity.
        Subclasses with nested value objects can override this method for custom hydration.
        """
        if self._entity_class is None:
            raise NotImplementedError(
                "entity_class must be provided or _to_entity overridden."
            )

        if dataclasses.is_dataclass(self._entity_class):
            fields = {
                field.name: getattr(model, field.name)
                for field in dataclasses.fields(self._entity_class)
                if hasattr(model, field.name)
            }
            return cast(EntityT, self._entity_class(**fields))

        raise NotImplementedError(
            f"Cannot auto-map model to non-dataclass entity: {self._entity_class}"
        )

    def _to_model(self, entity: EntityT) -> ModelT:
        """
        Default mapper: maps a domain entity -> ORM model instance.
        Subclasses with nested value objects can override this method for custom flattening.
        """
        if self._model_class is None:
            raise NotImplementedError(
                "model_class must be provided or _to_model overridden."
            )

        if dataclasses.is_dataclass(entity):
            fields: dict[str, Any] = {}
            for field in dataclasses.fields(entity):
                val = getattr(entity, field.name)
                if hasattr(self._model_class, field.name):
                    fields[field.name] = val
            return self._model_class(**fields)

        raise NotImplementedError(
            f"Cannot auto-map non-dataclass entity to model: {type(entity)}"
        )


__all__ = ["BaseSqlRepository"]
