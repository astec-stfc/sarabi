"""Which devices a machine is made of, and which of their variables are served."""

import os
import shutil

import pytest

from conftest import SARABI_ROOT, Machine


def variables(**protocols):
    return {h: {"dtype": "scalar", "protocol": p} for h, p in protocols.items()}


def build(machine: Machine) -> Machine:
    """A machine laid out in each of the ways that once lost PVs."""
    # One device type, in two branches of the tree
    machine.device("S01/Magnet/q1.yaml", "Q1", variables(SETI="CA", READI="CA"))
    machine.device(
        "S02/Magnet/q2.yaml", "Q2", variables(SETI="CA", READI="CA", EXTRA="CA")
    )
    # One device type whose name is the start of another's
    machine.device("BPMX/bx.yaml", "BX1", variables(X="CA"))
    machine.device("BPM/b1.yaml", "B1", variables(X="CA", Y="CA"))
    # A protocol used only by variables that only some devices have
    machine.device("Laser/l1.yaml", "L1", variables(POWER="CA"))
    machine.device("Laser/l2.yaml", "L2", variables(POWER="CA", TRIG="PVA"))
    machine.device("Cam/c1.yaml", "C1", variables(GAIN="PVA"))
    machine.device("Cam/c2.yaml", "C2", variables(GAIN="PVA", EXPO="CA"))
    # Devices of one type with no variable in common
    machine.device("Valve/v1.yaml", "V1", variables(OPEN="CA"))
    machine.device("Valve/v2.yaml", "V2", variables(CLOSE="CA"))
    # The same over TANGO
    machine.device("S01/Corrector/c1.yaml", "K1", variables(SETI="TANGO"))
    machine.device(
        "S02/Corrector/c2.yaml", "K2", variables(SETI="TANGO", EXTRA="TANGO")
    )
    return machine


EPICS_PVS = {
    "VM-Q1:SETI", "VM-Q1:READI", "VM-Q2:SETI", "VM-Q2:READI", "VM-Q2:EXTRA",
    "VM-BX1:X", "VM-B1:X", "VM-B1:Y",
    "VM-L1:POWER", "VM-L2:POWER", "VM-L2:TRIG",
    "VM-C1:GAIN", "VM-C2:GAIN", "VM-C2:EXPO",
    "VM-V1:OPEN", "VM-V2:CLOSE",
}  # fmt: skip


@pytest.fixture(scope="module")
def machine(module_machine):
    machine = build(module_machine())
    machine.render()
    return machine


def test_every_pv_is_served(machine):
    assert machine.served_pvs() == EPICS_PVS


def test_every_tango_attribute_is_served(machine):
    assert machine.tango_addresses() == {
        "VM/Corrector/K1/SETI": ("K1", "SETI"),
        "VM/Corrector/K2/SETI": ("K2", "SETI"),
        "VM/Corrector/K2/EXTRA": ("K2", "EXTRA"),
    }


def test_the_output_directory_can_be_inside_the_devices_directory(tmp_path):
    """Its folders are named after the device types, and once hid them all."""
    machine = Machine(tmp_path)
    machine.output_directory = machine.devices_directory / "generated"
    build(machine).render()
    assert machine.served_pvs() == EPICS_PVS
    assert len(machine.tango_addresses()) == 3


def test_devices_with_no_variable_in_common_are_rendered(machine):
    """Which once stopped rendering altogether."""
    ioc = machine.rendered_class("Valve/ValveBaseIOC.py")(prefix="")
    assert set(ioc.pvdb) == {"OPEN", "CLOSE"}


def test_a_protocol_only_some_devices_use_has_an_ioc(machine):
    """An IOC was only rendered for a protocol every device of the type used."""
    assert {"Laser/LaserBasePVAIOC.py", "Cam/CamBaseIOC.py"} <= machine.rendered()
    # and not for one that none of them do
    assert "BPM/BPMBasePVAIOC.py" not in machine.rendered()
    assert "Valve/ValveBaseTangoDevice.py" not in machine.rendered()


def test_folders_of_the_same_name_render_one_class_for_them_all(machine):
    """The second once overwrote the first, leaving out what only it defined."""
    ioc = machine.rendered_class("Magnet/MagnetBaseIOC.py")(prefix="")
    assert set(ioc.pvdb) == {"SETI", "READI", "EXTRA"}
    corrector = machine.rendered_class("Corrector/CorrectorBaseTangoDevice.py")
    assert set(corrector.INITIAL_VALUES) == {"SETI", "EXTRA"}
    assert set(corrector.OPTIONAL_ATTRIBUTES) == {"EXTRA"}


def test_every_pv_can_start_the_simulation(machine):
    """Only those every device has once could, and a device may have none of them."""
    for module, handles in (
        ("Valve/ValveBaseIOC.py", ("OPEN", "CLOSE")),
        ("Magnet/MagnetBaseIOC.py", ("SETI", "EXTRA")),
    ):
        ioc_class = machine.rendered_class(module)
        for handle in handles:
            assert getattr(ioc_class, handle).pvspec.startup is not None, handle


@pytest.mark.parametrize(
    "runner, served",
    [
        # Both branches
        ("Magnet/main.py", {"VM-Q1:SETI", "VM-Q1:READI", "VM-Q2:SETI", "VM-Q2:READI", "VM-Q2:EXTRA"}),
        # The folder was once chosen for having the type's name somewhere in its path
        ("BPM/main.py", {"VM-B1:X", "VM-B1:Y"}),
        ("BPMX/main.py", {"VM-BX1:X"}),
        # Both protocols
        ("Cam/main.py", {"VM-C1:GAIN", "VM-C2:GAIN", "VM-C2:EXPO"}),
    ],
)  # fmt: skip
def test_the_runner_of_one_device_type_serves_that_type(machine, runner, served):
    assert machine.served_pvs(runner) == served


def test_the_tango_runner_of_one_device_type(machine):
    assert len(machine.tango_addresses("Corrector/tango_main.py")) == 3


def test_definitions_are_merged_the_first_taking_precedence(tmp_path):
    """The last once won outright, so a sparse definition could strip the rest."""
    machine = Machine(tmp_path)
    first = {
        "MODE": {"dtype": "state", "states": {"OUT": 0, "IN": 1}},
        "POS": {"dtype": "scalar", "units": "mm", "description": "first"},
    }
    second = {"MODE": {}, "POS": {"description": "second", "units": "m"}}
    for protocol in ("CA", "TANGO"):
        for name, definition in (("A", first), ("B", second)):
            machine.device(
                f"Screen{protocol}/{name}.yaml",
                name,
                {
                    h: {**config, "protocol": protocol}
                    for h, config in definition.items()
                },
            )
    machine.render(main=False)

    ioc_class = machine.rendered_class("ScreenCA/ScreenCABaseIOC.py")
    ioc = ioc_class(prefix="")
    assert ioc.pvdb["MODE"].data_type.name == "ENUM"
    assert list(ioc.pvdb["MODE"].enum_strings) == ["OUT", "IN"]
    assert ioc.pvdb["POS"].units == "mm"
    assert ioc_class.POS.pvspec.doc == "first"
    device_class = machine.rendered_class("ScreenTANGO/ScreenTANGOBaseTangoDevice.py")
    assert device_class.MODE.attr_type.name == "DevEnum"


def test_ignored_device_types_are_not_rendered(tmp_path):
    machine = Machine(tmp_path)
    machine.ignore_device_types = ["PILaser"]
    machine.device("Magnet/q1.yaml", "Q1", variables(SETI="CA"))
    machine.device("PILaser/l1.yaml", "L1", variables(POWER="CA", ENERGY="TANGO"))
    machine.render()
    assert machine.rendered() == {"Magnet/MagnetBaseIOC.py"}
    assert machine.served_pvs() == {"VM-Q1:SETI"}


def test_definitions_removed_since_rendering_do_not_stop_it(tmp_path):
    machine = Machine(tmp_path)
    machine.device("Magnet/q1.yaml", "Q1", variables(SETI="CA"))
    machine.device("Valve/v1.yaml", "V1", variables(OPEN="CA"))
    machine.render()
    shutil.rmtree(machine.devices_directory / "Valve")

    output = machine.render()

    assert "Found no definitions for Valve" in output
    assert machine.served_pvs() == {"VM-Q1:SETI"}


def test_epics_needs_no_tango(tmp_path, clean_environment):
    """A machine with TANGO variables is rendered, and its IOCs run, without PyTango."""
    machine = Machine(tmp_path)
    machine.device("Magnet/q1.yaml", "Q1", variables(SETI="CA", READI="TANGO"))
    no_tango = tmp_path / "no_tango"
    no_tango.mkdir()
    (no_tango / "tango.py").write_text(
        'raise ImportError("PyTango is not installed")\n'
    )
    environment = clean_environment()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(no_tango), environment["PYTHONPATH"]]
    )

    machine.render(env=environment)

    assert "Magnet/MagnetBaseTangoDevice.py" in machine.rendered()
    assert machine.served_pvs(env=environment) == {"VM-Q1:SETI"}
    # Its TANGO class is left to the TANGO runner
    for runner in ("run_all_iocs.py", "Magnet/main.py"):
        assert "TangoDevice" not in (machine.output_directory / runner).read_text()


def test_another_package_called_core_is_not_mistaken_for_sarabi(
    tmp_path, clean_environment
):
    """SARABI's own is as plain a name as there is, and several on PyPI share it.

    The generated modules once looked for it last, so found any other first.
    """
    machine = Machine(tmp_path)
    machine.device("Magnet/q1.yaml", "Q1", variables(SETI="CA", READI="TANGO"))
    machine.render()
    elsewhere = tmp_path / "site-packages"
    (elsewhere / "core").mkdir(parents=True)
    (elsewhere / "core" / "__init__.py").write_text("# nothing to do with SARABI\n")
    environment = clean_environment()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(elsewhere), environment["PYTHONPATH"]]
    )

    assert machine.served_pvs(env=environment) == {"VM-Q1:SETI"}
    assert machine.served_pvs("Magnet/main.py", env=environment) == {"VM-Q1:SETI"}
    for runner in ("run_all_tango.py", "Magnet/tango_main.py"):
        result = machine.run_script(
            str(machine.output_directory / runner), "--list", env=environment
        )
        assert "VM/Magnet/Q1/READI" in result.stdout


def test_tango_templates_are_found_beside_customised_ones(tmp_path):
    """A templates directory copied before there were any still renders TANGO."""
    machine = Machine(tmp_path)
    machine.device("Magnet/q1.yaml", "Q1", variables(SETI="TANGO"))
    templates = tmp_path / "templates"
    templates.mkdir()
    for template in (SARABI_ROOT / "templates").glob("*.j2"):
        if not template.name.startswith("tango_"):
            shutil.copy(template, templates)
    settings = machine.write_settings()
    settings.write_text(
        settings.read_text().replace(str(SARABI_ROOT / "templates"), str(templates))
    )
    for script in ("render_iocs.py", "render_main.py"):
        machine.run_script(script, f"--settings={settings}")
    assert machine.tango_addresses() == {"VM/Magnet/Q1/SETI": ("Q1", "SETI")}
