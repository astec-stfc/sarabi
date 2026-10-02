"""The rendered IOCs, served and talked to over Channel Access and PV Access."""

import math
import sys
import time

import pytest
from caproto.sync.client import read, write
from p4p.client.thread import Context

from conftest import EpicsPorts, running, wait_for_pv

pytestmark = pytest.mark.live

STATES = {"OUT": 0, "IN": 1, "MOVING": 2}
DTYPES = {
    "POS": {"dtype": "scalar"},
    "COUNT": {"dtype": "int"},
    "MODE": {"dtype": "state", "states": STATES},
    "ENABLED": {"dtype": "binary"},
    "TRACE": {"dtype": "waveform"},
    "LABEL": {"dtype": "string"},
}
TAU = 0.3


def over(protocol, variables):
    return {h: {**config, "protocol": protocol} for h, config in variables.items()}


@pytest.fixture(scope="module")
def machine(module_machine):
    machine = module_machine()
    machine.device("ScreenCA/scr.yaml", "SCR-CA", over("CA", DTYPES))
    machine.device("ScreenPVA/scr.yaml", "SCR-PVA", over("PVA", DTYPES))
    machine.device(
        "Magnet/quad.yaml",
        "QUAD",
        over(
            "CA",
            {
                "SETI": {
                    "dtype": "scalar",
                    "readback": "READI",
                    "dynamics": {"model": "simmodels.FirstOrderResponse", "tau": TAU},
                },
                "READI": {"dtype": "scalar"},
                "READK": {
                    "dtype": "scalar",
                    "update": {
                        "function": "simmodels.Sinusoid",
                        "period": 2.0,
                        "amplitude": 0.5,
                    },
                },
            },
        ),
    )
    # Devices with nothing in common, so that every PV is one only some have
    machine.device(
        "Valve/v1.yaml",
        "V1",
        over(
            "CA",
            {
                "OPEN": {"dtype": "scalar", "readback": "OPEN_RB"},
                "OPEN_RB": {"dtype": "scalar"},
            },
        ),
    )
    machine.device("Valve/v2.yaml", "V2", over("CA", {"CLOSE": {"dtype": "scalar"}}))
    machine.device(
        "Kicker/k1.yaml",
        "K1",
        over(
            "PVA",
            {
                "SETV": {"dtype": "scalar", "readback": "READV"},
                "READV": {"dtype": "scalar"},
            },
        ),
    )
    machine.render()
    return machine


@pytest.fixture(scope="module")
def iocs(machine, tmp_path_factory):
    """Every IOC of the machine, serving on ports of its own."""
    ports = EpicsPorts()
    log_file = tmp_path_factory.mktemp("iocs") / "iocs.log"
    command = [
        sys.executable,
        "-u",
        machine.output_directory / "run_all_iocs.py",
        "--timestep=0.05",
    ]
    with running(command, log_file, ports.server_environment(), machine.root) as server:
        server.ports = ports
        yield server
    assert "Traceback" not in server.log, server.log[-3000:]


@pytest.fixture(autouse=True)
def channel_access_client(iocs, monkeypatch):
    """Point caproto's client, which reads its environment at each request, at the IOCs."""
    monkeypatch.setenv("EPICS_CA_SERVER_PORT", str(iocs.ports.ca))
    monkeypatch.setenv("EPICS_CA_ADDR_LIST", "127.0.0.1")
    monkeypatch.setenv("EPICS_CA_AUTO_ADDR_LIST", "NO")
    wait_for_pv(lambda: read("VM-QUAD:SETI", timeout=2))


@pytest.fixture
def pva(iocs):
    with Context("pva", conf=iocs.ports.pva_client, useenv=False) as context:
        wait_for_pv(lambda: context.get("VM-SCR-PVA:POS", timeout=2))
        yield context


def ca_get(pv):
    return read(pv, timeout=5).data


def ca_put(pv, value):
    write(pv, value, timeout=5, notify=True)


def native_type(pv) -> str:
    # The class of data type asked for comes back as one of the PV's own type
    return read(pv, data_type="control", timeout=5).data_type.name.split("_", 1)[1]


def test_channel_access_serves_every_data_type(iocs):
    pv = "VM-SCR-CA:{}".format
    assert {h: native_type(pv(h)) for h in DTYPES} == {
        "POS": "FLOAT",
        "COUNT": "LONG",
        "MODE": "ENUM",
        "ENABLED": "ENUM",
        "TRACE": "FLOAT",
        "LABEL": "STRING",
    }

    ca_put(pv("POS"), 1.5)
    ca_put(pv("COUNT"), 7)
    ca_put(pv("MODE"), 2)
    ca_put(pv("ENABLED"), 1)
    ca_put(pv("LABEL"), "hello")

    assert ca_get(pv("POS"))[0] == 1.5
    assert ca_get(pv("COUNT"))[0] == 7
    assert ca_get(pv("MODE"))[0] == b"MOVING"
    assert ca_get(pv("ENABLED"))[0] == b"On"
    assert ca_get(pv("LABEL"))[0] == b"hello"


def test_a_state_is_written_by_name_or_by_number(iocs):
    ca_put("VM-SCR-CA:MODE", "IN")
    assert ca_get("VM-SCR-CA:MODE")[0] == b"IN"
    ca_put("VM-SCR-CA:MODE", 0)
    assert ca_get("VM-SCR-CA:MODE")[0] == b"OUT"


def test_a_channel_access_waveform_takes_more_than_one_point(iocs):
    points = [float(i) for i in range(1000)]
    ca_put("VM-SCR-CA:TRACE", points)
    assert list(ca_get("VM-SCR-CA:TRACE")) == points


def test_pv_access_serves_every_data_type(pva):
    """Including those that once could not be constructed, or not be put to.

    An enumeration was given its states in a way p4p refused, waveforms,
    strings and binaries named a method that was never rendered, and putting to
    an enumeration raised in the IOC.
    """
    pv = "VM-SCR-PVA:{}".format
    values = {
        "POS": 1.5,
        "COUNT": 7,
        "MODE": 2,
        "ENABLED": True,
        "TRACE": [1.0, 2.5],
        "LABEL": "hello",
    }
    for handle, value in values.items():
        pva.put(pv(handle), value, timeout=5)

    raw = {handle: pva.get(pv(handle), timeout=5).raw for handle in values}

    assert {h: raw[h].type()["value"] for h in values if h != "MODE"} == {
        "POS": "d",
        "COUNT": "l",
        "ENABLED": "?",
        "TRACE": "ad",
        "LABEL": "s",
    }
    assert raw["MODE"].getID().startswith("epics:nt/NTEnum")
    assert raw["POS"].value == 1.5
    assert raw["COUNT"].value == 7
    assert raw["ENABLED"].value is True
    assert list(raw["TRACE"].value) == [1.0, 2.5]
    assert raw["LABEL"].value == "hello"
    # Its states survive being put to
    assert raw["MODE"].value.choices[raw["MODE"].value.index] == "MOVING"
    assert list(raw["MODE"].value.choices) == list(STATES)


def test_a_readback_follows_its_setpoint_through_its_dynamics(iocs):
    ca_put("VM-QUAD:SETI", 0.0)
    time.sleep(3 * TAU)
    ca_put("VM-QUAD:SETI", 10.0)
    time.sleep(1.0)
    readback = ca_get("VM-QUAD:READI")[0]
    # A first order response, from wherever the last test left it
    assert readback == pytest.approx(10 * (1 - math.exp(-1.0 / TAU)), abs=0.6)
    assert readback < 10.0


def test_an_update_signal_generates_a_value(iocs):
    first = ca_get("VM-QUAD:READK")[0]
    time.sleep(0.5)
    second = ca_get("VM-QUAD:READK")[0]
    assert first != second
    assert abs(first) <= 0.5 and abs(second) <= 0.5


def test_a_device_with_only_optional_pvs_is_simulated(iocs):
    """Only PVs every device has could once start the simulation, and V1 has none."""
    ca_put("VM-V1:OPEN", 42.0)
    time.sleep(0.5)
    assert ca_get("VM-V1:OPEN_RB")[0] == 42.0
    assert ca_get("VM-V2:CLOSE")[0] == 0.0


def test_pv_access_pvs_are_simulated(pva):
    pva.put("VM-K1:SETV", 3.5, timeout=5)
    time.sleep(0.5)
    assert pva.get("VM-K1:READV", timeout=5) == 3.5


def test_both_protocols_are_found_when_the_environment_gives_them_one_port(
    machine, tmp_path, monkeypatch
):
    """As a shell profile might. Whichever bound it last took every search."""
    ports = EpicsPorts()
    environment = ports.server_environment(EPICS_PVA_BROADCAST_PORT=ports.ca)
    command = [sys.executable, "-u", machine.output_directory / "run_all_iocs.py"]
    monkeypatch.setenv("EPICS_CA_SERVER_PORT", str(ports.ca))
    # Asked of the server itself, so as not to depend on where searches were moved to
    name_server = {
        "EPICS_PVA_NAME_SERVERS": f"127.0.0.1:{ports.pva}",
        "EPICS_PVA_AUTO_ADDR_LIST": "NO",
        "EPICS_PVA_ADDR_LIST": "",
    }

    with running(command, tmp_path / "iocs.log", environment, machine.root) as server:
        for _ in range(3):
            assert wait_for_pv(lambda: read("VM-QUAD:SETI", timeout=2)).data[0] == 0.0
        with Context("pva", conf=name_server, useenv=False) as context:
            assert wait_for_pv(lambda: context.get("VM-K1:SETV", timeout=2)) == 0.0
        assert "which is the Channel Access port" in server.log
        conf = server.log
    assert f"'EPICS_PVAS_BROADCAST_PORT': '{ports.ca}'" not in conf
