"""Owner-scoped project list paging/search contracts for Studio2 #106."""
import tempfile
import unittest
from pathlib import Path

from backend.db import Database
from backend.services import register_user, ServiceError
from backend.studio_projects import list_projects


class ProjectPaginationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.temp.name)/"paging.sqlite3")
        self.db.migrate()
        self.alice,_=register_user(self.db,"page_alice","Password12345!",
                                   "page-a@example.com","Alice","invite-a")
        self.bob,_=register_user(self.db,"page_bob","Password12345!",
                                 "page-b@example.com","Bob","invite-b")
        with self.db.transaction() as tx:
            for index in range(113):
                title=("海报" if index%2 else "秋日") + f"第{index:03}号"
                if index == 100:
                    title = "100%设计稿"
                if index == 101:
                    title = "带_下划线"
                # Many rows share a time, testing ID tie-breaking.
                stamp=f"2026-11-08T00:00:00.{index//3:06}Z"
                tx.execute(
                    """INSERT INTO studio_projects
                       (id,user_id,kind,title,authority,revision,draft_json,created_at,updated_at)
                       VALUES (?,?,?,?,?,1,'{}',?,?)""",
                    (f"project-{index:04}", self.alice["id"], "image",
                     title, "graph", stamp, stamp),
                )

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_every_project_reachable_once_with_stable_cursor(self):
        cursor=""
        ids=[]
        pages=0
        while True:
            result=list_projects(self.db,self.alice,cursor=cursor,limit=40)
            ids.extend(p["id"] for p in result["projects"])
            pages+=1
            if not result["hasMore"]:
                self.assertEqual(result["nextCursor"],"")
                break
            self.assertTrue(result["nextCursor"])
            cursor=result["nextCursor"]
        self.assertEqual(pages,3)
        self.assertEqual(len(ids),113)
        self.assertEqual(len(set(ids)),113)
        self.assertEqual(ids[0],"project-0112")
        self.assertEqual(ids[-1],"project-0000")

    def test_literal_search_does_not_treat_percent_or_underscore_as_wildcards(self):
        percent=list_projects(self.db,self.alice,query="%",limit=40)
        self.assertEqual([p["id"] for p in percent["projects"]],["project-0100"])
        underscore=list_projects(self.db,self.alice,query="_",limit=40)
        self.assertEqual([p["id"] for p in underscore["projects"]],["project-0101"])
        subset=list_projects(self.db,self.alice,query="秋日",limit=20)
        self.assertEqual(len(subset["projects"]),20)
        self.assertTrue(subset["hasMore"])
        next_page=list_projects(self.db,self.alice,query="秋日",cursor=subset["nextCursor"],limit=20)
        self.assertFalse(set(p["id"] for p in subset["projects"]) &
                         set(p["id"] for p in next_page["projects"]))

    def test_owner_and_invalid_cursor_limits(self):
        self.assertEqual(list_projects(self.db,self.bob)["projects"],[])
        for cursor in ["invalid-%", "!", "a"*400]:
            with self.subTest(cursor=cursor[:20]),self.assertRaises(ServiceError) as err:
                list_projects(self.db,self.alice,cursor=cursor)
            self.assertEqual(err.exception.status,400)
        for limit in [0,101,"20",True]:
            with self.subTest(limit=limit),self.assertRaises(ServiceError):
                list_projects(self.db,self.alice,limit=limit)
        with self.assertRaises(ServiceError):
            list_projects(self.db,self.alice,query="x"*121)


if __name__=="__main__":
    unittest.main()
