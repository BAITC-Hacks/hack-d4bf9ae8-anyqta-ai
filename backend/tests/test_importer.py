import tempfile
import unittest
from pathlib import Path

from backend.app.db import connect
from backend.app.importer import ImportValidationError, Package, import_package, load_full_package


DATASET = Path("/Users/IZinekenov/Downloads/case_1/career_quest_dataset")


@unittest.skipUnless(DATASET.exists(), "starter dataset is not available")
class ImporterIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.connection = connect(Path(self.temp.name) / "career_quest.db")
        self.package = load_full_package(DATASET)

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_full_import_persists_the_complete_starter_kit(self):
        import_package(self.connection, self.package, "full", str(DATASET))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0], 200)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM skills").fetchone()[0], 60)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 40)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM activity_history").fetchone()[0], 2743)

    def test_invalid_package_leaves_no_partial_rows(self):
        self.package.history[0]["event_id"] = "EV_DOES_NOT_EXIST"
        with self.assertRaises(ImportValidationError):
            import_package(self.connection, self.package, "full", str(DATASET))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM skills").fetchone()[0], 0)

    def test_identical_full_import_is_idempotent(self):
        import_package(self.connection, self.package, "full", str(DATASET))
        import_package(self.connection, self.package, "full", str(DATASET))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0], 200)

    def test_changed_existing_profile_is_rejected(self):
        import_package(self.connection, self.package, "full", str(DATASET))
        self.package.employees[0]["full_name"] = "Different Person"
        with self.assertRaises(ImportValidationError):
            import_package(self.connection, self.package, "full", str(DATASET))

    def test_changed_existing_role_requirement_is_rejected(self):
        import_package(self.connection, self.package, "full", str(DATASET))
        self.package.role_profiles[0]["required_skills"]["SK_PYTHON"] = 5
        with self.assertRaises(ImportValidationError):
            import_package(self.connection, self.package, "full", str(DATASET))

    def test_profile_package_can_reference_existing_catalog_and_manager(self):
        import_package(self.connection, self.package, "full", str(DATASET))
        employee = dict(self.package.employees[0])
        employee["employee_id"] = "E9999"
        employee["manager_id"] = "E0050"
        employee["full_name"] = "Jury Profile"
        record = dict(self.package.history[0])
        record["record_id"] = "R999999"
        record["employee_id"] = "E9999"
        package = Package(employees=[employee], history=[record])
        import_package(self.connection, package, "profiles", "jury package")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0], 201)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM activity_history WHERE employee_id = 'E9999'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
