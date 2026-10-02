"""Text from the definitions, written into the generated modules."""

import ast

import pytest

DESCRIPTION = (
    'The magnet\'s "set" current, in °A.\nPath C:\\temp\\new on a second line.\n'
)
UNITS = '°"A"'
STATES = {'Off "cold"': 0, "It's on": 1, "back\\slash": 2}


@pytest.fixture(scope="module")
def machine(module_machine):
    machine = module_machine()
    for protocol in ("CA", "PVA", "TANGO"):
        machine.device(
            f"Magnet{protocol}/quad.yaml",
            f"QUAD-{protocol}",
            {
                "SETI": {
                    "dtype": "scalar",
                    "protocol": protocol,
                    "description": DESCRIPTION,
                    "units": UNITS,
                },
                "MODE": {"dtype": "state", "protocol": protocol, "states": STATES},
            },
        )
    # Rendering fails, in formatting the modules, if any of them is not Python
    machine.render(main=False)
    return machine


def _keywords(source: str, name: str) -> list:
    return [
        ast.literal_eval(keyword.value)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == name
    ]


def test_channel_access_text_is_what_the_definition_said(machine):
    ioc_class = machine.rendered_class("MagnetCA/MagnetCABaseIOC.py")
    ioc = ioc_class(prefix="")
    assert ioc_class.SETI.pvspec.doc == DESCRIPTION
    assert ioc.pvdb["SETI"].units == UNITS
    assert list(ioc.pvdb["MODE"].enum_strings) == list(STATES)


def test_pv_access_text_is_what_the_definition_said(machine):
    ioc = machine.rendered_class("MagnetPVA/MagnetPVABasePVAIOC.py")()
    assert list(ioc.MODE.current().raw.value.choices) == list(STATES)


def test_tango_text_is_what_the_definition_said(machine):
    source = (
        machine.output_directory / "MagnetTANGO" / "MagnetTANGOBaseTangoDevice.py"
    ).read_text()
    assert DESCRIPTION in _keywords(source, "doc")
    assert _keywords(source, "unit") == [UNITS]
    assert _keywords(source, "enum_labels") == [list(STATES)]


def test_generated_modules_are_ascii(machine):
    """So that they read back the same whatever encoding a platform writes in."""
    for module in machine.rendered():
        (machine.output_directory / module).read_bytes().decode("ascii")


def test_text_is_left_readable(machine):
    """Escaped as Python would, not as HTML would: an apostrophe is no \\u0027."""
    source = (machine.output_directory / "MagnetCA" / "MagnetCABaseIOC.py").read_text()
    assert "It's on" in source
    assert "\\u0027" not in source
