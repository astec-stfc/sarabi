from .protocols import CA, PVA, TANGO, protocol_of


class PVInfo:
    def __init__(self, filename: str = None, pv_map: dict = None):
        self.filename = filename
        self.pv_map = pv_map if pv_map is not None else {}

    @property
    def handles(self) -> list[str]:
        return list(self.pv_map.keys())

    def _pvs_for(self, protocol: str) -> dict:
        return {
            key: value
            for key, value in self.pv_map.items()
            if protocol_of(value) == protocol
        }

    @property
    def channel_access_pvs(self) -> dict:
        # Defaults to "CA" if protocol is not specified
        return self._pvs_for(CA)

    @property
    def pv_access_pvs(self) -> dict:
        return self._pvs_for(PVA)

    @property
    def tango_pvs(self) -> dict:
        return self._pvs_for(TANGO)
