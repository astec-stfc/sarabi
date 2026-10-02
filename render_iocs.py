import argparse
import os
from typing import List
import format as formatter
import yaml
from jinja2 import Environment, Template
import numpy as np
from core.pv_info import PVInfo
from core.translator import SchemaTranslator
from core.settings import Settings
from core import tango_helper
from collections import Counter

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

# TANGO attribute types, as pytango dtype expressions. Keyed by the same type
# words as the EPICS maps; a scalar with no recognised type is a float.
TANGO_DTYPE_MAP = {
    "statistical": {"dtype": "float", "initial": 0.0},
    "scalar": {"dtype": "float", "initial": 0.0},
    "float": {"dtype": "float", "initial": 0.0},
    "int": {"dtype": "int", "initial": 0},
    "state": {"dtype": "DevEnum", "initial": 0},
    "binary": {"dtype": "bool", "initial": False},
    "waveform": {
        "dtype": "(float,)",
        "initial": "np.zeros(1, dtype=np.float64)",
        "max_dim_x": 65536,
    },
    "string": {"dtype": "str", "initial": "'undefined'"},
}


SETTINGS: Settings = None
TRANSLATOR: SchemaTranslator = None


def _find_yaml_files(device_path: str) -> List[str]:
    """Return a list of full paths to .yaml files under device_path (recursive)."""
    yaml_files = []
    for root, _, files in os.walk(device_path):
        for fn in files:
            if fn.endswith(".yaml") or fn.endswith(".yml"):
                yaml_files.append(os.path.join(root, fn))
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
    with open(settings_yaml, "r") as f:
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
    for yaml_file_path in _find_yaml_files(device_path):
        with open(yaml_file_path) as yaml_content:
            data = yaml.safe_load(yaml_content)
        pv_data = data.get(
            TRANSLATOR.controls_information_word,
            {},
        ).get(
            TRANSLATOR.signal_information_word,
            {},
        )
        if pv_data:
            rel_filename = os.path.relpath(yaml_file_path, device_path)
            pv_map = PVInfo(filename=rel_filename, pv_map=pv_data)
            pv_maps.append(pv_map)
    return pv_maps


def get_common_pvs(device_path) -> PVInfo:
    pv_maps = get_pv_maps(device_path)
    if not pv_maps:
        return None
    # Find common keys (present in all dictionaries)
    all_handles = []
    for entry in pv_maps:
        all_handles.append(set(entry.handles))
    if all_handles:
        if set.intersection(*all_handles):
            common_keys = set.intersection(*all_handles)
        else:
            # If no strict intersection, pick the most common handles across files.
            flat_handles = []
            for s in all_handles:
                flat_handles.extend(s)
            counts = Counter(flat_handles)
            if counts:
                max_count = max(counts.values())
                # Only consider items seen more than once as "common"
                if max_count > 1:
                    common_keys = {k for k, v in counts.items() if v == max_count}
                else:
                    return None
            else:
                return None
    else:
        return None
    if len(common_keys) == 0:
        raise ValueError("Could not find any common keys.")
    # Identify common PVs
    common_pvs = {}
    for map in pv_maps:
        for key in list(map.handles):
            if key in common_keys:
                common_pvs[key] = map.pv_map[key]
    common_pv_info = PVInfo(filename="", pv_map=common_pvs)
    return common_pv_info


def get_unique_pvs(device_path) -> PVInfo:
    pv_maps = get_pv_maps(device_path)
    if not pv_maps:
        return {}

    # Find common keys (present in all dictionaries)
    common_keys = get_common_pvs(device_path=device_path)
    if common_keys is None:
        common_keys = set()
    unique_keys = set()
    for entry in pv_maps:
        for handle in entry.handles:
            if not handle in common_keys.handles:
                unique_keys.add(handle)
    if len(unique_keys) == 0:
        return PVInfo(filename="", pv_map={})
    # Identify unique PVs
    unique_pvs = {}
    unique_pv_info = []
    for map in pv_maps:
        for key in list(map.handles):
            if key in unique_keys:
                unique_pvs[key] = map.pv_map[key]
    unique_pv_info = PVInfo(filename="", pv_map=unique_pvs)
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


def render_tango_base(
    device_type: str,
    common_pv_info: PVInfo,
    unique_pv_info: PVInfo,
    attribute_names: dict,
) -> None:
    """Render the TANGO device class for a device type, if it has TANGO variables."""
    common = common_pv_info.tango_pvs
    unique = unique_pv_info.tango_pvs if isinstance(unique_pv_info, PVInfo) else {}
    if not (common or unique):
        print(f"Found no TANGO variables for {device_type}")
        return
    class_name = f"{device_type}BaseTangoDevice"
    script = tango_base_template.render(
        device_type=device_type,
        class_name=class_name,
        pv_map=common,
        unique_pv_map=unique,
        dtype_map=TANGO_DTYPE_MAP,
        attribute_names=attribute_names,
    )
    output_path = os.path.join(SETTINGS.output_directory, device_type, f"{class_name}.py")
    os.makedirs(os.path.join(SETTINGS.output_directory, device_type), exist_ok=True)
    with open(output_path, "w") as f:
        print(f"Writing {output_path}..")
        f.write(script)
    open(os.path.join(SETTINGS.output_directory, device_type, "__init__.py"), "a").close()


def _load_template(path: str) -> Template:
    """Load a template with the `pyrepr` filter, which quotes a value as Python.

    Block tags do not leave blank lines or indentation behind, so the rendered
    module is tidy without relying on Black.
    """
    environment = Environment(trim_blocks=True, lstrip_blocks=True)
    environment.filters["pyrepr"] = repr
    with open(path) as f:
        return environment.from_string(f.read())


# Main execution
if __name__ == "__main__":
    # Parse command-line arguments
    args = parse_arguments()

    # Load settings from the specified file
    SETTINGS = _load_settings(args.settings)
    # Ensure output directory exists
    os.makedirs(SETTINGS.output_directory, exist_ok=True)

    with open(SETTINGS.ca_base_template_file) as f:
        ca_base_template = Template(f.read())
    with open(SETTINGS.pva_base_template_file) as f:
        pva_base_template = Template(f.read())
    tango_base_template = _load_template(SETTINGS.tango_base_template_file)

    TRANSLATOR = SchemaTranslator(SETTINGS.schema_file)
    # Iterate over device_type folders
    for device_type, device_path in _find_device_folders(SETTINGS.devices_directory):
        if (
            not os.path.isdir(device_path)
            or device_type in SETTINGS.ignore_device_types
        ):
            continue
        # Find common and unique PVs
        common_pvs = get_common_pvs(device_path)
        unique_pvs = get_unique_pvs(device_path)
        if common_pvs is None:
            continue
        # Render base class for with unique PVs as optional
        render_ca_base(device_type, common_pvs, unique_pv_info=unique_pvs)
        render_pva_base(device_type, common_pvs, unique_pv_info=unique_pvs)
        # TANGO attribute names are per class, so they are settled here across
        # every device of the type rather than per device at run time.
        attribute_names = tango_helper.common_attribute_names(
            [pv_info.pv_map for pv_info in get_pv_maps(device_path)], TRANSLATOR
        )
        render_tango_base(
            device_type, common_pvs, unique_pv_info=unique_pvs, attribute_names=attribute_names
        )
    formatter.run_black(SETTINGS.output_directory)
    print("IOC scripts generated and formatted with Black.")
