(function(global){
  'use strict';
  const labels={styles:'画风',layouts:'图型',colors:'主题色',works:'作品',forum:'社区'};
  const states={queued:'排队中',running:'重建中',swapping:'发布中',succeeded:'已完成',failed:'失败',unknown:'结果待核对'};
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function api(url,body){const r=await fetch(url,{credentials:'include',cache:'no-store',method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok||d.ok===false)throw Error(d.error||'请求失败');return d;}
  async function mount(root){
    let timer;
    async function load(){if(!root.isConnected){clearTimeout(timer);return;}try{
      const data=await api('/api/admin/search');if(!root.isConnected)return;
      root.innerHTML=`<section class="adm-panel"><div class="adm-panel-title"><h2>全文搜索索引</h2><p>引擎${data.available?'正常':'暂不可用'}。重建期间继续使用当前索引，完成后切换。</p></div><div class="adm-actions"><button class="adm-btn adm-btn-primary" data-rebuild="all">重建全站索引</button><button class="adm-btn" data-retry>重试失败增量</button><button class="adm-btn" data-refresh>刷新状态</button></div><div class="adm-table-wrap"><table class="adm-table"><thead><tr><th>频道</th><th>索引片段数</th><th>待同步</th><th>失败</th><th>最早积压</th><th>最近成功</th><th>操作</th></tr></thead><tbody>${data.channels.map(c=>`<tr><td>${labels[c.channel]}</td><td>${c.document_count}</td><td>${c.pending}</td><td>${c.failed}</td><td>${Math.round(c.lag_seconds||0)} 秒</td><td>${esc(c.last_success_at||'尚未同步')}${c.last_error?`<p>${esc(c.last_error)}</p>`:''}</td><td><button class="adm-btn adm-btn-sm" data-rebuild="${c.channel}">全量重建</button></td></tr>`).join('')}</tbody></table></div><h3>最近重建任务</h3>${data.jobs.map(j=>`<p>${labels[j.channel]} · ${states[j.status]||j.status} · ${j.done}/${j.total} · ${esc(j.created_at)} ${j.error?`<span>${esc(j.error)}</span>`:''}</p>`).join('')||'<p>暂无重建任务</p>'}<p role="status" data-index-message></p></section>`;
      root.querySelectorAll('[data-rebuild]').forEach(b=>b.onclick=()=>act(b,'/api/admin/search/rebuild',{channel:b.dataset.rebuild}));root.querySelector('[data-retry]').onclick=e=>act(e.target,'/api/admin/search/retry',{});root.querySelector('[data-refresh]').onclick=load;
    }catch(e){if(root.isConnected)root.textContent=e.message;}clearTimeout(timer);if(root.isConnected)timer=setTimeout(load,5000);}
    async function act(button,url,body){button.disabled=true;try{await api(url,body);await load();root.querySelector('[data-index-message]').textContent='操作已提交。';}catch(e){const m=root.querySelector('[data-index-message]');if(m)m.textContent=e.message;button.disabled=false;}}
    await load();
  }
  global.HandrawSearchAdmin={mount};
})(window);
