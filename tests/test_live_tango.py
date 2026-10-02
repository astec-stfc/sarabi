"""The rendered TANGO device server, served and talked to."""

import math
import signal
import sys
import time

import pytest
import tango

from conftest import free_port, running

pytestmark = pytest.mark.live

TAU = 0.3
DESCRIPTION = 'Set "current" \\ in °A'
STATES = {"OFF": 0, "ON": 1, "FAULT": 2}


def over_tango(variables):
    return {h: {**config, "protocol": "TANGO"} for h, config in variables.items()}


@pytest.fixture(scope="module")
def machine(module_machine):
    machine = module_machine()
    quad = {
        "SETI": {"dtype": "scalar", "readback": "READI"},
        "READI": {"dtype": "scalar"},
        # Every TANGO device has a State already
        "STATE": {"dtype": "state", "states": STATES, "units": "n/a"},
    }
    machine.device(
        "Magnet/quad-03.yaml",
        "QUAD-03",
        over_tango(
            {
                **quad,
                "SETI": {
                    **quad["SETI"],
                    "units": "A",
                    "description": DESCRIPTION,
                    "dynamics": {"model": "simmodels.FirstOrderResponse", "tau": TAU},
                },
                # Only this quadrupole has one
                "READK": {
                    "dtype": "scalar",
                    "update": {
                        "function": "simmodels.Sinusoid",
                        "period": 2.0,
                        "amplitude": 0.5,
                    },
                },
            }
        ),
    )
    machine.device("Magnet/quad-04.yaml", "QUAD-04", over_tango(quad))
    machine.device(
        "Diagnostics/BPM/bpm-01.yml",
        "BPM-01",
        over_tango(
            {
                # A TANGO name of its own, putting it on a device of its own
                "X": {
                    "dtype": "scalar",
                    "identifier": "tango://somehost:10000/jfel/dia/bpm-01/xpos",
                    "setpoint": "COUNT",
                },
                "COUNT": {"dtype": "int"},
                "TRACE": {"dtype": "waveform"},
                "LABEL": {"dtype": "string"},
                "ENABLED": {"dtype": "binary"},
            }
        ),
    )
    # Served over EPICS, so not by this server
    machine.device(
        "Valve/v1.yaml", "V1", {"OPEN": {"dtype": "scalar", "protocol": "CA"}}
    )
    machine.render()
    return machine


def tango_command(machine, *args):
    return [
        sys.executable,
        "-u",
        machine.output_directory / "run_all_tango.py",
        "--timestep=0.05",
        *args,
    ]


@pytest.fixture(scope="module")
def server(machine, tmp_path_factory, clean_environment):
    port = free_port()
    log_file = tmp_path_factory.mktemp("tango") / "server.log"
    command = tango_command(machine, f"--port={port}")
    with running(command, log_file, clean_environment(), machine.root) as server:
        server.wait_for("Ready to accept request")
        server.port = port
        yield server
    assert "Traceback" not in server.log, server.log[-3000:]


@pytest.fixture
def device(server):
    def proxy(name):
        return tango.DeviceProxy(f"tango://localhost:{server.port}/{name}#dbase=no")

    return proxy


def attributes(proxy):
    return sorted(set(proxy.get_attribute_list()) - {"State", "Status"})


def test_each_device_has_the_attributes_its_definition_gives_it(device):
    assert attributes(device("VM/Magnet/QUAD-03")) == [
        "READI",
        "READK",
        "SETI",
        "STATE_",
    ]
    # The class is shared, but READK is only added to the device that has it
    assert attributes(device("VM/Magnet/QUAD-04")) == ["READI", "SETI", "STATE_"]
    assert attributes(device("VM/BPM/BPM-01")) == ["COUNT", "ENABLED", "LABEL", "TRACE"]
    assert attributes(device("VM-jfel/dia/bpm-01")) == ["xpos"]
    assert device("VM/Magnet/QUAD-03").state() == tango.DevState.ON


def test_device_names_are_not_told_apart_by_case(device):
    assert device("vm/magnet/quad-04").ping() >= 0


def test_variables_served_over_epics_are_not_served(device):
    with pytest.raises(tango.DevFailed):
        device("VM/Valve/V1").ping()


def test_attributes_say_what_their_definitions_said(device):
    quad = device("VM/Magnet/QUAD-03")
    config = quad.get_attribute_config("SETI")
    assert config.unit == "A"
    assert config.description == DESCRIPTION
    assert config.writable == tango.AttrWriteType.READ_WRITE
    assert list(quad.get_attribute_config("STATE_").enum_labels) == list(STATES)


def test_every_data_type(device):
    bpm, quad = device("VM/BPM/BPM-01"), device("VM/Magnet/QUAD-04")
    types = {
        name: tango.CmdArgType.values[bpm.get_attribute_config(name).data_type].name
        for name in attributes(bpm)
    }
    assert types == {
        "COUNT": "DevLong64",
        "ENABLED": "DevBoolean",
        "LABEL": "DevString",
        "TRACE": "DevDouble",
    }
    assert (
        bpm.get_attribute_config("TRACE").data_format == tango.AttrDataFormat.SPECTRUM
    )

    bpm.TRACE = [1.0, 2.5, 4.0]
    bpm.LABEL = "hello"
    bpm.ENABLED = True
    bpm.COUNT = 7
    quad.STATE_ = 2

    assert list(bpm.TRACE) == [1.0, 2.5, 4.0]
    assert bpm.LABEL == "hello"
    assert bpm.ENABLED is True
    assert bpm.COUNT == 7
    assert quad.STATE_ == 2


def test_a_setpoint_can_be_read_before_it_has_been_written(device):
    assert device("VM/Magnet/QUAD-04").read_attribute("READI").w_value == 0.0


def test_a_readback_follows_its_setpoint_through_its_dynamics(device):
    quad = device("VM/Magnet/QUAD-03")
    quad.SETI = 0.0
    time.sleep(3 * TAU)
    quad.SETI = 10.0
    time.sleep(1.0)
    assert quad.READI == pytest.approx(10 * (1 - math.exp(-1.0 / TAU)), abs=0.6)
    assert quad.READI < 10.0


def test_devices_are_simulated_apart(device):
    """The class is shared by every device of a type; what it holds is not."""
    device("VM/Magnet/QUAD-03").SETI = 10.0
    other = device("VM/Magnet/QUAD-04")
    other.SETI = 5.0
    time.sleep(0.4)
    # With no dynamics of its own, its readback follows at once
    assert other.READI == 5.0
    assert device("VM/Magnet/QUAD-03").SETI == 10.0


def test_an_update_signal_generates_a_value(device):
    quad = device("VM/Magnet/QUAD-03")
    first = quad.READK
    time.sleep(0.5)
    second = quad.READK
    assert first != second
    assert abs(first) <= 0.5 and abs(second) <= 0.5


def test_a_pair_is_simulated_across_the_devices_of_one_definition(device):
    device("VM/BPM/BPM-01").COUNT = 42
    time.sleep(0.4)
    assert device("VM-jfel/dia/bpm-01").xpos == 42.0


def test_changes_are_pushed_to_subscribers(device):
    """Without polling having been configured, by the simulation and by writes."""
    quad = device("VM/Magnet/QUAD-03")
    quad.SETI = 0.0
    time.sleep(3 * TAU)
    events = []
    subscription = quad.subscribe_event(
        "READI",
        tango.EventType.CHANGE_EVENT,
        lambda event: events.append(None if event.err else event.attr_value.value),
    )
    try:
        quad.SETI = 10.0
        time.sleep(1.0)
    finally:
        quad.unsubscribe_event(subscription)
    values = [value for value in events if value is not None]
    assert len(values) >= 10
    # Closing on the setpoint, a timestep at a time
    assert values[1:] == sorted(values[1:])


def test_a_device_can_be_initialised_again(device):
    """Which deletes it and makes it anew, and must leave it simulated and pushing."""
    quad = device("VM/Magnet/QUAD-04")
    quad.SETI = 1.0
    quad.Init()
    # Its values are those of what it simulates, not of the device serving them
    assert quad.SETI == 1.0
    events = []
    subscription = quad.subscribe_event(
        "READI",
        tango.EventType.CHANGE_EVENT,
        lambda event: events.append(None if event.err else event.attr_value.value),
    )
    try:
        quad.SETI = 2.0
        time.sleep(0.5)
    finally:
        quad.unsubscribe_event(subscription)
    assert quad.READI == 2.0
    assert 2.0 in events


@pytest.mark.parametrize("attempt", range(3))
def test_stopping_a_server_in_the_middle_of_simulating(
    machine, tmp_path, clean_environment, attempt
):
    """The simulation pushes events from a thread of its own, and doing so to a
    device TANGO had begun to destroy brought the server down with a segmentation
    fault, more often than not at this rate."""
    command = tango_command(machine, f"--port={free_port()}", "--timestep=0.005")
    with running(
        command, tmp_path / "server.log", clean_environment(), machine.root
    ) as server:
        server.wait_for("Ready to accept request")
        time.sleep(0.5)
        assert server.stop(signal.SIGINT) == 0


def test_list_prints_every_address_without_serving(machine):
    assert machine.tango_addresses() == {
        "VM/Magnet/QUAD-03/SETI": ("QUAD-03", "SETI"),
        "VM/Magnet/QUAD-03/READI": ("QUAD-03", "READI"),
        "VM/Magnet/QUAD-03/STATE_": ("QUAD-03", "STATE"),
        "VM/Magnet/QUAD-03/READK": ("QUAD-03", "READK"),
        "VM/Magnet/QUAD-04/SETI": ("QUAD-04", "SETI"),
        "VM/Magnet/QUAD-04/READI": ("QUAD-04", "READI"),
        "VM/Magnet/QUAD-04/STATE_": ("QUAD-04", "STATE"),
        "VM-jfel/dia/bpm-01/xpos": ("BPM-01", "X"),
        "VM/BPM/BPM-01/COUNT": ("BPM-01", "COUNT"),
        "VM/BPM/BPM-01/TRACE": ("BPM-01", "TRACE"),
        "VM/BPM/BPM-01/LABEL": ("BPM-01", "LABEL"),
        "VM/BPM/BPM-01/ENABLED": ("BPM-01", "ENABLED"),
    }


def test_the_server_of_one_device_type(machine, tmp_path, clean_environment):
    port = free_port()
    command = [
        sys.executable,
        "-u",
        machine.output_directory / "Magnet" / "tango_main.py",
        f"--port={port}",
    ]
    with running(
        command, tmp_path / "server.log", clean_environment(), machine.root
    ) as server:
        server.wait_for("Ready to accept request")
        quad = tango.DeviceProxy(f"tango://localhost:{port}/VM/Magnet/QUAD-04#dbase=no")
        assert attributes(quad) == ["READI", "SETI", "STATE_"]
        with pytest.raises(tango.DevFailed):
            tango.DeviceProxy(f"tango://localhost:{port}/VM/BPM/BPM-01#dbase=no").ping()
        # As Ctrl-C would
        assert server.stop(signal.SIGINT) == 0


def test_nothing_to_serve_is_not_a_failure(tmp_path, clean_environment):
    from conftest import Machine

    machine = Machine(tmp_path)
    machine.device("Magnet/q.yaml", "Q", over_tango({"SETI": {"dtype": "scalar"}}))
    machine.render()
    # Switched back to EPICS since it was rendered
    machine.device(
        "Magnet/q.yaml", "Q", {"SETI": {"dtype": "scalar", "protocol": "CA"}}
    )

    result = machine.run_script(str(machine.output_directory / "run_all_tango.py"))

    assert "nothing to serve" in result.stdout


# Serving through a TANGO database


@pytest.fixture(scope="module")
def database(tmp_path_factory, clean_environment):
    """PyTango's own database server, which keeps its database in a file."""
    port = free_port()
    directory = tmp_path_factory.mktemp("database")
    environment = clean_environment(TANGO_HOST=f"localhost:{port}")
    command = [
        sys.executable,
        "-u",
        "-m",
        "tango.databaseds.database",
        f"--port={port}",
        "2",
    ]
    with running(command, directory / "database.log", environment, directory) as server:
        deadline = time.monotonic() + 60
        while "Ready to accept request" not in server.log:
            if server.process.poll() is not None or time.monotonic() > deadline:
                pytest.skip(
                    f"PyTango's database server did not start:\n{server.log[-1000:]}"
                )
            time.sleep(0.2)
        yield f"localhost:{port}"


def test_serving_through_a_database(machine, database, tmp_path, clean_environment):
    command = tango_command(machine, f"--database={database}", "--instance=pytest")
    registered = None
    # Twice, as the devices of a server already registered are registered afresh
    for attempt in ("first", "second"):
        log_file = tmp_path / f"{attempt}.log"
        with running(command, log_file, clean_environment(), machine.root) as server:
            server.wait_for("Ready to accept request")
            # Found by name alone, the database knowing where
            bpm = tango.DeviceProxy(f"tango://{database}/VM/BPM/BPM-01")
            bpm.COUNT = 9
            time.sleep(0.4)
            assert (
                tango.DeviceProxy(f"tango://{database}/VM-jfel/dia/bpm-01").xpos == 9.0
            )

            host, port = database.split(":")
            registered = tango.Database(host, int(port)).get_device_class_list(
                "Sarabi/pytest"
            )
            assert server.stop(signal.SIGINT) == 0
    devices = dict(zip(registered[::2], registered[1::2]))
    assert devices["VM/Magnet/QUAD-03"] == "MagnetBaseTangoDevice"
    assert devices["VM-jfel/dia/bpm-01"] == "BPMBaseTangoDevice"
    assert len([name for name in devices if name.startswith("VM")]) == 4


def test_a_server_that_cannot_start_says_so_and_fails(
    machine, tmp_path, clean_environment
):
    """Left to itself PyTango reports the failure and exits as though it had not."""
    nowhere = f"localhost:{free_port()}"
    command = tango_command(machine, f"--database={nowhere}")
    with running(
        command, tmp_path / "server.log", clean_environment(), machine.root
    ) as server:
        assert server.process.wait(timeout=120) == 1
    assert "The TANGO device server failed" in server.log
    assert "Traceback" not in server.log
