"""The control system protocols a variable may be served over.

Device definitions name the protocol of each variable under its ``protocol``
key. Three are supported:

* ``CA``    -- EPICS Channel Access, served by caproto;
* ``PVA``   -- EPICS PV Access, served by p4p;
* ``TANGO`` -- TANGO, served by pytango.

The spelling in a definition is normalised here so that the renderers and the
runtime agree on what each variable is, and so that a definition may say
``Tango`` or ``EPICS`` without either end having to know every variant.
"""

import warnings
from typing import Any, Dict, Optional

CA = "CA"
PVA = "PVA"
TANGO = "TANGO"

PROTOCOLS = (CA, PVA, TANGO)

DEFAULT_PROTOCOL = CA
"""The protocol assumed when a variable does not name one."""

_ALIASES = {
    "CA": CA,
    "EPICS": CA,
    "EPICS_CA": CA,
    "EPICS-CA": CA,
    "CHANNELACCESS": CA,
    "CHANNEL_ACCESS": CA,
    "PVA": PVA,
    "EPICS_PVA": PVA,
    "EPICS-PVA": PVA,
    "PVACCESS": PVA,
    "PV_ACCESS": PVA,
    "TANGO": TANGO,
    "PYTANGO": TANGO,
}

_warned = set()


def normalise_protocol(value: Optional[str]) -> str:
    """The canonical protocol name for `value`, one of `PROTOCOLS`.

    A missing value is `DEFAULT_PROTOCOL`. An unrecognised one is reported
    once and treated as the default, so that a misspelt definition is served
    rather than silently dropped.
    """
    if value is None or value == "":
        return DEFAULT_PROTOCOL
    key = str(value).strip().upper()
    protocol = _ALIASES.get(key)
    if protocol is None:
        if key not in _warned:
            _warned.add(key)
            warnings.warn(
                f"Unknown protocol '{value}'; expected one of {PROTOCOLS}. "
                f"Treating it as {DEFAULT_PROTOCOL}."
            )
        return DEFAULT_PROTOCOL
    return protocol


def protocol_of(config: Any, protocol_word: str = "protocol") -> str:
    """The protocol of one variable's definition, normalised."""
    if not isinstance(config, dict):
        return DEFAULT_PROTOCOL
    return normalise_protocol(config.get(protocol_word))


def split_by_protocol(
    pv_map: Dict[str, Any], protocol_word: str = "protocol"
) -> Dict[str, Dict[str, Any]]:
    """Group the variables of `pv_map` by protocol.

    Returns a dict with a (possibly empty) entry for every protocol in
    `PROTOCOLS`, so callers can index it without checking.
    """
    groups: Dict[str, Dict[str, Any]] = {protocol: {} for protocol in PROTOCOLS}
    for handle, config in pv_map.items():
        groups[protocol_of(config, protocol_word)][handle] = config
    return groups
