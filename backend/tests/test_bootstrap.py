import tempfile
import unittest
from pathlib import Path

from backend.app.bootstrap import bootstrap
from backend.app.db import connect


DATASET = Path(__file__).resolve().parents[2] / "data" / "career_quest_dataset"


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_imports_once_and_preserves_existing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "career_quest.db"
            self.assertTrue(bootstrap(database, DATASET))
            connection = connect(database)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0], 200)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 5)
            finally:
                connection.close()
            self.assertFalse(bootstrap(database, DATASET))
