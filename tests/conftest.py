"""Shared fixtures: building machines, rendering them, and running their servers.

The tests fall into three kinds, from fastest to slowest:

* those of the logic alone, which only import `core`;
* those of rendering, which render a machine with the scripts a user runs and
  inspect the classes that come out, without serving anything;
* those marked `live`, which start the rendered servers and talk to them with
  real clients. They serve on ports of their own, so can run beside a machine
  being simulated on the usual ones. Deselect them with ``-m "not live"``.
"""

import importlib.util
import itertools
import json
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# Where no name server can be reached, every lookup waits out a timeout of
# several seconds, and starting a TANGO server or client makes one for each
# network interface. The tests only ever talk to localhost, so nothing is lost
# by not waiting. Set before anything has made a lookup, which is when it is read.
os.environ.setdefault("RES_OPTIONS", "timeout:1 attempts:1")

import pytest
import yaml

SARABI_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent

# The keys each schema uses, for writing definitions in either
SCHEMAS = {
    "laura": {
        "controls": "controls",
        "variables": "variables",
        "identifier": "identifier",
        "dtype": "dtype",
    },
    "catap": {
        "controls": "controls_information",
        "variables": "pv_record_map",
        "identifier": "pv",
        "dtype": "type",
    },
}


def _clean_environment(**extra) -> dict:
    """The environment for a server: this one's, less anything EPICS or TANGO.

    A developer's shell often sets these, and the tests have to mean the same
    thing whatever it says. `extra` is then added; a None removes a variable.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("EPICS_", "TANGO_"))
    }
    # Simulation models named by the definitions are imported from here
    env["PYTHONPATH"] = os.pathsep.join(
        [str(TESTS_DIR)] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    )
    for key, value in extra.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = str(value)
    return env


def free_port() -> int:
    """A port nothing is listening on, over either TCP or UDP."""
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp:
            tcp.bind(("127.0.0.1", 0))
            port = tcp.getsockname()[1]
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                try:
                    udp.bind(("0.0.0.0", port))
                except OSError:
                    continue
                return port
    raise RuntimeError("Could not find a free port")


class Machine:
    """A directory of device definitions, and what is rendered from it."""

    def __init__(self, root: Path, schema: str = "laura", output: Path = None):
        self.root = root
        self.schema = schema
        self.words = SCHEMAS[schema]
        self.devices_directory = root / "yaml"
        self.output_directory = output if output is not None else root / "generated"
        self.settings_file = root / "settings.yaml"
        self.ignore_device_types = []
        self.devices_directory.mkdir(parents=True, exist_ok=True)

    def device(self, path: str, name: str, variables: dict) -> Path:
        """Define a device in the file `path`, relative to the devices directory.

        `variables` maps each handle to its definition, written with the
        `identifier` and `dtype` keys whatever the schema calls them. An
        identifier is made up for a variable that gives none.
        """
        translated = {}
        for handle, config in variables.items():
            config = dict(config)
            config.setdefault("identifier", f"{name}:{handle}")
            translated[handle] = {
                self.words.get(key, key): value for key, value in config.items()
            }
        yaml_file = self.devices_directory / path
        yaml_file.parent.mkdir(parents=True, exist_ok=True)
        definition = {
            "name": name,
            self.words["controls"]: {self.words["variables"]: translated},
        }
        with open(yaml_file, "w") as f:
            yaml.safe_dump(definition, f, sort_keys=False, allow_unicode=True)
        return yaml_file

    def write_settings(self) -> Path:
        settings = {
            "output_directory": str(self.output_directory),
            "templates_directory": str(SARABI_ROOT / "templates"),
            "schema_file": str(SARABI_ROOT / "schemas" / f"{self.schema}.json"),
            "devices_directory": str(self.devices_directory),
            "ignore_device_types": self.ignore_device_types,
        }
        with open(self.settings_file, "w") as f:
            yaml.safe_dump(settings, f)
        return self.settings_file

    def run_script(self, script: str, *args, env=None, check=True):
        """Run one of SARABI's scripts on this machine, as a user would."""
        result = subprocess.run(
            [sys.executable, str(SARABI_ROOT / script), *args],
            capture_output=True,
            text=True,
            # Anywhere but the checkout, so that nothing works by being beside it
            cwd=self.root,
            env=env if env is not None else _clean_environment(),
            timeout=180,
        )
        if check and result.returncode != 0:
            pytest.fail(
                f"{script} exited with {result.returncode}\n"
                f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
            )
        return result

    def render(self, main: bool = True, env=None, check=True):
        """Render the machine, returning what the rendering scripts printed."""
        settings = f"--settings={self.write_settings()}"
        result = self.run_script("render_iocs.py", settings, env=env, check=check)
        output = result.stdout + result.stderr
        if main and result.returncode == 0:
            result = self.run_script("render_main.py", settings, env=env, check=check)
            output += result.stdout + result.stderr
        self.render_returncode = result.returncode
        return output

    def module(self, path: str):
        """Import a rendered module, by its path relative to the output."""
        module_file = self.output_directory / path
        assert module_file.exists(), f"{path} was not rendered"
        name = f"rendered_{next(_module_numbers)}_{module_file.stem}"
        spec = importlib.util.spec_from_file_location(name, module_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def rendered_class(self, path: str):
        return getattr(self.module(path), Path(path).stem)

    def rendered(self) -> set:
        """The modules rendered, relative to the output, less the scripts."""
        scripts = {"__init__.py", "main.py", "tango_main.py"}
        return {
            str(p.relative_to(self.output_directory))
            for p in self.output_directory.glob("*/*.py")
            if p.name not in scripts
        }

    def served_pvs(self, runner: str = "run_all_iocs.py", env=None) -> set:
        """The PVs a rendered EPICS runner would serve, without serving them."""
        listing = self.root / f"served_{next(_module_numbers)}.json"
        result = subprocess.run(
            [
                sys.executable,
                str(TESTS_DIR / "list_epics_pvs.py"),
                str(self.output_directory / runner),
                str(listing),
            ],
            capture_output=True,
            text=True,
            cwd=self.root,
            env=env if env is not None else _clean_environment(),
            timeout=120,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        return set(json.loads(listing.read_text()))

    def tango_addresses(self, runner: str = "run_all_tango.py") -> dict:
        """Each attribute a rendered TANGO runner would serve, and its variable.

        Maps ``device/attribute`` to ``(definition name, handle)``.
        """
        result = self.run_script(str(self.output_directory / runner), "--list")
        addresses = {}
        for line in result.stdout.splitlines():
            if not line.startswith("tango://"):
                continue
            address, variable = line.split("\t")
            attribute = address.split("/", 3)[3].split("#")[0]
            addresses[attribute] = tuple(variable.split(" ", 1))
        return addresses


_module_numbers = itertools.count()


@pytest.fixture
def machine(tmp_path):
    """An empty machine in the LAURA schema."""
    return Machine(tmp_path)


@pytest.fixture(scope="module")
def module_machine(tmp_path_factory):
    """Make machines that outlive a test, for rendering once and testing often."""

    def make(schema: str = "laura", **kwargs) -> Machine:
        return Machine(tmp_path_factory.mktemp(schema), schema=schema, **kwargs)

    return make


class Server:
    """A rendered server running as a process of its own."""

    def __init__(self, process: subprocess.Popen, log_file: Path):
        self.process = process
        self.log_file = log_file

    @property
    def log(self) -> str:
        return self.log_file.read_text(errors="replace")

    def wait_for(self, text: str, timeout: float = 90) -> None:
        """Wait for the server to print `text`, failing if it exits first."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if text in self.log:
                return
            if self.process.poll() is not None:
                pytest.fail(
                    f"Server exited with {self.process.returncode} before printing "
                    f"{text!r}:\n{self.log[-3000:]}"
                )
            time.sleep(0.2)
        pytest.fail(
            f"Server did not print {text!r} in {timeout} s:\n{self.log[-3000:]}"
        )

    def stop(self, sig=signal.SIGTERM, timeout: float = 30) -> int:
        if self.process.poll() is None:
            self.process.send_signal(sig)
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        return self.process.returncode


@contextmanager
def running(command, log_file: Path, env: dict, cwd: Path):
    """Run `command` for as long as the block lasts."""
    # A server that is killed cannot clear up after itself, so what it keeps in
    # a temporary directory is kept where pytest clears up after the tests.
    env = {**env, "TMPDIR": str(log_file.parent)}
    with open(log_file, "w") as log:
        process = subprocess.Popen(
            [str(part) for part in command],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=cwd,
        )
    server = Server(process, log_file)
    try:
        yield server
    finally:
        server.stop()


class EpicsPorts:
    """Ports for one test's IOCs, and the environments that put them to use."""

    def __init__(self):
        self.ca = free_port()
        self.pva = free_port()

    def server_environment(self, **extra) -> dict:
        variables = {
            "EPICS_CA_SERVER_PORT": self.ca,
            "EPICS_PVA_SERVER_PORT": self.pva,
            "EPICS_PVA_BROADCAST_PORT": self.pva,
        }
        variables.update(extra)
        return _clean_environment(**variables)

    @property
    def pva_client(self) -> dict:
        """Configuration for a p4p client `Context`, to be used with useenv=False."""
        return {
            "EPICS_PVA_ADDR_LIST": "127.0.0.1",
            "EPICS_PVA_AUTO_ADDR_LIST": "NO",
            "EPICS_PVA_BROADCAST_PORT": str(self.pva),
        }


def wait_for_pv(read, timeout: float = 60):
    """Call `read` until it stops raising, which is when a server is serving."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return read()
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.3)


@pytest.fixture(scope="session")
def clean_environment():
    return _clean_environment
