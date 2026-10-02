# SARABI - Soft Architecture for Rendering Automated Backend IOCs

SARABI is a Python package designed to create virtual soft Input/Output Controllers (IOCs) from YAML configuration files. It provides a flexible architecture for rendering automated backend IOCs, making it easier to manage and simulate EPICS (Experimental Physics and Industrial Control System) records. The same configuration files can be served as TANGO device servers, so a machine can be simulated over either control system, or a mixture of the two.

## Features

- **Dynamic IOC Creation**: Automatically generates IOCs based on YAML configuration files.
- **EPICS and TANGO**: Serves each variable over Channel Access, PV Access or TANGO, as its definition asks.
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

Both commands walk the whole of `devices_directory`, as the servers do again when they start. Each folder
holding YAML files is a device type, named after the folder, at any depth; every `.yaml` and `.yml` file
in it defines one device of that type, and belongs to that type alone. Folders of the same name in
different places, such as `S01/Magnet` and `S02/Magnet`, are one device type. Folders holding no YAML
files are passed over, so `output_directory` is free to be inside `devices_directory`.

The devices of a type need not define the same variables. Those they all have are declared outright by
the type's IOC, and the rest as ones that "may not exist for all IOCs of this type"; each device serves
the ones its own file defines.

## Data types

A variable's data type is read from the key the schema translates `dtype` to, which is `dtype` for the
LAURA schema and `type` for the CATAP one, and is the same kind of thing over every protocol:

| Data type | Channel Access | PV Access | TANGO |
| --- | --- | --- | --- |
| `scalar`, `statistical`, `float` | `FLOAT` | `NTScalar` double | `DevDouble` |
| `int` | `LONG` | `NTScalar` 64-bit integer | `DevLong64` |
| `state` | `ENUM` | `NTEnum` | `DevEnum` |
| `binary` | `ENUM` of `Off` and `On`, Channel Access having no boolean | `NTScalar` boolean | `DevBoolean` |
| `waveform` | `FLOAT` array | `NTScalar` double array | `DevDouble` spectrum |
| `string` | `STRING` | `NTScalar` string | `DevString` |

A `state` takes its names from the variable's `states`, in order of their values:

```yaml
MODE:
  identifier: JFEL-S02-DIA-SCR-01:MODE
  dtype: state
  states: {OUT: 0, IN: 1, MOVING: 2}
```

A variable with no data type, or one not in the table, is served as a `scalar`, and a `state` with no
`states` as an `int`; rendering says so when it happens. Waveforms hold up to 65536 points.

These are set by `CA_DTYPE_MAP`, `PVA_DTYPE_MAP` and `TANGO_DTYPE_MAP` in `render_iocs.py`, which is the
place to add a data type: give it an entry in all three.

## Usage

To start everything that was rendered, for both control systems, until you press Ctrl-C:

```bash
python start_servers.py --settings=./settings.yaml
```

Add `--render` to run the two rendering commands first, and `--only=EPICS` or `--only=TANGO` to start
one control system alone. A control system with no variables to serve is not started. The rest of this
section describes running each by hand.

To run your iocs:
- go to `<output_directory>\<device_type>`
- run `python main.py`

This will run the all of the iocs for that device type on `localhost` with a default `EPICS_CA_SERVER_PORT` of `6090` as not to interfere with the default epics port of `5064`

Each PV defined in your device yaml files will have been prepended with `VM-` to avoid conflicts with the physical control system.

PV Access PVs are served in the same way, on `EPICS_PVA_SERVER_PORT` and `EPICS_PVA_BROADCAST_PORT`, both
`6091` by default, again so as not to answer searches meant for the physical control system on `5076`.

To use any EPICS cli tools you must set the following environment variables first:
- `EPICS_CA_SERVER_PORT=6090`
- `EPICS_CA_ADDR_LIST=localhost`
- `EPICS_PVA_BROADCAST_PORT=6091`, for PV Access
- `EPICS_PVA_ADDR_LIST=localhost`, for PV Access

Any of these ports can be changed by setting the variable before starting the IOCs. Channel Access and
PV Access must not be given the same one: both find PVs by UDP search, so only one of them would be
found. The IOCs warn of an environment asking for that, and move the PV Access searches to `6091`.

## TANGO

A variable is served over TANGO, rather than EPICS, by giving `TANGO` as its protocol:

```yaml
SETI:
  identifier: jfel/magnet/quad-03/current
  protocol: TANGO
```

This needs [PyTango](https://pytango.readthedocs.io), which is only imported by the generated TANGO
servers: machines served over EPICS alone render and run without it.

Rendering gives each device type a `<device_type>BaseTangoDevice.py` beside its IOCs, and:

- `<output_directory>/<device_type>/tango_main.py`, serving the devices of that type;
- `<output_directory>/run_all_tango.py`, serving every device, which is what `start_servers.py` runs.

Either one is a single TANGO device server, `Sarabi/<instance>`. By default it needs no TANGO database,
and serves on port `6092`, following on from the EPICS ports above:

```bash
python run_all_tango.py                   # --port=6092 --instance=virtual --timestep=0.1
python run_all_tango.py --list            # print the address of every attribute, and exit
```

Without a database a client gives the address of the server along with the name of the device:

```python
import tango

quad = tango.DeviceProxy("tango://localhost:6092/VM-jfel/magnet/quad-03#dbase=no")
quad.current = 10.0
```

To serve through a TANGO database instead, so that clients need only the device name, pass its address,
or pass `--database` alone to use `TANGO_HOST`. The devices are registered under `Sarabi/<instance>`,
replacing whatever that server had registered before:

```bash
python run_all_tango.py --database=localhost:10000
```

### Naming

A PV is a single name, where a TANGO attribute belongs to a device. Each variable's `identifier` is
resolved to one, and as PVs are prepended with `VM-`, devices are marked as virtual to avoid conflicts
with the physical control system:

| `identifier` | Served as |
| --- | --- |
| `jfel/magnet/quad-03/current` | `VM-jfel/magnet/quad-03/current` |
| `jfel/magnet/quad-03`, for the variable `SETI` | `VM-jfel/magnet/quad-03/SETI` |
| anything else, such as the PV name `JFEL-S02-MAG-QUAD-03:SETI` | `VM/<device_type>/<device name>/SETI` |

The last of these is what makes it possible to test an EPICS machine over TANGO without renaming
anything. The device name is the `name` in the YAML file, or the file's name without one. Names are made
valid where they have to be: `STATE` is served as `STATE_`, since every TANGO device has a `State`
already. `--list` shows where everything ended up.

All attributes are writable, as soft PVs are, and push change events, so clients can subscribe to them
without polling being configured.

### Switching an existing machine for testing

`switch_protocol.py` rewrites the protocol of the variables in every file of a devices directory, which
for the LAURA schema is the `controls -> variables -> {name} -> protocol` key:

```bash
python switch_protocol.py --settings=./settings.yaml --protocol=TANGO --dry-run
python switch_protocol.py --settings=./settings.yaml --protocol=TANGO
python start_servers.py --settings=./settings.yaml --render
```

The schema names the keys, so definitions in any schema can be switched; give `--directory` and
`--schema` to work on a directory other than the one in the settings. Comments, ordering and quoting are
kept, files with nothing to change are not touched, and a variable naming no protocol is given the key.
To switch part of a machine, narrow it down with `--from=CA`, `--device-types Magnet BPM` or
`--variables SETI READI`. `--output-directory` writes a switched copy and leaves the original alone;
without it the files are changed in place, and `--protocol=CA` switches them back.

Rendering never removes what it rendered before, so after switching, a device type keeps the module of
the control system it was switched from. It is harmless, having no variables left to serve, but delete
`output_directory` before rendering if you would rather not have it.

## Testing

```bash
pytest                   # everything, in a few minutes
pytest -m "not live"     # without starting any servers, in well under a minute
```

The tests render small machines with the same scripts you would run, and look at what comes out. Those
marked `live` go on to start the rendered servers and talk to them with real Channel Access, PV Access
and TANGO clients. They serve on ports of their own, so can be run beside a machine being simulated on
the usual ones, and need nothing installed beyond `requirements.txt`: TANGO is served without a
database, or through the one that comes with PyTango.

`tests/conftest.py` has a `Machine` for writing device definitions in either schema in a few lines,
which is the place to start when adding a test.

## Simulated dynamics

PVs can do more than hold the value last written to them. Two behaviours are read from the device
YAML and driven by the generated IOCs. TANGO attributes are driven in just the same way, by the same
definitions, provided both ends of a setpoint/readback pair are served over TANGO.

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

`tango_main.py`, `run_all_tango.py` and `start_servers.py` take the same argument.
