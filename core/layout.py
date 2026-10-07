"""
Restrict a render to the devices on one of a facility's beam paths.

A LAURA facility is one device tree with one or more layouts over it,
and it may not be necessary to generate IOCs for the entire lattice.

The lattice states this in two files beside its ``YAML/`` tree:

``layouts.yaml``
    ``default_layout``, and ``layouts: {<LAYOUT>: [<section>, ...]}``.
``sections.yaml``
    ``sections: {<section>: {elements: [...]}}``, or the bare element list.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Optional, Set

import yaml

LAYOUTS_FILENAME = "layouts.yaml"
SECTIONS_FILENAME = "sections.yaml"

ALLOWED_DEVICES_FILENAME = "layout_devices.txt"


class UnknownLayout(Exception):
    """A layout was requested that the lattice does not define."""


class MissingLayoutFiles(Exception):
    """A layout was requested but the lattice files describing it are absent."""


def _load(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def find_lattice_file(devices_directory: str, filename: str) -> Optional[str]:
    """
    Locate the filename for the lattice whose devices are in the directory.

    Parameters
    ----------
    devices_directory: str
        The ``YAML/`` tree for the devices
    filename: str
        The name of the file we are looking for

    Returns
    -------
    str, optional
        The filename defining the overall lattice (if it exists),
        i.e. ``layouts.yaml``, ``sections.yaml``
    """
    devices_directory = os.path.abspath(devices_directory)
    for candidate in (
        os.path.join(devices_directory, filename),
        os.path.join(os.path.dirname(devices_directory), filename),
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def _section_elements(section: Any) -> Iterable[str]:
    """
    The element names in one ``sections.yaml`` entry, either shape.

    Parameters
    ----------
    section: Any
        A dictionary or list containing the elements in a section

    Returns
    -------
    Iterable[str]
        The names of elements in a section
    """
    if isinstance(section, dict):
        return section.get("elements") or []
    if isinstance(section, list):
        return section
    return []


def layout_device_names(
    layouts_file: str, sections_file: str, layout: str
) -> Set[str]:
    """Every element name on ``layout``.

    Parameters
    ----------
    layouts_file: str
        The file defining lattice layouts
    sections_file: str
        The file defining lattice sections
    layout: str
        The layout to locate

    Returns
    -------
    Set[str]
        A set of element names in the layout

    Raises
    ------
    UnknownLayout
        If the layout is not defined, or if it names an undefined section.
    """
    layouts_data = _load(layouts_file)
    layouts = layouts_data.get("layouts") or {}
    if layout not in layouts:
        raise UnknownLayout(
            f"Unknown layout {layout!r}. "
            f"{layouts_file} defines: {', '.join(sorted(layouts)) or '(none)'}"
        )

    sections = _load(sections_file).get("sections") or {}
    names: Set[str] = set()
    missing = []
    for section in layouts[layout]:
        if section not in sections:
            missing.append(section)
            continue
        names.update(_section_elements(sections[section]))
    if missing:
        raise UnknownLayout(
            f"Layout {layout!r} names section(s) absent from {sections_file}: "
            f"{', '.join(missing)}"
        )
    return names


def resolve_allowed_devices(
    devices_directory: str,
    layout: Optional[str],
    layouts_file: Optional[str] = None,
    sections_file: Optional[str] = None,
) -> Optional[Set[str]]:
    """The names to render, or ``None`` for "no filtering".

    Parameters
    ----------
    devices_directory: str
        Directory containing device files
    layout: str, optional
        The layout to resolve
    layouts_file: str, optional
        File containing layout definitions
    sections_file: str, optional
        File containing section definitions

    Returns
    -------
    Set[str]
        Set of allowed device names from ``layout``

    Raises
    ------
    MissingLayoutFiles
        If the layout is not defined or found
    """
    if not layout:
        return None

    layouts_path = layouts_file or find_lattice_file(
        devices_directory, LAYOUTS_FILENAME
    )
    sections_path = sections_file or find_lattice_file(
        devices_directory, SECTIONS_FILENAME
    )
    absent = [
        name
        for name, path in (
            (LAYOUTS_FILENAME, layouts_path),
            (SECTIONS_FILENAME, sections_path),
        )
        if not path or not os.path.exists(path)
    ]
    if absent:
        raise MissingLayoutFiles(
            f"layout={layout!r} was requested but {' and '.join(absent)} "
            f"could not be found in {devices_directory} or its parent"
        )
    return layout_device_names(layouts_path, sections_path, layout)


def write_allowed_devices(output_directory: str, names: Optional[Set[str]]) -> None:
    """
    Record the filter for the generated scripts, or clear a stale one.

    Parameters
    ----------
    output_directory: str
        Name of directory to which to write files
    names: Set[str]
        Names of devices to write
    """
    path = os.path.join(output_directory, ALLOWED_DEVICES_FILENAME)
    if names is None:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(output_directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(sorted(names)) + "\n")


def load_allowed_devices(output_directory: str) -> Optional[Set[str]]:
    """
    Read back `write_allowed_devices`; ``None`` if no filter was written.

    Parameters
    ----------
    output_directory: str
        Directory to load from

    Returns
    -------
    Set[str]
        List of devices that were loaded
    """
    path = os.path.join(output_directory, ALLOWED_DEVICES_FILENAME)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return {line.strip() for line in handle if line.strip()}
