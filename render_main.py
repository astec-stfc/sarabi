import os
from pathlib import Path
from jinja2 import Template
import argparse
from core.settings import Settings
import yaml
import format as formatter

SETTINGS = None


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
    Search recursively under yaml_dir/device_type and return the absolute path
    of the first directory that contains at least one .yaml or .yml file.

    Raises FileNotFoundError if the device_type folder doesn't exist or no YAML
    files are found beneath it.
    """
    start_dir = Path(yaml_dir)
    if not start_dir.exists() or not start_dir.is_dir():
        raise FileNotFoundError(f"Root device directory not found: {start_dir}")

    for root, _, files in os.walk(start_dir):
        if device_type in root:
            if any(f.lower().endswith((".yaml", ".yml")) for f in files):
                return os.path.abspath(root)

    raise FileNotFoundError(f"No YAML files found under {start_dir}")


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
                if filename in ("__init__.py", "main.py"):
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
    for device_type, files in device_groups.items():
        ioc_modules = []
        ioc_classes = []
        for module_import, module_name in files:
            # module_name is the class/module stem; module_import is the relative dotted path
            ioc_modules.append((device_type, module_name))
            ioc_classes.append(module_name)
        yaml_dir = _find_device_yaml_folder(SETTINGS.devices_directory, device_type)
        rendered = template.render(
            device_type=device_type,
            yaml_root=yaml_dir,
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
        if "PVA" in class_name:
            device_ioc_class_map.setdefault(device_type, {})["PVA"] = class_name
        else:
            device_ioc_class_map.setdefault(device_type, {})["CA"] = class_name
    with open(SETTINGS.all_ioc_main_template_file) as f:
        run_all_template = Template(f.read())
    rendered_all = run_all_template.render(
        device_ioc_class_map=device_ioc_class_map,
        yaml_dir=SETTINGS.devices_directory,
        translator_file=os.path.abspath(SETTINGS.schema_file),
        imports=all_ioc_modules,
    )
    with open(os.path.join(SETTINGS.output_directory, "run_all_iocs.py"), "w") as f:
        f.write(rendered_all)
    formatter.run_black(SETTINGS.output_directory)
    print("run_all_iocs.py generated with all IOC classes.")
