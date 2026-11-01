"""Resource/forum contract acceptance in a disposable, non-demo database."""
import json
import unittest
import uuid
from tests import test_v2_curation as fixtures
from backend import curation as C, services as S, resource_discussions as D, forum_resources as R
from backend.admin_services import admin_moderate_comment


class ForumResourceTests(unittest.TestCase):
    setUp=fixtures.CurationTests.setUp
    tearDown=fixtures.CurationTests.tearDown
    item=fixtures.CurationTests.item
    ballot=fixtures.CurationTests.ballot

    def batch(self,price=0):
        # Works publish immediately and never enter review (D-02), so the work
        # is created through the publish path first; the submission carries only
        # catalogue items.  Mixing a work into a submission is rejected.
        work_item=self.item('work',price=price)
        published=S.publish_user_work(self.db,self.author,{
            'title':work_item['title'],'prompt':work_item['prompt'],'images':work_item['images'],
            'styles':work_item.get('styles') or [],'layout':work_item.get('layout') or '','price':price})
        result=C.submit(self.db,self.author,{'title':'测试资源共用帖','text':'公开创作心得',
            'items':[self.item('style',unlockCost=price)]})
        tid=result['topicId']
        sid=uuid.uuid4().hex
        target_id=C._stable_target_id('layout',None)
        now_iso=C._now()
        with self.db.transaction() as tx:
            tx.execute("INSERT INTO curation_submissions (id,topic_id,owner_username,owner_user_id,kind,target_id,status,current_revision,request_id,created_at,updated_at) VALUES (?,?,?,?,?,?,'pending',1,'',?,?)",
                       (sid,tid,self.author['username'],self.author['id'],'layout',target_id,now_iso,now_iso))
            tx.execute("INSERT INTO curation_versions (id,submission_id,revision,payload_json,created_at) VALUES (?,?,1,?,?)",
                       (uuid.uuid4().hex,sid,json.dumps(self.item('layout',unlockCost=price),ensure_ascii=False),now_iso))
            tx.execute("INSERT INTO curation_resource_topics (kind,target_id,topic_id,origin,created_at) VALUES ('layout',?,?, 'submission', ?)",
                       (target_id,tid,now_iso))
        subs={'style':result['submissions'][0], 'layout':{'id':sid,'kind':'layout','targetId':target_id,'status':'pending','revision':1}}
        result['submissions'].append(subs['layout'])
        subs['work']={'id':None,'kind':'work','targetId':published['workId'],
                      'topicId':published['topicId'],'status':'published'}
        return result,subs

    def approve_all(self):
        while C.review_queue(self.db,self.users['review_a'])['assignment']:
            self.ballot('review_a');self.ballot('review_b')

    def test_official_read_does_not_create_topic_and_first_last_comment_feed(self):
        before=self.db.get_conn().execute('SELECT COUNT(*) FROM forum_topics').fetchone()[0]
        detail=R.resource_detail(self.db,None,'asset','fa-001')
        self.assertTrue(detail['resource']['canUse'])
        self.assertEqual(detail['resource']['kind'],'style')
        self.assertIsNone(detail['thread'])
        self.assertEqual(self.db.get_conn().execute('SELECT COUNT(*) FROM forum_topics').fetchone()[0],before)
        posted=R.post_comment(self.db,self.author,'style','FA-001','这条是真实评论')
        tid=posted['topicId'];cid=posted['comment']['id']
        boot=S.build_boot_payload(self.db,None)
        self.assertIn(tid,[t['id'] for t in boot['topics']])
        self.assertEqual(R.resource_comments(self.db,None,'style','FA-001')['items'][0]['id'],cid)
        self.assertEqual(R.resource_detail(self.db,None,'style','FA-001')['thread']['commentCount'],1)
        admin_moderate_comment(self.db,self.admin,'asset_comment',cid,'hide')
        self.assertNotIn(tid,[t['id'] for t in S.build_boot_payload(self.db,None)['topics']])
        self.assertEqual(R.resource_comments(self.db,None,'style','FA-001')['total'],0)

    def test_pending_all_kinds_multi_siblings_and_one_comment_store(self):
        result,subs=self.batch()
        # Catalogue items are still pending review and share one thread.
        for kind in ('style','layout'):
            sub=subs[kind]
            detail=R.resource_detail(self.db,None,kind,sub['targetId'])
            self.assertFalse(detail['resource']['canUse'])
            self.assertFalse(detail['curation']['hasPublishedVersion'])
            self.assertEqual(detail['curation']['id'],sub['id'])
            self.assertEqual(len(detail['siblings']),2,'style and layout share the submission thread')
            self.assertNotIn('秘密',json.dumps(detail,ensure_ascii=False))
        # The work is already live on its own thread.
        work_detail=R.resource_detail(self.db,None,'work',subs['work']['targetId'])
        self.assertTrue(work_detail['resource']['canUse'])
        posted=R.post_comment(self.db,self.users['outsider'],'work',subs['work']['targetId'],'同帖讨论')
        comments=R.resource_comments(self.db,None,'work',subs['work']['targetId'])
        self.assertEqual(comments['items'][0]['id'],posted['replyId'])
        self.assertEqual(comments['items'][0]['type'],'forum_reply')
        self.assertEqual(self.db.get_conn().execute('SELECT COUNT(*) FROM work_comments').fetchone()[0],0)
        self.assertEqual(self.db.get_conn().execute('SELECT COUNT(*) FROM asset_comments').fetchone()[0],0)

    def test_paid_permissions_and_blackbox_never_leak(self):
        _,subs=self.batch(5);self.approve_all()
        for kind,sub in subs.items():
            target=sub['targetId']
            for user in (None,self.users['outsider']):
                detail=R.resource_detail(self.db,user,kind,target)
                self.assertFalse(detail['resource']['unlocked'])
                self.assertNotIn('秘密',json.dumps(detail,ensure_ascii=False))
            self.assertTrue(R.resource_detail(self.db,self.author,kind,target)['resource']['unlocked'])
            self.assertTrue(R.resource_detail(self.db,self.admin,kind,target)['resource']['unlocked'])
            S.unlock_paid_item(self.db,self.users['outsider'],'',target)
            self.assertTrue(R.resource_detail(self.db,self.users['outsider'],kind,target)['resource']['canUse'])
        style=subs['style']['targetId']
        with self.db.transaction() as tx:
            tx.execute("UPDATE catalog_assets SET source_type='exclusive',secret_blackbox_prompt='PRIVATE_BLACKBOX' WHERE code=?",(style,))
        self.assertNotIn('PRIVATE_BLACKBOX',json.dumps(R.resource_detail(self.db,self.admin,'style',style)))

    def test_exact_relations_pagination_no_hidden_pending_or_seed(self):
        _,subs=self.batch();self.approve_all()
        style=subs['style']['targetId'];layout=subs['layout']['targetId'];wid=subs['work']['targetId']
        with self.db.transaction() as tx:
            tx.execute('UPDATE works SET styles_json=?,layout_code=? WHERE id=?',(json.dumps([style,'FA-001']),layout,wid))
            for n in range(27):
                tx.execute("INSERT INTO works (id,author_username,author_name,title,images_json,styles_json,layout_code,prompt,status,published_at_ms,created_at,updated_at) VALUES (?,'author','测试作者',?, ?,?,?,'DO_NOT_SEARCH_SECRET',?,?,?,?)",(f'qa_work_{n:02}',f'关联作品{n:02}',json.dumps(['/images/FA-001.webp']),json.dumps([style]),layout,'hidden' if n==26 else 'published',n+1,S.utc_now_iso(),S.utc_now_iso()))
        preview=R.resource_detail(self.db,None,'style',style)
        works=next(r for r in preview['relations'] if r['tab']=='works')
        self.assertEqual(works['total'],27);self.assertEqual(len(works['items']),4)
        a=R.related_items(self.db,None,'style',style,'works',limit=24)
        b=R.related_items(self.db,None,'style',style,'works',offset=24,limit=24)
        self.assertEqual(a['total'],27);self.assertEqual(len(a['items']),24);self.assertEqual(len(b['items']),3)
        self.assertFalse({x['id'] for x in a['items']} & {x['id'] for x in b['items']})
        self.assertEqual(R.related_items(self.db,None,'style',style,'works',q='DO_NOT_SEARCH_SECRET')['total'],0)
        pairs=R.related_items(self.db,None,'style',style,'layouts')['items']
        self.assertEqual([(x['id'],x['usageCount']) for x in pairs],[(layout,27)])
        styles=R.related_items(self.db,None,'work',wid,'styles')['items']
        self.assertEqual({x['id'] for x in styles},{style,'FA-001'})
        self.assertNotIn('definition',json.dumps(styles))
        self.assertEqual({x['id'] for x in R.related_items(self.db,None,'layout',layout,'styles')['items']},{style,'FA-001'})
        with self.db.transaction() as tx:
            tx.execute("UPDATE catalog_assets SET status='hidden' WHERE code=?",(layout,))
        self.assertEqual(R.related_items(self.db,None,'style',style,'layouts')['total'],0)

    def test_hidden_overrides_thread_moderation_and_comment_authority(self):
        result,subs=self.batch();self.approve_all()
        sub=subs['style'];target=sub['targetId']
        posted=R.post_comment(self.db,self.admin,'style',target,'管理员回复')
        outsider=R.resource_comments(self.db,self.users['outsider'],'style',target)['items'][0]
        self.assertFalse(outsider['canDelete']);self.assertFalse(outsider['canHide'])
        with self.db.transaction() as tx:
            tx.execute("UPDATE forum_topics SET status='hidden' WHERE id=?",(result['topicId'],))
        detail=R.resource_detail(self.db,None,'style',target)
        self.assertTrue(detail['thread']['closed']);self.assertEqual(detail['thread']['body'],'')
        self.assertEqual(R.resource_comments(self.db,None,'style',target)['total'],0)
        with self.assertRaises(S.ServiceError): R.post_comment(self.db,self.author,'style',target,'不能绕过')
        with self.db.transaction() as tx:
            tx.execute("UPDATE catalog_assets SET code='FA-001',status='hidden' WHERE code=?",(target,))
        with self.assertRaises(S.ServiceError): R.resource_detail(self.db,None,'style','FA-001')

    def test_revision_uses_last_published_version(self):
        _,subs=self.batch();self.approve_all()
        sub=subs['style'];target=sub['targetId']
        C.revise(self.db,self.author,sub['id'],{'payload':self.item('style',name='新版未收录',definition='新的秘密',unlockCost=0)})
        detail=R.resource_detail(self.db,None,'style',target)
        self.assertEqual(detail['resource']['name'],'纸上微光')
        self.assertTrue(detail['resource']['canUse'])
        self.assertTrue(detail['curation']['hasPublishedVersion'])
        self.assertEqual(detail['curation']['revision'],2)
        self.assertNotIn('新的秘密',json.dumps(detail,ensure_ascii=False))

    def test_comment_paging_and_invalid_inputs(self):
        for n in range(22): R.post_comment(self.db,self.author,'style','FA-001',f'评论{n}')
        a=R.resource_comments(self.db,self.author,'style','FA-001',limit=20)
        b=R.resource_comments(self.db,None,'style','FA-001',offset=20,limit=20)
        self.assertEqual(a['total'],22);self.assertEqual(len(a['items']),20);self.assertEqual(len(b['items']),2)
        self.assertTrue(a['items'][0]['canDelete']);self.assertFalse(b['items'][0]['canDelete'])
        self.assertFalse({c['id'] for c in a['items']} & {c['id'] for c in b['items']})
        for offset,limit in [(-1,1),(0,0),('oops',3)]:
            with self.assertRaises(S.ServiceError): R.resource_comments(self.db,None,'style','FA-001',offset,limit)

    def test_image_without_reproduction_prompt_is_not_a_public_work(self):
        _,subs=self.batch();self.approve_all()
        wid=subs['work']['targetId'];style=subs['style']['targetId']
        with self.db.transaction() as tx:
            tx.execute('UPDATE works SET prompt=?,styles_json=? WHERE id=?',('   ',json.dumps([style]),wid))
        self.assertNotIn(wid,[w['id'] for w in S.build_boot_payload(self.db,None)['works']])
        self.assertIsNone(D.resolve_resource(self.db.get_conn(),'work',wid))
        with self.assertRaises(S.ServiceError): R.resource_detail(self.db,None,'work',wid)
        self.assertEqual(R.related_items(self.db,None,'style',style,'works')['total'],0)

    def test_http_read_auth_origin_and_error_status(self):
        import os,threading,urllib.request,urllib.error
        from unittest.mock import patch
        from backend.server import create_channel_server
        from backend.config import SESSION_COOKIE_NAME
        server=create_channel_server(0,'main',self.db)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}'
        def request(path,body=None,username=None,origin='http://trusted.test'):
            headers={'Origin':origin,'Content-Type':'application/json'}
            if username: headers['Cookie']=f'{SESSION_COOKIE_NAME}={self.tokens[username]}'
            try: response=urllib.request.urlopen(urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers=headers),timeout=5)
            except urllib.error.HTTPError as e: response=e
            with response: return response.status,response.headers,json.load(response)
        try:
            with patch.dict(os.environ,{'HANDRAW_ALLOWED_ORIGINS':'http://trusted.test'}):
                path='/api/forum/resources/style/FA-001'
                status,headers,data=request(path)
                self.assertEqual(status,200);self.assertIn('no-store',headers['Cache-Control'])
                self.assertTrue(data['resource']['image'].startswith('/images/'))
                self.assertEqual(request('/api/forum/resources/style/MISSING')[0],404)
                self.assertEqual(request(path+'/comments?limit=0')[0],400)
                self.assertEqual(request(path+'/comments',{'text':'anonymous'})[0],401)
                self.assertEqual(request(path+'/comments',{'text':'bad origin'},'author','http://evil.test')[0],403)
                status,_,posted=request(path+'/comments',{'text':'HTTP真实评论'},'author')
                self.assertEqual(status,200)
                self.assertEqual(request(path+'/comments')[2]['items'][0]['id'],posted['comment']['id'])
                with self.db.transaction() as tx:
                    tx.execute("UPDATE asset_comments SET status='hidden' WHERE id=?",(posted['comment']['id'],))
                status,_,old=request('/api/forum/resource-topics/'+posted['topicId'])
                self.assertEqual(status,200);self.assertEqual(old['id'],'FA-001')
        finally:
            server.shutdown();server.server_close()


if __name__=='__main__': unittest.main()
