"""Tests of `TangoSimulatedDevice` without a running TANGO server.

The class derives from pytango's `Device`, which cannot be instantiated outside
a server, so its methods are exercised on a stand-in that provides what they
use: the value store, the spec, and the TANGO calls they make.
"""

import warnings

import pytest
from tango import AttrWriteType

from core.device.base_server import (
    DEFAULT_TIMESTEP,
    PVPair,
    TangoAttribute,
    TangoDeviceSpec,
    TangoSimulatedDevice,
    UpdateSignal,
)


class Base(TangoSimulatedDevice):
    SETI = TangoAttribute(name="SETI", dtype=float, initial=1.0)
    READI = TangoAttribute(name="READI", dtype=float, access=AttrWriteType.READ)


class Derived(Base):
    STATE = TangoAttribute(name="STATE_", dtype=int, enum_labels=["OFF", "ON"], optional=True)
    READI = TangoAttribute(name="ReadI", dtype=float)  # overrides the base declaration


class StandIn:
    """Enough of a device for `TangoSimulatedDevice`'s methods to run on."""

    initialize_dynamic_attributes = TangoSimulatedDevice.initialize_dynamic_attributes
    _read_handle = TangoSimulatedDevice._read_handle
    _write_handle = TangoSimulatedDevice._write_handle
    _channel = TangoSimulatedDevice._channel
    tick = TangoSimulatedDevice.tick
    post = TangoSimulatedDevice.post
    value = TangoSimulatedDevice.value

    def __init__(self, cls, name, spec, fail_on=()):
        self._cls, self._name, self._spec, self._fail_on = cls, name, spec, fail_on
        self._values, self._attribute_names, self._handles, self._missing = {}, {}, {}, set()
        self.pv_pairs = list(spec.pv_pairs) if spec else []
        self.updates = list(spec.updates) if spec else []
        self.timestep = spec.timestep if spec else DEFAULT_TIMESTEP
        self.elapsed = 0.0
        self.added, self.events, self.pushed, self.started = [], [], [], False

    def get_name(self):
        return self._name

    def declared_attributes(self):
        return self._cls.declared_attributes()

    def add_attribute(self, attr):
        if attr.name in self._fail_on:
            raise RuntimeError(f"Attribute {attr.name} already exists for your device")
        self.added.append(attr)

    def set_change_event(self, name, implemented, detect):
        self.events.append((name, implemented, detect))

    def push_change_event(self, name, value):
        self.pushed.append((name, value))

    def start(self):
        self.started = True


class FakeAttr:
    def __init__(self, name, write_value=None):
        self._name, self._write_value, self.value = name, write_value, None

    def get_name(self):
        return self._name

    def set_value(self, value):
        self.value = value

    def get_write_value(self):
        return self._write_value


def test_tango_attribute_kwargs_and_writability():
    attr = TangoAttribute(name="X", dtype=float, unit="A", doc="d", enum_labels=["a"], max_dim_x=4)
    assert attr.attribute_kwargs() == {
        "name": "X",
        "dtype": float,
        "access": AttrWriteType.READ_WRITE,
        "unit": "A",
        "doc": "d",
        "enum_labels": ["a"],
        "max_dim_x": 4,
    }
    assert attr.writable
    assert TangoAttribute(name="X", dtype=float).attribute_kwargs() == {
        "name": "X",
        "dtype": float,
        "access": AttrWriteType.READ_WRITE,
    }
    assert not TangoAttribute(name="X", dtype=float, access=AttrWriteType.READ).writable


def test_declared_attributes_follow_the_mro():
    assert list(Base.declared_attributes()) == ["SETI", "READI"]
    derived = Derived.declared_attributes()
    assert list(derived) == ["SETI", "READI", "STATE"]
    assert derived["READI"].name == "ReadI"
    assert derived["STATE"].optional


def test_configure_keeps_a_registry_per_class():
    Base.configure("VM/T/Base", TangoDeviceSpec(handles=["SETI"]))
    Derived.configure("VM/T/Derived", TangoDeviceSpec(handles=["STATE"]))
    assert Base.configured_devices() == ["vm/t/base"]
    assert Derived.configured_devices() == ["vm/t/derived"]
    assert TangoSimulatedDevice.configured_devices() == []


def test_dynamic_attributes_are_created_for_the_devices_handles_only():
    spec = TangoDeviceSpec(handles=["SETI", "STATE"], initial_values={"STATE": 1})
    device = StandIn(Derived, "VM/T/1", spec)
    device.initialize_dynamic_attributes()

    assert [a.name for a in device.added] == ["SETI", "STATE_"]
    assert device._values == {"SETI": 1.0, "STATE": 1}
    assert device._attribute_names == {"SETI": "SETI", "STATE": "STATE_"}
    assert device._handles == {"seti": "SETI", "state_": "STATE"}
    assert device.events == [("SETI", True, False), ("STATE_", True, False)]
    assert device.started


def test_dynamic_attributes_default_to_every_declaration_without_a_spec():
    device = StandIn(Base, "VM/T/1", None)
    device.initialize_dynamic_attributes()
    assert [a.name for a in device.added] == ["SETI", "READI"]


def test_read_only_attributes_have_no_setter():
    device = StandIn(Base, "VM/T/1", TangoDeviceSpec(handles=["SETI", "READI"]))
    device.initialize_dynamic_attributes()
    by_name = {a.name: a for a in device.added}
    assert by_name["SETI"].fset is not None
    assert by_name["SETI"].attr_write == AttrWriteType.READ_WRITE
    assert getattr(by_name["READI"], "fset", None) is None
    assert by_name["READI"].attr_write == AttrWriteType.READ


def test_unknown_handle_is_reported_and_skipped():
    device = StandIn(Base, "VM/T/1", TangoDeviceSpec(handles=["SETI", "NOPE"]))
    with pytest.warns(UserWarning, match="no attribute for handle 'NOPE'"):
        device.initialize_dynamic_attributes()
    assert [a.name for a in device.added] == ["SETI"]


def test_failing_attribute_does_not_stop_the_rest():
    device = StandIn(Base, "VM/T/1", TangoDeviceSpec(handles=["SETI", "READI"]), fail_on=("SETI",))
    with pytest.warns(UserWarning, match="Cannot add attribute 'SETI'"):
        device.initialize_dynamic_attributes()
    assert [a.name for a in device.added] == ["READI"]
    assert device._values == {"READI": 0.0}
    assert "seti" not in device._handles
    assert device.events == [("READI", True, False)]


def test_read_and_write_go_through_the_value_store():
    device = StandIn(Derived, "VM/T/1", TangoDeviceSpec(handles=["STATE"]))
    device.initialize_dynamic_attributes()
    attr = FakeAttr("state_")  # TANGO attribute names are case-insensitive
    device._read_handle(attr)
    assert attr.value == 0
    device._write_handle(FakeAttr("STATE_", write_value=1))
    assert device.value("STATE") == 1


def test_tick_drives_pairs_and_updates_and_posts_changes():
    pair = PVPair(setpoint="SETI", readback="READI", dynamics=lambda target, dt: target / 2)
    update = UpdateSignal(handle="READI", signal=lambda t, value: value + t)
    spec = TangoDeviceSpec(handles=["SETI", "READI"], timestep=0.5, pv_pairs=[pair], updates=[update])
    device = StandIn(Base, "VM/T/1", spec)
    device.initialize_dynamic_attributes()
    device._values["SETI"] = 8.0

    device.tick()
    # Half of the setpoint, then the update composed on top with t = 0.
    assert device._values["READI"] == 4.0
    assert device.pushed == [("READI", 4.0)]
    assert device.elapsed == 0.5

    device.tick()
    assert device._values["READI"] == 4.5
    assert device.pushed[-1] == ("READI", 4.5)


def test_tick_skips_unchanged_values_and_missing_handles():
    pair = PVPair(setpoint="SETI", readback="READI")
    ghost = PVPair(setpoint="SETI", readback="GHOST")
    spec = TangoDeviceSpec(handles=["SETI", "READI"], pv_pairs=[pair, ghost])
    device = StandIn(Base, "VM/T/1", spec)
    device.initialize_dynamic_attributes()
    device._values["SETI"] = 1.0

    with pytest.warns(UserWarning, match="no attribute for 'GHOST'"):
        device.tick()
    assert device.pushed == [("READI", 1.0)]
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # the missing handle is reported once
        device.tick()
    assert device.pushed == [("READI", 1.0)]  # unchanged, so not posted again
