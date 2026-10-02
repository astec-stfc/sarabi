"""Where a variable served over TANGO is found on the network.

An EPICS PV is a single flat name. A TANGO attribute belongs to a device, named
``domain/family/member``, so a variable's identifier is resolved to a device
and an attribute on it:

* An identifier that is already a TANGO attribute name is served as written,
  with the domain marked as virtual, as PV names are, to avoid conflicts with
  the physical control system::

      jfel/magnet/quad-03/current  ->  VM-jfel/magnet/quad-03/current

  One naming only a device, ``jfel/magnet/quad-03``, is served on that device
  as an attribute named after the variable's handle.

* Any other identifier, such as the PV name left behind when a definition is
  switched to TANGO for testing, says nothing about a TANGO device. The
  variable is served on a device named after its definition, again as an
  attribute named after its handle::

      JFEL-S02-MAG-QUAD-03:SETI    ->  VM/Magnet/JFEL-S02-MAG-QUAD-03/SETI

Nothing here needs TANGO itself, so that servers can be rendered on a machine
that does not have it.
"""

import keyword
import re
import warnings
from typing import Any, Dict, Tuple

from .protocols import TANGO, protocol_of
from .translator import SchemaTranslator

VIRTUAL_PREFIX = "VM"
"""Marks the devices served here as virtual, as the "VM-" prefix does for PVs."""

_TANGO_NAME = re.compile(
    r"^(?:tango://[^/]+/)?"
    r"(?P<domain>[^/\s#]+)/(?P<family>[^/\s#]+)/(?P<member>[^/\s#]+)"
    r"(?:/(?P<attribute>[^/\s#]+))?"
    r"(?:#.*)?$"
)

# Every TANGO device has these attributes already, and attribute names are not
# case sensitive.
_RESERVED_ATTRIBUTES = {"state", "status"}


def device_field(text: str) -> str:
    """`text` as one field of a TANGO device name."""
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", str(text)) or "_"


def attribute_name(text: str) -> str:
    """`text` as a TANGO attribute name that is also a Python identifier.

    Generated device classes declare an attribute, and the methods reading and
    writing it, under this name.
    """
    name = re.sub(r"\W", "_", str(text), flags=re.ASCII) or "_"
    if name[0].isdigit():
        name = "_" + name
    if name.lower() in _RESERVED_ATTRIBUTES or keyword.iskeyword(name):
        name += "_"
    return name


def attribute_address(
    identifier: str, handle: str, device_type: str, device_name: str
) -> Tuple[str, str]:
    """The TANGO device and attribute serving the variable `handle`."""
    match = _TANGO_NAME.match(str(identifier or "").strip())
    if match:
        device = "/".join(
            (
                f"{VIRTUAL_PREFIX}-{device_field(match['domain'])}",
                device_field(match["family"]),
                device_field(match["member"]),
            )
        )
        return device, attribute_name(match["attribute"] or handle)
    device = "/".join(
        (VIRTUAL_PREFIX, device_field(device_type), device_field(device_name))
    )
    return device, attribute_name(handle)


def tango_devices(
    device_type: str,
    device_name: str,
    variables: Dict[str, Any],
    translator: SchemaTranslator,
) -> Dict[str, Dict[str, str]]:
    """The TANGO devices serving one definition's variables.

    Maps each device name to its attributes, and each attribute to the handle
    of the variable it serves. Identifiers usually place every variable on one
    device, but are free to spread them over several.
    """
    devices: Dict[str, Dict[str, str]] = {}
    for handle, config in variables.items():
        if protocol_of(config, translator.protocol_word) != TANGO:
            continue
        identifier = config.get(translator.identifier_word)
        if not identifier:
            # only serve variables that are named, as for PVs
            continue
        device, attribute = attribute_address(
            identifier, handle, device_type, device_name
        )
        attributes = devices.setdefault(device, {})
        # TANGO does not tell attribute names apart by case
        taken = {name.lower(): name for name in attributes}
        if attribute.lower() in taken:
            warnings.warn(
                f"{device_name}: '{handle}' and '{attributes[taken[attribute.lower()]]}' "
                f"are both the TANGO attribute {device}/{attribute}; "
                f"not serving '{handle}'."
            )
            continue
        attributes[attribute] = handle
    return devices
