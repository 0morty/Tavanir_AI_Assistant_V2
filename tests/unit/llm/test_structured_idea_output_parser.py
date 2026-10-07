"""The model's five plain-text blocks must be unambiguous before extraction."""

import unittest

from src.application.exceptions import LLMOutputParseError, LLMOutputSchemaError
from src.infrastructure.services.llm.structured_idea_output_parser import (
    StructuredIdeaOutputParser,
)


VALID_OUTPUT = (
    "{title}\nOccupancy-controlled lighting\n***\n"
    "{current problem}\nLights remain on in empty rooms.\n***\n"
    "{solutions}\nInstall occupancy sensors.\n***\n"
    "{advantage}\nPotential reduction in energy use.\n***\n"
    "{disadvantage}\nInstallation and maintenance costs.\n"
)


class StructuredIdeaOutputParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = StructuredIdeaOutputParser()

    def test_extracts_required_fields_and_maps_plural_solutions(self):
        result = self.parser.parse(VALID_OUTPUT)
        self.assertEqual(result.title, "Occupancy-controlled lighting")
        self.assertEqual(result.current_problem, "Lights remain on in empty rooms.")
        self.assertEqual(result.solution, "Install occupancy sensors.")
        self.assertEqual(result.advantage, "Potential reduction in energy use.")
        self.assertEqual(result.disadvantage, "Installation and maintenance costs.")

    def test_accepts_multiline_plain_text_and_windows_line_endings(self):
        raw = VALID_OUTPUT.replace(
            "Install occupancy sensors.", "Install sensors.\nConfigure their sensitivity."
        ).replace("\n", "\r\n")
        self.assertEqual(
            self.parser.parse(raw).solution,
            "Install sensors.\nConfigure their sensitivity.",
        )

    def test_rejects_empty_output(self):
        for raw in ("", " \n", None):
            with self.subTest(raw=raw), self.assertRaises(LLMOutputParseError):
                self.parser.parse(raw)

    def test_rejects_broken_structure_without_salvaging_fields(self):
        variants = (
            VALID_OUTPUT.replace("{solutions}", "{solution}"),
            VALID_OUTPUT.replace("{title}", "{advantage}", 1),
            VALID_OUTPUT.replace("\n***\n", "\n**\n", 1),
            VALID_OUTPUT.replace("\n***\n", " *** \n", 1),
            "Here is the result:\n" + VALID_OUTPUT,
            "```text\n" + VALID_OUTPUT + "```",
            '{"title": "Occupancy-controlled lighting"}',
            VALID_OUTPUT.replace("Install occupancy sensors.", ""),
            VALID_OUTPUT.replace("Install occupancy sensors.", " \n\t"),
            VALID_OUTPUT.replace("Install occupancy sensors.", "### Install sensors"),
            VALID_OUTPUT.replace("Install occupancy sensors.", "```\nInstall sensors\n```"),
            VALID_OUTPUT.replace("Install occupancy sensors.", "Install *** sensors"),
            VALID_OUTPUT + "***\n{extra}\nAdditional field",
            VALID_OUTPUT + "{summary}\nAdditional field",
        )
        for raw in variants:
            with self.subTest(raw=raw), self.assertRaises(LLMOutputSchemaError):
                self.parser.parse(raw)


if __name__ == "__main__":
    unittest.main()
