import os
from types import SimpleNamespace

import pytest

import start_servers
from core.settings import Settings
from tests.conftest import LAURA_SCHEMA, TEMPLATES


@pytest.fixture
def settings(devices_dir, tmp_path):
    output = tmp_path / "generated"
    output.mkdir()
    return Settings(str(output), TEMPLATES, LAURA_SCHEMA, devices_dir, ["RFCavity"])


def args(**overrides):
    values = dict(
        ca_port=None, pva_port=None, tango_host=None, tango_port=None, timestep=None, per_type=False
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_environment_defaults_and_overrides(monkeypatch):
    for key in ("EPICS_CA_SERVER_PORT", "EPICS_PVA_SERVER_PORT", "SARABI_TANGO_HOST", "SARABI_TANGO_PORT"):
        monkeypatch.delenv(key, raising=False)
    env = start_servers.environment(args())
    assert env["EPICS_CA_SERVER_PORT"] == "6090"
    assert env["EPICS_PVA_SERVER_PORT"] == "6091"
    assert env["SARABI_TANGO_HOST"] == "127.0.0.1"
    assert env["SARABI_TANGO_PORT"] == "10090"

    monkeypatch.setenv("SARABI_TANGO_PORT", "11111")
    env = start_servers.environment(args(ca_port=1, pva_port=2, tango_host="h"))
    assert env["EPICS_CA_SERVER_PORT"] == "1" and env["EPICS_PVA_SERVER_PORT"] == "2"
    assert env["SARABI_TANGO_HOST"] == "h" and env["SARABI_TANGO_PORT"] == "11111"
    assert start_servers.environment(args(tango_port=3))["SARABI_TANGO_PORT"] == "3"


def test_tango_devices_lists_devices_and_attribute_names(settings):
    devices = start_servers.tango_devices(settings)
    # RFCavity is ignored by the settings; SETK is Channel Access.
    assert devices == {
        "VM/Quadrupole/TEST-S01-MAG-QUAD-01": ["SETI", "READI", "NOISE", "STATE_"],
        "VM/Quadrupole/TEST-S01-MAG-QUAD-02": ["SETI", "READI", "ONLY_HERE"],
    }


def test_runner_commands(settings, tmp_path):
    output = settings.output_directory
    with pytest.raises(FileNotFoundError, match="run without --no-render"):
        start_servers.runner_commands(settings, args())
    with pytest.raises(FileNotFoundError, match="run without --no-render"):
        start_servers.runner_commands(settings, args(per_type=True))

    open(os.path.join(output, "run_all_iocs.py"), "w").close()
    for device_type in ("Quadrupole", "RFCavity"):
        os.makedirs(os.path.join(output, device_type))
        open(os.path.join(output, device_type, "main.py"), "w").close()

    (label, command, cwd), = start_servers.runner_commands(settings, args(timestep=0.05))
    assert label == "all"
    assert command[1:] == [os.path.join(output, "run_all_iocs.py"), "--timestep=0.05"]
    assert cwd == output

    commands = start_servers.runner_commands(settings, args(per_type=True))
    assert [c[0] for c in commands] == ["Quadrupole"]  # RFCavity is ignored
    assert commands[0][1][1:] == [os.path.join(output, "Quadrupole", "main.py")]
    assert commands[0][2] == os.path.join(output, "Quadrupole")


def test_load_settings_requires_the_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        start_servers.load_settings(str(tmp_path / "missing.yaml"))
