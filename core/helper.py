from typing import List, Dict, Tuple, Any, Type
import os
import warnings
from caproto.server import PVGroup, template_arg_parser
from p4p.server.thread import SharedPV
import yaml
from .device.base_server import (
    DEFAULT_TIMESTEP,
    PVPair,
    SimulatedPVGroup,
    UpdateSignal,
)
from .effects.resolve import build
from .translator import SchemaTranslator
from .IOCManager import IOCManager


def separate_by_protocol(pv_map: Dict) -> Tuple[
    Dict[str, Dict],
    Dict[str, Dict],
]:
    ca_pv_map = {}
    pva_pv_map = {}
    for key, value in pv_map.items():
        protocol = value.get("protocol", "CA")
        if protocol == "CA":
            ca_pv_map[key] = value
        else:
            pva_pv_map[key] = value
    return ca_pv_map, pva_pv_map


def _verify_classname(device_name: str, protocol: str = "CA") -> str:
    if protocol == "CA":
        class_name = (
            device_name.replace("-", "_").replace(":", "_") + "_IOC"
        )  # Replace invalid characters
        if class_name.startswith(
            tuple("0123456789")
        ):  # Check if it starts with a number
            class_name = (
                "_" + class_name
            )  # Prefix with underscore if it starts with a number
        return class_name
    elif protocol == "PVA":
        class_name = (
            device_name.replace("-", "_").replace(":", "_") + "_PVAIOC"
        )  # Replace invalid characters
        if class_name.startswith(
            tuple("0123456789")
        ):  # Check if it starts with a number
            class_name = (
                "_" + class_name
            )  # Prefix with underscore if it starts with a number
        return class_name
    else:
        raise ValueError(f"Unsupported protocol: {protocol}")


def _handle_for(reference: str, pv_map: Dict[str, Any], translator: SchemaTranslator) -> str:
    """The PV handle matching `reference`, which may be a handle or a PV name.

    Definitions may link a setpoint to its readback by either, since the handle
    is local to the device while the identifier is the name on the network.
    Returns None if neither matches.
    """
    if reference in pv_map:
        return reference
    for handle, config in pv_map.items():
        if isinstance(config, dict) and config.get(translator.identifier_word) == reference:
            return handle
    return None


def _build_effect(spec: Dict[str, Any], key: str, what: str, device_name: str):
    """Instantiate a response model or update signal, or None if it cannot be built.

    A definition naming something unimportable is reported and skipped, so that
    one bad device does not stop a machine from being simulated.
    """
    if not isinstance(spec, dict):
        warnings.warn(f"{what} for {device_name} must be a mapping, got {type(spec).__name__}")
        return None
    try:
        return build(spec, key)
    except (LookupError, TypeError) as exc:
        warnings.warn(f"Cannot build {what} for {device_name}: {exc}")
        return None


def build_simulation(
    pv_map: Dict[str, Any],
    device_name: str,
    translator: SchemaTranslator,
) -> Tuple[List[PVPair], List[UpdateSignal]]:
    """Build the setpoint/readback pairs and update signals for one device.

    Pairs may be declared from either end -- a setpoint naming its readback, or
    a readback naming its setpoint -- and the response model may be attached to
    either; the two ends are matched up here so each pair is simulated once.
    """
    pairs: Dict[Tuple[str, str], PVPair] = {}
    updates: List[UpdateSignal] = []

    for handle, config in pv_map.items():
        if not isinstance(config, dict):
            continue

        for word, this_is_setpoint in (
            (translator.readback_word, True),
            (translator.setpoint_word, False),
        ):
            reference = config.get(word)
            if not reference:
                continue
            other = _handle_for(reference, pv_map, translator)
            if other is None:
                warnings.warn(
                    f"Cannot find PV '{reference}' referenced by "
                    f"{device_name}:{handle}; not simulating that pair."
                )
                continue

            key = (handle, other) if this_is_setpoint else (other, handle)
            dynamics = config.get(translator.dynamics_word)
            if key in pairs and (pairs[key].dynamics is not None or dynamics is None):
                continue
            pairs[key] = PVPair(
                setpoint=key[0],
                readback=key[1],
                dynamics=(
                    _build_effect(
                        dynamics,
                        translator.dynamics_model_key,
                        "dynamics",
                        f"{device_name}:{handle}",
                    )
                    if dynamics
                    else None
                ),
            )

        update = config.get(translator.update_word)
        if update:
            signal = _build_effect(
                update,
                translator.update_function_key,
                "update",
                f"{device_name}:{handle}",
            )
            if signal is not None:
                updates.append(UpdateSignal(handle=handle, signal=signal))

    return list(pairs.values()), updates


def construct_ca_iocs(
    pv_map: Dict[str, Any],
    device_name: str,
    ioc_cls: Type = None,
    translator: SchemaTranslator = None,
    timestep: float = DEFAULT_TIMESTEP,
) -> Dict[str, Type]:
    if ioc_cls is None:
        raise ValueError("ioc_cls must be provided for constructing CA IOCs")
    if translator is None:
        raise ValueError("translator must be provided for constructing CA IOCs")
    ca_iocs = {}
    # Take caproto's default options without re-parsing the command line: the
    # script running the IOCs owns that, and passes anything relevant here as an
    # argument. `ioc_arg_parser` would parse sys.argv and reject those flags --
    # it accepts an `argv` argument but does not pass it on to `parse_args`.
    parser, split_args = template_arg_parser(
        default_prefix="", desc="Simulated EPICS records IOC", argv=[]
    )
    ioc_options, _ = split_args(parser.parse_args([]))
    if issubclass(ioc_cls, SimulatedPVGroup):
        # Pairs and signals are per-device, so they are built here rather than
        # in the generated class, which is shared by every device of its type.
        pv_pairs, updates = build_simulation(pv_map, device_name, translator)
        _ioc = ioc_cls(
            **ioc_options,
            timestep=timestep,
            pv_pairs=pv_pairs,
            updates=updates,
        )
    else:
        _ioc = ioc_cls(**ioc_options)
    for key, prop in _ioc.pvdb.items():
        pv_name = pv_map.get(key, {}).get(translator.identifier_word, "")
        if pv_name:
            # only add found PVs
            prop.name = "VM-" + pv_name
            ca_iocs.update({prop.name: prop})
    return ca_iocs


def construct_pva_iocs(
    pv_map: Dict[str, Any],
    device_name: str,
    ioc_cls: Type = None,
    translator: SchemaTranslator = None,
) -> Dict[str, Type]:
    if ioc_cls is None:
        raise ValueError("ioc_cls must be provided for constructing PVA IOCs")
    if translator is None:
        raise ValueError("translator must be provided for constructing PVA IOCs")
    pva_iocs = {}
    # Initialize the appropriate class based on the device name
    class_name = _verify_classname(device_name, protocol="PVA")
    _ioc = ioc_cls()
    for key, prop in pv_map.items():
        # Use the PV name from the YAML file if available
        pv_name = prop.get(translator.identifier_word, "")
        if pv_name:
            # only add found PVs
            try:
                handle = getattr(_ioc, key)
                pva_iocs.update({"VM-" + pv_name: handle})
            except AttributeError:
                print(
                    f"Warning: Attribute '{key}' not found in PV Access IOC class '{class_name}'."
                )
    return pva_iocs


def _get_device_info(
    yaml_dir: str, translator: SchemaTranslator
) -> List[Dict[str, Dict]]:
    device_info = []
    for filename in os.listdir(yaml_dir):
        yaml_file_path = os.path.join(yaml_dir, filename)
        if filename.endswith(".yaml"):
            with open(yaml_file_path) as f:
                data = yaml.safe_load(f)
            device_name = data.get("name", os.path.splitext(filename)[0])
            pv_map = data.get(translator.controls_information_word, {}).get(
                translator.signal_information_word, {}
            )
            if pv_map:
                # only add valid controls information
                device_info.append({device_name: pv_map})
    return device_info


def _create_ioc_manager(
    ca_pv_map: Dict[str, PVGroup], pva_pv_map: Dict[str, SharedPV]
) -> IOCManager:
    ioc_manager = IOCManager()
    if ca_pv_map:
        ioc_manager.update_ca_iocs(ca_pv_map)
    if pva_pv_map:
        ioc_manager.update_pva_iocs(pva_pv_map)
    return ioc_manager
