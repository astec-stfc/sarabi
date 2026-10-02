import warnings

import pytest

from core import protocols
from core.protocols import CA, PVA, TANGO, normalise_protocol, protocol_of, split_by_protocol


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, CA),
        ("", CA),
        ("CA", CA),
        ("ca", CA),
        ("EPICS", CA),
        ("epics_ca", CA),
        ("PVA", PVA),
        ("EPICS-PVA", PVA),
        ("TANGO", TANGO),
        ("Tango", TANGO),
        (" tango ", TANGO),
        ("pytango", TANGO),
    ],
)
def test_normalise_protocol(value, expected):
    assert normalise_protocol(value) == expected


def test_unknown_protocol_warns_once_and_defaults_to_ca():
    protocols._warned.clear()
    with pytest.warns(UserWarning, match="Unknown protocol 'MODBUS'"):
        assert normalise_protocol("MODBUS") == CA
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert normalise_protocol("modbus") == CA  # same spelling, reported already


def test_protocol_of_reads_the_translated_key():
    assert protocol_of({"protocol": "TANGO"}) == TANGO
    assert protocol_of({"proto": "TANGO"}, protocol_word="proto") == TANGO
    assert protocol_of({}) == CA
    assert protocol_of("not a mapping") == CA


def test_split_by_protocol_has_an_entry_for_every_protocol():
    groups = split_by_protocol(
        {"A": {"protocol": "CA"}, "B": {"protocol": "Tango"}, "C": {}, "D": {"protocol": "PVA"}}
    )
    assert set(groups) == {CA, PVA, TANGO}
    assert list(groups[CA]) == ["A", "C"]
    assert list(groups[PVA]) == ["D"]
    assert list(groups[TANGO]) == ["B"]
    assert split_by_protocol({}) == {CA: {}, PVA: {}, TANGO: {}}
