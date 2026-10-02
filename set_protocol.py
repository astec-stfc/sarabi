"""Set the protocol of every variable in a directory of device definitions.

Walks a directory of device YAML files and rewrites the ``protocol`` key of
each variable, e.g. ``controls -> variables -> READK -> protocol``, so that an
existing set of EPICS definitions can be served over TANGO (or PV Access) for
testing without editing each file by hand::

    python set_protocol.py --devices ./yaml/JFEL --protocol TANGO
    python set_protocol.py --devices ./yaml/JFEL --protocol PVA --only CA --dry-run
    python set_protocol.py --devices ./yaml/JFEL --protocol TANGO --handles READK,SETI

The key names are read from the schema (``--schema``, default the LAURA
schema), so the same script works for definitions written to any schema.
Files are rewritten in place, preserving key order; take a copy first if the
originals matter, since YAML comments are not preserved.
"""

import argparse
import os
import sys
from typing import Iterable, List, Optional, Tuple

import yaml

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from core.protocols import PROTOCOLS, normalise_protocol  # noqa: E402
from core.translator import SchemaTranslator  # noqa: E402

DEFAULT_SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas", "laura.json")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Rewrite the protocol of every variable in a directory of device YAML files."
    )
    parser.add_argument(
        "--devices", type=str, required=True, help="Directory of device YAML files, searched recursively."
    )
    parser.add_argument(
        "--protocol",
        type=str,
        required=True,
        help=f"Protocol to set, one of {', '.join(PROTOCOLS)} (case-insensitive; aliases such as 'Tango' are accepted).",
    )
    parser.add_argument(
        "--schema",
        type=str,
        default=DEFAULT_SCHEMA,
        help="Schema JSON naming the controls/variables/protocol keys (default: schemas/laura.json).",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Only change variables currently using this protocol (e.g. CA). Default: change all.",
    )
    parser.add_argument(
        "--handles",
        type=str,
        default=None,
        help="Comma-separated variable handles to change (e.g. READK,SETI). Default: all handles.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would change without writing any file."
    )
    return parser.parse_args()


def find_yaml_files(root: str) -> List[str]:
    files = []
    for dirpath, _, filenames in os.walk(root):
        for filename in sorted(filenames):
            if filename.lower().endswith((".yaml", ".yml")):
                files.append(os.path.join(dirpath, filename))
    return sorted(files)


def set_protocol(
    data: dict,
    translator: SchemaTranslator,
    protocol: str,
    only: Optional[str] = None,
    handles: Optional[Iterable[str]] = None,
) -> List[Tuple[str, Optional[str]]]:
    """Set the protocol of the variables in one loaded definition, in place.

    Returns the ``(handle, previous protocol)`` of every variable changed.
    """
    variables = (data or {}).get(translator.controls_information_word, {})
    if not isinstance(variables, dict):
        return []
    variables = variables.get(translator.signal_information_word, {})
    if not isinstance(variables, dict):
        return []

    wanted = set(handles) if handles else None
    changed = []
    for handle, config in variables.items():
        if not isinstance(config, dict):
            continue
        if wanted is not None and handle not in wanted:
            continue
        previous = config.get(translator.protocol_word)
        if only is not None and normalise_protocol(previous) != only:
            continue
        if previous == protocol:
            continue
        config[translator.protocol_word] = protocol
        changed.append((handle, previous))
    return changed


def main() -> int:
    args = parse_arguments()
    protocol = normalise_protocol(args.protocol)
    if str(args.protocol).strip().upper() not in (protocol, *PROTOCOLS) and protocol == "CA":
        # normalise_protocol falls back to CA for unknown names; do not let a
        # typo rewrite a whole directory to Channel Access.
        print(f"Unknown protocol '{args.protocol}'; expected one of {', '.join(PROTOCOLS)}.")
        return 2
    only = normalise_protocol(args.only) if args.only else None
    handles = [h.strip() for h in args.handles.split(",") if h.strip()] if args.handles else None

    if not os.path.isdir(args.devices):
        print(f"Not a directory: {args.devices}")
        return 2
    translator = SchemaTranslator(args.schema)

    files_changed = 0
    variables_changed = 0
    for path in find_yaml_files(args.devices):
        with open(path, "r") as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as exc:
                print(f"Skipping {path}: {exc}")
                continue
        if not isinstance(data, dict):
            continue
        changed = set_protocol(data, translator, protocol, only=only, handles=handles)
        if not changed:
            continue
        files_changed += 1
        variables_changed += len(changed)
        summary = ", ".join(f"{handle} ({previous or 'unset'} -> {protocol})" for handle, previous in changed)
        print(f"{'Would update' if args.dry_run else 'Updating'} {os.path.relpath(path, args.devices)}: {summary}")
        if not args.dry_run:
            with open(path, "w") as f:
                yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, default_flow_style=False)

    verb = "would be changed" if args.dry_run else "changed"
    print(f"{variables_changed} variable(s) in {files_changed} file(s) {verb}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
