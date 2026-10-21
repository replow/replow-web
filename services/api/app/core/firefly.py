from copy import deepcopy
from typing import Any


SENSITIVE_PARTS = {
    "password",
    "secret",
    "token",
    "apikey",
    "api_token",
    "access_key",
    "private_key",
    "auth",
}


def public_firefly_config(value: Any) -> Any:
    """Remove credentials before the Firefly object is sent to browsers."""
    if isinstance(value, list):
        return [public_firefly_config(item) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).replace("-", "_").lower()
        if any(part in normalized for part in SENSITIVE_PARTS):
            result[key] = ""
        else:
            result[key] = public_firefly_config(item)
    return result


def firefly_group(config: dict[str, Any], *names: str) -> dict[str, Any]:
    for name in names:
        value = config.get(name)
        if isinstance(value, dict):
            return value
    return {}


def first_image(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return ""
