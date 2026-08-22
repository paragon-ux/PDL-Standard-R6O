from __future__ import annotations

"""Local jsonschema registry so $refs resolve from the contracts directory."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRACTS = Path(__file__).resolve().parent / "contracts"


def build_registry() -> Registry:
    resources = {}
    for path in CONTRACTS.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        uri = schema.get("$id")
        if uri:
            resources[uri] = Resource.from_contents(schema)
    return Registry().with_resources(resources.items())


def make_validator(schema: dict) -> Draft202012Validator:
    return Draft202012Validator(schema, registry=build_registry())

