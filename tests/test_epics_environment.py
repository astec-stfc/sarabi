"""The ports the IOCs serve on."""

import os
import warnings

import pytest

from core import helper

PORT_VARIABLES = (
    "EPICS_CA_SERVER_PORT",
    "EPICS_PVA_SERVER_PORT",
    "EPICS_PVA_BROADCAST_PORT",
    "EPICS_PVAS_BROADCAST_PORT",
)


def _configure(monkeypatch, **environment):
    """The Channel Access port, and the PV Access TCP and UDP ports, chosen."""
    # An environment of the test's own, as the ports chosen are written to it
    own = {
        key: value
        for key, value in os.environ.items()
        if key not in (*PORT_VARIABLES, "EPICS_CA_ADDR_LIST")
    }
    own.update(environment)
    monkeypatch.setattr(os, "environ", own)
    helper.configure_epics_environment()
    # A server prefers the variable for servers alone, where there is one
    searches = os.getenv("EPICS_PVAS_BROADCAST_PORT") or os.getenv(
        "EPICS_PVA_BROADCAST_PORT"
    )
    return (
        os.environ["EPICS_CA_SERVER_PORT"],
        os.environ["EPICS_PVA_SERVER_PORT"],
        searches,
    )


def test_defaults_keep_away_from_the_physical_control_system(monkeypatch):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _configure(monkeypatch) == ("6090", "6091", "6091")
    assert os.environ["EPICS_CA_ADDR_LIST"] == "localhost"


def test_ports_the_environment_chooses_are_kept(monkeypatch):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ports = _configure(
            monkeypatch,
            EPICS_CA_SERVER_PORT="7000",
            EPICS_PVA_SERVER_PORT="7001",
            EPICS_PVA_BROADCAST_PORT="7002",
        )
    assert ports == ("7000", "7001", "7002")


def test_the_variable_for_servers_alone_is_honoured(monkeypatch):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ports = _configure(monkeypatch, EPICS_PVAS_BROADCAST_PORT="7777")
    assert ports == ("6090", "6091", "7777")


@pytest.mark.parametrize(
    "environment, expected",
    [
        # As a shell profile might: both protocols would search on one UDP port
        (
            {"EPICS_CA_SERVER_PORT": "6090", "EPICS_PVA_BROADCAST_PORT": "6090"},
            ("6090", "6091", "6091"),
        ),
        ({"EPICS_PVAS_BROADCAST_PORT": "6090"}, ("6090", "6091", "6091")),
        # Moved onto the default for PV Access searches, which moves on again
        ({"EPICS_CA_SERVER_PORT": "6091"}, ("6091", "6091", "6092")),
    ],
)
def test_pv_access_is_moved_off_the_channel_access_port(
    monkeypatch, environment, expected
):
    with pytest.warns(UserWarning, match="which is the Channel Access port"):
        ports = _configure(monkeypatch, **environment)
    assert ports == expected
    assert ports[0] != ports[2]
