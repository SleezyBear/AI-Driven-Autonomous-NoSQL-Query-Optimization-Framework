"""The initially supported safe action schemas and their exact inverses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActionSchema(BaseModel):
    """Base model that rejects arbitrary command fields from callers."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class IndexField(ActionSchema):
    """One ordinary ascending or descending B-tree index field."""

    field: str = Field(min_length=1, max_length=255)
    direction: Literal[-1, 1]


class DropIndexAction(ActionSchema):
    """Exact inverse of a typed CREATE_INDEX action."""

    action_type: Literal["DROP_INDEX"] = "DROP_INDEX"
    database: str = Field(min_length=1, max_length=63)
    collection: str = Field(min_length=1, max_length=255)
    index_name: str = Field(min_length=1, max_length=255)


class CreateIndexAction(ActionSchema):
    """Safe autonomous CREATE_INDEX action with every forbidden variant excluded."""

    action_type: Literal["CREATE_INDEX"] = "CREATE_INDEX"
    database: str = Field(min_length=1, max_length=63)
    collection: str = Field(min_length=1, max_length=255)
    index_name: str = Field(min_length=1, max_length=255)
    fields: tuple[IndexField, ...] = Field(min_length=1, max_length=5)
    unique: bool = False
    expire_after_seconds: int | None = None
    sparse: bool = False
    partial_filter_expression: dict[str, object] | None = None
    text: bool = False
    wildcard: bool = False
    geo: bool = False
    hashed: bool = False

    @model_validator(mode="after")
    def enforce_autonomous_restrictions(self) -> CreateIndexAction:
        """Reject index features that are outside the frozen autonomous boundary."""
        forbidden = {
            "unique": self.unique,
            "TTL": self.expire_after_seconds is not None,
            "sparse": self.sparse,
            "partial": self.partial_filter_expression is not None,
            "text": self.text,
            "wildcard": self.wildcard,
            "geo": self.geo,
            "hashed": self.hashed,
        }
        enabled = [name for name, value in forbidden.items() if value]
        if enabled:
            raise ValueError(f"Forbidden autonomous index variants: {', '.join(enabled)}")
        return self

    def inverse(self) -> DropIndexAction:
        """Return the typed exact inverse that removes this named index only."""
        return DropIndexAction(database=self.database, collection=self.collection, index_name=self.index_name)


class RestoreQuerySettingsIndexHintAction(ActionSchema):
    """Exact inverse that restores the query setting state observed before an update."""

    action_type: Literal["RESTORE_QUERY_SETTINGS_INDEX_HINT"] = "RESTORE_QUERY_SETTINGS_INDEX_HINT"
    database: str = Field(min_length=1, max_length=63)
    collection: str = Field(min_length=1, max_length=255)
    query_shape_hash: str = Field(min_length=1, max_length=255)
    index_hint: str | None = Field(default=None, min_length=1, max_length=255)


class SetQuerySettingsIndexHintAction(ActionSchema):
    """Typed SET_QUERY_SETTINGS_INDEX_HINT action with its prior state bound as evidence."""

    action_type: Literal["SET_QUERY_SETTINGS_INDEX_HINT"] = "SET_QUERY_SETTINGS_INDEX_HINT"
    database: str = Field(min_length=1, max_length=63)
    collection: str = Field(min_length=1, max_length=255)
    query_shape_hash: str = Field(min_length=1, max_length=255)
    index_hint: str = Field(min_length=1, max_length=255)
    previous_index_hint: str | None = Field(default=None, min_length=1, max_length=255)

    def inverse(self) -> RestoreQuerySettingsIndexHintAction:
        """Restore exactly the prior hint, including an intentionally absent setting."""
        return RestoreQuerySettingsIndexHintAction(
            database=self.database,
            collection=self.collection,
            query_shape_hash=self.query_shape_hash,
            index_hint=self.previous_index_hint,
        )
