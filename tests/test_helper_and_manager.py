from core import helper
from core.IOCManager import IOCManager


def test_separate_by_protocol_returns_three_maps():
    ca, pva, tango = helper.separate_by_protocol(
        {"A": {"protocol": "CA"}, "B": {"protocol": "Tango"}, "C": {}, "D": {"protocol": "PVA"}}
    )
    assert list(ca) == ["A", "C"]
    assert list(pva) == ["D"]
    assert list(tango) == ["B"]


def test_manager_records_tango_devices_and_their_classes():
    class Cls:
        pass

    manager = IOCManager()
    manager.update_tango_devices({"VM/T/1": {"X": "X"}})
    assert manager.tango_devices == {"VM/T/1": {"X": "X"}}
    assert manager.tango_classes == {}

    manager.update_tango_devices({"VM/T/1": {"X": "X"}, "VM/T/2": {"X": "X"}}, Cls)
    manager.update_tango_devices({"VM/T/2": {"X": "X"}}, Cls)  # no duplicates
    assert manager.tango_classes == {Cls: ["VM/T/1", "VM/T/2"]}


def test_create_ioc_manager_with_tango():
    class Cls:
        pass

    manager = helper._create_ioc_manager(
        {}, {}, tango_devices={"VM/T/1": {"X": "X"}}, tango_classes={Cls: ["VM/T/1"]}
    )
    assert manager.ca_iocs == {} and manager.pva_iocs == {}
    assert manager.tango_devices == {"VM/T/1": {"X": "X"}}
    assert manager.tango_classes == {Cls: ["VM/T/1"]}

    # Still works with the two-argument call the EPICS code makes.
    assert helper._create_ioc_manager({}, {}).tango_devices == {}
