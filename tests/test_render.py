import ast
import importlib.util
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

import render_iocs
from core.pv_info import PVInfo
from tests.conftest import QUAD_01, QUAD_02, ROOT, TEMPLATES

TANGO_TEMPLATE = os.path.join(TEMPLATES, "tango_base_template.j2")


def render(pv_map, unique=None, attribute_names=None, device_type="Magnet"):
    template = render_iocs._load_template(TANGO_TEMPLATE)
    names = attribute_names or {h: h for h in list(pv_map) + list(unique or {})}
    return template.render(
        device_type=device_type,
        class_name=f"{device_type}BaseTangoDevice",
        pv_map=pv_map,
        unique_pv_map=unique or {},
        dtype_map=render_iocs.TANGO_DTYPE_MAP,
        attribute_names=names,
    )


def load_module(path):
    spec = importlib.util.spec_from_file_location(os.path.basename(path)[:-3], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_template_renders_every_type_as_valid_python(tmp_path):
    pv_map = {
        "READI": {"dtype": "float", "units": "A", "description": 'Current "read"', "read_only": True},
        "STATE": {"dtype": "state", "states": {"ON": 1, "OFF": 0, "FAULT": 2}},
        "NOSTATES": {"dtype": "state"},
        "WAVE": {"type": "waveform"},
        "LABEL": {"dtype": "string"},
        "FLAG": {"dtype": "binary"},
        "N": {"dtype": "int"},
        "ODD": {"dtype": "no_such_type"},
        "BARE": {},
    }
    names = {h: h for h in pv_map}
    names["STATE"] = "STATE_"
    source = render(pv_map, unique={"EXTRA": {"control_type": "statistical"}}, attribute_names={**names, "EXTRA": "EXTRA"})
    ast.parse(source)
    path = tmp_path / "MagnetBaseTangoDevice.py"
    path.write_text(source)
    module = load_module(str(path))
    declared = module.MagnetBaseTangoDevice.declared_attributes()

    assert list(declared) == list(pv_map) + ["EXTRA"]
    readi = declared["READI"]
    assert (readi.dtype, readi.unit, readi.doc) == (float, "A", 'Current "read"')
    assert readi.access.name == "READ" and not readi.writable
    state = declared["STATE"]
    assert state.name == "STATE_" and state.enum_labels == ["OFF", "ON", "FAULT"]
    assert declared["NOSTATES"].enum_labels == ["UNDEFINED"]
    assert declared["WAVE"].dtype == (float,) and declared["WAVE"].max_dim_x == 65536
    assert declared["LABEL"].dtype is str and declared["LABEL"].initial == "undefined"
    assert declared["FLAG"].dtype is bool and declared["FLAG"].initial is False
    assert declared["N"].dtype is int
    assert declared["ODD"].dtype is float and declared["BARE"].dtype is float
    assert declared["EXTRA"].optional and not declared["READI"].optional
    assert "default description." == declared["BARE"].doc


def test_template_output_is_indented_without_black():
    source = render({"READK": {"dtype": "float"}})
    lines = source.splitlines()
    assert "    READK = TangoAttribute(" in lines
    assert not any(line.startswith("READK") for line in lines)
    assert "\n\n\n\n" not in source


def test_template_with_no_variables_is_valid():
    source = render({}, unique={})
    ast.parse(source)
    assert "    pass" in source


def test_render_tango_base_writes_module_and_package(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render_iocs, "SETTINGS", SimpleNamespace(output_directory=str(tmp_path)))
    monkeypatch.setattr(render_iocs, "tango_base_template", render_iocs._load_template(TANGO_TEMPLATE), raising=False)
    common = PVInfo(pv_map={h: c for h, c in QUAD_02.items() if h in ("SETI", "READI")})
    unique = PVInfo(pv_map={"ONLY_HERE": QUAD_02["ONLY_HERE"], "STATE": QUAD_01["STATE"]})
    names = {"SETI": "SETI", "READI": "READI", "ONLY_HERE": "ONLY_HERE", "STATE": "STATE_"}

    render_iocs.render_tango_base("Quadrupole", common, unique, names)

    module_path = tmp_path / "Quadrupole" / "QuadrupoleBaseTangoDevice.py"
    assert module_path.exists()
    assert (tmp_path / "Quadrupole" / "__init__.py").exists()
    declared = load_module(str(module_path)).QuadrupoleBaseTangoDevice.declared_attributes()
    assert list(declared) == ["SETI", "READI", "ONLY_HERE", "STATE"]
    assert declared["ONLY_HERE"].optional and declared["STATE"].name == "STATE_"


def test_render_tango_base_skips_types_without_tango_variables(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render_iocs, "SETTINGS", SimpleNamespace(output_directory=str(tmp_path)))
    monkeypatch.setattr(render_iocs, "tango_base_template", render_iocs._load_template(TANGO_TEMPLATE), raising=False)
    render_iocs.render_tango_base("RFCavity", PVInfo(pv_map={"A": {"protocol": "CA"}}), PVInfo(), {})
    assert "no TANGO variables for RFCavity" in capsys.readouterr().out
    assert not (tmp_path / "RFCavity").exists()


@pytest.mark.slow
def test_render_scripts_end_to_end(settings_file, tmp_path):
    """render_iocs.py then render_main.py, on the fixture devices, produce importable modules."""
    for script in ("render_iocs.py", "render_main.py"):
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, script), f"--settings={settings_file}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    output = tmp_path / "generated"
    quad = output / "Quadrupole"
    assert (quad / "QuadrupoleBaseTangoDevice.py").exists()
    assert (quad / "QuadrupoleBaseIOC.py").exists()  # SETK stays on Channel Access
    assert not (quad / "QuadrupoleBasePVAIOC.py").exists()
    assert (quad / "main.py").exists()
    cavity = output / "RFCavity"
    assert (cavity / "RFCavityBaseTangoDevice.py").exists()  # 'Tango' spelling
    assert (cavity / "RFCavityBaseIOC.py").exists()
    assert (cavity / "RFCavityBasePVAIOC.py").exists()

    declared = load_module(str(quad / "QuadrupoleBaseTangoDevice.py")).QuadrupoleBaseTangoDevice.declared_attributes()
    assert set(declared) == {"SETI", "READI", "NOISE", "STATE", "ONLY_HERE"}
    assert declared["NOISE"].optional and declared["ONLY_HERE"].optional and not declared["SETI"].optional
    assert declared["STATE"].name == "STATE_"

    run_all = (output / "run_all_iocs.py").read_text()
    ast.parse(run_all)
    assert '"TANGO": QuadrupoleBaseTangoDevice' in run_all
    assert '"TANGO": RFCavityBaseTangoDevice' in run_all
    assert '"CA": QuadrupoleBaseIOC' in run_all
    assert "tango_helper.run_tango_server" in run_all
    main = (quad / "main.py").read_text()
    ast.parse(main)
    assert "tango_helper.construct_tango_devices(" in main and '"Quadrupole"' in main
    assert "tango_helper.restore_signal_handlers()" in main
