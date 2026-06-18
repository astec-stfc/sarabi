import importlib.util
import os
import subprocess
import sys


def run_black(directory: str):
    # Find the Black package location
    spec = importlib.util.find_spec("black")
    if spec is None or not spec.submodule_search_locations:
        raise ImportError("Black is not installed or cannot be found.")
    black_dir = spec.submodule_search_locations[0]

    # Get the path to the black executable script
    # This works for most environments (pip, venv, etc.)
    black_exe = os.path.join(os.path.dirname(sys.executable), "black")

    # If that doesn't exist, fallback to running as a module
    if not os.path.exists(black_exe):
        subprocess.run([sys.executable, "-m", "black", "-vvv", directory], check=True)
    else:
        subprocess.run([black_exe, directory], check=True)

    print("Formatted with Black.")
