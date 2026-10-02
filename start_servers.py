"""Render and start the simulated control system servers.

One command to go from a directory of device definitions to running servers::

    python start_servers.py --settings=./settings.yaml

which renders the IOC and TANGO device modules (`render_iocs.py`), the runner
scripts (`render_main.py`), and then starts the servers. By default every
device type is served from one process (``run_all_iocs.py``); with
``--per-type`` each device type's ``main.py`` runs in a process of its own.

    python start_servers.py --settings=./settings.yaml --no-render
    python start_servers.py --settings=./settings.yaml --per-type --timestep=0.05
    python start_servers.py --settings=./settings.yaml --tango-port=10100 --check

Ports are set for the child processes through the same environment variables
the runners read, so anything else in the same shell sees the same values:

    EPICS_CA_SERVER_PORT   (default 6090)
    EPICS_PVA_SERVER_PORT  (default 6091)
    SARABI_TANGO_HOST      (default 127.0.0.1)
    SARABI_TANGO_PORT      (default 10090)

``--check`` waits for the TANGO server and reads one attribute from every
TANGO device, to confirm they are reachable. Stop everything with Ctrl-C.
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from typing import Dict, List, Tuple

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)
from core.settings import Settings  # noqa: E402
from core.translator import SchemaTranslator  # noqa: E402
from core import tango_helper  # noqa: E402
from core.protocols import TANGO, protocol_of  # noqa: E402


def parse_arguments():
    parser = argparse.ArgumentParser(description="Render and start the simulated servers.")
    parser.add_argument("--settings", type=str, required=True, help="Path to the settings YAML file.")
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="Start the previously rendered servers without rendering again.",
    )
    parser.add_argument(
        "--per-type",
        action="store_true",
        help="Run each device type's main.py in its own process rather than run_all_iocs.py.",
    )
    parser.add_argument(
        "--timestep",
        type=float,
        default=None,
        help="Interval, in seconds, on which simulated values are advanced (passed to the runners).",
    )
    parser.add_argument("--ca-port", type=int, default=None, help="EPICS Channel Access server port.")
    parser.add_argument("--pva-port", type=int, default=None, help="EPICS PV Access server port.")
    parser.add_argument("--tango-host", type=str, default=None, help="Host the TANGO server binds to.")
    parser.add_argument("--tango-port", type=int, default=None, help="TANGO server port.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Once the TANGO server is up, read one attribute from every TANGO device.",
    )
    parser.add_argument(
        "--check-timeout",
        type=float,
        default=180.0,
        help="Seconds to wait for the TANGO server before --check gives up (default 180).",
    )
    return parser.parse_args()


def load_settings(settings_yaml: str) -> Settings:
    if not os.path.exists(settings_yaml):
        raise FileNotFoundError(f"Could not find {settings_yaml}")
    with open(settings_yaml, "r") as f:
        return Settings(**yaml.load(f, Loader=yaml.SafeLoader))


def render(settings_yaml: str) -> None:
    for script in ("render_iocs.py", "render_main.py"):
        print(f"--- {script}")
        subprocess.run(
            [sys.executable, os.path.join(HERE, script), f"--settings={settings_yaml}"],
            check=True,
            cwd=HERE,
        )


def environment(args) -> Dict[str, str]:
    env = dict(os.environ)
    if args.ca_port is not None:
        env["EPICS_CA_SERVER_PORT"] = str(args.ca_port)
    if args.pva_port is not None:
        env["EPICS_PVA_SERVER_PORT"] = str(args.pva_port)
    if args.tango_host is not None:
        env["SARABI_TANGO_HOST"] = args.tango_host
    if args.tango_port is not None:
        env["SARABI_TANGO_PORT"] = str(args.tango_port)
    env.setdefault("EPICS_CA_SERVER_PORT", "6090")
    env.setdefault("EPICS_PVA_SERVER_PORT", "6091")
    env.setdefault("SARABI_TANGO_HOST", tango_helper.DEFAULT_TANGO_HOST)
    env.setdefault("SARABI_TANGO_PORT", str(tango_helper.DEFAULT_TANGO_PORT))
    return env


def runner_commands(settings: Settings, args) -> List[Tuple[str, List[str], str]]:
    """The ``(label, command, working directory)`` of each runner to start."""
    extra = [f"--timestep={args.timestep}"] if args.timestep is not None else []
    output = os.path.abspath(settings.output_directory)
    if not args.per_type:
        script = os.path.join(output, "run_all_iocs.py")
        if not os.path.exists(script):
            raise FileNotFoundError(f"{script} not found; run without --no-render first.")
        return [("all", [sys.executable, script, *extra], output)]
    commands = []
    for device_type in sorted(os.listdir(output)):
        if device_type in settings.ignore_device_types:
            continue
        script = os.path.join(output, device_type, "main.py")
        if os.path.exists(script):
            commands.append((device_type, [sys.executable, script, *extra], os.path.dirname(script)))
    if not commands:
        raise FileNotFoundError(f"No main.py found under {output}; run without --no-render first.")
    return commands


def tango_devices(settings: Settings) -> Dict[str, List[str]]:
    """The TANGO device name and attribute names of every definition using TANGO."""
    translator = SchemaTranslator(settings.schema_file)
    devices: Dict[str, List[str]] = {}
    for root, _, files in os.walk(settings.devices_directory):
        device_type = os.path.basename(root)
        if device_type in settings.ignore_device_types:
            continue
        for filename in files:
            if not filename.lower().endswith((".yaml", ".yml")):
                continue
            with open(os.path.join(root, filename)) as f:
                data = yaml.safe_load(f) or {}
            pv_map = (data.get(translator.controls_information_word) or {}).get(
                translator.signal_information_word
            ) or {}
            tango_map = {
                handle: config
                for handle, config in pv_map.items()
                if isinstance(config, dict) and protocol_of(config, translator.protocol_word) == TANGO
            }
            if not tango_map:
                continue
            name = data.get("name", os.path.splitext(filename)[0])
            identifiers = [c.get(translator.identifier_word) for c in tango_map.values()]
            device = tango_helper.tango_device_name(name, device_type, identifiers)
            devices[device] = [
                tango_helper.tango_attribute_name(c.get(translator.identifier_word), h)
                for h, c in tango_map.items()
            ]
    return devices


def check_tango(settings: Settings, env: Dict[str, str], timeout: float) -> bool:
    """Wait for the TANGO server, then read one attribute from every device."""
    import tango

    devices = tango_devices(settings)
    if not devices:
        print("No TANGO variables in the definitions; nothing to check.")
        return True
    host, port = env["SARABI_TANGO_HOST"], int(env["SARABI_TANGO_PORT"])
    first = sorted(devices)[0]
    print(f"Waiting up to {timeout:.0f}s for the TANGO server on {host}:{port} ({len(devices)} devices)...")
    deadline = time.time() + timeout
    proxy = None
    while time.time() < deadline:
        try:
            proxy = tango.DeviceProxy(tango_helper.device_address(first, host, port))
            proxy.ping()
            break
        except Exception:
            proxy = None
            time.sleep(2.0)
    if proxy is None:
        print("TANGO server did not come up in time.")
        return False

    failures = 0
    for device, attributes in sorted(devices.items()):
        try:
            proxy = tango.DeviceProxy(tango_helper.device_address(device, host, port))
            served = {a.lower() for a in proxy.get_attribute_list()}
            missing = [a for a in attributes if a.lower() not in served]
            value = proxy.read_attribute(attributes[0]).value
            status = "OK" if not missing else f"MISSING {missing}"
            if missing:
                failures += 1
            print(f"  {status:<8} {device}/{attributes[0]} = {value}")
        except Exception as exc:
            failures += 1
            print(f"  FAILED   {device}: {str(exc).splitlines()[0]}")
    print(f"TANGO check: {len(devices) - failures}/{len(devices)} devices OK.")
    return failures == 0


def main() -> int:
    args = parse_arguments()
    settings_yaml = os.path.abspath(args.settings)
    settings = load_settings(settings_yaml)
    if not args.no_render:
        render(settings_yaml)

    env = environment(args)
    commands = runner_commands(settings, args)
    print("--- starting servers")
    print(
        f"EPICS CA port {env['EPICS_CA_SERVER_PORT']}, PVA port {env['EPICS_PVA_SERVER_PORT']}, "
        f"TANGO {env['SARABI_TANGO_HOST']}:{env['SARABI_TANGO_PORT']}"
    )
    processes = []
    for label, command, cwd in commands:
        print(f"[{label}] {' '.join(command)}")
        processes.append((label, subprocess.Popen(command, cwd=cwd, env=env)))

    exit_code = 0
    try:
        if args.check:
            exit_code = 0 if check_tango(settings, env, args.check_timeout) else 1
        while True:
            for label, process in processes:
                code = process.poll()
                if code is not None:
                    print(f"[{label}] exited with code {code}")
                    return code or 1
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping servers...")
    finally:
        for _, process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        deadline = time.time() + 10
        for label, process in processes:
            try:
                process.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                print(f"[{label}] did not stop; killing.")
                process.kill()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
