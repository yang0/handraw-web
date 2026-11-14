(function(global){
  'use strict';
  const S=global.HANDRAW_SHARED,esc=S.esc;
  const channels={all:'全站',styles:'画风',layouts:'图型',colors:'主题色',works:'作品',forum:'社区'};
  const root=document.getElementById('search-root');
  let revision=0,request=null,account='',cursor='',query='',channel='all',sort='relevance';
  const parts=items=>(items||[]).map(p=>p.match?`<mark>${esc(p.text)}</mark>`:esc(p.text)).join('');
  function readURL(){const p=new URLSearchParams(location.search);query=p.get('q')||'';channel=channels[p.get('channel')]?p.get('channel'):'all';sort=p.get('sort')==='newest'?'newest':'relevance';}
  function layout(){
    const topQ=document.getElementById('hw-global-search-input');
    const topCh=document.getElementById('hw-global-search-channel');
    if(topQ)topQ.value=query;
    if(topCh&&channels[channel])topCh.value=channel;
    root.innerHTML=`<header class="hw-search-heading"><p>发现资源与社区经验</p><h1>全站全文搜索</h1></header>
      <form id="search-form" class="hw-search-form"><label class="hw-search-query"><span class="hw-search-label">搜索内容</span><input class="hw-input" type="search" name="q" maxlength="200" required value="${esc(query)}" placeholder="搜索中文关键词、标题、正文或资源编号" autocomplete="off"></label><button class="btn btn-primary">搜索</button></form>
      <div class="hw-search-controls"><div class="hw-pills-row" aria-label="搜索频道">${Object.entries(channels).map(([key,label])=>`<button type="button" class="hw-pill ${channel===key?'is-active':''}" data-search-channel="${key}" aria-pressed="${channel===key}">${label}</button>`).join('')}</div><label class="hw-search-sort">排序<select class="hw-select" id="search-sort"><option value="relevance" ${sort==='relevance'?'selected':''}>相关性</option><option value="newest" ${sort==='newest'?'selected':''}>最新发布</option></select></label></div>
      <p role="status" aria-live="polite" id="search-status"></p><div id="search-results" class="hw-search-results"></div><button type="button" class="btn hw-search-more" id="search-more" hidden>加载更多</button>`;
    root.querySelector('form').onsubmit=e=>{e.preventDefault();query=root.querySelector('[name=q]').value.trim();navigate();};
    root.querySelectorAll('[data-search-channel]').forEach(b=>{b.onclick=()=>{query=root.querySelector('[name=q]').value.trim();channel=b.dataset.searchChannel;navigate();};});
    root.querySelector('#search-sort').onchange=e=>{sort=e.target.value;navigate();};
    root.querySelector('#search-more').onclick=()=>load(true);
  }
  function navigate(){const url=new URL(location.href);url.search='';if(query)url.searchParams.set('q',query);if(channel!=='all')url.searchParams.set('channel',channel);if(sort!=='relevance')url.searchParams.set('sort',sort);history.pushState({},'',url);layout();load();}
  function appendAllChannelSwitch(status){
    if(channel==='all')return;
    const allBtn=document.createElement('button');
    allBtn.type='button';
    allBtn.className='btn btn-sm hw-fulltext-button';
    allBtn.textContent='搜索全站';
    allBtn.onclick=()=>{channel='all';navigate();};
    status.append(' ',allBtn);
  }
  async function load(append=false){
    if(!query){const status=root.querySelector('#search-status');status.textContent='输入关键词，搜索画风、图型、主题色、作品与社区正文。';appendAllChannelSwitch(status);return;}
    const current=++revision;request?.abort();request=new AbortController();
    const status=root.querySelector('#search-status'),results=root.querySelector('#search-results'),more=root.querySelector('#search-more');
    if(!append){results.textContent='';cursor='';}more.hidden=true;status.textContent='正在搜索…';
    const p=new URLSearchParams({q:query,channel,sort});if(append&&cursor)p.set('cursor',cursor);
    try{
      const response=await fetch('/api/search?'+p,{credentials:'include',cache:'no-store',signal:request.signal});const data=await response.json();
      if(current!==revision||!root.isConnected)return;
      if(!response.ok||data.ok===false)throw Object.assign(new Error(data.error||'搜索失败'),{code:data.code});
      for(const hit of data.hits){const article=document.createElement('article');article.className='hw-search-result';
        const url=S.safeHref(hit.url),image=S.safeMediaUrl(hit.image);
        article.innerHTML=`${image?`<a class="hw-search-image" href="${esc(url)}" tabindex="-1" aria-hidden="true"><img data-hw-src="${esc(image)}" alt="" loading="lazy"></a>`:''}<div class="hw-search-result-body"><p class="hw-search-meta"><span>${esc(channels[hit.channel]||'内容')}</span>${hit.code?`<span>${esc(hit.code)}</span>`:''}${hit.author?`<span>${esc(hit.author)}</span>`:''}</p><h2><a href="${esc(url)}">${parts(hit.titleParts)||esc(hit.title)}</a></h2><p class="hw-search-snippet">${parts(hit.snippetParts)}</p></div>`;results.append(article);}
      cursor=data.nextCursor||'';more.hidden=!data.hasMore;
      const count=results.children.length;status.textContent=count?`已显示 ${count} 条结果${data.limited?'，可增加关键词缩小范围':''}`:'没有找到匹配内容，试试更短的关键词或切换频道。';
      appendAllChannelSwitch(status);
      global.HandrawImageLoader?.scan(results);
    }catch(e){if(e.name==='AbortError'||current!==revision)return;status.textContent=e.message;const retry=document.createElement('button');retry.className='btn btn-sm';retry.textContent=e.code==='invalid_search_cursor'?'重新搜索':'重试';retry.onclick=()=>load(false);status.append(' ',retry);appendAllChannelSwitch(status);}
  }
  async function boot(){try{await S.initApp('main',()=>{const next=String(S.App.state?.user?.id||'guest');if(account&&next!==account){revision++;request?.abort();cursor='';layout();load();}account=next;});S.App.view='search';S.renderChrome();readURL();layout();load();}catch(e){root.textContent=e.message;}}
  addEventListener('popstate',()=>{readURL();layout();load();});
  addEventListener('pageshow',e=>{if(e.persisted){revision++;request?.abort();root.querySelector('#search-results')?.replaceChildren();S.refreshFromServer().then(()=>load());}});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)S.refreshFromServer();});
  boot();
})(window);
