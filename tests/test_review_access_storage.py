"""Preserve earned reviewer access while using PostgreSQL."""
from tests.postgres_support import open_isolated_postgres
import unittest

from backend.curation import _accepted_kinds_for
from backend.seed import seed_ids


class AcceptedKindsTests(unittest.TestCase):
    def test_case_insensitive_authors_and_optional_registry(self):
        db = open_isolated_postgres(self, initialize=False)
        with db.transaction() as conn:
            conn.execute('''
                CREATE TABLE catalog_assets(code TEXT,kind TEXT,author_username TEXT,source_type TEXT,status TEXT);
                CREATE TABLE works(id TEXT,author_username TEXT,status TEXT);
                INSERT INTO catalog_assets VALUES('personal_style','style','MixedUser','community','published');
                INSERT INTO catalog_assets VALUES('draft_layout','layout','MixedUser','community','draft');
                INSERT INTO catalog_assets VALUES('official_layout','layout','MixedUser','official','published');
                INSERT INTO works VALUES('personal_work','MixedUser','published');
            ''')
            self.assertEqual(_accepted_kinds_for(conn, 'mixeduser'), {'style', 'work'})
            self.assertEqual(_accepted_kinds_for(conn, 'other_user'), set())
            conn.execute('CREATE TABLE cold_start_registry(kind TEXT,item_id TEXT)')
            self.assertEqual(_accepted_kinds_for(conn, 'mixeduser'), {'style', 'work'})
            conn.execute("INSERT INTO cold_start_registry VALUES('user','mixeduser')")
            self.assertEqual(_accepted_kinds_for(conn, 'mixeduser'), set())

    def test_seed_contributions_do_not_confer_access(self):
        db = open_isolated_postgres(self, initialize=False)
        with db.transaction() as conn:
            conn.execute('''
                CREATE TABLE catalog_assets(code TEXT,kind TEXT,author_username TEXT,source_type TEXT,status TEXT);
                CREATE TABLE works(id TEXT,author_username TEXT,status TEXT);
            ''')
            for code in seed_ids('assets'):
                conn.execute("INSERT INTO catalog_assets VALUES(?,'style','seed_owner','community','published')", (code,))
            for work_id in seed_ids('works'):
                conn.execute("INSERT INTO works VALUES(?,'seed_owner','published')", (work_id,))
            self.assertEqual(_accepted_kinds_for(conn, 'seed_owner'), set())


if __name__ == '__main__':
    unittest.main()
