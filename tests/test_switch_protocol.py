"""Switching the protocol of the variables in a directory of definitions."""

import sys
import textwrap

import pytest
import yaml

import switch_protocol
from conftest import SARABI_ROOT

LAURA = str(SARABI_ROOT / "schemas" / "laura.json")

QUAD = textwrap.dedent("""\
    # Quadrupole 3 -- a comment that has to survive
    name: QUAD-03
    aliases:
      - Q3
      - QUAD3
    controls:
      variables:
        SETI:
          identifier: QUAD-03:SETI
          description: Set current   # and one on the end of a line
          protocol: CA
          dynamics: {model: simmodels.FirstOrderResponse, tau: 0.3}
        READI:
          identifier: QUAD-03:READI
          protocol: "CA"
        READK:
          identifier: QUAD-03:READK
        COUNT:
          identifier: QUAD-03:COUNT
          protocol: PVA
    """)
FLOW = 'name: L1\ncontrols: {variables: {POWER: {identifier: "L1:POWER"}}}\n'


@pytest.fixture
def definitions(tmp_path):
    directory = tmp_path / "yaml"
    (directory / "Magnet").mkdir(parents=True)
    (directory / "Laser").mkdir()
    (directory / "Magnet" / "quad.yaml").write_text(QUAD)
    (directory / "Laser" / "laser.yml").write_text(FLOW)
    (directory / "Laser" / "notes.yaml").write_text("- not a definition\n")
    return directory


def switch(monkeypatch, directory, *args):
    monkeypatch.setattr(
        sys,
        "argv",
        ["switch_protocol.py", f"--directory={directory}", f"--schema={LAURA}", *args],
    )
    return switch_protocol.main()


def protocols(yaml_file):
    variables = yaml.safe_load(yaml_file.read_text())["controls"]["variables"]
    return {name: config.get("protocol") for name, config in variables.items()}


def changed_lines(before: str, after: str):
    before, after = before.splitlines(), after.splitlines()
    return [line for line in after if line not in before]


def test_every_variable_is_switched(monkeypatch, definitions, capsys):
    assert switch(monkeypatch, definitions, "--protocol=TANGO") == 0

    assert protocols(definitions / "Magnet" / "quad.yaml") == dict.fromkeys(
        ["SETI", "READI", "READK", "COUNT"], "TANGO"
    )
    assert protocols(definitions / "Laser" / "laser.yml") == {"POWER": "TANGO"}
    assert "Switched 5 variables in 2 files to TANGO" in capsys.readouterr().out


def test_nothing_but_the_protocol_changes(monkeypatch, definitions):
    """The definitions live in repositories of their own, where this shows as a diff."""
    switch(monkeypatch, definitions, "--protocol=TANGO")

    after = (definitions / "Magnet" / "quad.yaml").read_text()
    assert changed_lines(QUAD, after) == [
        "      protocol: TANGO",
        # Written as it was written: this one was quoted
        '      protocol: "TANGO"',
        # READK named no protocol, so is given the key
        "      protocol: TANGO",
        "      protocol: TANGO",
    ]
    assert len(after.splitlines()) == len(QUAD.splitlines()) + 1
    # A mapping written on one line stays on it
    assert (definitions / "Laser" / "laser.yml").read_text() == FLOW.replace(
        '"L1:POWER"}', '"L1:POWER", protocol: TANGO}'
    )


def test_switching_back_restores_the_protocols(monkeypatch, definitions):
    switch(monkeypatch, definitions, "--protocol=TANGO")
    switch(monkeypatch, definitions, "--protocol=CA")
    assert protocols(definitions / "Magnet" / "quad.yaml") == dict.fromkeys(
        ["SETI", "READI", "READK", "COUNT"], "CA"
    )


def test_a_dry_run_writes_nothing(monkeypatch, definitions, capsys):
    switch(monkeypatch, definitions, "--protocol=TANGO", "--dry-run")
    assert (definitions / "Magnet" / "quad.yaml").read_text() == QUAD
    assert "Would switch 5 variables in 2 files" in capsys.readouterr().out


def test_files_with_nothing_to_switch_are_not_rewritten(monkeypatch, definitions):
    quad = definitions / "Magnet" / "quad.yaml"
    # Laid out as the script itself never would, so a rewrite would show
    quad.write_text(
        "name:    Q\ncontrols:\n    variables:\n        A: {protocol:   CA}\n"
    )
    before = quad.read_text()
    switch(monkeypatch, definitions, "--protocol=CA", "--device-types", "Magnet")
    assert quad.read_text() == before


def test_only_variables_served_over_one_protocol(monkeypatch, definitions):
    switch(monkeypatch, definitions, "--protocol=TANGO", "--from=CA")
    assert protocols(definitions / "Magnet" / "quad.yaml") == {
        "SETI": "TANGO",
        "READI": "TANGO",
        # Naming no protocol is being served over Channel Access
        "READK": "TANGO",
        "COUNT": "PVA",
    }


def test_only_some_device_types(monkeypatch, definitions):
    switch(monkeypatch, definitions, "--protocol=TANGO", "--device-types", "Laser")
    assert (definitions / "Magnet" / "quad.yaml").read_text() == QUAD
    assert protocols(definitions / "Laser" / "laser.yml") == {"POWER": "TANGO"}


def test_only_some_variables(monkeypatch, definitions):
    switch(monkeypatch, definitions, "--protocol=TANGO", "--variables", "SETI", "POWER")
    assert protocols(definitions / "Magnet" / "quad.yaml") == {
        "SETI": "TANGO",
        "READI": "CA",
        "READK": None,
        "COUNT": "PVA",
    }


def test_a_switched_copy_leaves_the_original_alone(monkeypatch, definitions, tmp_path):
    copy = tmp_path / "switched"
    switch(monkeypatch, definitions, "--protocol=TANGO", f"--output-directory={copy}")

    assert (definitions / "Magnet" / "quad.yaml").read_text() == QUAD
    assert protocols(copy / "Magnet" / "quad.yaml")["SETI"] == "TANGO"
    # The copy is the whole directory, not just the files that were switched
    assert (copy / "Laser" / "notes.yaml").exists()

    with pytest.raises(SystemExit, match="already exists"):
        switch(monkeypatch, definitions, "--protocol=CA", f"--output-directory={copy}")


def test_the_protocol_is_given_in_any_case(monkeypatch, definitions):
    switch(monkeypatch, definitions, "--protocol=tango")
    assert protocols(definitions / "Laser" / "laser.yml") == {"POWER": "TANGO"}


def test_the_wrong_schema_is_pointed_out(monkeypatch, definitions, capsys):
    """Definitions in one schema have nothing under the keys of another."""
    catap = str(SARABI_ROOT / "schemas" / "catap.json")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "switch_protocol.py",
            f"--directory={definitions}",
            f"--schema={catap}",
            "--protocol=TANGO",
        ],
    )
    switch_protocol.main()
    assert "Is " in capsys.readouterr().out
    assert (definitions / "Magnet" / "quad.yaml").read_text() == QUAD


def test_the_settings_name_the_directory_and_schema(monkeypatch, definitions, tmp_path):
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        yaml.safe_dump({"devices_directory": str(definitions), "schema_file": LAURA})
    )
    monkeypatch.setattr(
        sys, "argv", ["switch_protocol.py", f"--settings={settings}", "--protocol=PVA"]
    )
    assert switch_protocol.main() == 0
    assert protocols(definitions / "Laser" / "laser.yml") == {"POWER": "PVA"}
