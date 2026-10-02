"""Start the servers of a simulated machine, for both control systems.

Runs the EPICS IOCs and the TANGO device server rendered for the machine in the
settings, each in a process of its own, until interrupted::

    python start_servers.py --settings=./settings.yaml --render

Each is only started if it was rendered and there is something for it to serve,
so a machine served entirely over one control system starts that one alone.
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from typing import Dict, List

import yaml

from core.discovery import find_device_files, iter_devices
from core.protocols import CA, PVA, TANGO, protocol_of
from core.settings import Settings
from core.translator import SchemaTranslator

SARABI_ROOT = os.path.dirname(os.path.abspath(__file__))
EPICS = "EPICS"
CONTROL_SYSTEMS = (EPICS, TANGO)
# The script rendered to run every server of each control system
RUN_ALL_SCRIPTS = {EPICS: "run_all_iocs.py", TANGO: "run_all_tango.py"}
SERVED_BY = {CA: EPICS, PVA: EPICS, TANGO: TANGO}


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Start the EPICS IOCs and TANGO device server of a simulated "
        "machine."
    )
    parser.add_argument(
        "--settings", type=str, required=True, help="Path to the settings YAML file."
    )
    parser.add_argument(
        "--render",
        action="store_true",
        help="Render the servers from the device definitions before starting them.",
    )
    parser.add_argument(
        "--only",
        type=str.upper,
        choices=CONTROL_SYSTEMS,
        help="Start the servers of this control system alone.",
    )
    parser.add_argument(
        "--timestep",
        type=float,
        default=None,
        help="Interval, in seconds, on which simulated values are advanced.",
    )
    tango = parser.add_argument_group("TANGO")
    tango.add_argument(
        "--tango-database",
        nargs="?",
        const=True,
        default=None,
        metavar="HOST:PORT",
        help="Register the devices in a TANGO database and serve them through it, "
        "rather than without one. Uses TANGO_HOST if no address is given.",
    )
    tango.add_argument(
        "--tango-port", type=int, default=None, help="Port to serve TANGO devices on."
    )
    tango.add_argument(
        "--tango-instance",
        type=str,
        default=None,
        help="Instance name of the TANGO device server.",
    )
    return parser.parse_args()


def _load_settings(settings_yaml: str) -> Settings:
    if not os.path.exists(settings_yaml):
        raise FileNotFoundError(f"Could not find {settings_yaml}")
    with open(settings_yaml, "r") as f:
        return Settings(**yaml.load(f, Loader=yaml.SafeLoader))


def render(settings_yaml: str) -> None:
    """Render the servers, as running the rendering scripts by hand would."""
    for script in ("render_iocs.py", "render_main.py"):
        subprocess.run(
            [
                sys.executable,
                os.path.join(SARABI_ROOT, script),
                "--settings",
                settings_yaml,
            ],
            check=True,
        )


def count_variables(settings: Settings) -> Dict[str, int]:
    """How many variables the definitions ask each control system to serve."""
    translator = SchemaTranslator(settings.schema_file)
    counts = dict.fromkeys(CONTROL_SYSTEMS, 0)
    device_files = find_device_files(
        settings.devices_directory, settings.ignore_device_types
    )
    for yaml_files in device_files.values():
        for _, variables in iter_devices(yaml_files, translator):
            for config in variables.values():
                served_by = SERVED_BY.get(protocol_of(config, translator.protocol_word))
                if served_by:
                    counts[served_by] += 1
    return counts


def _command(control_system: str, script: str, args) -> List[str]:
    command = [sys.executable, "-u", script]
    if args.timestep is not None:
        command.append(f"--timestep={args.timestep}")
    if control_system == TANGO:
        if args.tango_database is True:
            command.append("--database")
        elif args.tango_database:
            command.append(f"--database={args.tango_database}")
        if args.tango_port is not None:
            command.append(f"--port={args.tango_port}")
        if args.tango_instance:
            command.append(f"--instance={args.tango_instance}")
    return command


def start(settings: Settings, args) -> Dict[str, subprocess.Popen]:
    """Start the servers of each control system that has something to serve."""
    counts = count_variables(settings)
    servers = {}
    for control_system in CONTROL_SYSTEMS:
        if args.only and args.only != control_system:
            continue
        if not counts[control_system]:
            print(f"No {control_system} variables are defined; not starting it.")
            continue
        script = os.path.join(
            os.path.abspath(settings.output_directory), RUN_ALL_SCRIPTS[control_system]
        )
        if not os.path.exists(script):
            print(
                f"{counts[control_system]} {control_system} variables are defined, but "
                f"{script} has not been rendered. Run again with --render.",
                file=sys.stderr,
            )
            continue
        command = _command(control_system, script, args)
        print(f"Starting {control_system}: {' '.join(command)}")
        servers[control_system] = subprocess.Popen(command)
    return servers


def _wait(servers: Dict[str, subprocess.Popen], timeout: float) -> bool:
    """Wait for every server to exit, returning whether they all did."""
    deadline = time.monotonic() + timeout
    for server in servers.values():
        try:
            server.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            return False
    return True


def stop(servers: Dict[str, subprocess.Popen], interrupted: bool = False) -> None:
    """Stop every server, as gently as each allows.

    A Ctrl-C at a terminal interrupts the servers along with this script, so
    they are given a moment to stop by themselves before being asked again.
    """
    if interrupted and _wait(servers, timeout=3):
        return
    # Interrupting, as Ctrl-C would, lets each server shut down in its own way,
    # but on Windows cannot be aimed at one process without reaching this one.
    asks = (
        ("terminate", "kill") if os.name == "nt" else ("interrupt", "terminate", "kill")
    )
    for ask in asks:
        for control_system, server in servers.items():
            if server.poll() is not None:
                continue
            if ask == "interrupt":
                server.send_signal(signal.SIGINT)
            elif ask == "terminate":
                server.terminate()
            else:
                print(f"{control_system} did not stop; killing it.", file=sys.stderr)
                server.kill()
        if _wait(servers, timeout=5):
            return


class _Terminated(Exception):
    """This script was asked to stop, other than by Ctrl-C."""


def _terminated(signum, frame):
    raise _Terminated()


def main() -> int:
    args = parse_arguments()
    if args.render:
        render(args.settings)
    settings = _load_settings(args.settings)
    # Whatever runs this script other than a terminal, such as a service
    # manager or `timeout`, stops it by terminating it, which would otherwise
    # leave the servers running with nothing to stop them.
    signal.signal(signal.SIGTERM, _terminated)
    servers = start(settings, args)
    if not servers:
        print("Nothing to serve.", file=sys.stderr)
        return 1
    print("Press Ctrl-C to stop.")
    try:
        while True:
            for control_system, server in servers.items():
                if server.poll() is not None:
                    # The servers are one machine, so are not left half running
                    print(
                        f"{control_system} exited with code {server.returncode}; "
                        "stopping.",
                        file=sys.stderr,
                    )
                    stop(servers)
                    return server.returncode or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop(servers, interrupted=True)
        return 0
    except _Terminated:
        stop(servers)
        return 0


if __name__ == "__main__":
    sys.exit(main())
