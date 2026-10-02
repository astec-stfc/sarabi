"""Switch the protocol of the variables in a directory of device definitions.

Rewrites the protocol of every variable in every YAML file under a devices
directory, which for the LAURA schema is ``controls -> variables -> {name} ->
protocol``, so that an existing machine can be served over another control
system for testing::

    python switch_protocol.py --settings=./settings.yaml --protocol=TANGO

The schema names the keys, so definitions in any schema can be switched.
Comments, ordering and quoting are kept, and files with nothing to change are
left untouched. Identifiers are not changed: see `core.tango_naming` for where
a variable with a PV name is served over TANGO.
"""

import argparse
import os
import shutil
import sys
from typing import List, Optional, Tuple

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from core.discovery import is_yaml_file
from core.protocols import DEFAULT_PROTOCOL, PROTOCOLS, protocol_of
from core.translator import SchemaTranslator


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Switch the protocol of the variables in a directory of device "
        "definitions."
    )
    parser.add_argument(
        "--protocol",
        type=str.upper,
        required=True,
        choices=PROTOCOLS,
        help="Protocol to serve the variables over.",
    )
    parser.add_argument(
        "--settings",
        type=str,
        help="Path to the settings YAML file, naming the devices directory and schema.",
    )
    parser.add_argument(
        "--directory",
        type=str,
        help="Directory of device definitions, if not the one in the settings.",
    )
    parser.add_argument(
        "--schema",
        type=str,
        help="Schema file of the definitions, if not the one in the settings.",
    )
    parser.add_argument(
        "--from",
        dest="from_protocol",
        type=str.upper,
        choices=PROTOCOLS,
        help="Only switch variables currently served over this protocol.",
    )
    parser.add_argument(
        "--device-types",
        nargs="+",
        metavar="TYPE",
        help="Only switch definitions in the folders of these device types.",
    )
    parser.add_argument(
        "--variables",
        nargs="+",
        metavar="NAME",
        help="Only switch the variables with these names.",
    )
    parser.add_argument(
        "--output-directory",
        type=str,
        help="Write a switched copy of the directory here, leaving the original "
        "as it is.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be switched without writing anything.",
    )
    args = parser.parse_args()
    if not args.settings and not (args.directory and args.schema):
        parser.error("give --settings, or both --directory and --schema")
    return args


def _resolve_locations(args) -> Tuple[str, str]:
    """The devices directory and schema file to work from."""
    directory, schema = args.directory, args.schema
    if args.settings and not (directory and schema):
        with open(args.settings) as f:
            settings = yaml.safe_load(f)
        directory = directory or settings["devices_directory"]
        schema = schema or settings["schema_file"]
    if not os.path.isdir(directory):
        raise SystemExit(f"Could not find devices directory: {directory}")
    if not os.path.isfile(schema):
        raise SystemExit(f"Could not find schema file: {schema}")
    return directory, schema


def _round_trip_yaml() -> YAML:
    round_trip = YAML(typ="rt")
    round_trip.preserve_quotes = True
    # Long values are left on the line they were written on
    round_trip.width = 2**16
    round_trip.indent(mapping=2, sequence=4, offset=2)
    return round_trip


def switch_variables(
    variables,
    protocol: str,
    protocol_word: str,
    from_protocol: Optional[str] = None,
    only: Optional[List[str]] = None,
) -> List[Tuple[str, str]]:
    """Switch the variables of one definition, in place.

    Returns the name and former protocol of each variable that was switched.
    A variable naming no protocol is served over the default one, and is given
    the key if it is switched to another.
    """
    switched = []
    for name, config in variables.items():
        if only and name not in only:
            continue
        if not hasattr(config, "keys"):
            continue
        current = protocol_of(dict(config), protocol_word)
        if current == protocol:
            continue
        if from_protocol and current != from_protocol:
            continue
        config[protocol_word] = protocol
        switched.append((str(name), current or DEFAULT_PROTOCOL))
    return switched


def switch_file(
    source: str,
    destination: str,
    translator: SchemaTranslator,
    args,
) -> List[Tuple[str, str]]:
    """Switch one file, writing it to `destination` if anything changed."""
    round_trip = _round_trip_yaml()
    with open(source) as f:
        data = round_trip.load(f)
    variables = None
    if hasattr(data, "get"):
        controls = data.get(translator.controls_information_word)
        if hasattr(controls, "get"):
            variables = controls.get(translator.signal_information_word)
    if not hasattr(variables, "items"):
        return []
    switched = switch_variables(
        variables,
        args.protocol,
        translator.protocol_word,
        from_protocol=args.from_protocol,
        only=args.variables,
    )
    if switched and not args.dry_run:
        with open(destination, "w") as f:
            round_trip.dump(data, f)
    return switched


def main() -> int:
    args = parse_arguments()
    directory, schema = _resolve_locations(args)
    translator = SchemaTranslator(schema)

    output = args.output_directory
    if output and not args.dry_run:
        if os.path.abspath(output) == os.path.abspath(directory):
            raise SystemExit("--output-directory is the devices directory itself.")
        if os.path.exists(output):
            raise SystemExit(f"{output} already exists; not writing over it.")
        shutil.copytree(directory, output)

    files = variables = failures = 0
    for root, dirs, filenames in os.walk(directory):
        dirs.sort()
        if args.device_types and os.path.basename(root) not in args.device_types:
            continue
        for filename in sorted(filenames):
            if not is_yaml_file(filename):
                continue
            source = os.path.join(root, filename)
            relative = os.path.relpath(source, directory)
            destination = os.path.join(output, relative) if output else source
            try:
                switched = switch_file(source, destination, translator, args)
            except (YAMLError, OSError) as exc:
                failures += 1
                print(f"Could not switch {relative}: {exc}", file=sys.stderr)
                continue
            if switched:
                files += 1
                variables += len(switched)
                was = ", ".join(sorted({former for _, former in switched}))
                print(f"{relative}: switched {len(switched)} from {was}")

    action = "Would switch" if args.dry_run else "Switched"
    where = f" in {output}" if output and not args.dry_run else ""
    print(f"{action} {variables} variables in {files} files to {args.protocol}{where}.")
    if not variables:
        print(
            f"Found nothing to switch under '{translator.controls_information_word}' "
            f"-> '{translator.signal_information_word}'. Is {schema} the schema of "
            "these definitions?"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
