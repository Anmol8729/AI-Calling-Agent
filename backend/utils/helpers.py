import uuid as _uuid
from datetime import datetime, date
from typing import Any, Optional

from fastapi.responses import JSONResponse
from sqlalchemy import inspect as sa_inspect


def to_uuid(value: Any) -> Optional[_uuid.UUID]:
    """Best-effort conversion of a value to a uuid.UUID, or None if invalid.

    Used to safely coerce string ids coming from JWTs / path params into the
    UUID type expected by the Postgres columns.
    """
    if value is None:
        return None
    if isinstance(value, _uuid.UUID):
        return value
    try:
        return _uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def serialize_model(obj: Any) -> Optional[dict]:
    """Convert a SQLAlchemy model instance into a JSON-safe dict.

    - UUID values become strings (so the API keeps returning string ids, as the
      previous Mongo `_id -> id` serialization did).
    - datetime/date values become ISO strings.
    - JSONB fields (lists/dicts) pass through unchanged.
    """
    if obj is None:
        return None
    result: dict = {}
    for attr in sa_inspect(obj).mapper.column_attrs:
        key = attr.key
        val = getattr(obj, key)
        if isinstance(val, _uuid.UUID):
            val = str(val)
        elif isinstance(val, (datetime, date)):
            val = val.isoformat()
        result[key] = val
    return result


def serialize_models(objs: list) -> list:
    return [serialize_model(obj) for obj in objs if obj is not None]


def api_response(
    success: bool,
    message: str,
    data: Optional[Any] = None,
    error: Optional[Any] = None,
    status_code: int = 200,
    meta: Optional[dict] = None,
) -> JSONResponse:
    """Standard response envelope.

    `meta` carries out-of-band information such as pagination state. It sits beside
    `data` rather than inside it so a list endpoint can gain paging without changing
    the shape of `data` and breaking existing dashboard code. Omitted entirely when
    unused, so every other response is unchanged.
    """
    content = {
        "success": success,
        "message": message,
        "data": data,
        "error": error,
    }
    if meta is not None:
        content["meta"] = meta
    return JSONResponse(status_code=status_code, content=content)
