const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const window={};vm.runInNewContext(fs.readFileSync('demo/assets/forum-board-admin.js','utf8'),{window,Symbol,String});
const ui=window.HandrawForumBoardsAdmin;
test('forum controls explain invitations, closure and immutable private history; names escape',()=>{
 const html=ui.render([{key:'board_1',label:'<img src=x onerror=alert(1)>',description:'</textarea><script>x</script>',visibility:'private',state:'open',topic_count:2,member_count:1,members:[{username:'<member>'}]}]);
 assert(!html.includes('<img'));assert(!html.includes('<script>'));
 for(const text of ['受邀账号','转发链接不增加权限','关闭论坛','重新开放','撤销邀请','创建论坛'])assert(html.includes(text));
 assert(html.includes('name="visibility" disabled'));assert(html.includes('&lt;member&gt;'));
});
test('closed forum retains editable settings and reopening but provides no enter link',()=>{
 const html=ui.render([{key:'board_2',label:'Closed',description:'',visibility:'public',state:'closed',topic_count:1,member_count:0,members:[]}]);
 assert(html.includes('重新开放'));assert(!html.includes('/forum/?category=board_2'));
});
