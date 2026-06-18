class PVInfo:
    def __init__(self, filename: str = None, pv_map: dict = None):
        self.filename = filename
        self.pv_map = pv_map if pv_map is not None else {}

    @property
    def handles(self) -> list[str]:
        return list(self.pv_map.keys())

    @property
    def channel_access_pvs(self) -> dict:
        ca_pvs = {}
        for key, value in self.pv_map.items():
            # Default to "CA" if protocol is not specified
            if isinstance(value, dict) and value.get("protocol", "CA") == "CA":
                ca_pvs[key] = value
        return ca_pvs

    @property
    def pv_access_pvs(self) -> dict:
        pva_pvs = {}
        for key, value in self.pv_map.items():
            if isinstance(value, dict) and value.get("protocol", "") == "PVA":
                pva_pvs[key] = value
        return pva_pvs
