/* Handraw private cloud center: personal style/layout definitions and private history. */
(function () {
  "use strict";
  const rootSelector = "#hw-private-cloud-center";
  const escapeHtml = (value) => String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
  const printable = (value) => escapeHtml(value).replace(/\n/g, "<br>");
  const safeImage = (item) => {
    const url = typeof item === "string" ? item : (item && (item.url || item.imageUrl));
    return typeof url === "string" && /^\/(?:uploads|generated|images)\/[a-z0-9/_\.%-]+$/i.test(url) ? url : "";
  };
  const state = () => ({
    resources: [], history: [], resourcesCursor: null, historyCursor: null,
    editing: null, isBusy: false
  });
  function editor(resource) {
    const form = document.querySelector(rootSelector + " [data-cloud-editor]");
    if (!form) return;
    form.hidden = false;
    form.style.display = "grid";
    form.elements.kind.value = resource ? resource.kind : "style";
    form.elements.name.value = resource ? resource.name : "";
    form.elements.zh.value = resource ? resource.definition.zh : "";
    form.elements.en.value = resource ? resource.definition.en : "";
    form.elements.license.value = resource ? resource.license : "个人使用";
    form.elements.version.value = resource ? resource.version : "1.0.0";
    form.elements.examples.value = resource ? (resource.examples || []).join("\n") : "";
    form.dataset.id = resource ? resource.id : "";
    form.dataset.revision = resource ? String(resource.revision) : "";
    form.dataset.origin = resource ? JSON.stringify(resource.origin || null) : "null";
    form.querySelector("[data-cloud-editor-heading]").textContent = resource ? "编辑私有资源" : "新建私有资源";
    form.elements.name.focus();
  }
  function renderLists(container, data) {
    const list = container.querySelector("[data-cloud-resources]");
    list.innerHTML = data.resources.length ? data.resources.map((resource) => `
      <article class="hw-detail-section-card" style="padding:14px;margin-bottom:10px;">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
          <div style="min-width:0;">
            <strong>${escapeHtml(resource.name)}</strong>
            <div style="font-size:12px;color:var(--ink-muted);">
              ${resource.kind === "layout" ? "自建图型" : "自建画风"} · v${escapeHtml(resource.version)}
              · 修订 ${Number(resource.revision) || 1}
              · <span>仅自己可见</span>
            </div>
          </div>
          <button type="button" class="btn btn-sm" data-cloud-edit="${escapeHtml(resource.id)}">编辑</button>
        </div>
      </article>`).join("") :
      '<p style="color:var(--ink-muted);">暂无自建画风和图型。你可以在 Skill 创建后同步，也可以在这里新建。</p>';
    const moreResources = container.querySelector("[data-cloud-more-resources]");
    moreResources.hidden = !data.resourcesCursor;
    const history = container.querySelector("[data-cloud-history]");
    history.innerHTML = data.history.length ? data.history.map((run) => {
      const links = Array.isArray(run.images) ? run.images.slice(0, 6).map(safeImage).filter(Boolean) : [];
      return `<article class="hw-detail-section-card" style="padding:14px;margin-bottom:10px;">
        <div><strong>${run.originClient === "skill" ? "Skill 创作" : "网站创作"}</strong>
        <span style="color:var(--ink-muted);font-size:12px;"> · ${escapeHtml(run.status)} · ${escapeHtml(run.createdAt)}</span></div>
        <p style="white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;margin:8px 0;color:var(--ink-body);">${escapeHtml((run.originalRequest || "").slice(0, 180))}</p>
        ${links.length ? '<div style="display:flex;gap:8px;overflow-x:auto;">' +
          links.map((url) => '<img loading="lazy" alt="生成结果" src="' + escapeHtml(url) +
            '" style="width:80px;height:80px;object-fit:cover;border-radius:8px;" />').join("") + '</div>' : ""}
        ${run.canPublish ? '<button type="button" class="btn btn-primary btn-sm" style="margin-top:10px;" data-cloud-publish="' +
           escapeHtml(run.id) + '">选择并发布到作品广场</button>' : ""}
        ${run.publishedWorkId ? '<a class="btn btn-sm" style="margin-top:10px;" href="/?view=work&id=' +
          encodeURIComponent(run.publishedWorkId) + '">查看已发布作品</a>' : ""}
      </article>`;
    }).join("") : '<p style="color:var(--ink-muted);">暂无云端生成历史。</p>';
    container.querySelector("[data-cloud-more-history]").hidden = !data.historyCursor;
  }
  async function mount(container, api) {
    if (!container || typeof api !== "function") return;
    const data = state();
    container.innerHTML = `
      <div class="hw-cloud-center" id="hw-private-cloud-center">
        <p style="color:var(--ink-muted);margin:0 0 18px;">你的私有画风、图型和创作历史可以从 Skill 同步到同一 Handraw 账号；同步不会自动公开发布。</p>
        <p data-cloud-status role="status" aria-live="polite" style="min-height:1.5em;color:var(--ink-muted);"></p>
        <section>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
            <h3 style="margin:0;">我的画风与图型</h3>
            <button type="button" class="btn btn-primary btn-sm" data-cloud-new>新建私有资源</button>
          </div>
          <div data-cloud-resources style="margin-top:12px;"></div>
          <button type="button" class="btn btn-sm" data-cloud-more-resources hidden>加载更多资源</button>
        </section>
        <form data-cloud-editor hidden style="border:1px solid var(--line,#ddd);border-radius:12px;padding:16px;margin:18px 0;display:none;gap:10px;">
          <h3 data-cloud-editor-heading style="margin:0;">新建私有资源</h3>
          <label>资源类型 <select name="kind" required><option value="style">画风</option><option value="layout">图型</option></select></label>
          <label>名称 <input name="name" required maxlength="120" style="width:100%;" /></label>
          <label>中文定义 <textarea name="zh" required maxlength="16000" rows="4" style="width:100%;"></textarea></label>
          <label>英文定义 <textarea name="en" required maxlength="16000" rows="4" style="width:100%;"></textarea></label>
          <label>许可说明 <input name="license" maxlength="2000" required style="width:100%;" /></label>
          <label>版本 <input name="version" maxlength="50" required value="1.0.0" style="width:100%;" /></label>
          <label>示例（每行一个） <textarea name="examples" rows="2" style="width:100%;"></textarea></label>
          <div style="display:flex;gap:10px;">
            <button type="submit" class="btn btn-primary btn-sm">保存到私有云空间</button>
            <button type="button" class="btn btn-sm" data-cloud-cancel>取消</button>
          </div>
        </form>
        <section style="margin-top:24px;">
          <h3>我的生成历史</h3>
          <p style="color:var(--ink-muted);font-size:13px;">这里只对账号本人显示云端记录。历史不等于公开作品；只有明确发布后才进入作品广场。</p>
          <div data-cloud-history></div>
          <button type="button" class="btn btn-sm" data-cloud-more-history hidden>加载更多历史</button>
        </section>
      </div>`;
    const shell = container.querySelector(rootSelector);
    const status = (text, error = false) => {
      if (!shell.isConnected) return;
      const node = shell.querySelector("[data-cloud-status]");
      node.textContent = text;
      node.style.color = error ? "var(--vermilion)" : "var(--ink-muted)";
    };
    async function loadResources(more = false) {
      const path = "/api/v1/me/resources?limit=100" + (more && data.resourcesCursor ? "&since=" + encodeURIComponent(data.resourcesCursor) : "");
      const response = await api(path);
      if (!shell.isConnected) return;
      const rows = (response.items || []).filter((x) => !x.deletedAt);
      data.resources = more ? data.resources.concat(rows) : rows;
      data.resourcesCursor = response.hasMore ? response.nextCursor : null;
      renderLists(shell, data);
    }
    async function loadHistory(more = false) {
      const path = "/api/v1/me/generations?limit=50" + (more && data.historyCursor ? "&cursor=" + encodeURIComponent(data.historyCursor) : "");
      const response = await api(path);
      if (!shell.isConnected) return;
      data.history = more ? data.history.concat(response.items || []) : (response.items || []);
      data.historyCursor = response.hasMore ? response.nextCursor : null;
      renderLists(shell, data);
    }
    async function run(work, successMessage = "已同步。所有个人定义默认私有。") {
      if (data.isBusy) return;
      data.isBusy = true;
      status("正在处理…");
      try {
        await work();
        status(successMessage);
      } catch (error) {
        status(error && error.message ? error.message : "网络暂时不可用，请重试。", true);
      } finally {
        data.isBusy = false;
      }
    }
    shell.querySelector("[data-cloud-new]").addEventListener("click", () => editor(null));
    shell.querySelector("[data-cloud-cancel]").addEventListener("click", () => {
      shell.querySelector("[data-cloud-editor]").hidden = true;
      shell.querySelector("[data-cloud-editor]").style.display = "none";
    });
    shell.addEventListener("click", (event) => {
      const edit = event.target.closest("[data-cloud-edit]");
      if (edit) {
        const resource = data.resources.find((r) => r.id === edit.dataset.cloudEdit);
        if (resource) editor(resource);
        return;
      }
      const publish = event.target.closest("[data-cloud-publish]");
      if (publish) {
        const item = data.history.find((r) => r.id === publish.dataset.cloudPublish);
        if (!item || !item.canPublish || data.isBusy) return;
        const title = window.prompt("请输入作品标题（将对所有访客公开）", "我的 Handraw 作品");
        if (title === null || !title.trim()) return;
        const prompt = window.prompt("请编辑并确认即将公开的提示词。不要包含隐私或商业机密。", item.originalRequest || "");
        if (prompt === null || !prompt.trim()) return;
        const images = Array.isArray(item.images) ? item.images : [];
        const count = Math.min(images.length, 9);
        if (!count || !window.confirm(
          "即将公开标题、你确认的提示词和前 " + count + " 张图片。发布后其他用户可查看，确定继续吗？"
        )) return;
        run(async () => {
          const response = await api(
            "/api/v1/me/generations/" + encodeURIComponent(item.id) + "/publish",
            { method: "POST", body: { title: title.trim(), prompt, confirmed: true,
              indices: Array.from({ length: count }, (_, i) => i) } }
          );
          item.canPublish = false;
          item.publishedWorkId = response.workId;
          renderLists(shell, data);
        }, "作品发布成功，可在个人主页和作品广场查看。");
      }
    });
    shell.querySelector("[data-cloud-more-resources]").addEventListener("click", () => run(() => loadResources(true)));
    shell.querySelector("[data-cloud-more-history]").addEventListener("click", () => run(() => loadHistory(true)));
    shell.querySelector("[data-cloud-editor]").addEventListener("submit", (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      if (!form.reportValidity()) return;
      run(async () => {
        const id = form.dataset.id || (window.crypto && crypto.randomUUID ? crypto.randomUUID() : "");
        if (!id) throw new Error("当前浏览器不支持安全创建资源 ID");
        const payload = {
          id, kind: form.elements.kind.value, name: form.elements.name.value.trim(),
          definition: { zh: form.elements.zh.value, en: form.elements.en.value },
          license: form.elements.license.value, version: form.elements.version.value,
          examples: form.elements.examples.value.split(/\r?\n/).map(x => x.trim()).filter(Boolean),
          origin: JSON.parse(form.dataset.origin || "null"),
          visibility: "private", schemaVersion: 1
        };
        if (form.dataset.revision) payload.baseRevision = Number(form.dataset.revision);
        await api("/api/v1/me/resources/" + encodeURIComponent(id), { method: "PUT", body: payload });
        form.hidden = true;
        form.style.display = "none";
        await loadResources();
      });
    });
    await run(async () => { await Promise.all([loadResources(), loadHistory()]); });
  }
  window.HandrawCloudCenter = { mount };
})();
