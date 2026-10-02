"""Building and running the TANGO devices of generated device servers.

This is to the generated TANGO servers what `helper` is to the generated IOCs.
It is kept apart from it so that neither control system needs the other's
libraries installed.
"""

import argparse
import atexit
import os
import shutil
import tempfile
import threading
import warnings
from typing import Any, Dict, List, Tuple, Type

import tango
from tango.server import run

from .device.base_server import DEFAULT_TIMESTEP
from .device.tango_server import (
    BINDINGS,
    DeviceBinding,
    SimulatedModel,
    TangoSimulatedDevice,
    bind,
    drive,
)
from .discovery import find_device_files, iter_devices
from .helper import build_simulation
from .protocols import TANGO, protocol_of
from .tango_naming import tango_devices
from .translator import SchemaTranslator

SERVER_NAME = "Sarabi"
DEFAULT_INSTANCE = "virtual"
DEFAULT_PORT = 6092
"""Follows on from the ports the IOCs serve Channel Access and PV Access on."""


def construct_tango_devices(
    variables: Dict[str, Any],
    device_name: str,
    device_type: str,
    translator: SchemaTranslator = None,
    timestep: float = DEFAULT_TIMESTEP,
) -> Tuple[SimulatedModel, Dict[str, DeviceBinding]]:
    """The model simulating one device definition, and the devices serving it.

    Pairs and signals are per-device, so they are built here rather than in the
    generated class, which is shared by every device of its type.
    """
    if translator is None:
        raise ValueError("translator must be provided for constructing TANGO devices")
    tango_variables = {
        handle: config
        for handle, config in variables.items()
        if protocol_of(config, translator.protocol_word) == TANGO
    }
    pv_pairs, updates = build_simulation(tango_variables, device_name, translator)
    model = SimulatedModel(
        device_name, timestep=timestep, pv_pairs=pv_pairs, updates=updates
    )
    bindings = {
        name: DeviceBinding(model=model, handles=handles)
        for name, handles in tango_devices(
            device_type, device_name, tango_variables, translator
        ).items()
    }
    return model, bindings


def construct_servers(
    device_classes: Dict[str, Type[TangoSimulatedDevice]],
    yaml_dir: str,
    translator: SchemaTranslator,
    timestep: float = DEFAULT_TIMESTEP,
) -> Tuple[Dict[Type[TangoSimulatedDevice], List[str]], List[SimulatedModel]]:
    """Bind every device defined under `yaml_dir` to its model.

    Returns the names of the devices each class is to serve, and the models to
    advance while it does.
    """
    device_files = find_device_files(yaml_dir)
    devices: Dict[Type[TangoSimulatedDevice], List[str]] = {}
    models: List[SimulatedModel] = []
    served = {}
    for device_type, device_cls in device_classes.items():
        for device_name, variables in iter_devices(
            device_files.get(device_type, []), translator
        ):
            model, bindings = construct_tango_devices(
                variables,
                device_name,
                device_type,
                translator=translator,
                timestep=timestep,
            )
            for name, binding in bindings.items():
                if name.lower() in served:
                    warnings.warn(
                        f"{device_name} and {served[name.lower()]} both define the "
                        f"TANGO device {name}; not serving it for {device_name}."
                    )
                    continue
                served[name.lower()] = device_name
                bind(name, binding)
                devices.setdefault(device_cls, []).append(name)
            if bindings:
                models.append(model)
    return devices, models


def _write_file_database(
    path: str, instance: str, devices: Dict[Type[TangoSimulatedDevice], List[str]]
) -> None:
    """Describe the server's devices in a file TANGO reads in place of a database."""
    with open(path, "w") as f:
        for device_cls, names in devices.items():
            f.write(f"{SERVER_NAME}/{instance}/DEVICE/{device_cls.__name__}: ")
            f.write(", ".join(names))
            f.write("\n")


def _register_devices(
    instance: str, devices: Dict[Type[TangoSimulatedDevice], List[str]]
) -> None:
    """Register the server's devices in the TANGO database.

    The server is registered afresh, so that devices whose definitions have
    since been removed are not served again.
    """
    database = tango.Database()
    server = f"{SERVER_NAME}/{instance}"
    if server.lower() in (s.lower() for s in database.get_server_list(server)):
        database.delete_server(server)
    for device_cls, names in devices.items():
        for name in names:
            info = tango.DbDevInfo()
            info.name = name
            info._class = device_cls.__name__
            info.server = server
            database.add_device(info)


def _print_addresses(
    devices: Dict[Type[TangoSimulatedDevice], List[str]], prefix: str, suffix: str
) -> None:
    """Print where each variable is served, alongside the variable it is."""
    for names in devices.values():
        for name in names:
            binding = BINDINGS[name.lower()]
            for attribute, handle in binding.handles.items():
                print(
                    f"{prefix}{name}/{attribute}{suffix}\t{binding.model.name} {handle}"
                )


def parse_arguments(description: str = "Run the simulated TANGO device servers."):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--timestep",
        type=float,
        default=DEFAULT_TIMESTEP,
        help="Interval, in seconds, on which simulated attributes are advanced.",
    )
    parser.add_argument(
        "--instance",
        type=str,
        default=DEFAULT_INSTANCE,
        help=f"Instance name of the {SERVER_NAME} device server.",
    )
    parser.add_argument(
        "--database",
        nargs="?",
        const=True,
        default=None,
        metavar="HOST:PORT",
        help="Register the devices in a TANGO database and serve them through it, "
        "rather than without one. Uses TANGO_HOST if no address is given.",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="",
        help="Interface to serve on without a database. Defaults to all of them.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Port to serve on. Defaults to {DEFAULT_PORT} without a database.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the address of every attribute that would be served, and exit.",
    )
    parser.add_argument(
        "--verbose",
        type=int,
        default=0,
        metavar="LEVEL",
        help="TANGO's own logging level, from 1 to 5.",
    )
    return parser.parse_args()


def serve(
    device_classes: Dict[str, Type[TangoSimulatedDevice]],
    yaml_dir: str,
    translator: SchemaTranslator,
    args: argparse.Namespace,
) -> None:
    """Serve every device defined under `yaml_dir` from one device server.

    `device_classes` gives the generated class serving each device type.
    """
    devices, models = construct_servers(
        device_classes, yaml_dir, translator, timestep=args.timestep
    )
    if not devices:
        print(f"Found no TANGO variables under {yaml_dir}; nothing to serve.")
        return

    server_args = [SERVER_NAME, args.instance]
    if args.database:
        if args.database is not True:
            os.environ["TANGO_HOST"] = args.database
        if not os.getenv("TANGO_HOST"):
            raise SystemExit("--database needs an address, or TANGO_HOST to be set.")
        prefix, suffix = f"tango://{os.environ['TANGO_HOST']}/", ""
        port = args.port
    else:
        port = args.port if args.port is not None else DEFAULT_PORT
        prefix = f"tango://{args.host or 'localhost'}:{port}/"
        suffix = "#dbase=no"

    if args.list:
        _print_addresses(devices, prefix, suffix)
        return

    if not args.database:
        directory = tempfile.mkdtemp(prefix="sarabi-tango-")
        atexit.register(shutil.rmtree, directory, ignore_errors=True)
        database_file = os.path.join(directory, "devices.db")
        _write_file_database(database_file, args.instance, devices)
        server_args.append(f"-file={database_file}")
    if port is not None:
        server_args += ["-ORBendPoint", f"giop:tcp:{args.host}:{port}"]
    if args.verbose:
        server_args.append(f"-v{args.verbose}")

    count = sum(len(names) for names in devices.values())
    print(f"Serving {count} TANGO devices as {SERVER_NAME}/{args.instance}, e.g.")
    print(f"  {prefix}{next(iter(devices.values()))[0]}{suffix}")
    print("Run with --list for the address of every attribute.")

    def start_simulation():
        threading.Thread(
            target=drive, args=(models, args.timestep), daemon=True
        ).start()

    # Left to itself `run` reports a server that fails to start and returns as
    # though it had not, which whatever started this one could not tell from
    # it having been stopped.
    try:
        if args.database:
            _register_devices(args.instance, devices)
        run(
            tuple(devices),
            args=server_args,
            post_init_callback=start_simulation,
            raises=True,
        )
    except KeyboardInterrupt:
        print("Interrupted; stopping.")
    except tango.DevFailed as exc:
        raise SystemExit(f"The TANGO device server failed:\n{exc}")
