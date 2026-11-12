"""Import worker ownership and teardown follow the database instance."""
import unittest

from backend.document_importer import get_import_manager
from tests.postgres_support import open_isolated_postgres


class ImportManagerOwnershipTests(unittest.TestCase):
    def test_managers_are_isolated_and_close_stops_workers(self):
        first_db = open_isolated_postgres(self)
        second_db = open_isolated_postgres(self)
        first = get_import_manager(first_db)
        second = get_import_manager(second_db)
        self.assertIs(get_import_manager(first_db), first)
        self.assertIsNot(first, second)
        self.assertIs(first.db, first_db)
        self.assertIs(second.db, second_db)
        threads = [*first.workers, first._watchdog_thread]
        first_db.close()
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertIsNone(first_db._import_manager)
        self.assertTrue(second._started)
        self.assertTrue(all(thread.is_alive() for thread in second.workers))
        second.stop()
        replacement = get_import_manager(second_db)
        self.assertIsNot(replacement, second)
        self.assertTrue(replacement._started)
