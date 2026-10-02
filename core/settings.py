from typing import List
import os
import json
import warnings


class NoDeviceDirectories(Exception):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class NoDeviceFiles(Warning):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class Settings:
    output_directory: str
    templates_directory: str
    schema_file: str
    devices_directory: str
    ignore_device_types: List[str]

    def __init__(
        self,
        output_directory: str,
        templates_directory: str,
        schema_file: str,
        devices_directory: str,
        ignore_device_types: List[str],
    ):
        self.templates_directory = self._validate_templates(templates_directory)
        self.output_directory = output_directory
        self.schema_file = self._validate_schema(schema_file)
        self.devices_directory = self._validate_devices(devices_directory)
        self.ignore_device_types = ignore_device_types

    def _validate_templates(self, templates_directory) -> str:
        if not os.path.exists(templates_directory):
            raise FileNotFoundError(
                f"Could not find templates folder {templates_directory}"
            )
        templates = os.listdir(templates_directory)
        if "ioc_base_template.j2" not in templates:
            raise FileNotFoundError(f"Could not find ioc base template.")
        if "pva_base_template.j2" not in templates:
            raise FileNotFoundError(f"Could not find pva base template.")
        if "tango_base_template.j2" not in templates:
            raise FileNotFoundError(f"Could not find tango base template.")
        if "main_template.j2" not in templates:
            raise FileNotFoundError(f"Could not find main.py template.")
        if "all_ioc_main_template.j2" not in templates:
            raise FileNotFoundError(f"Could not find all_ioc_main.py template.")
        return os.path.abspath(templates_directory)

    @property
    def ca_base_template_file(self) -> str:
        return os.path.join(self.templates_directory, "ioc_base_template.j2")

    @property
    def pva_base_template_file(self) -> str:
        return os.path.join(self.templates_directory, "pva_base_template.j2")

    @property
    def tango_base_template_file(self) -> str:
        return os.path.join(self.templates_directory, "tango_base_template.j2")

    @property
    def ca_main_template_file(self) -> str:
        return os.path.join(self.templates_directory, "main_template.j2")

    @property
    def all_ioc_main_template_file(self) -> str:
        return os.path.join(self.templates_directory, "all_ioc_main_template.j2")

    def _validate_schema(self, schema_file) -> str:
        if not os.path.exists(schema_file):
            raise FileNotFoundError(f"Could not find schema file: {schema_file}")
        with open(file=schema_file, mode="r") as f:
            _schema = json.load(f)
            if "translations" not in _schema.keys():
                raise KeyError(f"Could not find translations in {schema_file}")
            for k in [
                "controls_information",
                "signal_information",
                "description",
                "identifier",
                "dtype",
                "protocol",
            ]:
                if k not in _schema["translations"].keys():
                    raise KeyError(
                        f"Could not find translation for keyword {k} in {schema_file}"
                    )
        return schema_file

    def _validate_devices(self, devices_directory: str) -> str:
        if not os.path.exists(devices_directory):
            raise FileNotFoundError(
                f"Could not find devices directory: {devices_directory}"
            )
        device_folders = [
            d
            for d in os.listdir(devices_directory)
            if os.path.isdir(os.path.join(devices_directory, d))
        ]
        if not device_folders:
            raise NoDeviceDirectories(
                f"No device directories found in {devices_directory}"
            )
        for folder in device_folders:
            path = os.path.join(devices_directory, folder)
            # Recursively search for any .yaml/.yml files under the device folder
            found_yaml = False
            for root, _, files in os.walk(path):
                for filename in files:
                    if filename.lower().endswith((".yaml", ".yml")):
                        found_yaml = True
                        break
                if found_yaml:
                    break
            if not found_yaml:
                warnings.warn(
                    f"Could not find yaml files in {path}, no ioc will be generated for {folder}",
                )
        return os.path.abspath(devices_directory)
