import os
from pathlib import Path
from jinja2 import Template
import argparse
from core.discovery import find_device_files
from core.settings import Settings
import yaml
import format as formatter

SETTINGS = None

SARABI_ROOT = os.path.dirname(os.path.abspath(__file__))
TANGO_SUFFIX = "BaseTangoDevice"
# Scripts rendered here, rather than modules for them to import
RENDERED_MAINS = ("__init__.py", "main.py", "tango_main.py")


def _protocol_of_module(module_name: str) -> str:
    """The protocol served by a generated module, going by how it is named."""
    if module_name.endswith(TANGO_SUFFIX):
        return "TANGO"
    if "PVA" in module_name:
        return "PVA"
    return "CA"


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


def _find_device_yaml_folder(yaml_dir: str, device_type: str):
    """
    Return the absolute path of the first folder of `device_type` under
    yaml_dir, which is one named exactly that and holding .yaml or .yml files.

    Raises FileNotFoundError if yaml_dir doesn't exist or has no such folder.
    """
    start_dir = Path(yaml_dir)
    if not start_dir.exists() or not start_dir.is_dir():
        raise FileNotFoundError(f"Root device directory not found: {start_dir}")

    yaml_files = find_device_files(yaml_dir).get(device_type)
    if not yaml_files:
        raise FileNotFoundError(f"No YAML files found for {device_type} under {start_dir}")
    return os.path.abspath(os.path.dirname(yaml_files[0]))


if __name__ == "__main__":
    # Parse command-line arguments
    args = parse_arguments()

    # Load settings from the specified file
    SETTINGS = _load_settings(args.settings)
    # Load template
    with open(SETTINGS.ca_main_template_file) as f:
        template = Template(f.read())

    # Group files by device_type
    device_groups = {}
    for device_type in os.listdir(SETTINGS.output_directory):
        device_type_dir = os.path.join(SETTINGS.output_directory, device_type)
        if not os.path.isdir(device_type_dir):
            continue

        # Walk recursively to find .py modules under this device_type folder
        for root, _, files in os.walk(device_type_dir):
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                if filename in RENDERED_MAINS:
                    continue

                # module import path relative to the device_type package
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(
                    full_path, device_type_dir
                )  # e.g. "sub1/sub2/MyIOC.py"
                module_import = rel_path[:-3].replace(
                    os.path.sep, "."
                )  # e.g. "sub1.sub2.MyIOC"
                module_name = module_import.split(".")[-1]  # file stem, e.g. "MyIOC"

                device_groups.setdefault(device_type, []).append(
                    (module_import, module_name)
                )

    # Render main.py for each device_type
    all_device_types = set(device_groups.keys())
    for ignored in SETTINGS.ignore_device_types:
        if ignored in all_device_types:
            all_device_types.remove(ignored)
    print(f"Found device types: {all_device_types}")
    all_ioc_classes = []
    all_ioc_modules = []
    all_tango_modules = []
    with open(SETTINGS.tango_main_template_file) as f:
        tango_template = Template(f.read())
    for device_type, files in device_groups.items():
        ioc_modules = []
        ioc_classes = []
        tango_modules = []
        for module_import, module_name in files:
            # module_name is the class/module stem; module_import is the relative dotted path
            if _protocol_of_module(module_name) == "TANGO":
                # Served by a device server of its own, so that the IOCs do not
                # need TANGO installed, nor the device server EPICS.
                tango_modules.append((device_type, module_name))
                continue
            ioc_modules.append((device_type, module_name))
            ioc_classes.append(module_name)
        if tango_modules:
            rendered = tango_template.render(
                sarabi_root=SARABI_ROOT,
                yaml_dir=SETTINGS.devices_directory,
                translator_file=os.path.abspath(SETTINGS.schema_file),
                imports=[(d, name, name) for d, name in tango_modules],
            )
            with open(
                os.path.join(SETTINGS.output_directory, device_type, "tango_main.py"),
                "w",
            ) as f:
                f.write(rendered)
            all_tango_modules.extend(tango_modules)
        if not ioc_modules:
            continue
        try:
            yaml_dir = _find_device_yaml_folder(SETTINGS.devices_directory, device_type)
        except FileNotFoundError:
            # Rendered from definitions that have since been removed or renamed
            print(f"Found no definitions for {device_type}, not rendering its main.py.")
            continue
        rendered = template.render(
            device_type=device_type,
            sarabi_root=SARABI_ROOT,
            yaml_root=yaml_dir,
            devices_directory=SETTINGS.devices_directory,
            translator_file=os.path.abspath(SETTINGS.schema_file),
            imports=ioc_modules,
        )
        all_ioc_classes.extend(ioc_classes)
        all_ioc_modules.extend(ioc_modules)

        output_path = os.path.join(
            os.path.join(SETTINGS.output_directory, device_type), "main.py"
        )
        with open(output_path, "w") as f:
            f.write(rendered)
    print("main.py files generated for each device type.")
    device_ioc_class_map = {}
    for module in all_ioc_modules:
        device_type = module[0]
        class_name = module[1]
        protocol = _protocol_of_module(class_name)
        device_ioc_class_map.setdefault(device_type, {})[protocol] = class_name
    with open(SETTINGS.all_ioc_main_template_file) as f:
        run_all_template = Template(f.read())
    rendered_all = run_all_template.render(
        sarabi_root=SARABI_ROOT,
        device_ioc_class_map=device_ioc_class_map,
        yaml_dir=SETTINGS.devices_directory,
        translator_file=os.path.abspath(SETTINGS.schema_file),
        imports=all_ioc_modules,
    )
    with open(os.path.join(SETTINGS.output_directory, "run_all_iocs.py"), "w") as f:
        f.write(rendered_all)
    if all_tango_modules:
        rendered_all_tango = tango_template.render(
            sarabi_root=SARABI_ROOT,
            yaml_dir=SETTINGS.devices_directory,
            translator_file=os.path.abspath(SETTINGS.schema_file),
            imports=[(d, f"{d}.{name}", name) for d, name in all_tango_modules],
        )
        with open(
            os.path.join(SETTINGS.output_directory, "run_all_tango.py"), "w"
        ) as f:
            f.write(rendered_all_tango)
    formatter.run_black(SETTINGS.output_directory)
    print("run_all_iocs.py generated with all IOC classes.")
