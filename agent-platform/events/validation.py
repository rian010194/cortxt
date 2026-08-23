from __future__ import annotations

import re
from typing import Any, Mapping

from .errors import EventError


def validate_data(value: Any, schema: Mapping[str, Any], path: str = "$") -> None:
    """Validate a value against a closed JSON schema dictionary."""
    expected = schema.get("type")
    matches = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "null": lambda v: v is None,
    }

    if expected is not None:
        expected_types = expected if isinstance(expected, list) else [expected]
        if not any(item in matches and matches[item](value) for item in expected_types):
            types_str = ", ".join(expected_types)
            raise EventError("validation_error", f"{path}: expected type {types_str}, got {type(value).__name__}")

    if "const" in schema and value != schema["const"]:
        raise EventError("validation_error", f"{path}: expected {schema['const']!r}")

    if "enum" in schema and value not in schema["enum"]:
        raise EventError("validation_error", f"{path}: value {value!r} not in enum {schema['enum']}")

    if "pattern" in schema and isinstance(value, str):
        if not re.search(schema["pattern"], value):
            raise EventError("validation_error", f"{path}: string does not match pattern {schema['pattern']}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise EventError("validation_error", f"{path}: missing required field: {sorted(missing)[0]}")

        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise EventError("validation_error", f"{path}: unknown field: {sorted(unknown)[0]}")

        for key, item in value.items():
            if key in properties:
                validate_data(item, properties[key], f"{path}.{key}")

    elif isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise EventError("validation_error", f"{path}: array length exceeds maxItems {schema['maxItems']}")
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise EventError("validation_error", f"{path}: array length below minItems {schema['minItems']}")
        if "items" in schema:
            for index, item in enumerate(value):
                validate_data(item, schema["items"], f"{path}[{index}]")

    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise EventError("validation_error", f"{path}: value {value} below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise EventError("validation_error", f"{path}: value {value} above maximum {schema['maximum']}")
