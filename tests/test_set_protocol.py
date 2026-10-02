import copy
import os
import sys

import pytest
import yaml

import set_protocol
from tests.conftest import LAURA_SCHEMA, QUAD_01


def load(path):
    with open(path) as f:
        return yaml.safe_load(f)


def protocols(path):
    return {h: c.get("protocol") for h, c in load(path)["controls"]["variables"].items()}


def test_set_protocol_rewrites_in_place_and_reports(translator):
    data = {"controls": {"variables": copy.deepcopy(QUAD_01)}}
    changed = set_protocol.set_protocol(data, translator, "PVA")
    assert changed == [("SETI", "TANGO"), ("READI", "TANGO"), ("NOISE", "TANGO"), ("STATE", "TANGO"), ("SETK", "CA")]
    assert {c["protocol"] for c in data["controls"]["variables"].values()} == {"PVA"}
    assert set_protocol.set_protocol(data, translator, "PVA") == []  # nothing left to change


def test_set_protocol_filters_by_current_protocol_and_handle(translator):
    data = {"controls": {"variables": copy.deepcopy(QUAD_01)}}
    assert set_protocol.set_protocol(data, translator, "PVA", only="CA") == [("SETK", "CA")]
    data = {"controls": {"variables": copy.deepcopy(QUAD_01)}}
    assert set_protocol.set_protocol(data, translator, "PVA", handles=["READI", "NOPE"]) == [("READI", "TANGO")]
    # A variable with no protocol counts as CA.
    data = {"controls": {"variables": {"A": {"identifier": "x"}, "B": {"protocol": "PVA"}}}}
    assert set_protocol.set_protocol(data, translator, "TANGO", only="CA") == [("A", None)]


def test_set_protocol_tolerates_malformed_definitions(translator):
    assert set_protocol.set_protocol({}, translator, "TANGO") == []
    assert set_protocol.set_protocol({"controls": "oops"}, translator, "TANGO") == []
    assert set_protocol.set_protocol({"controls": {"variables": ["a"]}}, translator, "TANGO") == []
    assert set_protocol.set_protocol({"controls": {"variables": {"A": "oops"}}}, translator, "TANGO") == []


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["set_protocol.py", *args])
    return set_protocol.main()


def test_main_rewrites_a_directory(devices_dir, monkeypatch, capsys):
    quad1 = os.path.join(devices_dir, "Magnet", "Quadrupole", "TEST-S01-MAG-QUAD-01.yaml")
    cavity = os.path.join(devices_dir, "RF", "RFCavity", "TEST-L01-RF-CAV-01.yaml")
    before = load(quad1)

    assert run_main(monkeypatch, "--devices", devices_dir, "--protocol", "pva", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "Would update" in out and "would be changed" in out
    assert load(quad1) == before  # dry run leaves files alone

    assert run_main(monkeypatch, "--devices", devices_dir, "--protocol", "pva", "--schema", LAURA_SCHEMA) == 0
    out = capsys.readouterr().out
    assert "11 variable(s) in 3 file(s) changed." in out
    assert protocols(quad1) == {h: "PVA" for h in QUAD_01}
    assert protocols(cavity) == {"PHASE": "PVA", "AMP": "PVA", "POWER": "PVA"}
    after = load(quad1)
    after_vars = after["controls"]["variables"]
    assert list(after_vars) == list(before["controls"]["variables"])  # key order kept
    assert after_vars["SETI"]["dynamics"] == QUAD_01["SETI"]["dynamics"]  # other keys untouched
    assert after["name"] == before["name"]


def test_main_only_and_handles(devices_dir, monkeypatch, capsys):
    cavity = os.path.join(devices_dir, "RF", "RFCavity", "TEST-L01-RF-CAV-01.yaml")
    assert run_main(monkeypatch, "--devices", devices_dir, "--protocol", "TANGO", "--only", "CA", "--handles", "PHASE,SETK") == 0
    assert protocols(cavity) == {"PHASE": "TANGO", "AMP": "PVA", "POWER": "Tango"}
    quad2 = os.path.join(devices_dir, "Magnet", "Quadrupole", "TEST-S01-MAG-QUAD-02.yaml")
    assert protocols(quad2)["SETK"] == "TANGO"
    assert "3 variable(s) in 3 file(s) changed." in capsys.readouterr().out


def test_main_rejects_unknown_protocol_and_missing_directory(devices_dir, monkeypatch, capsys, tmp_path):
    assert run_main(monkeypatch, "--devices", devices_dir, "--protocol", "MODBUS") == 2
    assert "Unknown protocol 'MODBUS'" in capsys.readouterr().out
    assert run_main(monkeypatch, "--devices", str(tmp_path / "nowhere"), "--protocol", "TANGO") == 2
