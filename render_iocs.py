import argparse
import os
from typing import List
import format as formatter
import yaml
import warnings
from jinja2 import Template
import numpy as np
from core.pv_info import PVInfo
from core.translator import SchemaTranslator
from core.settings import Settings
from collections import Counter
from core.yaml_loader import iter_yaml_files, is_schema_yaml, resolve_device_config
from core.layout import write_allowed_devices

# Define dtype_map
CA_DTYPE_MAP = {
    "statistical": {"dtype": "ChannelType.FLOAT", "initial": 0.0},
    "scalar": {"dtype": "ChannelType.FLOAT", "initial": 0.0},
    "state": {"dtype": "ChannelType.ENUM", "initial": 0},
    "binary": {"dtype": "bool", "initial": False},
    "waveform": {
        "dtype": "ChannelType.FLOAT",
        "initial": np.zeros(1, dtype=np.float32),
    },
    "string": {
        "dtype": "ChannelType.STRING",
        "initial": "'undefined'",
    },
}

PVA_DTYPE_MAP = {
    "statistical": {"dtype": "NTScalar", "initial": 0.0},
    "float": {"dtype": "NTScalar", "initial": 0.0},
    "scalar": {"dtype": "NTScalar", "initial": 0.0},
    "int": {"dtype": "NTScalar", "initial": 0},
    "state": {"dtype": "NTEnum", "initial": 0},
    "binary": {"dtype": "NTScalar", "initial": False},
    "waveform": {
        "dtype": "NTScalar",
        "initial": np.zeros(1, dtype=np.float32),
    },
    "string": {
        "dtype": "NTScalar",
        "initial": "undefined",
    },
}


SETTINGS: Settings = None
TRANSLATOR: SchemaTranslator = None
ALLOWED_DEVICES: set = None


def _find_yaml_files(device_path: str) -> List[str]:
    """Return a list of full paths to .yaml files under device_path (recursive)."""
    yaml_files = []
    for yaml_file in iter_yaml_files(device_path, recursive=True):
        if is_schema_yaml(yaml_file):
            continue
        yaml_files.append(yaml_file)
    return yaml_files


def _find_device_folders(device_root: str) -> List[str]:
    """Return a sorted set of tuples relating device-type to yaml-folder"""
    folders = set()
    for root, _, files in os.walk(device_root):
        for fn in files:
            if fn.endswith(".yaml"):
                rel = os.path.relpath(root, device_root)
                if rel == ".":
                    # skip yaml files directly in the device_root; only include subfolders
                    continue
                folders.add((rel.split(os.sep)[-1], root))
                break
    return sorted(folders)


def _load_settings(settings_yaml: str) -> Settings:
    if not os.path.exists(settings_yaml):
        raise FileNotFoundError(f"Could not find {settings_yaml}")
    with open(settings_yaml, "r", encoding="utf-8") as f:
        _settings = yaml.load(f, Loader=yaml.SafeLoader)
        settings = Settings(**_settings)
    return settings


# Set up command-line argument parsing
def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Render IOC scripts from YAML configurations."
    )
    parser.add_argument(
        "--settings", type=str, required=True, help="Path to the settings YAML file."
    )
    return parser.parse_args()


def get_pv_maps(device_path) -> list[PVInfo]:
    pv_maps = []
    for resolved in _get_resolved_devices(device_path):
        pv_data = resolved.pv_map
        if pv_data:
            rel_filename = os.path.relpath(resolved.file_path, device_path)
            pv_map = PVInfo(filename=rel_filename, pv_map=pv_data)
            pv_maps.append(pv_map)
    return pv_maps


def _get_resolved_devices(device_path: str):
    resolved = []
    for yaml_file_path in _find_yaml_files(device_path):
        try:
            device = resolve_device_config(yaml_file_path, TRANSLATOR)
        except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
            warnings.warn(f"Skipping '{yaml_file_path}': {exc}")
            continue
        if ALLOWED_DEVICES is not None and device.device_name not in ALLOWED_DEVICES:
            continue
        resolved.append(device)
    return resolved


def _analyze_pvs(device_path: str) -> tuple[PVInfo | None, PVInfo]:
    resolved_devices = _get_resolved_devices(device_path)
    pv_maps = [
        PVInfo(filename=device.file_path, pv_map=device.pv_map)
        for device in resolved_devices
        if device.pv_map
    ]
    if not pv_maps:
        return None, PVInfo(filename="", pv_map={})

    shared_schema_paths = {
        device.schema_path for device in resolved_devices if device.uses_schema
    }
    all_use_schema = bool(resolved_devices) and all(
        device.uses_schema for device in resolved_devices
    )

    if all_use_schema and len(shared_schema_paths) == 1:
        schema_handles = resolved_devices[0].schema_handles or set()
        if schema_handles:
            representative = resolved_devices[0].pv_map
            common_map = {
                handle: representative[handle]
                for handle in sorted(schema_handles)
                if handle in representative
            }
            unique_map = {}
            common_handle_set = set(common_map.keys())
            for device in resolved_devices:
                for handle, config in device.pv_map.items():
                    if handle not in common_handle_set:
                        unique_map[handle] = config
            return PVInfo(filename="", pv_map=common_map), PVInfo(
                filename="", pv_map=unique_map
            )

    all_handles = [set(entry.handles) for entry in pv_maps]
    if all_handles and set.intersection(*all_handles):
        common_keys = set.intersection(*all_handles)
    else:
        flat_handles = []
        for handle_set in all_handles:
            flat_handles.extend(handle_set)
        counts = Counter(flat_handles)
        if not counts:
            return None, PVInfo(filename="", pv_map={})
        max_count = max(counts.values())
        if max_count <= 1:
            return None, PVInfo(filename="", pv_map={})
        common_keys = {key for key, value in counts.items() if value == max_count}

    common_map = {}
    for pv_info in pv_maps:
        for handle in pv_info.handles:
            if handle in common_keys:
                common_map[handle] = pv_info.pv_map[handle]

    unique_map = {}
    for pv_info in pv_maps:
        for handle in pv_info.handles:
            if handle not in common_keys:
                unique_map[handle] = pv_info.pv_map[handle]

    return PVInfo(filename="", pv_map=common_map), PVInfo(filename="", pv_map=unique_map)


def get_common_pvs(device_path) -> PVInfo:
    common_pv_info, _ = _analyze_pvs(device_path)
    return common_pv_info


def get_unique_pvs(device_path) -> PVInfo:
    _, unique_pv_info = _analyze_pvs(device_path)
    return unique_pv_info


def santizie_class_name(name: str) -> str:
    if name[0].isdigit():
        name = "_" + name
    return name.replace("-", "_").replace(":", "_")


def render_ca_base(device_type: str, pv_info: PVInfo, unique_pv_info: PVInfo) -> None:
    # Render base class
    base_class_name = f"{device_type}BaseIOC"
    if pv_info.channel_access_pvs:
        base_script = ca_base_template.render(
            device_type=device_type,
            class_name=base_class_name,
            pv_map=pv_info.channel_access_pvs,
            unique_pv_map=unique_pv_info.channel_access_pvs,
            dtype_map=CA_DTYPE_MAP,
        )
        base_output_path = os.path.join(
            SETTINGS.output_directory, device_type, f"{base_class_name}.py"
        )
        os.makedirs(os.path.join(SETTINGS.output_directory, device_type), exist_ok=True)
        with open(base_output_path, "w") as f:
            print(f"Writing {base_output_path}..")
            f.write(base_script)
        open(
            os.path.join(SETTINGS.output_directory, device_type, "__init__.py"), "a"
        ).close()
    else:
        print(f"Found no channel access PVs for {device_type}")


def render_pva_base(
    device_type: str, common_pv_info: PVInfo, unique_pv_info: PVInfo
) -> None:
    # Render base class
    if common_pv_info.pv_access_pvs:
        base_class_name = f"{device_type}BasePVAIOC"
        base_script = pva_base_template.render(
            device_type=device_type,
            class_name=base_class_name,
            pv_map=common_pv_info.pv_access_pvs,
            unique_pv_map=unique_pv_info.pv_access_pvs,
            dtype_map=PVA_DTYPE_MAP,
        )
        base_output_path = os.path.join(
            SETTINGS.output_directory, device_type, f"{base_class_name}.py"
        )
        os.makedirs(os.path.join(SETTINGS.output_directory, device_type), exist_ok=True)
        with open(base_output_path, "w") as f:
            f.write(base_script)
        open(
            os.path.join(SETTINGS.output_directory, device_type, "__init__.py"), "a"
        ).close()
    else:
        print(f"Could not find PV Access PVs for {device_type}")


# Main execution
if __name__ == "__main__":
    # Parse command-line arguments
    args = parse_arguments()

    # Load settings from the specified file
    SETTINGS = _load_settings(args.settings)
    # Ensure output directory exists
    os.makedirs(SETTINGS.output_directory, exist_ok=True)

    with open(SETTINGS.ca_base_template_file, encoding="utf-8") as f:
        ca_base_template = Template(f.read())
    with open(SETTINGS.pva_base_template_file, encoding="utf-8") as f:
        pva_base_template = Template(f.read())

    TRANSLATOR = SchemaTranslator(SETTINGS.schema_file)

    ALLOWED_DEVICES = SETTINGS.allowed_devices
    if ALLOWED_DEVICES is None:
        print("No layout selected; rendering every device.")
    else:
        print(
            f"Layout {SETTINGS.layout}: rendering {len(ALLOWED_DEVICES)} devices."
        )
    write_allowed_devices(SETTINGS.output_directory, ALLOWED_DEVICES)

    # Iterate over device_type folders
    for device_type, device_path in _find_device_folders(SETTINGS.devices_directory):
        if (
            not os.path.isdir(device_path)
            or device_type in SETTINGS.ignore_device_types
        ):
            continue
        # Find common and unique PVs in one pass per device type.
        common_pvs, unique_pvs = _analyze_pvs(device_path)
        if common_pvs is None:
            continue
        # Render base class for with unique PVs as optional
        render_ca_base(device_type, common_pvs, unique_pv_info=unique_pvs)
        render_pva_base(device_type, common_pvs, unique_pv_info=unique_pvs)
    formatter.run_black(SETTINGS.output_directory)
    print("IOC scripts generated and formatted with Black.")
