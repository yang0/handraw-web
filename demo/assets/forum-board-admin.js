/* Forum lifecycle and account invitations, available only in the admin console. */
(function(global){
  "use strict";
  const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  function fields(board={}){
    return `<div class="adm-form-grid"><label class="adm-field">论坛名称<input class="adm-input" name="label" required maxlength="80" value="${esc(board.label)}"></label>
      <label class="adm-field">可见范围<select class="adm-select" name="visibility" ${board.visibility==='private'&&board.topic_count?'disabled':''}>
        <option value="public">公开论坛</option><option value="private" ${board.visibility==='private'?'selected':''}>私密 · 仅受邀账号</option></select></label></div>
      <label class="adm-field">论坛介绍<textarea class="adm-input" name="description" maxlength="1000" rows="2">${esc(board.description)}</textarea></label>`;
  }
  function render(boards){
    return `<div class="adm-panel"><h3 class="adm-panel-title">论坛管理</h3>
      <p>公开论坛面向所有人。私密论坛只有受邀账号能看到入口并进入，转发链接不增加权限。超级管理员可管理全部论坛。</p>
      <p>关闭后入口和内容暂不可访问，帖子保留；重新开放即可恢复。已有私密帖子的论坛不能直接改为公开。</p>
      <details><summary>＋ 新增论坛</summary><form data-board-create>${fields()}<button class="adm-btn adm-btn-primary" type="submit">创建论坛</button></form></details></div>
      <p data-board-message role="status" aria-live="polite"></p>
      ${boards.map(board=>`<section class="adm-panel" data-board-key="${esc(board.key)}">
        <h3 class="adm-panel-title">${esc(board.label)} <small>${board.visibility==='private'?'私密':'公开'} · ${board.state==='closed'?'已关闭':'开放中'}</small></h3>
        <p>${board.topic_count} 篇帖子 · ${board.member_count} 位受邀成员 ${board.state==='open'?`· <a href="/forum/?category=${esc(board.key)}" target="_blank" rel="noopener">进入论坛 ↗</a>`:''}</p>
        <form data-board-edit>${fields(board)}<div class="adm-toolbar">
          <button class="adm-btn adm-btn-primary" type="submit">保存设置</button>
          <button class="adm-btn" type="button" data-board-toggle>${board.state==='open'?'关闭论坛':'重新开放'}</button></div></form>
        <details ${board.visibility==='private'?'open':''}><summary>受邀成员</summary>
          <form data-board-invite><label class="adm-field">邀请已注册账号（用户名，用逗号或换行分隔）<textarea class="adm-input" name="usernames" rows="2" required placeholder="例如：alice，bob"></textarea></label><button class="adm-btn" type="submit">邀请进入</button></form>
          <div class="adm-toolbar">${board.members.map(m=>`<span>@${esc(m.username)} <button type="button" class="adm-btn adm-btn-sm" data-board-revoke="${esc(m.username)}" aria-label="撤销 ${esc(m.username)} 的邀请">撤销邀请</button></span>`).join('')||'<p>尚未邀请成员</p>'}</div>
        </details></section>`).join('')}`;
  }
  async function mount(root,api){
    const scope=Symbol();root._forumBoardScope=scope;
    let boards=[],busy=false;
    const active=()=>root.isConnected&&root._forumBoardScope===scope;
    const message=text=>{if(active())root.querySelector('[data-board-message]').textContent=text;};
    const load=async()=>{const result=await api('/api/admin/forum-boards');if(!active())return;boards=result.items;root.innerHTML=render(boards);};
    const apply=async(path,body,text)=>{
      if(busy)return;busy=true;
      root.querySelectorAll('button').forEach(b=>b.disabled=true);
      try{await api(path,{method:'POST',body});await load();message(text);}
      catch(error){message(error.message||'保存失败，请重试');}
      finally{busy=false;if(active())root.querySelectorAll('button').forEach(b=>b.disabled=false);}
    };
    const boardFor=el=>boards.find(b=>b.key===el.closest('[data-board-key]')?.dataset.boardKey);
    const settings=board=>({label:board.label,description:board.description,visibility:board.visibility,state:board.state,revision:board.revision});
    root.onsubmit=event=>{
      event.preventDefault();const form=event.target;
      if(form.matches('[data-board-create]')){void apply('/api/admin/forum-boards',{label:form.elements.label.value,description:form.elements.description.value,visibility:form.elements.visibility.value},'论坛已创建');return;}
      const board=boardFor(form);if(!board)return;
      if(form.matches('[data-board-edit]'))void apply('/api/admin/forum-boards/'+board.key,{...settings(board),label:form.elements.label.value,description:form.elements.description.value,visibility:form.elements.visibility.value},'论坛设置已保存');
      if(form.matches('[data-board-invite]'))void apply('/api/admin/forum-boards/'+board.key+'/members',{usernames:form.elements.usernames.value.split(/[,，\s]+/).filter(Boolean)},'成员已邀请；对方登录后即可看到论坛入口');
    };
    root.onclick=event=>{
      const toggle=event.target.closest('[data-board-toggle]'),revoke=event.target.closest('[data-board-revoke]');
      const board=boardFor(event.target);if(!board)return;
      if(toggle)void apply('/api/admin/forum-boards/'+board.key,{...settings(board),state:board.state==='open'?'closed':'open'},board.state==='open'?'论坛已关闭，内容已保留':'论坛已重新开放');
      if(revoke)void apply('/api/admin/forum-boards/'+board.key+'/members',{action:'revoke',usernames:[revoke.dataset.boardRevoke]},'邀请已撤销，对方将无法继续访问');
    };
    root.innerHTML='<p data-board-message role="status">正在加载论坛…</p>';
    try{await load();}catch(error){message(error.message||'加载失败，请刷新重试');}
  }
  global.HandrawForumBoardsAdmin={mount,render};
})(window);
