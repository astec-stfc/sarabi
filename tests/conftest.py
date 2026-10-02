"""Shared fixtures: a small tree of device definitions covering every protocol."""

import os
import sys
from typing import Dict

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.translator import SchemaTranslator  # noqa: E402

LAURA_SCHEMA = os.path.join(ROOT, "schemas", "laura.json")
TEMPLATES = os.path.join(ROOT, "templates")


def write_device(directory: str, name: str, variables: Dict[str, Dict], **extra) -> str:
    """Write one LAURA-schema device definition and return its path."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{name}.yaml")
    data = {"name": name, "controls": {"variables": variables}}
    data.update(extra)
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    return path


QUAD_01 = {
    "SETI": {
        "identifier": "TEST-S01-MAG-QUAD-01:SETI",
        "dtype": "float",
        "protocol": "TANGO",
        "units": "A",
        "description": "Current setpoint.",
        "readback": "READI",
        "dynamics": {"model": "tests.fakes.HalfWay"},
    },
    "READI": {
        "identifier": "TEST-S01-MAG-QUAD-01:READI",
        "dtype": "float",
        "protocol": "TANGO",
        "read_only": True,
    },
    "NOISE": {
        "identifier": "TEST-S01-MAG-QUAD-01:NOISE",
        "dtype": "float",
        "protocol": "TANGO",
        "update": {"function": "tests.fakes.Clock"},
    },
    "STATE": {
        "identifier": "TEST-S01-MAG-QUAD-01:STATE",
        "dtype": "state",
        "protocol": "TANGO",
        "states": {"OFF": 0, "ON": 1, "FAULT": 2},
    },
    "SETK": {
        "identifier": "TEST-S01-MAG-QUAD-01:SETK",
        "dtype": "float",
        "protocol": "CA",
    },
}

QUAD_02 = {
    "SETI": {
        "identifier": "TEST-S01-MAG-QUAD-02:SETI",
        "dtype": "float",
        "protocol": "TANGO",
        "units": "A",
        "readback": "READI",
    },
    "READI": {
        "identifier": "TEST-S01-MAG-QUAD-02:READI",
        "dtype": "float",
        "protocol": "TANGO",
        "read_only": True,
    },
    "ONLY_HERE": {
        "identifier": "TEST-S01-MAG-QUAD-02:ONLY_HERE",
        "dtype": "string",
        "protocol": "TANGO",
    },
    "SETK": {
        "identifier": "TEST-S01-MAG-QUAD-02:SETK",
        "dtype": "float",
        "protocol": "CA",
    },
}

CAVITY_01 = {
    "PHASE": {"identifier": "TEST-L01-RF-CAV-01:PHASE", "dtype": "float"},
    "AMP": {"identifier": "TEST-L01-RF-CAV-01:AMP", "dtype": "float", "protocol": "PVA"},
    "POWER": {"identifier": "TEST-L01-RF-CAV-01:POWER", "dtype": "float", "protocol": "Tango"},
}


@pytest.fixture
def translator() -> SchemaTranslator:
    return SchemaTranslator(LAURA_SCHEMA)


@pytest.fixture
def devices_dir(tmp_path) -> str:
    """A devices directory with two quadrupoles and one cavity, mixing protocols."""
    root = tmp_path / "devices"
    quads = str(root / "Magnet" / "Quadrupole")
    write_device(quads, "TEST-S01-MAG-QUAD-01", QUAD_01, hardware_type="Quadrupole")
    write_device(quads, "TEST-S01-MAG-QUAD-02", QUAD_02, hardware_type="Quadrupole")
    write_device(str(root / "RF" / "RFCavity"), "TEST-L01-RF-CAV-01", CAVITY_01, hardware_type="RFCavity")
    return str(root)


@pytest.fixture
def settings_file(tmp_path, devices_dir) -> str:
    """A settings YAML pointing at the fixture devices and a temporary output directory."""
    output = tmp_path / "generated"
    output.mkdir()
    path = tmp_path / "settings.yaml"
    with open(path, "w") as f:
        yaml.safe_dump(
            {
                "output_directory": str(output),
                "templates_directory": TEMPLATES,
                "schema_file": LAURA_SCHEMA,
                "devices_directory": devices_dir,
                "ignore_device_types": [],
            },
            f,
        )
    return str(path)
