# SARABI - Soft Architecture for Rendering Automated Backend IOCs

SARABI is a Python package designed to create virtual soft Input/Output Controllers (IOCs) from YAML configuration files. It provides a flexible architecture for rendering automated backend IOCs, making it easier to manage and simulate EPICS (Experimental Physics and Industrial Control System) records.

## Features

- **Dynamic IOC Creation**: Automatically generates IOCs based on YAML configuration files.
- **Schema Translation**: Utilizes a schema translator to map YAML data to EPICS records.
- **Customizable**: Easily extendable to support various device types and configurations.
- **Environment Configuration**: Configures EPICS environment variables for seamless integration.

## Installation

To install SARABI, clone the repository and install the required dependencies:

```bash
git clone https://gitlab.stfc.ac.uk/ujo48515/sarabi.git
cd sarabi
pip install -r requirements.txt
```

## Configuration

Change the `settings.yaml` to point to the relevant directories:

- `output_directory`: Where you want your generated IOC source files to live.
- `templates_directory`: The location of thesource code jinja template files to use. Default should be fine for this.
- `schema_file`: The json file denoted the key translations for your device files.
- `devices_directory`: The location of your device yaml files.
- `ignore_device_types`: A list of the device folders to be ignored in generation.

## Rendering

Once you're settings are configured for your project, run the following command to render the ioc source files:

- `python render_iocs.py --settings=./settings.yaml`

This next command will generate the `main.py` per device type, and allow you start all of the iocs for that device type:

- `python render_main.py --settings=./settings.yaml`

## Usage

To run your iocs:
- go to `<output_directory>\<device_type>`
- run `python main.py`

This will run the all of the iocs for that device type on `localhost` with a default `EPICS_CA_SERVER_PORT` of `6090` as not to interfere with the default epics port of `5064`

Each PV defined in your device yaml files will have been prepended with `VM-` to avoid conflicts with the physical control system.

To use any EPICS cli tools you must set the following environment variables first:
- `EPICS_CA_SERVER_PORT=6090`
- `EPICS_CA_ADDR_LIST=localhost`