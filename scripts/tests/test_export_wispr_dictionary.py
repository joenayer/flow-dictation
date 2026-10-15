import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from export_wispr_dictionary import (  # noqa: E402
    ExportError,
    FORMAT,
    VERSION,
    create_transfer_file,
    read_personal_dictionary,
)


PERSONAL_ID = "00000000-0000-0000-0000-000000000000"


def make_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE Dictionary ("
        "id TEXT, phrase TEXT NOT NULL, replacement TEXT, teamDictionaryId TEXT NOT NULL, "
        "isDeleted INTEGER NOT NULL, isSnippet INTEGER NOT NULL)"
    )
    connection.executemany(
        "INSERT INTO Dictionary (id, phrase, replacement, teamDictionaryId, isDeleted, isSnippet) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("one", "Private Test Word", None, PERSONAL_ID, 0, 0),
            ("two", "heard wrong", "correct text", PERSONAL_ID, 0, 0),
            ("team", "Team Only", None, "team-id", 0, 0),
            ("deleted", "Deleted Word", None, PERSONAL_ID, 1, 0),
            ("snippet", "Snippet Trigger", "Expansion", PERSONAL_ID, 0, 1),
        ],
    )
    connection.commit()
    connection.close()


class WisprDictionaryExportTest(unittest.TestCase):
    def test_reads_only_active_personal_dictionary_words_and_corrections(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "flow.sqlite"
            make_database(database)

            entries = read_personal_dictionary(database)

            self.assertEqual(
                [
                    {"phrase": "heard wrong", "replacement": "correct text"},
                    {"phrase": "Private Test Word", "replacement": None},
                ],
                entries,
            )

    def test_transfer_file_has_versioned_format_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "flow.sqlite"
            output = root / "Downloads"
            make_database(database)

            first, count = create_transfer_file(database, output)
            first_contents = first.read_text(encoding="utf-8")
            second, second_count = create_transfer_file(database, output)

            self.assertEqual(2, count)
            self.assertEqual(2, second_count)
            self.assertEqual("Wispr-Flow-Dictionary.json", first.name)
            self.assertEqual("Wispr-Flow-Dictionary (2).json", second.name)
            self.assertEqual(first_contents, first.read_text(encoding="utf-8"))
            self.assertIn(f'"format": "{FORMAT}"', first_contents)
            self.assertIn(f'"version": {VERSION}', first_contents)

    def test_missing_schema_fails_without_exporting(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "flow.sqlite"
            sqlite3.connect(database).close()

            with self.assertRaises(ExportError):
                read_personal_dictionary(database)

    def test_oversized_transfer_is_rejected_before_creating_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "flow.sqlite"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE Dictionary (phrase TEXT NOT NULL, replacement TEXT, "
                "teamDictionaryId TEXT NOT NULL, isDeleted INTEGER NOT NULL, isSnippet INTEGER NOT NULL)"
            )
            connection.execute(
                "INSERT INTO Dictionary VALUES (?, ?, ?, ?, ?)",
                ("Long correction", "x" * 2_000_000, PERSONAL_ID, 0, 0),
            )
            connection.commit()
            connection.close()

            output = root / "Downloads"
            with self.assertRaises(ExportError):
                create_transfer_file(database, output)
            self.assertEqual([], list(output.glob("*.json")))

    def test_empty_dictionary_fails_without_creating_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "flow.sqlite"
            make_database(database)
            connection = sqlite3.connect(database)
            connection.execute("DELETE FROM Dictionary")
            connection.commit()
            connection.close()

            output = root / "Downloads"
            with self.assertRaises(ExportError):
                create_transfer_file(database, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
