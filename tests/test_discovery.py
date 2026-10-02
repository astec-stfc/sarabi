"""Walking a directory of device definitions."""

from core.discovery import find_device_files, iter_devices, load_variables
from core.translator import SchemaTranslator

from conftest import SARABI_ROOT


def _names(device_files):
    return {
        device_type: sorted(path.rsplit("/", 1)[-1] for path in paths)
        for device_type, paths in device_files.items()
    }


def test_a_file_belongs_to_the_type_of_the_folder_it_is_in(machine):
    machine.device("Magnet/q1.yaml", "Q1", {"SETI": {}})
    machine.device("Diagnostics/BPM/b1.yaml", "B1", {"X": {}})
    machine.device("Diagnostics/d1.yaml", "D1", {"X": {}})

    found = find_device_files(machine.devices_directory)

    # b1 is a BPM alone, though it is also somewhere under Diagnostics
    assert _names(found) == {
        "BPM": ["b1.yaml"],
        "Diagnostics": ["d1.yaml"],
        "Magnet": ["q1.yaml"],
    }


def test_yml_files_are_definitions_too(machine):
    machine.device("BPM/b1.yml", "B1", {"X": {}})
    machine.device("BPM/b2.YAML", "B2", {"X": {}})
    assert _names(find_device_files(machine.devices_directory)) == {
        "BPM": ["b1.yml", "b2.YAML"]
    }


def test_folders_of_the_same_name_are_one_device_type(machine):
    machine.device("S01/Magnet/q1.yaml", "Q1", {"SETI": {}})
    machine.device("S02/Magnet/q2.yaml", "Q2", {"SETI": {}})
    assert _names(find_device_files(machine.devices_directory)) == {
        "Magnet": ["q1.yaml", "q2.yaml"]
    }


def test_folders_holding_no_definitions_are_passed_over(machine):
    """Such as the output directory, which may be inside the devices directory."""
    machine.device("Magnet/q1.yaml", "Q1", {"SETI": {}})
    generated = machine.devices_directory / "generated" / "Magnet"
    generated.mkdir(parents=True)
    (generated / "MagnetBaseIOC.py").write_text("")

    found = find_device_files(machine.devices_directory)

    assert list(found) == ["Magnet"]
    assert "generated" not in found["Magnet"][0]


def test_files_in_no_device_type_folder_are_skipped(machine):
    machine.device("loose.yaml", "LOOSE", {"X": {}})
    machine.device("Magnet/q1.yaml", "Q1", {"SETI": {}})
    assert list(find_device_files(machine.devices_directory)) == ["Magnet"]


def test_ignored_device_types(machine):
    machine.device("Magnet/q1.yaml", "Q1", {"SETI": {}})
    machine.device("PILaser/l1.yaml", "L1", {"POWER": {}})
    found = find_device_files(machine.devices_directory, ["PILaser"])
    assert list(found) == ["Magnet"]


def test_a_device_is_named_by_its_file_when_it_gives_no_name(machine):
    translator = SchemaTranslator(SARABI_ROOT / "schemas" / "laura.json")
    yaml_file = machine.device("Magnet/QUAD-07.yaml", "", {"SETI": {}})
    name, variables = load_variables(str(yaml_file), translator)
    assert name == "QUAD-07"
    assert list(variables) == ["SETI"]


def test_files_that_are_not_definitions_define_nothing(machine):
    translator = SchemaTranslator(SARABI_ROOT / "schemas" / "laura.json")
    folder = machine.devices_directory / "Magnet"
    folder.mkdir()
    (folder / "list.yaml").write_text("- just\n- a list\n")
    (folder / "empty.yaml").write_text("")
    (folder / "other.yaml").write_text("name: X\ncontrols: nothing here\n")
    machine.device("Magnet/q1.yaml", "Q1", {"SETI": {}})

    files = find_device_files(machine.devices_directory)["Magnet"]

    assert [name for name, _ in iter_devices(files, translator)] == ["Q1"]


def test_variables_are_found_under_the_keys_the_schema_names(tmp_path):
    from conftest import Machine

    catap = Machine(tmp_path, schema="catap")
    yaml_file = catap.device("Magnet/q1.yaml", "Q1", {"SETI": {}})
    translator = SchemaTranslator(SARABI_ROOT / "schemas" / "catap.json")
    _, variables = load_variables(str(yaml_file), translator)
    assert variables == {"SETI": {"pv": "Q1:SETI"}}
