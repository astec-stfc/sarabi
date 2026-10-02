"""The data type a variable is rendered as, over each protocol and in each schema."""

import ast

import pytest
from tango import AttrDataFormat, CmdArgType

from conftest import SCHEMAS

STATES = {"OUT": 0, "IN": 1, "MOVING": 2}

# Every data type, and the ways a definition can fail to give one
VARIABLES = {
    "POS": {"dtype": "scalar"},
    "SIGMA": {"dtype": "statistical"},
    "GAIN": {"dtype": "float"},
    "COUNT": {"dtype": "int"},
    "MODE": {"dtype": "state", "states": STATES},
    "ENABLED": {"dtype": "binary"},
    "TRACE": {"dtype": "waveform"},
    "LABEL": {"dtype": "string"},
    "UNTYPED": {},
    "ODD": {"dtype": "quaternion"},
    "BARE": {"dtype": "state"},
    "SHOUTED": {"dtype": "INT"},
}

PROTOCOLS = ("CA", "PVA", "TANGO")
CLASSES = {
    "CA": "ScreenCA/ScreenCABaseIOC.py",
    "PVA": "ScreenPVA/ScreenPVABasePVAIOC.py",
    "TANGO": "ScreenTANGO/ScreenTANGOBaseTangoDevice.py",
}


@pytest.fixture(scope="module")
def machines(module_machine):
    """The same device over each protocol, defined in each schema."""
    rendered = {}
    for schema in SCHEMAS:
        machine = module_machine(schema)
        for protocol in PROTOCOLS:
            variables = {
                handle: {**config, "protocol": protocol}
                for handle, config in VARIABLES.items()
            }
            machine.device(f"Screen{protocol}/scr.yaml", f"SCR-{protocol}", variables)
        machine.output = machine.render(main=False)
        rendered[schema] = machine
    return rendered


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_the_schema_names_the_key_the_data_type_is_read_from(machines, protocol):
    """Each template once read the key of one schema, and no data types in the other.

    Channel Access read CATAP's `type`, leaving every LAURA variable a float,
    and PV Access read LAURA's `dtype`, leaving out every CATAP variable.
    """
    laura = (machines["laura"].output_directory / CLASSES[protocol]).read_text()
    catap = (machines["catap"].output_directory / CLASSES[protocol]).read_text()
    assert laura == catap


@pytest.mark.parametrize("schema", SCHEMAS)
def test_channel_access_data_types(machines, schema):
    ioc = machines[schema].rendered_class(CLASSES["CA"])(prefix="")
    types = {handle: ioc.pvdb[handle].data_type.name for handle in VARIABLES}
    assert types == {
        "POS": "FLOAT",
        "SIGMA": "FLOAT",
        "GAIN": "FLOAT",
        "COUNT": "LONG",
        "MODE": "ENUM",
        # Channel Access has no boolean: it is an enumeration of Off and On
        "ENABLED": "ENUM",
        "TRACE": "FLOAT",
        "LABEL": "STRING",
        "UNTYPED": "FLOAT",
        "ODD": "FLOAT",
        "BARE": "LONG",
        "SHOUTED": "LONG",
    }
    assert list(ioc.pvdb["MODE"].enum_strings) == ["OUT", "IN", "MOVING"]
    assert list(ioc.pvdb["ENABLED"].enum_strings) == ["Off", "On"]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_a_channel_access_waveform_can_hold_one(machines, schema):
    """With no length given it held a single point, and refused any more."""
    ioc = machines[schema].rendered_class(CLASSES["CA"])(prefix="")
    assert ioc.pvdb["TRACE"].max_length == 65536
    assert ioc.pvdb["POS"].max_length == 1


@pytest.mark.parametrize("schema", SCHEMAS)
def test_pv_access_data_types(machines, schema):
    ioc = machines[schema].rendered_class(CLASSES["PVA"])()
    types = {}
    for handle in VARIABLES:
        raw = getattr(ioc, handle).current().raw
        is_enum = raw.getID().startswith("epics:nt/NTEnum")
        types[handle] = "NTEnum" if is_enum else raw.type()["value"]
    assert types == {
        "POS": "d",
        "SIGMA": "d",
        "GAIN": "d",
        # Once a double
        "COUNT": "l",
        "MODE": "NTEnum",
        # Once a signed byte, "b", which is not p4p's boolean
        "ENABLED": "?",
        "TRACE": "ad",
        "LABEL": "s",
        "UNTYPED": "d",
        "ODD": "d",
        "BARE": "l",
        "SHOUTED": "l",
    }
    assert list(ioc.MODE.current().raw.value.choices) == ["OUT", "IN", "MOVING"]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_tango_data_types(machines, schema):
    device_class = machines[schema].rendered_class(CLASSES["TANGO"])
    types = {
        handle: getattr(device_class, handle).attr_type.name for handle in VARIABLES
    }
    assert types == {
        "POS": "DevDouble",
        "SIGMA": "DevDouble",
        "GAIN": "DevDouble",
        "COUNT": "DevLong64",
        "MODE": "DevEnum",
        "ENABLED": "DevBoolean",
        "TRACE": "DevDouble",
        "LABEL": "DevString",
        "UNTYPED": "DevDouble",
        "ODD": "DevDouble",
        "BARE": "DevLong64",
        "SHOUTED": "DevLong64",
    }
    assert device_class.TRACE.attr_format == AttrDataFormat.SPECTRUM
    assert device_class.TRACE.dim_x == 65536
    assert device_class.POS.attr_format == AttrDataFormat.SCALAR
    assert device_class.MODE.attr_type == CmdArgType.DevEnum


def test_tango_enumerations_are_told_their_states(machines):
    source = (machines["laura"].output_directory / CLASSES["TANGO"]).read_text()
    labels = [
        ast.literal_eval(keyword.value)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "enum_labels"
    ]
    assert labels == [["OUT", "IN", "MOVING"]]


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_initial_values_suit_their_data_types(machines, protocol):
    machine = machines["laura"]
    if protocol == "CA":
        ioc = machine.rendered_class(CLASSES["CA"])(prefix="")
        values = {handle: ioc.pvdb[handle].value for handle in VARIABLES}
        values["TRACE"] = list(values["TRACE"])
    elif protocol == "PVA":
        ioc = machine.rendered_class(CLASSES["PVA"])()
        values = {h: getattr(ioc, h).current() for h in VARIABLES if h != "MODE"}
        values["TRACE"] = list(values["TRACE"])
        values["MODE"] = ioc.MODE.current().raw.value.index
    else:
        values = dict(machine.rendered_class(CLASSES["TANGO"]).INITIAL_VALUES)
    assert values["POS"] == 0.0
    assert values["COUNT"] == 0
    assert values["TRACE"] == [0.0]
    assert values["LABEL"] == "undefined"
    assert values["MODE"] in (0, "OUT")
    assert not values["ENABLED"] or values["ENABLED"] == "Off"


@pytest.mark.parametrize("schema", SCHEMAS)
def test_rendering_says_what_it_made_of_a_data_type_it_could_not_use(machines, schema):
    output = machines[schema].output
    word = SCHEMAS[schema]["dtype"]
    for protocol in PROTOCOLS:
        assert (
            f"Unknown {word} 'quaternion' for Screen{protocol} variable ODD, "
            "rendering it as a scalar." in output
        )
        assert (
            f"No states are defined for Screen{protocol} variable BARE, "
            "rendering it as an int." in output
        )
    # Nothing is said of a variable that simply gives no data type
    assert "UNTYPED" not in output


def test_every_protocol_can_serve_every_data_type():
    """A data type is added by giving it an entry in all three maps."""
    import render_iocs

    assert (
        set(render_iocs.CA_DTYPE_MAP)
        == set(render_iocs.PVA_DTYPE_MAP)
        == set(render_iocs.TANGO_DTYPE_MAP)
        == render_iocs.DTYPES
    )


def test_units_are_given_only_to_what_channel_access_takes_them_for(module_machine):
    """It refuses them for anything but a number, which stopped the whole IOC."""
    machine = module_machine()
    variables = {
        handle: {**config, "units": "mm", "protocol": "CA"}
        for handle, config in VARIABLES.items()
    }
    machine.device("Screen/scr.yaml", "SCR", variables)
    machine.render(main=False)

    ioc = machine.rendered_class("Screen/ScreenBaseIOC.py")(prefix="")

    with_units = {h for h in VARIABLES if getattr(ioc.pvdb[h], "units", "") == "mm"}
    assert with_units == {
        "POS", "SIGMA", "GAIN", "COUNT", "TRACE", "UNTYPED", "ODD", "BARE", "SHOUTED"
    }  # fmt: skip
