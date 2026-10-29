"""Community collection and review acceptance against a disposable SQLite database."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from backend.server import init_database
from backend import curation as C, services as S, resource_discussions as D


class CurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'HANDRAW_DEMO_MODE':'0','HANDRAW_PRIVATE_STORAGE':self.tmp.name})
        self.env.start()
        self.db=init_database(Path(self.tmp.name)/'curation.db')
        self.users={}
        self.tokens={}
        for name in ('author','review_a','review_b','review_c','outsider','admin_user'):
            user,token=S.register_user(self.db,name,'isolated-test-password')
            self.users[name]=user
            self.tokens[name]=token
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET role='admin' WHERE username='admin_user'")
        self.admin=dict(self.users['admin_user'],role='admin')
        self.author=self.users['author']
        C.grant_access(self.db,self.admin,{'usernames':['review_a','review_b','review_c'],'kinds':['style','layout','work'],'action':'grant','reason':'验收审核组'})

    def tearDown(self):
        self.db.close();self.env.stop();self.tmp.cleanup()

    def item(self,kind='style',**overrides):
        return dict({'kind':kind,'name':'纸上微光','title':'纸上微光作品','images':['/images/FA-001.webp'],'definition':'秘密定义：自然纸纹和墨线','prompt':'秘密提示：窗边一束花','unlockCost':5},**overrides)

    def submit(self,kind='style',**overrides):
        return C.submit(self.db,self.author,{'title':'微光投稿测试','text':'公开介绍','items':[self.item(kind,**overrides)],'requestId':overrides.get('requestId','')})

    def ballot(self,name,decision='approve',reason=''):
        task=C.review_queue(self.db,self.users[name])['assignment']
        self.assertIsNotNone(task)
        return C.vote(self.db,self.users[name],{'assignmentId':task['assignmentId'],'decision':decision,'reason':reason})

    def test_collection_gate_multi_item_idempotence_and_paid_privacy(self):
        # Works publish immediately (D-02) and are rejected inside a submission,
        # so only catalogue items go through review here.
        work_item=self.item('work')
        S.publish_user_work(self.db,self.author,{
            'title':work_item['title'],'prompt':work_item['prompt'],'images':work_item['images'],
            'styles':work_item.get('styles') or [],'layout':work_item.get('layout') or ''})
        body={'title':'多项分享','requestId':'stable-key','items':[self.item('style'),self.item('layout')]}
        res=C.submit(self.db,self.author,body)
        self.assertEqual(C.submit(self.db,self.author,body)['topicId'],res['topicId'])
        self.assertEqual(len(res['submissions']),2)
        boot=S.build_boot_payload(self.db,None)
        self.assertEqual(len([t for t in boot['topics'] if t['id']==res['topicId']]),1)
        self.assertNotIn('秘密定义',json.dumps(boot,ensure_ascii=False))
        self.assertEqual(self.db.get_conn().execute('SELECT COUNT(*) FROM catalog_assets').fetchone()[0],0)
        pending_code=res['submissions'][0]['targetId']
        with self.assertRaises(S.ServiceError) as generation_error:
            S.prepare_cloud_generation(self.db,self.author,{'style1':pending_code,'prompt':'不能绕过收录'})
        self.assertEqual(generation_error.exception.code,'asset_not_collected')
        with self.assertRaises(S.ServiceError):
            S.build_skill_asset_content(self.db,self.author,pending_code)
        for _ in range(2):
            self.ballot('review_a');self.ballot('review_b')
        boot=S.build_boot_payload(self.db,None)
        self.assertEqual(len(boot['communityResources']),2)
        self.assertEqual(len(boot['works']),1)
        self.assertNotIn('秘密定义',json.dumps(boot,ensure_ascii=False))
        self.assertIn('style',C.review_access(self.db,self.author)['kinds'])
        self.assertEqual(self.db.get_conn().execute('SELECT role FROM users WHERE id=?',(self.author['id'],)).fetchone()[0],'user')

    def test_no_self_review_cap_and_majority(self):
        res=self.submit()
        C.grant_access(self.db,self.admin,{'usernames':['author'],'kinds':['style'],'action':'grant'})
        self.assertIsNone(C.review_queue(self.db,self.author)['assignment'])
        a=C.review_queue(self.db,self.users['review_a'])['assignment']
        b=C.review_queue(self.db,self.users['review_b'])['assignment']
        self.assertIsNone(C.review_queue(self.db,self.users['review_c'])['assignment'])
        with self.assertRaises(S.ServiceError):
            C.vote(self.db,self.users['outsider'],{'assignmentId':a['assignmentId'],'decision':'approve'})
        C.vote(self.db,self.users['review_a'],{'assignmentId':a['assignmentId'],'decision':'approve'})
        self.assertIsNone(C.review_queue(self.db,self.users['review_c'])['assignment'])
        C.vote(self.db,self.users['review_b'],{'assignmentId':b['assignmentId'],'decision':'changes','reason':'定义需清楚'})
        result=self.ballot('review_c')
        self.assertEqual(result['status'],'approved')
        count=self.db.get_conn().execute('SELECT COUNT(*) FROM ledgers WHERE event_key LIKE \'pub_asset_%\'').fetchone()[0]
        C.vote(self.db,self.users['review_a'],{'assignmentId':a['assignmentId'],'decision':'approve'})
        self.assertEqual(count,1)
        self.assertEqual(self.db.get_conn().execute('SELECT COUNT(*) FROM ledgers WHERE event_key LIKE \'pub_asset_%\'').fetchone()[0],1)

    def test_pause_resume_do_not_mint_access_and_release_slots(self):
        for action in ('pause','resume'):
            C.grant_access(self.db,self.admin,{'usernames':['outsider'],'kinds':['work'],'action':action})
        self.assertEqual(C.review_access(self.db,self.users['outsider'])['kinds'],[])
        self.submit()
        task=C.review_queue(self.db,self.users['review_a'])['assignment']
        C.grant_access(self.db,self.admin,{'usernames':['review_a'],'kinds':['style'],'action':'pause'})
        with self.assertRaises(S.ServiceError):
            C.vote(self.db,self.users['review_a'],{'assignmentId':task['assignmentId'],'decision':'approve'})
        C.grant_access(self.db,self.admin,{'usernames':['review_a'],'kinds':['style'],'action':'resume'})
        self.ballot('review_a');self.ballot('review_b')

    def test_admin_catalog_cannot_create_community_resource_without_collection(self):
        from backend.admin_services import admin_upsert_catalog_asset
        with self.assertRaises(S.ServiceError):
            admin_upsert_catalog_asset(self.db,self.admin,dict(self.item(),sourceType='community',code='USR-S-BYPASS'))
        self.assertIsNone(self.db.get_conn().execute("SELECT 1 FROM catalog_assets WHERE code='USR-S-BYPASS'").fetchone())

    def test_revision_preserves_public_version_qualification_and_reward(self):
        res=self.submit();sid=res['submissions'][0]['id'];code=res['code']
        oldtask=C.review_queue(self.db,self.users['review_c'])['assignment']
        self.ballot('review_a');self.ballot('review_c')
        row=dict(self.db.get_conn().execute('SELECT * FROM catalog_assets WHERE code=?',(code,)).fetchone())
        C.revise(self.db,self.author,sid,{'payload':self.item(name='新版微光',definition='新版秘密定义')})
        self.assertIn('style',C.review_access(self.db,self.author)['kinds'])
        with self.assertRaises(S.ServiceError):
            C.vote(self.db,self.users['review_c'],{'assignmentId':oldtask['assignmentId'],'decision':'changes','reason':'旧票'})
        self.assertEqual(self.db.get_conn().execute('SELECT name FROM catalog_assets WHERE code=?',(code,)).fetchone()[0],row['name'])
        self.ballot('review_a');self.ballot('review_b')
        latest=dict(self.db.get_conn().execute('SELECT * FROM catalog_assets WHERE code=?',(code,)).fetchone())
        self.assertEqual(latest['name'],'新版微光')
        self.assertEqual(latest['published_at_ms'],row['published_at_ms'])
        self.assertEqual(self.db.get_conn().execute('SELECT COUNT(*) FROM ledgers WHERE event_key=?',(f'pub_asset_{code}',)).fetchone()[0],1)

    def test_return_resubmit_appeal_and_admin_self_boundary(self):
        res=self.submit();sid=res['submissions'][0]['id']
        self.ballot('review_a','changes','示例需补充');self.ballot('review_b','changes','缺少适用范围')
        self.assertIsNone(C.review_queue(self.db,self.users['review_c'])['assignment'])
        with self.assertRaises(S.ServiceError):
            C.admin_review(self.db,self.admin,{'submissionId':sid,'action':'approve','reason':'未申诉'})
        C.appeal(self.db,self.author,sid,'已包含说明')
        C.admin_review(self.db,self.admin,{'submissionId':sid,'action':'reopen','reason':'请社群重新复核'})
        self.assertEqual(C.my_submissions(self.db,self.author)['submissions'][0]['revision'],2)
        self.ballot('review_a');self.ballot('review_b')
        own=C.submit(self.db,self.admin,{'items':[self.item()]})['submissions'][0]['id']
        with self.assertRaises(S.ServiceError):
            C.admin_review(self.db,self.admin,{'submissionId':own,'action':'withdraw','reason':'自审'})

    def test_official_comment_shared_store_hide_restore_and_public_time(self):
        code=next(k for k,v in D.static_catalog().items() if v['kind']=='style')
        before=S.build_boot_payload(self.db,None)
        self.assertNotIn(code,before['discussions'])
        res=S.add_comment_to_asset(self.db,self.author,code,'纸纹很好用','style')
        topicid=res['topicId'];cid=res['comment']['id']
        boot=S.build_boot_payload(self.db,None)
        topic=next(t for t in boot['topics'] if t['id']==topicid)
        self.assertEqual(topic['replies'][0]['id'],boot['assetComments'][code][0]['id'])
        S.publish_forum_reply_post(self.db,self.users['outsider'],topicid,'我也试了')
        self.assertEqual(self.db.get_conn().execute('SELECT COUNT(*) FROM forum_replies WHERE topic_id=?',(topicid,)).fetchone()[0],0)
        with self.db.transaction() as tx:
            tx.execute("UPDATE asset_comments SET status='hidden' WHERE asset_code=?",(code,))
        self.assertNotIn(topicid,[t['id'] for t in S.build_boot_payload(self.db,None)['topics']])
        restored=S.add_comment_to_asset(self.db,self.author,code,'新的使用心得','style')
        self.assertEqual(restored['topicId'],topicid)
        self.assertEqual(len(S.build_boot_payload(self.db,None)['assetComments'][code]),1)
        S.forum_moderator_action(self.db,self.admin,{'topicId':topicid,'replyId':restored['comment']['id'],'op':'hide_reply'})
        self.assertNotIn(topicid,[t['id'] for t in S.build_boot_payload(self.db,None)['topics']])
        S.forum_moderator_action(self.db,self.admin,{'topicId':topicid,'replyId':restored['comment']['id'],'op':'publish_reply'})
        self.assertEqual(len(S.build_boot_payload(self.db,None)['assetComments'][code]),1)

    def test_submission_detail_and_forum_comments_are_identical(self):
        res=self.submit();self.ballot('review_a');self.ballot('review_b')
        S.add_comment_to_asset(self.db,self.users['outsider'],res['code'],'喜欢这个画风','style')
        boot=S.build_boot_payload(self.db,None)
        topic=next(t for t in boot['topics'] if t['id']==res['topicId'])
        self.assertEqual(boot['assetComments'][res['code']],topic['replies'])
        self.assertEqual(self.db.get_conn().execute('SELECT COUNT(*) FROM asset_comments').fetchone()[0],0)

    def test_http_private_routes_media_ownership_and_old_publish_gate(self):
        import threading
        import urllib.request
        import urllib.error
        from backend.server import create_channel_server
        from backend.config import SESSION_COOKIE_NAME
        server=create_channel_server(0,'main',self.db)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        def request(path,user=None,body=None,origin='http://trusted.test'):
            headers={'Origin':origin}
            if user:headers['Cookie']=f'{SESSION_COOKIE_NAME}={self.tokens[user]}'
            if body is not None:headers['Content-Type']='application/json'
            data=json.dumps(body).encode() if body is not None else None
            try:response=urllib.request.urlopen(urllib.request.Request(base+path,data=data,headers=headers),timeout=5)
            except urllib.error.HTTPError as e:response=e
            with response:return response.status,response.headers,json.load(response)
        try:
            with patch.dict(os.environ,{'HANDRAW_ALLOWED_ORIGINS':'http://trusted.test'}):
                for route in ('mine','access','admin','review-queue'):
                    self.assertEqual(request('/api/curation/'+route)[0],401)
                self.assertEqual(request('/api/curation/admin','outsider')[0],403)
                self.assertEqual(request('/api/curation/access','outsider',{'usernames':['outsider'],'kinds':['style'],'action':'grant'})[0],403)
                self.assertEqual(request('/api/curation/submissions','author',{'items':[self.item()]},origin='https://untrusted.test')[0],403)
                status,headers,res=request('/api/curation/drafts','author',{'payload':self.item()})
                self.assertEqual(status,200,res);draft=res['id']
                self.assertIn('no-store',headers['Cache-Control'])
                self.assertEqual(request('/api/curation/drafts/'+draft,'outsider')[0],404)
                self.assertEqual(request('/api/curation/drafts/'+draft,'author')[0],200)
                png='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5ioAAAAASUVORK5CYII='
                status,_,upload=request('/api/uploads','author',{'dataUrl':png,'nameZh':'验收图'})
                self.assertEqual(status,200,upload)
                foreign=self.item(images=[upload['url']])
                self.assertEqual(request('/api/curation/submissions','outsider',{'items':[foreign]})[0],403)
                status,_,res=request('/api/works','author',self.item('work',images=[upload['url']]))
                self.assertEqual(status,200,res)
                # D-02: works publish immediately.  Double review remains for
                # styles and layouts, which feed the shared catalogue.
                self.assertEqual(res['status'],'published')
                self.assertIsNotNone(self.db.get_conn().execute('SELECT 1 FROM works WHERE id=?',(res['workId'],)).fetchone())
                self.assertEqual(res['url'],f"/forum/?view=resource&kind=work&id={res['workId']}")
                status,_,boot=request('/api/boot')
                self.assertTrue(any(t['id']==res['topicId'] for t in boot['topics']))
                self.assertTrue(any(w['id']==res['workId'] for w in boot['works']))
                self.assertEqual(len(self.db.get_conn().execute('SELECT * FROM media_public_grants WHERE target_id=?',(res['topicId'],)).fetchall()),1)
                board=self.db.get_conn().execute('SELECT category FROM forum_topics WHERE id=?',(res['topicId'],)).fetchone()
                self.assertEqual(board['category'],'showcase')
        finally:
            server.shutdown();server.server_close();thread.join(5)

    def test_concurrent_queue_and_identical_vote_replay(self):
        self.submit()
        names=['review_a','review_b','review_c']
        with ThreadPoolExecutor(max_workers=3) as pool:
            assigned=list(pool.map(lambda n:(n,C.review_queue(self.db,self.users[n])['assignment']),names))
        tasks=[(n,a) for n,a in assigned if a]
        self.assertEqual(len(tasks),2)
        name,task=tasks[0]
        body={'assignmentId':task['assignmentId'],'decision':'approve'}
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda _:C.vote(self.db,self.users[name],body),range(3)))
        self.assertTrue(all(r['ok'] for r in results))
        self.assertEqual(self.db.get_conn().execute('SELECT COUNT(*) FROM curation_votes').fetchone()[0],1)


if __name__=='__main__':unittest.main()
