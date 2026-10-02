from core.pv_info import PVInfo


def test_pv_info_splits_handles_by_protocol():
    info = PVInfo(
        filename="x.yaml",
        pv_map={
            "A": {"protocol": "CA"},
            "B": {"protocol": "TANGO"},
            "C": {},
            "D": {"protocol": "PVA"},
            "E": "not a mapping",
        },
    )
    assert info.handles == ["A", "B", "C", "D", "E"]
    assert list(info.channel_access_pvs) == ["A", "C"]
    assert list(info.pv_access_pvs) == ["D"]
    assert list(info.tango_pvs) == ["B"]


def test_pv_info_accepts_protocol_spellings():
    info = PVInfo(pv_map={"A": {"protocol": "tango"}, "B": {"protocol": "EPICS"}})
    assert list(info.tango_pvs) == ["A"]
    assert list(info.channel_access_pvs) == ["B"]
