/* Standalone account recovery, notifications, guides and owner editors. */
(function () {
  "use strict";
  const S = window.HANDRAW_SHARED;
  const views = new Set(["guide", "recovery", "reset-password", "verify-email", "notifications", "edit-work", "edit-topic"]);
  const linkToken = new URLSearchParams(location.search).get("token") || "";
  let activeRender = 0;
  const mainUrl = (view, extra = {}) => S.channelUrl("main", { view, ...extra });
  const esc = S.esc;

  function safeHtml(value) {
    const template=document.createElement("template");template.innerHTML=String(value||"");
    const allowed=new Set("p br div span h1 h2 h3 h4 h5 h6 strong b em i u s ul ol li blockquote pre code a img figure figcaption hr table thead tbody tr th td".split(" "));
    for(const node of [...template.content.querySelectorAll("*")]){
      const tag=node.tagName.toLowerCase();
      if(!allowed.has(tag)){if(["script","style","iframe","object","embed","svg","math","link","meta"].includes(tag))node.remove();else node.replaceWith(...node.childNodes);continue;}
      for(const attr of [...node.attributes]){
        const name=attr.name.toLowerCase(),value=attr.value.trim();
        if(name==="href" || name==="src"){
          const local=value.startsWith("/")&&!value.startsWith("//");
          const external=/^https?:\/\//i.test(value);
          const inlineImage=name==="src" && /^data:image\/(png|jpeg|webp|gif);base64,[a-z0-9+/=\s]+$/i.test(value);
          if(!local&&!external&&!inlineImage)node.removeAttribute(attr.name);
        }else if(!["class","alt","title","colspan","rowspan"].includes(name) && !/^data-(card-|media-)/.test(name))node.removeAttribute(attr.name);
      }
      if(tag==="a")node.setAttribute("rel","noopener noreferrer");
    }
    return template.innerHTML;
  }

  function shell(root, title, body) {
    root.innerHTML = `<section class="hw-account-page"><div class="hw-subpage-bar"><a class="btn btn-sm" href="${esc(mainUrl("styles"))}">← 返回画风库</a></div><h1>${esc(title)}</h1>${body}<p id="account-feedback" role="status" aria-live="polite"></p></section>`;
  }
  function feedback(root, message, error = false) {
    const el = root.querySelector("#account-feedback");
    if (el) { el.textContent = message; el.classList.toggle("is-error", error); }
  }
  function bindForm(root, fn) {
    root.querySelector("form").onsubmit = async (event) => {
      event.preventDefault();
      const button = event.currentTarget.querySelector('[type="submit"]');
      button.disabled = true;
      try { await fn(new FormData(event.currentTarget)); }
      catch (error) { feedback(root, error.message, true); }
      finally { if (button.isConnected) button.disabled = false; }
    };
  }
  function targetUrl(item) {
    if(item.kind==="system")return S.channelUrl("admin",{module:"gateway"});
    if(item.target_type==="generation"){
      const u = S.App.state?.user?.username || "";
      return S.channelUrl("main", u ? { view: "profile", user: u, ptab: "generations" } : { view: "auth" });
    }
    if (item.target_type === "topic") return S.channelUrl("forum", { view:"topic",id:item.target_id });
    if (item.target_type === "work") return mainUrl("work",{id:item.target_id});
    if (item.target_type === "asset" || item.target_type === "style" || item.target_type === "layout") return mainUrl("asset",{id:item.target_id});
    return mainUrl("wallet");
  }

  async function render(root, view) {
    const generation = ++activeRender;
    const currentUser = S.App.state?.user?.id || null;
    const isCurrent = () => generation === activeRender && (S.App.state?.user?.id || null) === currentUser;
    if (!views.has(view)) return false;
    if (view === "guide") {
      shell(root,"从一张图开始",`<p class="hw-lead">选一种画风，写下主题，成功生成的公开作品自动展示在作品广场，有人评论后进入论坛。请勿上传不希望公开的内容。</p><ol class="hw-guide-steps"><li><h2>选画风和图型</h2><p>画风决定笔触与质感，图型决定排版结构。也可以只选其中一种，或自由创作。</p><a class="btn" href="${esc(mainUrl("styles"))}">浏览画风</a> <a class="btn" href="${esc(mainUrl("layouts"))}">浏览图型</a></li><li><h2>输入主题与参考</h2><p>在创作台写清主体、场景和需要出现的文字，设置比例。需要保持人物或物件时，再加入参考图片。</p><a class="btn btn-primary" href="${esc(S.channelUrl("studio"))}">进入创作台</a></li><li><h2>确认费用并生成</h2><p>运行前查看本批张数与额度，等待真实任务完成。暂时离开后，可以回到创作台继续查看任务。</p></li><li><h2>保存或分享</h2><p>先检查成图与文字，再下载保存。点击晒图或发布到论坛才会公开相关内容，请确认图片和素材的使用权。</p><a class="btn" href="${esc(S.channelUrl("forum"))}">进入社区</a></li></ol><h2>常用帮助</h2><p><a href="${esc(mainUrl("skill"))}">Skill 与本地个人库同步</a> · <a href="${esc(mainUrl("recovery"))}">找回密码</a></p>`);
      const tutorials=document.createElement("section");tutorials.innerHTML='<h2>官方教程</h2><p>正在读取教程索引…</p>';root.querySelector(".hw-account-page").append(tutorials);
      try{const guides=await S.apiJson("/api/guides");if(!isCurrent())return true;
        tutorials.innerHTML='<h2>官方教程</h2>'+guides.items.map(g=>`<article class="hw-detail-section-card"><a href="${esc(g.url)}" target="_blank" rel="noopener noreferrer">${esc(g.title)} ↗</a><p>${esc(g.summary)}</p></article>`).join("");
      }catch(error){tutorials.textContent="教程索引暂时无法读取，请稍后重试。";}
      return true;
    }
    if (view === "recovery") {
      shell(root,"找回密码",`<p>输入注册邮箱，我们会发送一次性重置链接。</p><form class="hw-account-form"><label>注册邮箱<input class="hw-input" name="email" type="email" autocomplete="email" required></label><button class="btn btn-primary" type="submit">发送重置邮件</button></form><p><a href="${esc(mainUrl("auth"))}">返回登录</a></p>`);
      bindForm(root,async data=>{ const result=await S.apiJson("/api/auth/forgot-password",{method:"POST",body:{email:data.get("email")}});feedback(root,result.message); });
      return true;
    }
    if (view === "reset-password") {
      shell(root,"设置新密码",`<form class="hw-account-form"><label>新密码<input class="hw-input" name="password" type="password" minlength="8" autocomplete="new-password" required></label><label>再次输入新密码<input class="hw-input" name="confirm" type="password" minlength="8" autocomplete="new-password" required></label><button class="btn btn-primary" type="submit">重置密码</button></form>`);
      bindForm(root,async data=>{
        if(data.get("password")!==data.get("confirm")) throw new Error("两次输入的密码不一致");
        const result=await S.apiJson("/api/auth/reset-password",{method:"POST",body:{token:linkToken,password:data.get("password")}});
        if(isCurrent()){shell(root,"密码已重置",`<p>${esc(result.message)}</p><a class="btn btn-primary" href="${esc(mainUrl("auth"))}">重新登录</a>`);}
      });
      return true;
    }
    if(view==="verify-email" && linkToken){
      shell(root,"验证邮箱",`<p>确认后完成邮箱验证。链接仅能使用一次。</p><form><button class="btn btn-primary" type="submit">确认验证</button></form>`);
      bindForm(root,async()=>{const result=await S.apiJson("/api/auth/verify-email",{method:"POST",body:{token:linkToken}});feedback(root,result.message);});
      return true;
    }
    if(!S.App.state?.loggedIn){
      shell(root,"请先登录",`<p>此页面仅供当前账号访问。</p><a class="btn btn-primary" href="${esc(mainUrl("auth"))}">登录账号</a>`);return true;
    }
    if(view==="verify-email"){
      shell(root,"邮箱验证",`<p>正在检查邮箱状态…</p>`);
      try{
        const status=await S.apiJson("/api/account/status");if(!isCurrent())return true;
        shell(root,"邮箱验证",`<p>当前邮箱：${esc(status.email || "尚未填写")}</p><p>${status.emailVerified?"已验证":"尚未验证"}</p>${status.emailVerified?"":'<form><button class="btn btn-primary" type="submit">发送验证邮件</button></form>'}`);
        if(!status.emailVerified)bindForm(root,async()=>{const r=await S.apiJson("/api/auth/send-verification",{method:"POST",body:{}});feedback(root,r.message);});
      }catch(e){if(isCurrent())feedback(root,e.message,true);}
      return true;
    }
    if(view==="notifications"){
      shell(root,"消息通知",`<p>正在读取消息…</p>`);
      try{
        const result=await S.apiJson("/api/notifications");if(!isCurrent())return true;
        shell(root,"消息通知",`<p>${result.unread} 条未读消息</p><button class="btn" id="notifications-read-all">全部标为已读</button><div class="hw-notification-list">${result.items.map(n=>`<article class="hw-detail-section-card ${n.read_at?"":"is-unread"}"><a href="${esc(targetUrl(n))}" data-notification-id="${n.id}">${esc(n.title)}</a><small>${esc(n.created_at)}</small></article>`).join("")||'<p class="hw-empty-state">暂时没有新消息。收到回复、评论或处理结果后，会出现在这里。</p>'}</div>${result.nextBefore?'<button class="btn" id="notifications-more">加载更早消息</button>':""}`);
        root.querySelector("#notifications-read-all").onclick=async()=>{await S.apiJson("/api/notifications/read",{method:"POST",body:{all:true}});render(root,view);};
        root.querySelectorAll("[data-notification-id]").forEach(a=>a.addEventListener("click",()=>{S.apiJson("/api/notifications/read",{method:"POST",body:{id:Number(a.dataset.notificationId)}}).catch(()=>{});}));
        let before=result.nextBefore;
        const more=root.querySelector("#notifications-more");
        if(more)more.onclick=async()=>{
          more.disabled=true;
          try{const page=await S.apiJson(`/api/notifications?before=${before}`);if(!isCurrent())return;
            const list=root.querySelector(".hw-notification-list");
            page.items.forEach(n=>{const article=document.createElement("article");article.className="hw-detail-section-card";const a=document.createElement("a");a.href=targetUrl(n);a.textContent=n.title;a.onclick=()=>S.apiJson("/api/notifications/read",{method:"POST",body:{id:n.id}}).catch(()=>{});article.append(a);list.append(article);});before=page.nextBefore;more.hidden=!before;
          }catch(e){feedback(root,e.message,true);}finally{more.disabled=false;}
        };
      }catch(e){if(isCurrent())feedback(root,e.message,true);}
      return true;
    }
    if(view==="edit-work" || view==="edit-topic"){
      const kind=view==="edit-work"?"works":"topics";
      const id=new URLSearchParams(location.search).get("id")||"";
      shell(root,"编辑我的内容","<p>正在读取…</p>");
      try{
        const {item}=await S.apiJson(`/api/content/${kind}/${encodeURIComponent(id)}/edit`);if(!isCurrent())return true;
        shell(root,kind==="works"?"编辑我的作品":"编辑我的帖子",`<form class="hw-account-form"><label>标题<input class="hw-input" name="title" value="${esc(item.title)}" minlength="4" maxlength="140" required></label>${kind==="works"?`<label>实际提示词<textarea class="hw-textarea" name="prompt" rows="9" required>${esc(item.prompt)}</textarea></label><label>创作说明<textarea class="hw-textarea" name="notes" rows="5">${esc(item.notes)}</textarea></label>`:'<label>公开正文<div class="hw-owner-rich-editor" id="owner-public-body" contenteditable="true" role="textbox" aria-multiline="true"></div></label>'+(item.price>0?'<label>解锁正文<div class="hw-owner-rich-editor" id="owner-locked-body" contenteditable="true" role="textbox" aria-multiline="true"></div></label>':"")}<p>本次编辑保留原有图片、价格与解锁记录。</p><button class="btn btn-primary" type="submit">保存修改</button></form>`);
        if(kind==="topics"){
          root.querySelector("#owner-public-body").innerHTML=safeHtml(item.summary);
          const locked=root.querySelector("#owner-locked-body");if(locked)locked.innerHTML=safeHtml(item.locked_body);
        }
        bindForm(root,async data=>{
          const payload={title:data.get("title")};
          if(kind==="works"){payload.prompt=data.get("prompt");payload.notes=data.get("notes");}
          else {payload.body=root.querySelector("#owner-public-body").innerHTML;payload.lockedBody=root.querySelector("#owner-locked-body")?.innerHTML||"";}
          await S.apiJson(`/api/content/${kind}/${encodeURIComponent(id)}/edit`,{method:"POST",body:payload});
          location.href=kind==="works"?mainUrl("work",{id}):S.channelUrl("forum",{view:"topic",id});
        });
      }catch(e){if(isCurrent())feedback(root,e.message,true);}
    }
    return true;
  }

  function mountLinks(){
    const nav=document.querySelector(".hw-topbar") || document.querySelector("#hw-topbar-mount");
    const navKey=String(S.App.state?.user?.id || "guest");
    if(nav && nav.querySelector("[data-account-tools-nav]")?.dataset.accountKey!==navKey){
      nav.querySelector("[data-account-tools-nav]")?.remove();
      const group=document.createElement("span");group.dataset.accountToolsNav="1";group.dataset.accountKey=navKey;group.className="hw-account-quicklinks";
      group.innerHTML=`<a href="https://github.com/yang0/handraw-style" target="_blank" rel="noopener noreferrer">GitHub ↗</a>${S.App.state?.loggedIn?`<a href="${esc(mainUrl("notifications"))}">消息</a>`:""}`;
      nav.append(group);
    }
    const login=document.querySelector("#login-demo-password");
    if(login && !document.querySelector("[data-account-recovery]")){
      const a=document.createElement("a");a.dataset.accountRecovery="1";a.href=mainUrl("recovery");a.textContent="忘记密码？";login.parentElement.append(a);
    }
    const account=document.querySelector("#standalone-account-settings-form");
    if(account && !account.querySelector("[data-account-verify]")){
      const a=document.createElement("a");a.dataset.accountVerify="1";a.className="btn btn-sm";a.href=mainUrl("verify-email");a.textContent="验证邮箱";account.append(a);
    }
    for(const [selector,items,view] of [["#standalone-work-detail-page",S.App.state?.works,"edit-work"],["#standalone-topic-detail-page",S.App.state?.topics,"edit-topic"]]){
      const page=document.querySelector(selector);
      if(!page || page.querySelector('[data-owner-edit]') || !S.App.state?.loggedIn)continue;
      const id=new URLSearchParams(location.search).get("id")||"";
      const item=(items||[]).find(i=>i.id===id);
      if(!item || item.author!==S.App.state.user?.username)continue;
      const a=document.createElement("a");a.dataset.ownerEdit="1";a.className="btn btn-sm";a.href=mainUrl(view,{id});a.textContent="编辑我的内容";
      (page.querySelector('.hw-subpage-bar')||page).append(a);
    }
  }
  let scheduled=false;
  new MutationObserver(()=>{if(scheduled)return;scheduled=true;requestAnimationFrame(()=>{scheduled=false;mountLinks();});}).observe(document.body,{childList:true,subtree:true});
  window.HandrawAccountTools={views,render,mainUrl,safeHtml};
  mountLinks();
})();
