"""Fail-closed validation for the checked JSON Schema subset used here.

This is not a general JSON Schema implementation.  It validates every
assertion keyword used by the bundled Draft 2020-12 schemas and rejects a
schema that introduces an unsupported assertion keyword.  Keeping the
validator in the standard library preserves the engine-independent package's
dependency boundary.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any


class CheckedSchemaError(ValueError):
    """Raised when a checked schema or instance is outside the supported subset."""


_ANNOTATIONS = frozenset({"$id", "$schema", "title", "description"})
_ASSERTIONS = frozenset(
    {
        "$defs",
        "$ref",
        "additionalProperties",
        "allOf",
        "const",
        "else",
        "enum",
        "if",
        "items",
        "maxItems",
        "maximum",
        "minItems",
        "minimum",
        "not",
        "oneOf",
        "pattern",
        "properties",
        "required",
        "then",
        "type",
        "uniqueItems",
    }
)
_SCHEMA_KEYS = _ANNOTATIONS | _ASSERTIONS
_JSON_TYPES = frozenset({"array", "boolean", "integer", "null", "number", "object", "string"})


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise CheckedSchemaError(f"value is not finite JSON data: {exc}") from exc


def _schema_object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CheckedSchemaError(f"{path}: schema object required")
    unknown = set(value) - _SCHEMA_KEYS
    if unknown:
        raise CheckedSchemaError(f"{path}: unsupported schema keywords: {sorted(unknown)}")
    return value


def check_schema_supported(schema: Mapping[str, Any]) -> None:
    """Validate that the schema uses only the complete checked subset."""

    root = _schema_object(schema, "$")

    def walk(node: Any, path: str) -> None:
        current = _schema_object(node, path)
        schema_type = current.get("type")
        if schema_type is not None:
            types = [schema_type] if isinstance(schema_type, str) else schema_type
            if (
                not isinstance(types, Sequence)
                or isinstance(types, (str, bytes))
                or not types
                or any(not isinstance(item, str) or item not in _JSON_TYPES for item in types)
                or len(set(types)) != len(types)
            ):
                raise CheckedSchemaError(f"{path}.type: invalid JSON type declaration")
        for name in ("required",):
            if name in current:
                value = current[name]
                if (
                    not isinstance(value, list)
                    or any(not isinstance(item, str) for item in value)
                    or len(set(value)) != len(value)
                ):
                    raise CheckedSchemaError(f"{path}.{name}: unique string list required")
        for name in ("minItems", "maxItems"):
            if name in current and (
                not isinstance(current[name], int)
                or isinstance(current[name], bool)
                or current[name] < 0
            ):
                raise CheckedSchemaError(f"{path}.{name}: nonnegative integer required")
        if "minItems" in current and "maxItems" in current and current["minItems"] > current["maxItems"]:
            raise CheckedSchemaError(f"{path}: minItems exceeds maxItems")
        for name in ("minimum", "maximum"):
            if name in current and (
                not isinstance(current[name], (int, float))
                or isinstance(current[name], bool)
                or not math.isfinite(float(current[name]))
            ):
                raise CheckedSchemaError(f"{path}.{name}: finite number required")
        if "pattern" in current:
            if not isinstance(current["pattern"], str):
                raise CheckedSchemaError(f"{path}.pattern: string required")
            try:
                re.compile(current["pattern"])
            except re.error as exc:
                raise CheckedSchemaError(f"{path}.pattern: invalid regular expression: {exc}") from exc
        if "additionalProperties" in current and current["additionalProperties"] is not False:
            raise CheckedSchemaError(
                f"{path}.additionalProperties: only fail-closed false is supported"
            )
        for name in ("properties", "$defs"):
            if name in current:
                collection = current[name]
                if not isinstance(collection, Mapping) or any(not isinstance(key, str) for key in collection):
                    raise CheckedSchemaError(f"{path}.{name}: object required")
                for key, child in collection.items():
                    walk(child, f"{path}.{name}.{key}")
        if "items" in current:
            walk(current["items"], f"{path}.items")
        for name in ("if", "then", "else", "not"):
            if name in current:
                walk(current[name], f"{path}.{name}")
        for name in ("allOf", "oneOf"):
            if name in current:
                children = current[name]
                if not isinstance(children, list) or not children:
                    raise CheckedSchemaError(f"{path}.{name}: nonempty schema list required")
                for index, child in enumerate(children):
                    walk(child, f"{path}.{name}[{index}]")
        if "$ref" in current:
            reference = current["$ref"]
            if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
                raise CheckedSchemaError(f"{path}.$ref: only local $defs references are supported")
            name = reference.removeprefix("#/$defs/")
            if not name or name not in root.get("$defs", {}):
                raise CheckedSchemaError(f"{path}.$ref: unresolved local definition {reference!r}")
        if "enum" in current and (not isinstance(current["enum"], list) or not current["enum"]):
            raise CheckedSchemaError(f"{path}.enum: nonempty array required")
        if "uniqueItems" in current and current["uniqueItems"] is not True:
            raise CheckedSchemaError(f"{path}.uniqueItems: only true is supported")

    walk(root, "$")


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, Mapping)
    raise CheckedSchemaError(f"unsupported JSON type: {expected}")


def validate_instance(instance: Any, schema: Mapping[str, Any], *, label: str = "instance") -> None:
    """Validate one instance against every assertion in a checked schema."""

    check_schema_supported(schema)
    root = schema

    def validate(value: Any, node: Mapping[str, Any], path: str) -> None:
        if "$ref" in node:
            name = node["$ref"].removeprefix("#/$defs/")
            validate(value, root["$defs"][name], path)
        if "allOf" in node:
            for child in node["allOf"]:
                validate(value, child, path)
        if "oneOf" in node:
            matches = 0
            for child in node["oneOf"]:
                try:
                    validate(value, child, path)
                except CheckedSchemaError:
                    continue
                matches += 1
            if matches != 1:
                raise CheckedSchemaError(f"{path}: expected exactly one oneOf branch, matched {matches}")
        if "not" in node:
            try:
                validate(value, node["not"], path)
            except CheckedSchemaError:
                pass
            else:
                raise CheckedSchemaError(f"{path}: value matches prohibited `not` schema")
        if "if" in node:
            try:
                validate(value, node["if"], path)
            except CheckedSchemaError:
                branch = node.get("else")
            else:
                branch = node.get("then")
            if branch is not None:
                validate(value, branch, path)

        expected_type = node.get("type")
        if expected_type is not None:
            types = [expected_type] if isinstance(expected_type, str) else expected_type
            if not any(_matches_type(value, item) for item in types):
                raise CheckedSchemaError(f"{path}: expected type {types}, found {type(value).__name__}")
        if "const" in node and _canonical(value) != _canonical(node["const"]):
            raise CheckedSchemaError(f"{path}: const mismatch")
        if "enum" in node and all(_canonical(value) != _canonical(item) for item in node["enum"]):
            raise CheckedSchemaError(f"{path}: value is outside enum")

        if isinstance(value, Mapping):
            required = set(node.get("required", []))
            missing = required - set(value)
            if missing:
                raise CheckedSchemaError(f"{path}: missing required properties {sorted(missing)}")
            properties = node.get("properties", {})
            if node.get("additionalProperties") is False:
                extra = set(value) - set(properties)
                if extra:
                    raise CheckedSchemaError(f"{path}: unrecognized properties {sorted(extra)}")
            for key, child in properties.items():
                if key in value:
                    validate(value[key], child, f"{path}.{key}")

        if isinstance(value, list):
            if "minItems" in node and len(value) < node["minItems"]:
                raise CheckedSchemaError(f"{path}: fewer than {node['minItems']} items")
            if "maxItems" in node and len(value) > node["maxItems"]:
                raise CheckedSchemaError(f"{path}: more than {node['maxItems']} items")
            if node.get("uniqueItems") is True:
                rendered = [_canonical(item) for item in value]
                if len(set(rendered)) != len(rendered):
                    raise CheckedSchemaError(f"{path}: duplicate array item")
            if "items" in node:
                for index, item in enumerate(value):
                    validate(item, node["items"], f"{path}[{index}]")

        if isinstance(value, str) and "pattern" in node and re.search(node["pattern"], value) is None:
            raise CheckedSchemaError(f"{path}: string does not match required pattern")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(float(value)):
                raise CheckedSchemaError(f"{path}: nonfinite number")
            if "minimum" in node and value < node["minimum"]:
                raise CheckedSchemaError(f"{path}: value is below minimum")
            if "maximum" in node and value > node["maximum"]:
                raise CheckedSchemaError(f"{path}: value is above maximum")

    validate(instance, schema, label)
