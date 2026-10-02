import os
import shutil

import pytest

from core.settings import Settings
from tests.conftest import LAURA_SCHEMA, TEMPLATES


def test_settings_exposes_tango_template(devices_dir, tmp_path):
    settings = Settings(str(tmp_path / "out"), TEMPLATES, LAURA_SCHEMA, devices_dir, [])
    assert settings.tango_base_template_file == os.path.join(TEMPLATES, "tango_base_template.j2")
    assert os.path.exists(settings.tango_base_template_file)


def test_settings_requires_tango_template(devices_dir, tmp_path):
    templates = tmp_path / "templates"
    shutil.copytree(TEMPLATES, templates)
    os.remove(templates / "tango_base_template.j2")
    with pytest.raises(FileNotFoundError, match="tango base template"):
        Settings(str(tmp_path / "out"), str(templates), LAURA_SCHEMA, devices_dir, [])
