import argparse
import os
from typing import List
import format as formatter
import yaml
from jinja2 import Environment
import numpy as np
from core.pv_info import PVInfo
from core.translator import SchemaTranslator
from core.settings import Settings
from core.discovery import find_device_files, iter_devices, load_variables
from core.tango_naming import tango_devices
from collections import Counter

WAVEFORM_MAX_LENGTH = 65536
"""Most points a waveform can be written with, which it has to be told."""

DEFAULT_DTYPE = "scalar"
"""What a variable is served as when its definition does not say."""

# Define dtype_map. Every protocol has an entry for every data type, so that a
# variable is the same kind of thing whichever it is served over. Only numbers
# have "units" in Channel Access, which refuses them of anything else.
CA_DTYPE_MAP = {
    "statistical": {"dtype": "ChannelType.FLOAT", "initial": 0.0, "units": True},
    "float": {"dtype": "ChannelType.FLOAT", "initial": 0.0, "units": True},
    "scalar": {"dtype": "ChannelType.FLOAT", "initial": 0.0, "units": True},
    "int": {"dtype": "ChannelType.LONG", "initial": 0, "units": True},
    "state": {"dtype": "ChannelType.ENUM", "initial": 0},
    "binary": {"dtype": "bool", "initial": False},
    "waveform": {
        "dtype": "ChannelType.FLOAT",
        "initial": np.zeros(1, dtype=np.float32),
        "max_length": WAVEFORM_MAX_LENGTH,
        "units": True,
    },
    "string": {
        "dtype": "ChannelType.STRING",
        "initial": "'undefined'",
    },
}

# "code" is the type of the value, as p4p spells it.
PVA_DTYPE_MAP = {
    "statistical": {"dtype": "NTScalar", "code": "d", "initial": 0.0},
    "float": {"dtype": "NTScalar", "code": "d", "initial": 0.0},
    "scalar": {"dtype": "NTScalar", "code": "d", "initial": 0.0},
    "int": {"dtype": "NTScalar", "code": "l", "initial": 0},
    "state": {"dtype": "NTEnum", "initial": 0},
    "binary": {"dtype": "NTScalar", "code": "?", "initial": False},
    "waveform": {
        "dtype": "NTScalar",
        "code": "ad",
        "initial": np.zeros(1, dtype=np.float32),
    },
    "string": {
        "dtype": "NTScalar",
        "code": "s",
        "initial": "'undefined'",
    },
}

# TANGO attributes are typed by Python type, given here as it is to be written
# into the generated class.
TANGO_DTYPE_MAP = {
    "statistical": {"dtype": "float", "initial": 0.0},
    "float": {"dtype": "float", "initial": 0.0},
    "scalar": {"dtype": "float", "initial": 0.0},
    "int": {"dtype": "int", "initial": 0},
    "state": {"dtype": '"DevEnum"', "initial": 0},
    "binary": {"dtype": "bool", "initial": False},
    "waveform": {
        "dtype": "(float,)",
        "initial": "[0.0]",
        "max_length": WAVEFORM_MAX_LENGTH,
    },
    "string": {"dtype": "str", "initial": "'undefined'"},
}

DTYPES = set(CA_DTYPE_MAP) & set(PVA_DTYPE_MAP) & set(TANGO_DTYPE_MAP)
"""The data types every protocol can serve, which are the ones rendered."""

SARABI_ROOT = os.path.dirname(os.path.abspath(__file__))

SETTINGS: Settings = None
TRANSLATOR: SchemaTranslator = None


def _python_string(value) -> str:
    """`value` as the Python string literal to write into a generated module.

    Text from the device definitions is free to hold quotes, backslashes and
    line breaks. Anything outside ASCII is escaped, so that the module reads
    back the same whatever encoding the platform writes files in.
    """
    return ascii(str(value))


def _load_template(template_file: str):
    environment = Environment()
    environment.filters["pystr"] = _python_string
    with open(template_file) as f:
        return environment.from_string(f.read())


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


def get_pv_maps(yaml_files: List[str]) -> list[PVInfo]:
    pv_maps = []
    for yaml_file_path in yaml_files:
        _, pv_data = load_variables(yaml_file_path, TRANSLATOR)
        if pv_data:
            pv_maps.append(PVInfo(filename=yaml_file_path, pv_map=pv_data))
    return pv_maps


def _common_handles(pv_maps: list[PVInfo]) -> set:
    """The handles to treat as common to the devices of a type.

    Those present in every device or, where there are none, those present in
    the most devices, provided that is more than one. Devices with nothing in
    common have no common handles, which is not an error: all of their PVs are
    then ones that "may not exist for all IOCs of this type".
    """
    all_handles = [set(entry.handles) for entry in pv_maps]
    common_keys = set.intersection(*all_handles)
    if common_keys:
        return common_keys
    counts = Counter(handle for handles in all_handles for handle in handles)
    max_count = max(counts.values())
    # Only consider items seen more than once as "common"
    if max_count > 1:
        return {k for k, v in counts.items() if v == max_count}
    return set()


def _definitions(pv_maps: list[PVInfo], handles: set) -> dict:
    """What the devices' definitions say of each of `handles`.

    The class is shared by every device of the type, so describes a PV with
    everything any of their definitions say of it, the first to say something
    taking precedence, as for TANGO attributes.
    """
    definitions = {}
    for entry in pv_maps:
        for handle, config in entry.pv_map.items():
            if handle not in handles:
                continue
            if not isinstance(config, dict):
                definitions.setdefault(handle, config)
                continue
            definition = definitions.setdefault(handle, {})
            if isinstance(definition, dict):
                for key, value in config.items():
                    definition.setdefault(key, value)
    return definitions


def get_common_pvs(yaml_files: List[str]) -> PVInfo:
    """The PVs common to the devices of a type, or None if it defines no PVs."""
    pv_maps = get_pv_maps(yaml_files)
    if not pv_maps:
        return None
    return PVInfo(filename="", pv_map=_definitions(pv_maps, _common_handles(pv_maps)))


def get_unique_pvs(yaml_files: List[str]) -> PVInfo:
    """The PVs that only some devices of a type have."""
    pv_maps = get_pv_maps(yaml_files)
    if not pv_maps:
        return PVInfo(filename="", pv_map={})
    common_keys = _common_handles(pv_maps)
    unique_keys = {h for entry in pv_maps for h in entry.handles} - common_keys
    return PVInfo(filename="", pv_map=_definitions(pv_maps, unique_keys))


def get_kinds(device_type: str, pv_map: dict) -> dict:
    """The data type each variable of `pv_map` is to be rendered as.

    Read from the key the schema names, so that definitions in any schema are
    typed, and resolved here rather than in each template, so that a variable
    is the same data type over every protocol.
    """
    kinds = {}
    for name, config in pv_map.items():
        dtype = config.get(TRANSLATOR.dtype_word)
        kind = str(dtype).strip().lower() if dtype is not None else DEFAULT_DTYPE
        if kind not in DTYPES:
            print(
                f"Unknown {TRANSLATOR.dtype_word} '{dtype}' for {device_type} "
                f"variable {name}, rendering it as a {DEFAULT_DTYPE}."
            )
            kind = DEFAULT_DTYPE
        if kind == "state" and not config.get("states"):
            # An enumeration has to be told its states
            print(
                f"No states are defined for {device_type} variable {name}, "
                "rendering it as an int."
            )
            kind = "int"
        kinds[name] = kind
    return kinds


def santizie_class_name(name: str) -> str:
    if name[0].isdigit():
        name = "_" + name
    return name.replace("-", "_").replace(":", "_")


def render_ca_base(device_type: str, pv_info: PVInfo, unique_pv_info: PVInfo) -> None:
    # Render base class
    base_class_name = f"{device_type}BaseIOC"
    if pv_info.channel_access_pvs or unique_pv_info.channel_access_pvs:
        base_script = ca_base_template.render(
            device_type=device_type,
            class_name=base_class_name,
            pv_map=pv_info.channel_access_pvs,
            unique_pv_map=unique_pv_info.channel_access_pvs,
            dtype_map=CA_DTYPE_MAP,
            kinds=get_kinds(
                device_type,
                {
                    **pv_info.channel_access_pvs,
                    **unique_pv_info.channel_access_pvs,
                },
            ),
            sarabi_root=SARABI_ROOT,
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
    if common_pv_info.pv_access_pvs or unique_pv_info.pv_access_pvs:
        base_class_name = f"{device_type}BasePVAIOC"
        base_script = pva_base_template.render(
            device_type=device_type,
            class_name=base_class_name,
            pv_map=common_pv_info.pv_access_pvs,
            unique_pv_map=unique_pv_info.pv_access_pvs,
            dtype_map=PVA_DTYPE_MAP,
            kinds=get_kinds(
                device_type,
                {**common_pv_info.pv_access_pvs, **unique_pv_info.pv_access_pvs},
            ),
            sarabi_root=SARABI_ROOT,
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


def get_tango_attributes(device_type: str, yaml_files: List[str]) -> tuple[dict, dict]:
    """The attributes of a device type's TANGO devices, and their definitions.

    Returns those every device of the type has, which its class declares, and
    those only some have, which are added to the devices that do.
    """
    definitions = {}
    attributes_of_each_device = []
    for device_name, variables in iter_devices(yaml_files, TRANSLATOR):
        for attributes in tango_devices(
            device_type, device_name, variables, TRANSLATOR
        ).values():
            attributes_of_each_device.append(set(attributes))
            for attribute, handle in attributes.items():
                # The class is shared by every device of the type, so describes
                # an attribute with everything any of their definitions say of
                # it, the first to say something taking precedence.
                definition = definitions.setdefault(attribute, {})
                for key, value in variables[handle].items():
                    definition.setdefault(key, value)
    if not attributes_of_each_device:
        return {}, {}
    common_keys = set.intersection(*attributes_of_each_device)
    common = {k: v for k, v in definitions.items() if k in common_keys}
    unique = {k: v for k, v in definitions.items() if k not in common_keys}
    return common, unique


def render_tango_base(device_type: str, yaml_files: List[str]) -> None:
    # Render base class
    common_pvs, unique_pvs = get_tango_attributes(device_type, yaml_files)
    if common_pvs or unique_pvs:
        base_class_name = f"{santizie_class_name(device_type)}BaseTangoDevice"
        base_script = tango_base_template.render(
            device_type=device_type,
            class_name=base_class_name,
            pv_map=common_pvs,
            unique_pv_map=unique_pvs,
            dtype_map=TANGO_DTYPE_MAP,
            kinds=get_kinds(device_type, {**common_pvs, **unique_pvs}),
            description_word=TRANSLATOR.description_word,
            sarabi_root=SARABI_ROOT,
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
        print(f"Found no TANGO variables for {device_type}")


# Main execution
if __name__ == "__main__":
    # Parse command-line arguments
    args = parse_arguments()

    # Load settings from the specified file
    SETTINGS = _load_settings(args.settings)
    # Ensure output directory exists
    os.makedirs(SETTINGS.output_directory, exist_ok=True)

    ca_base_template = _load_template(SETTINGS.ca_base_template_file)
    pva_base_template = _load_template(SETTINGS.pva_base_template_file)
    tango_base_template = _load_template(SETTINGS.tango_base_template_file)

    TRANSLATOR = SchemaTranslator(SETTINGS.schema_file)
    # Iterate over device types. A file belongs to the type of the folder it is
    # in, which is how the running servers find their devices again.
    for device_type, yaml_files in find_device_files(
        SETTINGS.devices_directory, SETTINGS.ignore_device_types
    ).items():
        # Find common and unique PVs
        common_pvs = get_common_pvs(yaml_files)
        if common_pvs is None:
            continue
        unique_pvs = get_unique_pvs(yaml_files)
        # Render base class for with unique PVs as optional
        render_ca_base(device_type, common_pvs, unique_pv_info=unique_pvs)
        render_pva_base(device_type, common_pvs, unique_pv_info=unique_pvs)
        render_tango_base(device_type, yaml_files)
    formatter.run_black(SETTINGS.output_directory)
    print("IOC scripts generated and formatted with Black.")
