"""Layout selection: restricting a render to one of a facility's beam paths.

A facility is one device tree with one or more layouts over it. JFEL has a
single layout and must be unaffected by all of this; LCLS has seventeen and
only a quarter of its elements are on any one of them.
"""

import os
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.layout import (  # noqa: E402
    ALLOWED_DEVICES_FILENAME,
    MissingLayoutFiles,
    UnknownLayout,
    find_lattice_file,
    layout_device_names,
    load_allowed_devices,
    resolve_allowed_devices,
    write_allowed_devices,
)
from core.settings import Settings  # noqa: E402


LAYOUTS = {
    "default_layout": "CU_HXR",
    "layouts": {
        "CU_HXR": ["GUN", "BSYH"],
        "CU_SXR": ["GUN", "BSYS"],
        "BROKEN": ["GUN", "NO_SUCH_SECTION"],
    },
}

# Both shapes the lattice uses: a mapping with an `elements` key, and the
# bare list.
SECTIONS = {
    "sections": {
        "GUN": {"elements": ["RFGUN", "SOL1"], "reference_energy": 6e6},
        "BSYH": ["QSXH17", "XCSX17"],
        "BSYS": ["QSXH20"],
    }
}


def _write_lattice(root):
    """A facility root holding layouts/sections beside a `YAML/` device tree."""
    devices = os.path.join(root, "YAML")
    os.makedirs(devices, exist_ok=True)
    with open(os.path.join(root, "layouts.yaml"), "w") as fh:
        yaml.safe_dump(LAYOUTS, fh)
    with open(os.path.join(root, "sections.yaml"), "w") as fh:
        yaml.safe_dump(SECTIONS, fh)
    return devices


class TestLayoutDeviceNames(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.devices = _write_lattice(self.tmp.name)
        self.layouts = os.path.join(self.tmp.name, "layouts.yaml")
        self.sections = os.path.join(self.tmp.name, "sections.yaml")

    def tearDown(self):
        self.tmp.cleanup()

    def test_collects_elements_from_both_section_shapes(self):
        self.assertEqual(
            layout_device_names(self.layouts, self.sections, "CU_HXR"),
            {"RFGUN", "SOL1", "QSXH17", "XCSX17"},
        )

    def test_layouts_differ(self):
        self.assertEqual(
            layout_device_names(self.layouts, self.sections, "CU_SXR"),
            {"RFGUN", "SOL1", "QSXH20"},
        )

    def test_unknown_layout_lists_the_real_ones(self):
        with self.assertRaises(UnknownLayout) as caught:
            layout_device_names(self.layouts, self.sections, "CU_NOPE")
        self.assertIn("CU_HXR", str(caught.exception))
        self.assertIn("CU_SXR", str(caught.exception))

    def test_layout_naming_an_undefined_section_is_an_error(self):
        # Silently dropping it would give an IOC missing devices with no
        # indication of why.
        with self.assertRaises(UnknownLayout) as caught:
            layout_device_names(self.layouts, self.sections, "BROKEN")
        self.assertIn("NO_SUCH_SECTION", str(caught.exception))


class TestFindLatticeFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.devices = _write_lattice(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_found_in_parent_of_the_device_tree(self):
        self.assertEqual(
            find_lattice_file(self.devices, "layouts.yaml"),
            os.path.join(self.tmp.name, "layouts.yaml"),
        )

    def test_found_inside_the_device_tree_too(self):
        flat = os.path.join(self.devices, "layouts.yaml")
        with open(flat, "w") as fh:
            yaml.safe_dump(LAYOUTS, fh)
        self.assertEqual(find_lattice_file(self.devices, "layouts.yaml"), flat)

    def test_absent_returns_none(self):
        self.assertIsNone(find_lattice_file(self.devices, "nope.yaml"))


class TestResolveAllowedDevices(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.devices = _write_lattice(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_layout_means_no_filtering(self):
        # None, not the empty set: a single-layout facility should not have to
        # enumerate its devices to be rendered in full.
        self.assertIsNone(resolve_allowed_devices(self.devices, None))
        self.assertIsNone(resolve_allowed_devices(self.devices, ""))

    def test_layout_resolves_against_the_lattice_beside_the_devices(self):
        self.assertEqual(
            resolve_allowed_devices(self.devices, "CU_HXR"),
            {"RFGUN", "SOL1", "QSXH17", "XCSX17"},
        )

    def test_explicit_paths_win(self):
        other = os.path.join(self.tmp.name, "other_sections.yaml")
        with open(other, "w") as fh:
            yaml.safe_dump({"sections": {"GUN": ["ONLY_ONE"], "BSYH": []}}, fh)
        self.assertEqual(
            resolve_allowed_devices(self.devices, "CU_HXR", sections_file=other),
            {"ONLY_ONE"},
        )

    def test_missing_lattice_files_is_an_error_naming_them(self):
        os.remove(os.path.join(self.tmp.name, "sections.yaml"))
        with self.assertRaises(MissingLayoutFiles) as caught:
            resolve_allowed_devices(self.devices, "CU_HXR")
        self.assertIn("sections.yaml", str(caught.exception))


class TestAllowedDevicesFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip(self):
        write_allowed_devices(self.tmp.name, {"B", "A"})
        self.assertEqual(load_allowed_devices(self.tmp.name), {"A", "B"})

    def test_absent_file_means_no_filter(self):
        self.assertIsNone(load_allowed_devices(self.tmp.name))

    def test_writing_none_clears_a_stale_filter(self):
        write_allowed_devices(self.tmp.name, {"A"})
        write_allowed_devices(self.tmp.name, None)
        self.assertFalse(
            os.path.exists(os.path.join(self.tmp.name, ALLOWED_DEVICES_FILENAME))
        )
        self.assertIsNone(load_allowed_devices(self.tmp.name))


class TestSettingsLayout(unittest.TestCase):
    """`Settings` is constructed straight from the settings YAML, so the new
    keys have to be optional and an empty string has to read as unset."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.devices = _write_lattice(self.tmp.name)
        # one device folder, so _validate_devices is satisfied
        os.makedirs(os.path.join(self.devices, "Quadrupole"), exist_ok=True)
        with open(os.path.join(self.devices, "Quadrupole", "Q1.yaml"), "w") as fh:
            yaml.safe_dump({"name": "Q1"}, fh)
        self.repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._layout_env = os.environ.pop("LAYOUT", None)

    def tearDown(self):
        if self._layout_env is not None:
            os.environ["LAYOUT"] = self._layout_env
        else:
            os.environ.pop("LAYOUT", None)
        self.tmp.cleanup()

    def _settings(self, **kwargs):
        return Settings(
            output_directory=os.path.join(self.tmp.name, "out"),
            templates_directory=os.path.join(self.repo, "templates"),
            schema_file=os.path.join(self.repo, "schemas", "laura.json"),
            devices_directory=self.devices,
            ignore_device_types=[],
            **kwargs,
        )

    def test_absent_layout_is_none(self):
        self.assertIsNone(self._settings().layout)
        self.assertIsNone(self._settings().allowed_devices)

    def test_empty_string_reads_as_unset(self):
        # How a sed-templated deployment spells "not set".
        self.assertIsNone(self._settings(layout="").layout)

    def test_layout_from_settings(self):
        settings = self._settings(layout="CU_HXR")
        self.assertEqual(settings.layout, "CU_HXR")
        self.assertEqual(
            settings.allowed_devices, {"RFGUN", "SOL1", "QSXH17", "XCSX17"}
        )

    def test_layout_from_environment(self):
        os.environ["LAYOUT"] = "CU_SXR"
        self.assertEqual(self._settings().layout, "CU_SXR")

    def test_settings_value_beats_the_environment(self):
        os.environ["LAYOUT"] = "CU_SXR"
        self.assertEqual(self._settings(layout="CU_HXR").layout, "CU_HXR")


if __name__ == "__main__":
    unittest.main()
