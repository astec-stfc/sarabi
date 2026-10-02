import os
import re
import threading

import pytest

from core import tango_helper as th
from core.device.base_server import TangoAttribute, TangoDeviceSpec, TangoSimulatedDevice
from tests.conftest import QUAD_01, QUAD_02


@pytest.mark.parametrize(
    "field, expected",
    [
        ("JFEL-L01-MAG-SOL-01", "JFEL-L01-MAG-SOL-01"),
        ("a b/c#d*e:f", "a_b_c_d_e_f"),
        ("  ", "unnamed"),
    ],
)
def test_sanitise_field(field, expected):
    assert th.sanitise_field(field) == expected


@pytest.mark.parametrize(
    "name, expected",
    [
        ("CalcK", "CalcK"),
        ("2X-Y", "_2X_Y"),
        ("a.b c", "a_b_c"),
        ("STATE", "STATE_"),
        ("status", "status_"),
        ("", "unnamed"),
    ],
)
def test_sanitise_attribute_name(name, expected):
    assert th.sanitise_attribute_name(name) == expected


def test_is_tango_address():
    assert th.is_tango_address("sys/tg_test/1/ampli")
    assert not th.is_tango_address("sys/tg_test/1")
    assert not th.is_tango_address("JFEL-L01-MAG-SOL-01:CalcK")
    assert not th.is_tango_address(None)


def test_tango_attribute_name_from_identifier_or_handle():
    assert th.tango_attribute_name("JFEL-L01-MAG-SOL-01:CalcK", "READK") == "CalcK"
    assert th.tango_attribute_name("JFEL-L01-MAG-SOL-01", "READK") == "READK"
    assert th.tango_attribute_name("JFEL-L01-MAG-SOL-01:", "READK") == "READK"
    assert th.tango_attribute_name(None, "READK") == "READK"
    assert th.tango_attribute_name("sys/tg_test/1/ampli", "H") == "ampli"
    assert th.tango_attribute_name("sys/tg_test/1/a/b", "H") == "a_b"
    assert th.tango_attribute_name("X:STATE", "STATE") == "STATE_"


def test_tango_device_name_is_derived_or_taken_from_identifiers():
    assert th.tango_device_name("JFEL-L01-MAG-SOL-01", "Solenoid") == "VM/Solenoid/JFEL-L01-MAG-SOL-01"
    assert th.tango_device_name("x", "Magnet", ["x:CalcK", None]) == "VM/Magnet/x"
    assert th.tango_device_name("x", "Magnet", ["sys/tg_test/1/ampli"]) == "VM-sys/tg_test/1"
    with pytest.warns(UserWarning, match="more than one TANGO device"):
        assert th.tango_device_name("x", "M", ["b/b/b/a", "a/a/a/a"]) == "VM-a/a/a"


def test_common_attribute_names(translator):
    names = th.common_attribute_names([QUAD_01, QUAD_02], translator)
    assert names == {
        "SETI": "SETI",
        "READI": "READI",
        "NOISE": "NOISE",
        "STATE": "STATE_",
        "SETK": "SETK",
        "ONLY_HERE": "ONLY_HERE",
    }


def test_common_attribute_names_falls_back_to_handle_on_disagreement(translator):
    maps = [{"READK": {"identifier": "A:CalcK"}}, {"READK": {"identifier": "B:READK"}}]
    with pytest.warns(UserWarning, match="several TANGO attribute names"):
        assert th.common_attribute_names(maps, translator) == {"READK": "READK"}


def test_addresses_follow_environment(monkeypatch):
    monkeypatch.delenv("SARABI_TANGO_HOST", raising=False)
    monkeypatch.delenv("SARABI_TANGO_PORT", raising=False)
    assert th.device_address("VM/T/1") == "tango://127.0.0.1:10090/VM/T/1#dbase=no"
    monkeypatch.setenv("SARABI_TANGO_HOST", "10.0.0.1")
    monkeypatch.setenv("SARABI_TANGO_PORT", "12345")
    assert th.tango_host() == "10.0.0.1" and th.tango_port() == 12345
    assert th.attribute_address("VM/T/1", "X") == "tango://10.0.0.1:12345/VM/T/1/X#dbase=no"
    assert th.device_address("VM/T/1", "h", 1) == "tango://h:1/VM/T/1#dbase=no"


class QuadDevice(TangoSimulatedDevice):
    SETI = TangoAttribute(name="SETI", dtype=float)
    READI = TangoAttribute(name="READI", dtype=float)
    NOISE = TangoAttribute(name="NOISE", dtype=float)
    STATE = TangoAttribute(name="STATE_", dtype=int)


def test_construct_tango_devices_registers_a_spec(translator):
    devices = th.construct_tango_devices(
        {h: c for h, c in QUAD_01.items() if h != "SETK"},
        "TEST-S01-MAG-QUAD-01",
        "Quadrupole",
        device_cls=QuadDevice,
        translator=translator,
        timestep=0.25,
    )
    name = "VM/Quadrupole/TEST-S01-MAG-QUAD-01"
    assert devices == {name: {"SETI": "SETI", "READI": "READI", "NOISE": "NOISE", "STATE_": "STATE"}}
    assert QuadDevice.configured_devices() == [name.lower()]
    spec = QuadDevice._specs[name.lower()]
    assert isinstance(spec, TangoDeviceSpec)
    assert spec.handles == ["SETI", "READI", "NOISE", "STATE"]
    assert spec.timestep == 0.25
    assert [(p.setpoint, p.readback) for p in spec.pv_pairs] == [("SETI", "READI")]
    assert spec.pv_pairs[0].dynamics is not None
    assert [u.handle for u in spec.updates] == ["NOISE"]
    # The base class registry is untouched.
    assert TangoSimulatedDevice.configured_devices() == []


def test_construct_tango_devices_skips_undeclared_handles(translator, capsys):
    # SETI names READI as its readback, which this map lacks: reported, not fatal.
    with pytest.warns(UserWarning, match="Cannot find PV 'READI'"):
        devices = th.construct_tango_devices(
            {"SETI": QUAD_02["SETI"], "ONLY_HERE": QUAD_02["ONLY_HERE"]},
            "TEST-S01-MAG-QUAD-02",
            "Quadrupole",
            device_cls=QuadDevice,
            translator=translator,
        )
    assert devices == {"VM/Quadrupole/TEST-S01-MAG-QUAD-02": {"SETI": "SETI"}}
    assert "'ONLY_HERE' not found" in capsys.readouterr().out


def test_construct_tango_devices_requires_class_and_translator(translator):
    with pytest.raises(ValueError):
        th.construct_tango_devices({"A": {}}, "d", "T", translator=translator)
    with pytest.raises(ValueError):
        th.construct_tango_devices({"A": {}}, "d", "T", device_cls=QuadDevice)
    assert th.construct_tango_devices({}, "d", "T", device_cls=QuadDevice, translator=translator) == {}
    assert th.construct_tango_devices({"NOPE": {}}, "d", "T", device_cls=QuadDevice, translator=translator) == {}


def test_write_file_database(tmp_path):
    path = th.write_file_database(
        str(tmp_path / "sarabi.db"),
        {"QuadDevice": ["VM/Quadrupole/Q-01", "VM/Quadrupole/Q-02"], "Empty": [], "SolDevice": ["VM/Solenoid/S-01"]},
    )
    # Validation rewrites the file in TANGO's own layout, with continuation
    # lines, so normalise before reading the device lists back. (Do not query
    # a file `tango.Database` for them: `get_device_name` segfaults cppTango
    # outside a server.)
    text = open(path).read().replace("\\\n", " ")
    entries = {
        match.group(1): re.findall(r'"([^"]+)"', match.group(2))
        for match in re.finditer(r"^SarabiTango/sim/DEVICE/(\w+):(.*)$", text, re.MULTILINE)
    }
    assert entries == {
        "QuadDevice": ["VM/Quadrupole/Q-01", "VM/Quadrupole/Q-02"],
        "SolDevice": ["VM/Solenoid/S-01"],
    }
    # A class with no devices is left out of the file altogether.
    assert "Empty" not in text


def test_devices_by_class_drops_case_insensitive_duplicates():
    result = th.devices_by_class({QuadDevice: ["VM/T/1", "vm/t/1", "VM/T/2"]})
    assert result == {QuadDevice: ["VM/T/1", "VM/T/2"]}


def test_describe_lists_every_device_and_attribute():
    text = th.describe({"VM/T/2": {"B": "b"}, "VM/T/1": {"Y": "y", "X": "x"}}, "h", 9)
    lines = text.splitlines()
    assert lines[0] == "tango://h:9/VM/T/1#dbase=no"
    assert lines[1].split() == ["X", "(x)"]
    assert lines[2].split() == ["Y", "(y)"]
    assert lines[3] == "tango://h:9/VM/T/2#dbase=no"


def test_report_when_ready_prints_after_the_event(capsys):
    ready = threading.Event()
    thread = th.report_when_ready(ready, {"VM/T/1": {"X": "x"}}, "h", 9)
    assert "Starting TANGO server for 1 device(s) on h:9" in capsys.readouterr().out
    ready.set()
    thread.join(timeout=5)
    out = capsys.readouterr().out
    assert "TANGO server ready" in out
    assert "tango://h:9/VM/T/1#dbase=no" in out
    assert "tango.DeviceProxy('tango://h:9/VM/T/1#dbase=no')" in out


def test_restore_signal_handlers_is_a_no_op_when_python_owns_them():
    assert th.restore_signal_handlers() is False


def test_run_tango_server_with_nothing_to_serve_returns():
    assert th.run_tango_server({QuadDevice: []}) is None
