from typing import List, Dict, Tuple, Any, Type
import os
from caproto.server import ioc_arg_parser, PVGroup
from p4p.server.thread import SharedPV
import yaml
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


def construct_ca_iocs(
    pv_map: Dict[str, Any],
    device_name: str,
    ioc_cls: Type = None,
    translator: SchemaTranslator = None,
) -> Dict[str, Type]:
    if ioc_cls is None:
        raise ValueError("ioc_cls must be provided for constructing CA IOCs")
    if translator is None:
        raise ValueError("translator must be provided for constructing CA IOCs")
    ca_iocs = {}
    ioc_options, _ = ioc_arg_parser(
        default_prefix="", desc="Simulated EPICS records IOC"
    )
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
