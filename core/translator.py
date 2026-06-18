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
