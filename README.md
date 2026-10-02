# SARABI - Soft Architecture for Rendering Automated Backend IOCs

SARABI is a Python package designed to create virtual soft Input/Output Controllers (IOCs) and TANGO device servers from YAML configuration files. It provides a flexible architecture for rendering automated backend control system servers, making it easier to manage and simulate EPICS (Experimental Physics and Industrial Control System) records and TANGO devices.

## Features

- **Dynamic IOC Creation**: Automatically generates IOCs based on YAML configuration files.
- **Three protocols**: Each variable is served over EPICS Channel Access (caproto), EPICS PV Access (p4p) or TANGO (pytango), chosen per variable by its `protocol` key.
- **Schema Translation**: Utilizes a schema translator to map YAML data to EPICS records and TANGO attributes.
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

Alternatively, `start_servers.py` does both renders and then starts the servers (see [Starting the servers](#starting-the-servers)):

- `python start_servers.py --settings=./settings.yaml`

## Usage

To run your iocs:
- go to `<output_directory>\<device_type>`
- run `python main.py`

This will run the all of the iocs for that device type on `localhost` with a default `EPICS_CA_SERVER_PORT` of `6090` as not to interfere with the default epics port of `5064`

Each PV defined in your device yaml files will have been prepended with `VM-` to avoid conflicts with the physical control system.

To use any EPICS cli tools you must set the following environment variables first:
- `EPICS_CA_SERVER_PORT=6090`
- `EPICS_CA_ADDR_LIST=localhost`

## Protocols

Every variable in a device YAML file names the protocol it is served over:

```yaml
controls:
  variables:
    READK:
      identifier: JFEL-L01-MAG-SOL-01:CalcK
      dtype: float
      protocol: TANGO      # CA (default), PVA or TANGO
```

`CA` is assumed when the key is missing. Spellings such as `Tango`, `EPICS` (Channel Access) and
`EPICS_PVA` are accepted; see `core/protocols.py`. Variables of a device may mix protocols, and
each device type gets one generated module per protocol it uses:

| Protocol | Library | Generated module              | Template                 |
|----------|---------|-------------------------------|--------------------------|
| `CA`     | caproto | `<type>BaseIOC.py`            | `ioc_base_template.j2`   |
| `PVA`    | p4p     | `<type>BasePVAIOC.py`         | `pva_base_template.j2`   |
| `TANGO`  | pytango | `<type>BaseTangoDevice.py`    | `tango_base_template.j2` |

### Switching a directory of definitions to another protocol

`set_protocol.py` walks a directory of device YAML files and rewrites the
`controls -> variables -> <name> -> protocol` key of every variable, which is the quickest way to
test an existing set of EPICS definitions over TANGO:

```bash
python set_protocol.py --devices ./yaml/JFEL --protocol TANGO --dry-run   # report only
python set_protocol.py --devices ./yaml/JFEL --protocol TANGO             # rewrite in place
python set_protocol.py --devices ./yaml/JFEL/Magnet --protocol PVA --only CA --handles READK,SETI
```

The key names are read from the schema (`--schema`, default `schemas/laura.json`). Files are
rewritten with their key order preserved, but YAML comments are not kept, so work on a copy if the
originals matter. Re-run `render_iocs.py` and `render_main.py` (or `start_servers.py`) afterwards.

## TANGO

TANGO variables are served by one database-less TANGO device server per process, built with
[pytango](https://pytango.readthedocs.io/). No TANGO database (`TANGO_HOST`) is needed: the server
is started from a file database written at startup, and the devices are addressed directly.

### Naming

TANGO addresses are `domain/family/member/attribute`, so the `VM-` prefix that EPICS PVs get becomes:

- device `VM/<device type>/<device name>`, e.g. `VM/Solenoid/JFEL-L01-MAG-SOL-01`. A definition whose
  identifiers are already TANGO addresses (`a/b/c/attr`) keeps them, with the domain prefixed: `VM-a/b/c`.
- attribute: the last field of the identifier, `CalcK` for `JFEL-L01-MAG-SOL-01:CalcK`, or the
  handle (`READK`) if the identifier has no such field. TANGO attribute names belong to the device
  class, so if the devices of a type disagree on the name for a handle it is declared under the
  handle, and a warning is printed at render time. Every TANGO device already has `State` and
  `Status` attributes, so a variable with either name (in any case) is served as `STATE_`/`Status_`.

Each device exposes only the handles its own YAML file names; handles that not every device of the
type defines are declared `optional` in the generated module. `dtype` maps as `float`/`scalar`/
`statistical` → double, `int` → long, `binary` → boolean, `string` → string, `waveform` → double
spectrum, `state` → `DevEnum` with the `states` as labels; `read_only: true` makes an attribute
read-only.

### Connecting

The runner prints every device address once the server is up. From Python:

```python
import tango
proxy = tango.DeviceProxy("tango://127.0.0.1:10090/VM/Solenoid/JFEL-L01-MAG-SOL-01#dbase=no")
proxy.CalcK            # read
proxy.CalcK = 1.25     # write
proxy.subscribe_event("CalcK", tango.EventType.CHANGE_EVENT, print)  # simulated changes are pushed
```

or, with the `#dbase=no` fragment, any TANGO tool that takes a full device name. The host and port
default to `127.0.0.1:10090` (not TANGO's usual 10000, to keep clear of a real database) and are set
with `SARABI_TANGO_HOST` and `SARABI_TANGO_PORT`.

TANGO resolves the name of every local network interface when a server starts, which on a machine
with many interfaces (VPN, container bridges) can take half a minute or more. The runner says when
the server is ready; `start_servers.py --check` waits for it.

### Starting the servers

`start_servers.py` renders everything and starts the runners, with the ports set through the
environment variables above:

```bash
python start_servers.py --settings=./settings.yaml                     # render, then run run_all_iocs.py
python start_servers.py --settings=./settings.yaml --no-render         # skip rendering
python start_servers.py --settings=./settings.yaml --per-type          # one process per device type
python start_servers.py --settings=./settings.yaml --check             # read one attribute from every TANGO device once up
python start_servers.py --settings=./settings.yaml --tango-port=10100 --ca-port=6090 --timestep=0.05
```

Ctrl-C stops every server it started.

## Tests

```bash
pytest                                             # unit tests and a rendering round trip
SARABI_TEST_TANGO_SERVER=1 pytest tests/test_tango_server_live.py   # also start a real TANGO server
```

The live TANGO test is opt-in because a server takes a while to start and TANGO allows one per process.

## Simulated dynamics

PVs can do more than hold the value last written to them. Two behaviours are read from the device
YAML and driven by the generated IOCs.

A **setpoint/readback pair** makes a readback follow its setpoint over time, rather than instantly.
Link the two with `readback` (or `setpoint`, from the other end), naming either the PV handle or its
identifier, and give the `dynamics` that relate them:

```yaml
SETI:
  identifier: JFEL-S02-MAG-QUAD-03:SETI
  readback: READI
  dynamics:
    model: laura.utils.dynamics.FirstOrderResponse
    tau: 0.5
READI:
  identifier: JFEL-S02-MAG-QUAD-03:READI
```

An **update signal** generates a PV's value on every timestep:

```yaml
READK:
  identifier: JFEL-S02-MAG-QUAD-03:READK
  update:
    function: laura.utils.signals.Sinusoid
    period: 10.0
    amplitude: 0.5
```

`model` and `function` are fully qualified import paths, and the remaining keys are the arguments to
that class. SARABI imports whatever the path names and does not depend on the package it comes from:
the paths above need LAURA importable at run time, but a definition naming your own
`mypackage.signals.MyModel` needs nothing else installed.

A response model is called as `model(target, dt)` and is stateful, holding one instance per readback.
A signal may declare any of `t`, `value` and `dt` as arguments, and is passed the ones it asks for.

Both are advanced on a single timestep shared by every IOC, given when the IOCs are started:

```bash
python main.py --timestep=0.05      # default 0.1 s
```

Both behaviours work the same for every protocol. Over TANGO, each change is also pushed as a
change event, so a client may subscribe to a readback rather than poll it.
