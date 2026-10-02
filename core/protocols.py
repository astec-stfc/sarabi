"""The control system protocols a variable can be served over.

A variable names its protocol in the device definition; one that names none is
served over Channel Access, as it always has been.
"""

from typing import Any

CA = "CA"
PVA = "PVA"
TANGO = "TANGO"

PROTOCOLS = (CA, PVA, TANGO)
DEFAULT_PROTOCOL = CA


def protocol_of(config: Any, protocol_word: str = "protocol") -> str:
    """The protocol a variable's definition asks for, upper-cased.

    Returns the default for a definition that names none, and an empty string
    for one that is not a mapping, which no protocol serves.
    """
    if not isinstance(config, dict):
        return ""
    protocol = config.get(protocol_word)
    if protocol is None:
        return DEFAULT_PROTOCOL
    return str(protocol).strip().upper()
