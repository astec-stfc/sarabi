from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Dict, Iterable, Optional, Set

import yaml

from .translator import SchemaTranslator


_SCHEMA_SUFFIXES = ("_schema.yaml", "_schema.yml")


@dataclass
class ResolvedDeviceConfig:
    file_path: str
    device_name: str
    pv_map: Dict[str, Any]
    uses_schema: bool
    schema_path: Optional[str] = None
    schema_handles: Optional[Set[str]] = None


def is_schema_yaml(path_or_name: str) -> bool:
    return os.path.basename(path_or_name).lower().endswith(_SCHEMA_SUFFIXES)


def iter_yaml_files(device_path: str, recursive: bool = True) -> Iterable[str]:
    if recursive:
        for root, _, files in os.walk(device_path):
            for file_name in files:
                if file_name.lower().endswith((".yaml", ".yml")):
                    yield os.path.join(root, file_name)
    else:
        for file_name in os.listdir(device_path):
            if file_name.lower().endswith((".yaml", ".yml")):
                yield os.path.join(device_path, file_name)


def _load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data or {}


def _expand_identifier_templates(
    pv_map: Dict[str, Any], identifier_pattern: str, identifier_key: str
) -> Dict[str, Any]:
    expanded: Dict[str, Any] = {}
    for handle, config in pv_map.items():
        if not isinstance(config, dict):
            expanded[handle] = config
            continue
        cfg = dict(config)
        identifier = cfg.get(identifier_key)
        if isinstance(identifier, str):
            cfg[identifier_key] = identifier.replace("{name}", identifier_pattern)
        expanded[handle] = cfg
    return expanded


def _merge_variable_maps(
    schema_variables: Dict[str, Any], inline_variables: Dict[str, Any]
) -> Dict[str, Any]:
    merged: Dict[str, Any] = {handle: value for handle, value in schema_variables.items()}
    for handle, inline_value in inline_variables.items():
        schema_value = merged.get(handle)
        if isinstance(schema_value, dict) and isinstance(inline_value, dict):
            merged[handle] = {**schema_value, **inline_value}
        else:
            merged[handle] = inline_value
    return merged


def resolve_device_config(
    yaml_file_path: str, translator: SchemaTranslator
) -> ResolvedDeviceConfig:
    data = _load_yaml(yaml_file_path)
    device_name = data.get("name", os.path.splitext(os.path.basename(yaml_file_path))[0])

    controls = data.get(translator.controls_information_word, {}) or {}
    inline_variables = controls.get(translator.signal_information_word, {}) or {}

    schema_ref = controls.get("schema")
    uses_schema = bool(schema_ref)
    schema_variables: Dict[str, Any] = {}
    schema_handles: Optional[Set[str]] = None
    schema_path: Optional[str] = None

    if uses_schema:
        identifier_pattern = controls.get("identifier_pattern", device_name)
        if not identifier_pattern:
            raise ValueError(
                f"Missing controls.identifier_pattern or name in '{yaml_file_path}' while controls.schema is set."
            )
        schema_path = os.path.join(os.path.dirname(yaml_file_path), schema_ref)
        if not os.path.exists(schema_path):
            raise FileNotFoundError(
                f"Schema file '{schema_ref}' referenced by '{yaml_file_path}' was not found at '{schema_path}'."
            )
        schema_data = _load_yaml(schema_path)
        schema_variables = schema_data.get(translator.signal_information_word, {}) or {}
        schema_handles = set(schema_variables.keys())
        schema_variables = _expand_identifier_templates(
            schema_variables,
            identifier_pattern=identifier_pattern,
            identifier_key=translator.identifier_word,
        )

    pv_map = _merge_variable_maps(schema_variables, inline_variables)

    return ResolvedDeviceConfig(
        file_path=yaml_file_path,
        device_name=device_name,
        pv_map=pv_map,
        uses_schema=uses_schema,
        schema_path=schema_path,
        schema_handles=schema_handles,
    )
