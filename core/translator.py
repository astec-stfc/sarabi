import json


class SchemaTranslator:

    def __init__(self, schema_file):
        self.schema = {
            "controls_information": "controls_information",
            "signal_information": "signal_information",
            "description": "description",
            "identifier": "identifier",
            "dtype": "dtype",
            "protocol": "protocol",
        }
        with open(schema_file, "r") as f:
            self.schema = dict(json.load(f)).get("translations", self.schema)

    @property
    def controls_information_word(self) -> str:
        return self.schema.get(
            "controls_information",
            "controls_information",
        )

    @property
    def signal_information_word(self) -> str:
        return self.schema.get(
            "signal_information",
            "signal_information",
        )

    @property
    def description_word(self) -> str:
        return self.schema.get(
            "description",
            "description",
        )

    @property
    def identifier_word(self) -> str:
        return self.schema.get(
            "identifier",
            "identifier",
        )

    @property
    def dtype_word(self) -> str:
        return self.schema.get(
            "dtype",
            "dtype",
        )

    @property
    def protocol_word(self) -> str:
        return self.schema.get(
            "protocol",
            "protocol",
        )

    # The following describe simulated behaviour, and are optional: schemas
    # written before they existed fall back to the default wording.

    @property
    def readback_word(self) -> str:
        return self.schema.get(
            "readback",
            "readback",
        )

    @property
    def setpoint_word(self) -> str:
        return self.schema.get(
            "setpoint",
            "setpoint",
        )

    @property
    def dynamics_word(self) -> str:
        return self.schema.get(
            "dynamics",
            "dynamics",
        )

    @property
    def update_word(self) -> str:
        return self.schema.get(
            "update",
            "update",
        )

    @property
    def dynamics_model_key(self) -> str:
        """Key naming the response model within a `dynamics` definition."""
        return self.schema.get(
            "dynamics_model",
            "model",
        )

    @property
    def update_function_key(self) -> str:
        """Key naming the signal within an `update` definition."""
        return self.schema.get(
            "update_function",
            "function",
        )
