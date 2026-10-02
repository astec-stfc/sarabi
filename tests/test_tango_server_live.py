"""Serve devices with a real TANGO server and talk to them.

TANGO allows one server per process and takes a while to start (it resolves
every local network interface), so this runs only when asked for:

    SARABI_TEST_TANGO_SERVER=1 pytest tests/test_tango_server_live.py
"""

import os
import socket
import threading
import time

import pytest

from core import tango_helper as th
from core.device.base_server import PVPair, TangoAttribute, TangoDeviceSpec, TangoSimulatedDevice, UpdateSignal

pytestmark = pytest.mark.skipif(
    not os.getenv("SARABI_TEST_TANGO_SERVER"),
    reason="set SARABI_TEST_TANGO_SERVER=1 to start a real TANGO server",
)


class LiveQuad(TangoSimulatedDevice):
    SETI = TangoAttribute(name="SETI", dtype=float, unit="A")
    READI = TangoAttribute(name="READI", dtype=float, access=None)
    STATE = TangoAttribute(name="STATE_", dtype="DevEnum", enum_labels=["OFF", "ON"])
    CLOCK = TangoAttribute(name="CLOCK", dtype=float, optional=True)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_live_server_serves_configured_devices():
    import tango

    LiveQuad.STATE.dtype = tango.DevEnum
    pair = PVPair(setpoint="SETI", readback="READI")  # immediate tracking
    LiveQuad.configure("VM/Quadrupole/LIVE-01", TangoDeviceSpec(handles=["SETI", "READI", "STATE", "CLOCK"], timestep=0.1, pv_pairs=[pair], updates=[UpdateSignal("CLOCK", lambda t: t)]))
    LiveQuad.configure("VM/Quadrupole/LIVE-02", TangoDeviceSpec(handles=["SETI", "READI"]))
    port = free_port()
    stop, ready = threading.Event(), threading.Event()
    thread = threading.Thread(
        target=th.run_tango_server,
        args=({LiveQuad: ["VM/Quadrupole/LIVE-01", "VM/Quadrupole/LIVE-02"]},),
        kwargs=dict(stop_event=stop, ready_event=ready, host="127.0.0.1", port=port),
        daemon=True,
    )
    thread.start()
    assert ready.wait(180), "TANGO server did not start"

    try:
        dev1 = tango.DeviceProxy(th.device_address("VM/Quadrupole/LIVE-01", "127.0.0.1", port))
        dev2 = tango.DeviceProxy(th.device_address("VM/Quadrupole/LIVE-02", "127.0.0.1", port))
        assert list(dev1.get_attribute_list()) == ["SETI", "READI", "STATE_", "CLOCK", "State", "Status"]
        assert list(dev2.get_attribute_list()) == ["SETI", "READI", "State", "Status"]
        assert dev1.state() == tango.DevState.ON
        assert dev1.get_attribute_config("SETI").unit == "A"
        assert dev1.get_attribute_config("STATE_").enum_labels == ["OFF", "ON"]

        seen = []
        event = dev1.subscribe_event(
            "READI", tango.EventType.CHANGE_EVENT, lambda e: seen.append(e.attr_value.value) if not e.err else None
        )
        dev1.SETI = 2.5
        time.sleep(0.5)
        assert dev1.READI == 2.5
        assert 2.5 in seen
        dev1.unsubscribe_event(event)

        dev1.STATE_ = 1
        assert dev1.STATE_ == 1
        first = dev1.CLOCK
        time.sleep(0.5)
        assert dev1.CLOCK > first
        # LIVE-02 has no setpoint/readback pair, so its readback stays put.
        dev2.SETI = -1.0
        time.sleep(0.5)
        assert dev2.SETI == -1.0
        assert dev2.READI == 0.0
    finally:
        stop.set()
        thread.join(timeout=15)
    assert not thread.is_alive()
