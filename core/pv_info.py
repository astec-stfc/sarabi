from .protocols import CA, PVA, TANGO, split_by_protocol


class PVInfo:
    def __init__(self, filename: str = None, pv_map: dict = None):
        self.filename = filename
        self.pv_map = pv_map if pv_map is not None else {}

    @property
    def handles(self) -> list[str]:
        return list(self.pv_map.keys())

    def _by_protocol(self, protocol: str) -> dict:
        return {
            key: value
            for key, value in split_by_protocol(self.pv_map)[protocol].items()
            if isinstance(value, dict)
        }

    @property
    def channel_access_pvs(self) -> dict:
        # A variable with no protocol is Channel Access.
        return self._by_protocol(CA)

    @property
    def pv_access_pvs(self) -> dict:
        return self._by_protocol(PVA)

    @property
    def tango_pvs(self) -> dict:
        return self._by_protocol(TANGO)
