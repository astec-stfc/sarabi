"""Write, as JSON, the PVs a rendered EPICS runner would serve.

Usage: list_epics_pvs.py RUNNER OUTPUT_FILE

Written to a file rather than printed, as what is printed is not this script's
alone: a library the runner imports may print too, as caproto's colouring of
its log does when told it is running in an IDE.

Builds the IOCs as the runner does, without starting the servers, so that what
a machine serves can be tested without a network. Run as a script, because a
runner imports its device types as though they were top-level packages, which
a test process rendering several machines could only do for one of them.
"""

import json
import os
import runpy
import sys
import warnings

runner, output_file = sys.argv[1:3]
# As running the runner itself would
sys.path.insert(0, os.path.dirname(runner))
warnings.simplefilter("ignore")

namespace = runpy.run_path(runner, run_name="listing")
managers = namespace["_construct_iocs"]()
if not isinstance(managers, list):
    # The runner of one device type makes a single manager
    managers = [managers]
served = set()
for manager in managers:
    served |= set(manager.ca_iocs) | set(manager.pva_iocs)
with open(output_file, "w") as f:
    json.dump(sorted(served), f)
