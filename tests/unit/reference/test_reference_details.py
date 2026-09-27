"""Schema extraction for annotated and dataclass Reference subclasses."""

import unittest
from dataclasses import InitVar, dataclass
from typing import ClassVar

from src.domain.entities import Reference, ReferenceDetails


class ReferenceDetailsTests(unittest.TestCase):
    def test_plain_and_dataclass_references_have_the_same_schema(self) -> None:
        class PlainReference(Reference):
            title: str
            page: int

            def __init__(self, title: str, page: int) -> None:
                self.title = title
                self.page = page

            @property
            def description(self) -> str:
                return "A page in a named source."

        @dataclass
        class DataclassReference(Reference):
            title: str
            page: int

            @property
            def description(self) -> str:
                return "A page in a named source."

        expected = ReferenceDetails((("title", "str"), ("page", "int")))
        plain = PlainReference("Relay Maintenance Log", 42)
        dataclass_reference = DataclassReference("Relay Maintenance Log", 42)

        self.assertEqual(plain.details, expected)
        self.assertEqual(dataclass_reference.details, expected)
        self.assertEqual(plain.details.hash(), dataclass_reference.details.hash())

    def test_plain_reference_includes_all_declared_properties_in_order(self) -> None:
        class DocumentReference(Reference):
            document_name: str
            page: int
            section: str

            def __init__(self) -> None:
                self.document_name = "Outage Dispatch Review"
                self.page = 12
                self.section = "Crew Assignment"

            @property
            def description(self) -> str:
                return "A document section."

        details = DocumentReference().details
        self.assertEqual(
            details.properties,
            (("document_name", "str"), ("page", "int"), ("section", "str")),
        )
        self.assertEqual(
            details.canonical(),
            "document_name|str,page|int,section|str",
        )

    def test_inherited_fields_are_base_first_without_duplicates(self) -> None:
        class BaseReference(Reference):
            source: str

            @property
            def description(self) -> str:
                return "A source."

        class ChildReference(BaseReference):
            title: str
            page: int
            source: str

            def __init__(self) -> None:
                self.source = "Operations Archive"
                self.title = "Relay Maintenance Log"
                self.page = 42

        self.assertEqual(
            ChildReference().details.properties,
            (("source", "str"), ("title", "str"), ("page", "int")),
        )

    def test_dataclass_inheritance_preserves_base_field_order(self) -> None:
        @dataclass
        class BaseReference(Reference):
            source: str

            @property
            def description(self) -> str:
                return "A source."

        @dataclass
        class ChildReference(BaseReference):
            title: str
            page: int

        reference = ChildReference("Operations Archive", "Relay Maintenance Log", 42)
        self.assertEqual(
            reference.details.properties,
            (("source", "str"), ("title", "str"), ("page", "int")),
        )

    def test_none_and_unset_fields_are_unavailable(self) -> None:
        class PartialReference(Reference):
            title: str
            page: int
            note: str | None
            active: bool

            def __init__(self) -> None:
                self.title = "Relay Maintenance Log"
                self.page = 0
                self.note = None

            @property
            def description(self) -> str:
                return "A partial source."

        self.assertEqual(
            PartialReference().details.properties,
            (("title", "str"), ("page", "int")),
        )

    def test_class_variables_and_dataclass_init_variables_are_excluded(self) -> None:
        @dataclass
        class DataclassReference(Reference):
            title: str
            transient: InitVar[str]
            category: ClassVar[str] = "source"

            @property
            def description(self) -> str:
                return "A named source."

        self.assertEqual(
            DataclassReference("Relay Maintenance Log", "ignore").details.properties,
            (("title", "str"),),
        )

    def test_declared_type_is_used_when_value_has_a_subtype(self) -> None:
        class SpecializedTitle(str):
            pass

        class TitleReference(Reference):
            title: str

            def __init__(self) -> None:
                self.title = SpecializedTitle("Relay Maintenance Log")

            @property
            def description(self) -> str:
                return "A named source."

        self.assertEqual(TitleReference().details.properties, (("title", "str"),))

    def test_complex_declared_types_remain_distinguishable(self) -> None:
        class TypedReference(Reference):
            tags: list[str]
            note: str | None

            def __init__(self) -> None:
                self.tags = ["relay"]
                self.note = "reviewed"

            @property
            def description(self) -> str:
                return "A tagged source."

        self.assertEqual(
            TypedReference().details.properties,
            (("tags", "list[str]"), ("note", "str | None")),
        )


if __name__ == "__main__":
    unittest.main()
