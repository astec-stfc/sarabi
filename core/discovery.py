"""Walking a directory of device definitions.

A devices directory holds one folder per device type, at any depth, each
holding the YAML definitions of the devices of that type::

    yaml/JFEL/
        Magnet/
            JFEL-S02-MAG-QUAD-03.yaml
        Diagnostics/
            BPM/
                JFEL-S02-DIA-BPM-01.yml

The rendering scripts and the running servers both find their definitions
here, so that the devices a server creates are those its classes were rendered
from.
"""

import os
from typing import Any, Dict, Iterable, Iterator, List, Tuple

import yaml

from .translator import SchemaTranslator

YAML_EXTENSIONS = (".yaml", ".yml")


def is_yaml_file(filename: str) -> bool:
    return filename.lower().endswith(YAML_EXTENSIONS)


def find_device_files(
    devices_directory: str, ignore_device_types: Iterable[str] = ()
) -> Dict[str, List[str]]:
    """Every YAML file under `devices_directory`, grouped by device type.

    A file's device type is the name of the folder it sits in, so each file
    belongs to exactly one type, and folders of the same name in different
    branches of the tree describe the same type. Files directly in
    `devices_directory` are in no device type folder and are skipped.
    """
    ignored = set(ignore_device_types)
    device_files: Dict[str, List[str]] = {}
    for root, dirs, files in os.walk(devices_directory):
        dirs.sort()
        if os.path.abspath(root) == os.path.abspath(devices_directory):
            continue
        device_type = os.path.basename(root)
        if device_type in ignored:
            continue
        yaml_files = sorted(os.path.join(root, f) for f in files if is_yaml_file(f))
        if yaml_files:
            device_files.setdefault(device_type, []).extend(yaml_files)
    return dict(sorted(device_files.items()))


def load_variables(
    yaml_file: str, translator: SchemaTranslator
) -> Tuple[str, Dict[str, Any]]:
    """The name of the device a YAML file defines, and its variables.

    The variables are empty for a file that defines none, such as one that is
    not a device definition at all.
    """
    with open(yaml_file) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return "", {}
    device_name = data.get("name") or os.path.splitext(os.path.basename(yaml_file))[0]
    controls = data.get(translator.controls_information_word) or {}
    variables = {}
    if isinstance(controls, dict):
        variables = controls.get(translator.signal_information_word) or {}
    if not isinstance(variables, dict):
        variables = {}
    return str(device_name), variables


def iter_devices(
    yaml_files: Iterable[str], translator: SchemaTranslator
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """The name and variables of each device defined in `yaml_files`."""
    for yaml_file in yaml_files:
        device_name, variables = load_variables(yaml_file, translator)
        if variables:
            yield device_name, variables
