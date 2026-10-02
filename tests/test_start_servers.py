"""The script starting the servers of both control systems."""

import os
import signal
import subprocess
import sys
import time

import pytest
import tango
from caproto.sync.client import read

from conftest import SARABI_ROOT, EpicsPorts, Machine, free_port, running, wait_for_pv

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.name == "nt", reason="stops servers with POSIX signals"),
]


def scalar(protocol):
    return {"dtype": "scalar", "protocol": protocol}


@pytest.fixture(scope="module")
def mixed(module_machine):
    machine = module_machine()
    machine.device("Magnet/q1.yaml", "Q1", {"SETI": scalar("CA")})
    machine.device("BPM/b1.yaml", "B1", {"X": scalar("TANGO")})
    machine.render()
    return machine


def start_servers(machine, *args):
    return [
        sys.executable, "-u", SARABI_ROOT / "start_servers.py",
        f"--settings={machine.settings_file}", "--timestep=0.05", *args,
    ]  # fmt: skip


def children_of(pid):
    result = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True)
    return [int(child) for child in result.stdout.split()]


def is_running(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
def both(mixed, tmp_path, monkeypatch):
    """Both control systems of the mixed machine, started by the script."""
    ports, tango_port = EpicsPorts(), free_port()
    monkeypatch.setenv("EPICS_CA_SERVER_PORT", str(ports.ca))
    monkeypatch.setenv("EPICS_CA_ADDR_LIST", "127.0.0.1")
    monkeypatch.setenv("EPICS_CA_AUTO_ADDR_LIST", "NO")
    command = start_servers(mixed, f"--tango-port={tango_port}")
    # The IOCs take their ports from the environment, handed down by the script
    with running(
        command, tmp_path / "start.log", ports.server_environment(), mixed.root
    ) as script:
        script.wait_for("Ready to accept request")
        wait_for_pv(lambda: read("VM-Q1:SETI", timeout=2))
        script.bpm = tango.DeviceProxy(
            f"tango://localhost:{tango_port}/VM/BPM/B1#dbase=no"
        )
        script.servers = children_of(script.process.pid)
        yield script
        script.stop()
    # Whatever the test did, nothing is to be left running: not by the script,
    # which is what is being tested, nor by a test of it that has failed.
    left_running = [pid for pid in script.servers if is_running(pid)]
    for pid in left_running:
        os.kill(pid, signal.SIGKILL)
    assert not left_running


def test_both_control_systems_are_started(both):
    assert len(both.servers) == 2
    assert read("VM-Q1:SETI", timeout=5).data[0] == 0.0
    assert both.bpm.X == 0.0
    assert "Starting EPICS" in both.log and "Starting TANGO" in both.log


def test_terminating_the_script_stops_the_servers(both):
    """As a service manager or `timeout` would, which once left them running."""
    assert both.stop(signal.SIGTERM) == 0
    assert not any(is_running(pid) for pid in both.servers)
    assert "did not stop" not in both.log


def test_interrupting_the_script_stops_the_servers(both):
    assert both.stop(signal.SIGINT) == 0
    assert not any(is_running(pid) for pid in both.servers)


def test_the_servers_are_one_machine(both):
    """So when one of them dies the other is stopped, and the script fails."""
    os.kill(both.servers[-1], signal.SIGKILL)
    assert both.process.wait(timeout=60) != 0
    assert "stopping" in both.log
    assert not any(is_running(pid) for pid in both.servers)


def test_a_control_system_with_nothing_to_serve_is_not_started(tmp_path, monkeypatch):
    machine = Machine(tmp_path)
    machine.device("Magnet/q1.yaml", "Q1", {"SETI": scalar("CA")})
    machine.render()
    ports = EpicsPorts()
    monkeypatch.setenv("EPICS_CA_SERVER_PORT", str(ports.ca))
    monkeypatch.setenv("EPICS_CA_ADDR_LIST", "127.0.0.1")
    monkeypatch.setenv("EPICS_CA_AUTO_ADDR_LIST", "NO")

    with running(
        start_servers(machine),
        tmp_path / "start.log",
        ports.server_environment(),
        machine.root,
    ) as script:
        wait_for_pv(lambda: read("VM-Q1:SETI", timeout=2))
        assert len(children_of(script.process.pid)) == 1
        assert "No TANGO variables are defined; not starting it." in script.log


def test_only_one_control_system(mixed, tmp_path):
    tango_port = free_port()
    command = start_servers(mixed, "--only=tango", f"--tango-port={tango_port}")
    with running(
        command, tmp_path / "start.log", EpicsPorts().server_environment(), mixed.root
    ) as script:
        script.wait_for("Ready to accept request")
        assert len(children_of(script.process.pid)) == 1
        assert "Starting EPICS" not in script.log


def test_render_renders_before_starting(tmp_path, monkeypatch):
    machine = Machine(tmp_path)
    machine.device("Magnet/q1.yaml", "Q1", {"SETI": scalar("CA")})
    machine.write_settings()
    ports = EpicsPorts()
    monkeypatch.setenv("EPICS_CA_SERVER_PORT", str(ports.ca))
    monkeypatch.setenv("EPICS_CA_ADDR_LIST", "127.0.0.1")
    monkeypatch.setenv("EPICS_CA_AUTO_ADDR_LIST", "NO")

    command = start_servers(machine, "--render")
    with running(
        command, tmp_path / "start.log", ports.server_environment(), machine.root
    ):
        assert (
            wait_for_pv(lambda: read("VM-Q1:SETI", timeout=2), timeout=120).data[0]
            == 0.0
        )


def test_servers_that_were_not_rendered_are_pointed_out(tmp_path, clean_environment):
    machine = Machine(tmp_path)
    machine.device("Magnet/q1.yaml", "Q1", {"SETI": scalar("CA")})
    result = machine.run_script(
        "start_servers.py", f"--settings={machine.write_settings()}", check=False
    )
    assert result.returncode == 1
    assert "has not been rendered. Run again with --render." in result.stderr
