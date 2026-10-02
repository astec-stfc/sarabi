"""Where a variable served over TANGO is found on the network."""

import pytest

from core.tango_naming import attribute_address, attribute_name, tango_devices
from core.translator import SchemaTranslator

from conftest import SARABI_ROOT


def _address(identifier, handle="SETI"):
    device, attribute = attribute_address(
        identifier, handle, "Magnet", "JFEL-S02-MAG-QUAD-03"
    )
    return f"{device}/{attribute}"


@pytest.mark.parametrize(
    "identifier, expected",
    [
        # The three rows of the table in the README
        ("jfel/magnet/quad-03/current", "VM-jfel/magnet/quad-03/current"),
        ("jfel/magnet/quad-03", "VM-jfel/magnet/quad-03/SETI"),
        ("JFEL-S02-MAG-QUAD-03:SETI", "VM/Magnet/JFEL-S02-MAG-QUAD-03/SETI"),
        # However fully a TANGO name is given
        ("tango://host:10000/a/b/c/d", "VM-a/b/c/d"),
        ("tango://host:10000/a/b/c/d#dbase=no", "VM-a/b/c/d"),
        (None, "VM/Magnet/JFEL-S02-MAG-QUAD-03/SETI"),
    ],
)
def test_attribute_address(identifier, expected):
    assert _address(identifier) == expected


def test_a_handle_that_is_not_a_name_is_made_one():
    assert _address("CAM-01:ANA:X_RBV", handle="X RBV").endswith("/X_RBV")


@pytest.mark.parametrize(
    "text, expected",
    [
        ("SETI", "SETI"),
        ("A-B", "A_B"),
        ("1ST", "_1ST"),
        # Every TANGO device has these already, whatever their case
        ("STATE", "STATE_"),
        ("Status", "Status_"),
        # It is also to be the name of a Python attribute
        ("class", "class_"),
    ],
)
def test_attribute_name(text, expected):
    assert attribute_name(text) == expected
    assert attribute_name(text).isidentifier()


@pytest.fixture
def translator():
    return SchemaTranslator(SARABI_ROOT / "schemas" / "laura.json")


def test_only_named_tango_variables_are_served(translator):
    variables = {
        "A": {"identifier": "X:A", "protocol": "tango"},
        "B": {"identifier": "X:B", "protocol": "CA"},
        "C": {"identifier": "X:C"},
        "D": {"protocol": "TANGO"},
        "E": "not a mapping",
    }
    assert tango_devices("T", "dev", variables, translator) == {"VM/T/dev": {"A": "A"}}


def test_identifiers_can_spread_a_definition_over_several_devices(translator):
    variables = {
        "X": {"identifier": "jfel/dia/bpm-01/xpos", "protocol": "TANGO"},
        "Y": {"identifier": "BPM-01:Y", "protocol": "TANGO"},
    }
    assert tango_devices("BPM", "BPM-01", variables, translator) == {
        "VM-jfel/dia/bpm-01": {"xpos": "X"},
        "VM/BPM/BPM-01": {"Y": "Y"},
    }


def test_attributes_differing_only_by_case_are_the_same_to_tango(translator):
    variables = {
        "SETI": {"identifier": "X:SETI", "protocol": "TANGO"},
        "seti": {"identifier": "X:seti", "protocol": "TANGO"},
    }
    with pytest.warns(UserWarning, match="both the TANGO attribute"):
        devices = tango_devices("T", "dev", variables, translator)
    assert devices == {"VM/T/dev": {"SETI": "SETI"}}
