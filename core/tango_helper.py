"""Building and serving the TANGO devices of a simulated machine.

The EPICS side of SARABI renames each IOC's PVs to the identifiers in the
device definitions, prefixed with ``VM-``. TANGO addresses are structured --
``domain/family/member/attribute`` -- so the equivalent here is:

* the device is ``VM/<device type>/<device name>``, e.g.
  ``VM/Solenoid/JFEL-L01-MAG-SOL-01``; a definition whose identifiers are
  already TANGO addresses (``domain/family/member/attribute``) keeps them,
  with ``VM-`` prefixed to the domain;
* the attribute is the last field of the identifier -- ``CalcK`` for
  ``JFEL-L01-MAG-SOL-01:CalcK`` -- or the handle if the identifier has no
  such field.

The servers run without a TANGO database, from a file database written at
startup, so nothing has to be registered with a running TANGO system. Clients
address the devices as ``tango://<host>:<port>/<device>#dbase=no``.
"""

import os
import re
import signal
import tempfile
import threading
import warnings
from typing import Any, Dict, Iterable, List, Optional, Tuple, Type

from .device.base_server import (
    DEFAULT_TIMESTEP,
    TangoDeviceSpec,
    TangoSimulatedDevice,
)
from .helper import build_simulation
from .translator import SchemaTranslator

DEFAULT_TANGO_HOST = "127.0.0.1"
DEFAULT_TANGO_PORT = 10090
"""Not TANGO's own default (10000), so as not to collide with a real database."""

SERVER_NAME = "SarabiTango"
INSTANCE_NAME = "sim"
NO_DB_FRAGMENT = "dbase=no"
DEVICE_DOMAIN = "VM"

_FIELD_FORBIDDEN = re.compile(r"[\s/#*:\\]+")
_ATTRIBUTE_FORBIDDEN = re.compile(r"[^A-Za-z0-9_]+")
RESERVED_ATTRIBUTES = ("state", "status")
"""Attributes every TANGO device has already; a variable so named is suffixed."""


def tango_host() -> str:
    return os.getenv("SARABI_TANGO_HOST", DEFAULT_TANGO_HOST)


def tango_port() -> int:
    return int(os.getenv("SARABI_TANGO_PORT", str(DEFAULT_TANGO_PORT)))


def sanitise_field(field: str) -> str:
    """A valid TANGO device-name field: no separators, wildcards or whitespace."""
    cleaned = _FIELD_FORBIDDEN.sub("_", str(field).strip()).strip("_")
    return cleaned or "unnamed"


def sanitise_attribute_name(name: str) -> str:
    """A valid TANGO attribute name: letters, digits and underscores."""
    cleaned = _ATTRIBUTE_FORBIDDEN.sub("_", str(name).strip()).strip("_")
    if not cleaned:
        return "unnamed"
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    if cleaned.lower() in RESERVED_ATTRIBUTES:
        # `State` and `Status` exist on every device (names are case-insensitive).
        cleaned += "_"
    return cleaned


def is_tango_address(identifier: Optional[str]) -> bool:
    """Whether `identifier` is already ``domain/family/member/attribute``."""
    return isinstance(identifier, str) and identifier.count("/") >= 3


def tango_attribute_name(identifier: Optional[str], handle: str) -> str:
    """The attribute name for a variable, from its identifier or else its handle."""
    if is_tango_address(identifier):
        return sanitise_attribute_name("_".join(identifier.split("/")[3:]))
    if isinstance(identifier, str) and ":" in identifier:
        suffix = identifier.rsplit(":", 1)[1]
        if suffix:
            return sanitise_attribute_name(suffix)
    return sanitise_attribute_name(handle)


def tango_device_name(
    device_name: str, device_type: str, identifiers: Iterable[Optional[str]] = ()
) -> str:
    """The TANGO device name for one definition.

    Definitions addressed by TANGO name keep it, with ``VM-`` prefixed to the
    domain; all others are ``VM/<device type>/<device name>``.
    """
    addressed = {
        "/".join(identifier.split("/")[:3])
        for identifier in identifiers
        if is_tango_address(identifier)
    }
    if addressed:
        if len(addressed) > 1:
            warnings.warn(
                f"{device_name} names more than one TANGO device {sorted(addressed)}; "
                f"using {sorted(addressed)[0]}."
            )
        domain, family, member = sorted(addressed)[0].split("/")
        return "/".join(
            (
                f"{DEVICE_DOMAIN}-{sanitise_field(domain)}",
                sanitise_field(family),
                sanitise_field(member),
            )
        )
    return "/".join(
        (DEVICE_DOMAIN, sanitise_field(device_type), sanitise_field(device_name))
    )


def common_attribute_names(
    pv_maps: Iterable[Dict[str, Any]], translator: SchemaTranslator
) -> Dict[str, str]:
    """The attribute name to declare for each handle of a device type.

    TANGO attribute names are fixed per class where EPICS PV names are per
    device, so a handle whose identifiers do not agree on a name across the
    devices of a type is declared under its handle instead, and reported.
    """
    candidates: Dict[str, set] = {}
    for pv_map in pv_maps:
        for handle, config in pv_map.items():
            if not isinstance(config, dict):
                continue
            identifier = config.get(translator.identifier_word)
            candidates.setdefault(handle, set()).add(
                tango_attribute_name(identifier, handle)
            )
    names = {}
    for handle, options in candidates.items():
        if len(options) == 1:
            names[handle] = next(iter(options))
        else:
            names[handle] = sanitise_attribute_name(handle)
            warnings.warn(
                f"Handle '{handle}' has several TANGO attribute names across devices "
                f"{sorted(options)}; declaring it as '{names[handle]}'."
            )
    return names


def device_address(device_name: str, host: str = None, port: int = None) -> str:
    """The full, database-less address of a device."""
    host = host or tango_host()
    port = port or tango_port()
    return f"tango://{host}:{port}/{device_name}#{NO_DB_FRAGMENT}"


def attribute_address(
    device_name: str, attribute_name: str, host: str = None, port: int = None
) -> str:
    host = host or tango_host()
    port = port or tango_port()
    return f"tango://{host}:{port}/{device_name}/{attribute_name}#{NO_DB_FRAGMENT}"


def construct_tango_devices(
    pv_map: Dict[str, Any],
    device_name: str,
    device_type: str,
    device_cls: Type[TangoSimulatedDevice] = None,
    translator: SchemaTranslator = None,
    timestep: float = DEFAULT_TIMESTEP,
) -> Dict[str, Dict[str, str]]:
    """Register one definition's TANGO device with its generated class.

    Returns ``{device name: {attribute name: handle}}`` for the device, in the
    way the EPICS constructors return the PVs they serve keyed by PV name.
    The device itself is created by the TANGO server when it starts.
    """
    if device_cls is None:
        raise ValueError("device_cls must be provided for constructing TANGO devices")
    if translator is None:
        raise ValueError("translator must be provided for constructing TANGO devices")
    if not pv_map:
        return {}

    declared = device_cls.declared_attributes()
    handles = []
    attributes = {}
    for handle, config in pv_map.items():
        if not isinstance(config, dict):
            continue
        if handle not in declared:
            print(
                f"Warning: Attribute '{handle}' not found in TANGO device class "
                f"'{device_cls.__name__}'."
            )
            continue
        handles.append(handle)
        attributes[declared[handle].name] = handle
    if not handles:
        return {}

    identifiers = [
        config.get(translator.identifier_word)
        for config in pv_map.values()
        if isinstance(config, dict)
    ]
    name = tango_device_name(device_name, device_type, identifiers)
    pv_pairs, updates = build_simulation(pv_map, device_name, translator)
    device_cls.configure(
        name,
        TangoDeviceSpec(
            handles=handles,
            timestep=timestep,
            pv_pairs=pv_pairs,
            updates=updates,
        ),
    )
    return {name: attributes}


def write_file_database(
    path: str,
    devices_by_class: Dict[str, List[str]],
    server_name: str = SERVER_NAME,
    instance_name: str = INSTANCE_NAME,
) -> str:
    """Write a TANGO file database listing the devices of each class.

    A file database lets one server host several classes without a TANGO
    database; ``-nodb -dlist`` only supports one.
    """
    from tango import Database

    with open(path, "w") as f:
        for class_name, device_names in devices_by_class.items():
            if not device_names:
                continue
            quoted = ", ".join(f'"{name}"' for name in device_names)
            f.write(f"{server_name}/{instance_name}/DEVICE/{class_name}: {quoted}\n")
    Database(path)  # raises DevFailed if the file is not a valid database
    return path


def _kill_server() -> None:
    """Ask the running TANGO server to shut down, from any thread."""
    import tango

    with tango.EnsureOmniThread():
        try:
            tango.Util.instance().get_dserver_device().kill()
        except Exception as exc:  # pragma: no cover - only at shutdown
            warnings.warn(f"Could not stop the TANGO server cleanly: {exc}")


def run_tango_server(
    devices_by_class: Dict[Type[TangoSimulatedDevice], List[str]],
    stop_event: threading.Event = None,
    ready_event: threading.Event = None,
    host: str = None,
    port: int = None,
    server_name: str = SERVER_NAME,
    instance_name: str = INSTANCE_NAME,
    verbose: int = 0,
) -> None:
    """Serve `devices_by_class` until `stop_event` is set. Blocks.

    Runs one database-less TANGO server hosting every class given. TANGO
    allows one server per process, so this is called once, in its own thread
    if EPICS IOCs share the process. `ready_event` is set once every device
    has been created and the server is accepting connections, which can take
    a while: TANGO resolves the name of every network interface on startup.
    """
    from tango.server import run

    host = host or tango_host()
    port = port or tango_port()
    classes = [cls for cls, names in devices_by_class.items() if names]
    if not classes:
        return

    handle, db_path = tempfile.mkstemp(prefix="sarabi_tango_", suffix=".db")
    os.close(handle)
    write_file_database(
        db_path,
        {cls.__name__: names for cls, names in devices_by_class.items()},
        server_name=server_name,
        instance_name=instance_name,
    )
    args = [
        server_name,
        instance_name,
        "-ORBendPoint",
        f"giop:tcp:{host}:{port}",
        f"-file={db_path}",
    ]
    if verbose:
        args.append(f"-v{int(verbose)}")

    started = threading.Event()
    exited = threading.Event()

    def post_init():
        started.set()
        if ready_event is not None:
            ready_event.set()
        if stop_event is not None:
            # The server owns this thread once running, so the stop request
            # is watched from another and delivered as a Kill -- unless the
            # server has already gone, as it has when TANGO handled a SIGINT
            # or SIGTERM itself.
            def wait_and_kill():
                stop_event.wait()
                if not exited.is_set():
                    _kill_server()

            threading.Thread(target=wait_and_kill, daemon=True, name="tango stop").start()

    try:
        run(classes, args, post_init_callback=post_init, raises=True)
    except Exception as exc:
        if started.is_set():
            # The server ran and has been asked to stop, by our Kill or by a
            # signal TANGO handled itself. Its cleanup complains when not run
            # from the main thread, which is of no consequence.
            print(f"TANGO server stopped ({type(exc).__name__}: {exc})")
        else:
            raise
    finally:
        exited.set()
        if stop_event is not None:
            # Whatever ended the server, tell the process it is gone.
            stop_event.set()
        try:
            os.remove(db_path)
        except OSError:
            pass


def _raise_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt


def restore_signal_handlers() -> bool:
    """Re-install Python's SIGINT and SIGTERM handlers where TANGO has replaced them.

    Once its server starts, TANGO handles both signals itself and stops the
    TANGO server alone. `run_tango_server` reports that by setting its stop
    event, which the runners treat as a request to stop everything; this is
    the other half, giving Ctrl-C back to Python where TANGO installed a
    handler of its own (`signal.getsignal` returns None for one not set from
    Python). Call it from the main thread; returns whether anything changed.
    """
    if threading.current_thread() is not threading.main_thread():
        return False
    restored = False
    if signal.getsignal(signal.SIGINT) is None:
        signal.signal(signal.SIGINT, signal.default_int_handler)
        restored = True
    if signal.getsignal(signal.SIGTERM) is None:
        signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
        restored = True
    return restored


def devices_by_class(
    class_devices: Dict[Type[TangoSimulatedDevice], Iterable[str]]
) -> Dict[Type[TangoSimulatedDevice], List[str]]:
    """Normalise a mapping of class to device names, dropping duplicates."""
    result = {}
    for cls, names in class_devices.items():
        seen = []
        for name in names:
            if name.lower() not in [s.lower() for s in seen]:
                seen.append(name)
        result[cls] = seen
    return result


def describe(devices: Dict[str, Dict[str, str]], host: str = None, port: int = None) -> str:
    """A listing of every device and attribute address being served."""
    lines = []
    for device_name in sorted(devices):
        lines.append(device_address(device_name, host, port))
        for attribute_name, handle in sorted(devices[device_name].items()):
            lines.append(f"    {attribute_name:<24} ({handle})")
    return "\n".join(lines)


def report_when_ready(
    ready_event: threading.Event,
    devices: Dict[str, Dict[str, str]],
    host: str = None,
    port: int = None,
) -> threading.Thread:
    """Print the served addresses once the TANGO server is up. Returns the thread."""
    host = host or tango_host()
    port = port or tango_port()
    print(
        f"Starting TANGO server for {len(devices)} device(s) on {host}:{port}; "
        "this can take up to a minute while TANGO resolves the local network interfaces..."
    )

    def report():
        ready_event.wait()
        print("TANGO server ready. Devices (dbase=no):")
        print(describe(devices, host, port))
        print(
            f"Client example: tango.DeviceProxy({device_address(sorted(devices)[0], host, port)!r})"
            if devices
            else ""
        )

    thread = threading.Thread(target=report, daemon=True, name="tango report")
    thread.start()
    return thread
