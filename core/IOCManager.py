from typing import Dict


class IOCManager:
    def __init__(self):
        self.ca_iocs = {}
        self.pva_iocs = {}

    def add_ca_ioc(self, name, ioc):
        self.ca_iocs[name] = ioc

    def add_pva_ioc(self, name, ioc):
        self.pva_iocs[name] = ioc

    def update_ca_iocs(self, iocs: Dict):
        self.ca_iocs.update(iocs)

    def update_pva_iocs(self, iocs: Dict):
        self.pva_iocs.update(iocs)
