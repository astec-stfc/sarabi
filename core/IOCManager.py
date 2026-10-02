from typing import Dict


class IOCManager:
    def __init__(self):
        self.ca_iocs = {}
        self.pva_iocs = {}
        self.tango_devices = {}
        self.tango_classes = {}

    def add_ca_ioc(self, name, ioc):
        self.ca_iocs[name] = ioc

    def add_pva_ioc(self, name, ioc):
        self.pva_iocs[name] = ioc

    def add_tango_device(self, name, device):
        self.tango_devices[name] = device

    def update_ca_iocs(self, iocs: Dict):
        self.ca_iocs.update(iocs)

    def update_pva_iocs(self, iocs: Dict):
        self.pva_iocs.update(iocs)

    def update_tango_devices(self, devices: Dict, device_cls=None):
        """Record TANGO devices, keyed by device name.

        Each value is a mapping of TANGO attribute name to the handle it serves,
        so that the record is the address a client uses (``device/attribute``),
        in the same way the EPICS records are keyed by PV name. `device_cls` is
        the generated class serving them, kept in `tango_classes` for the server.
        """
        self.tango_devices.update(devices)
        if device_cls is not None:
            names = self.tango_classes.setdefault(device_cls, [])
            for name in devices:
                if name not in names:
                    names.append(name)
