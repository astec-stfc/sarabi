"""Which control system serves a variable."""

import pytest

from core import helper
from core.protocols import CA, PVA, TANGO, protocol_of
from core.pv_info import PVInfo


@pytest.mark.parametrize(
    "config, expected",
    [
        ({"protocol": "CA"}, CA),
        ({"protocol": "PVA"}, PVA),
        ({"protocol": "TANGO"}, TANGO),
        ({"protocol": "tango"}, TANGO),
        ({"protocol": " Tango "}, TANGO),
        # One that names none is served over Channel Access, as it always was
        ({}, CA),
        ({"protocol": None}, CA),
        # Served by nothing, rather than by whatever comes last
        ({"protocol": "MODBUS"}, "MODBUS"),
        ("not a mapping", ""),
    ],
)
def test_protocol_of(config, expected):
    assert protocol_of(config) == expected


def test_protocol_is_read_from_the_key_the_schema_names():
    assert protocol_of({"transport": "PVA"}, "transport") == PVA


VARIABLES = {
    "A": {"protocol": "CA"},
    "B": {"protocol": "PVA"},
    "C": {"protocol": "TANGO"},
    "D": {},
    "E": {"protocol": "MODBUS"},
    "F": "not a mapping",
}


def test_pv_info_splits_variables_three_ways():
    info = PVInfo(pv_map=VARIABLES)
    assert set(info.channel_access_pvs) == {"A", "D"}
    assert set(info.pv_access_pvs) == {"B"}
    assert set(info.tango_pvs) == {"C"}


def test_tango_variables_are_not_mistaken_for_pv_access():
    """Anything that was not Channel Access used to be served over PV Access."""
    variables = {k: v for k, v in VARIABLES.items() if isinstance(v, dict)}
    ca, pva = helper.separate_by_protocol(variables)
    assert set(ca) == {"A", "D"}
    assert set(pva) == {"B"}
