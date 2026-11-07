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
    return typeof url === "string" && (
      /^\/api\/library\/assets\/[0-9a-f-]{36}\/image$/i.test(url) ||
      /^\/(?:uploads|generated|images)\/[a-z0-9/_\.%-]+$/i.test(url)
    ) ? url : "";
  };
  const state = () => ({
    resources: [], history: [], assets: [], collections: [],
    resourcesCursor: null, historyCursor: null, assetsCursor: null,
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
    const assets = container.querySelector("[data-cloud-assets]");
    assets.innerHTML = data.assets.length ? data.assets.map((item) => {
      const url = safeImage(item.imageUrl || item.publicUrl); // Always prefer owner-authenticated image endpoint.
      return `<article class="hw-detail-section-card" style="padding:10px;min-width:105px;width:130px;">
        ${url ? '<img loading="lazy" alt="' + escapeHtml(item.name) + '" src="' + escapeHtml(url) +
          '" style="width:100%;aspect-ratio:1;object-fit:cover;border-radius:7px;" />' : ""}
        <strong style="font-size:12px;overflow-wrap:anywhere;">${escapeHtml(item.name || item.localId || item.uid)}</strong>
        <div style="font-size:11px;color:var(--ink-muted);">${escapeHtml(item.cat)}</div>
      </article>`;
    }).join("") : '<p style="color:var(--ink-muted);">尚无云端个人素材。可以从 Skill 的自建图库同步。</p>';
    container.querySelector("[data-cloud-more-assets]").hidden = !data.assetsCursor;
    const collections = container.querySelector("[data-cloud-collections]");
    collections.innerHTML = data.collections.length ? data.collections.map(item => `
      <article class="hw-detail-section-card" style="padding:11px;margin-bottom:7px;">
        <strong>${escapeHtml(item.name || item.title || item.ref)}</strong>
        <span style="font-size:12px;color:var(--ink-muted);">
          · ${item.kind === "layout" ? "图型" : "画风"}
          · ${item.unlocked && item.syncEligible ? "已授权，可同步 Skill" : item.unlocked ? "已获取，暂不可离线导出" : "仅收藏，未解锁完整定义"}
        </span>
      </article>`).join("") : '<p style="color:var(--ink-muted);">暂无已收藏或已获取资源。</p>';
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
        ${run.publishedWorkId ? '<a class="btn btn-sm" style="margin-top:10px;" href="/?view=work&id=' +
          encodeURIComponent(run.publishedWorkId) + '">查看公开作品</a>' : ""}
      </article>`;
    }).join("") : '<p style="color:var(--ink-muted);">暂无云端生成历史。</p>';
    container.querySelector("[data-cloud-more-history]").hidden = !data.historyCursor;
  }
  async function mount(container, api) {
    if (!container || typeof api !== "function") return;
    const data = state();
    container.innerHTML = `
      <div class="hw-cloud-center" id="hw-private-cloud-center">
        <p style="color:var(--ink-muted);margin:0 0 18px;">你的自建画风、图型与个人图库仍属于私有资源；网站成功生成的图片和 Skill 主动上传的作品会直接公开展示。</p>
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
          <h3>我的图库</h3>
          <p style="color:var(--ink-muted);font-size:13px;">Skill 自建角色、道具和场景同步后，会保留到你的私有图库。这里仅展示本人素材。</p>
          <div data-cloud-assets style="display:flex;flex-wrap:wrap;gap:10px;"></div>
          <button type="button" class="btn btn-sm" data-cloud-more-assets hidden>加载更多素材</button>
        </section>
        <section style="margin-top:24px;">
          <h3>我的画风与图型收藏</h3>
          <p style="color:var(--ink-muted);font-size:13px;">收藏与完整访问资格不同。已解锁且允许离线使用的定义才能同步到 Skill。</p>
          <div data-cloud-collections></div>
        </section>
        <section style="margin-top:24px;">
          <h3>我的生成历史</h3>
          <p style="color:var(--ink-muted);font-size:13px;">历史详情仅本人查看；网站新成功生成的图片与 Skill 上传的作品会自动进入公开作品列表。旧私有历史不会自动公开。</p>
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
    async function loadAssets(more = false) {
      const path = "/api/library/assets?limit=100" + (more && data.assetsCursor ?
        "&since=" + encodeURIComponent(data.assetsCursor) : "");
      const response = await api(path);
      if (!shell.isConnected) return;
      const rows = (response.items || []).filter(item => !item.deletedAt);
      data.assets = more ? data.assets.concat(rows) : rows;
      data.assetsCursor = response.hasMore ? response.nextCursor : null;
      renderLists(shell, data);
    }
    async function loadCollections() {
      const response = await api("/api/v1/me/collection-items");
      if (!shell.isConnected) return;
      data.collections = response.items || [];
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
    });
    shell.querySelector("[data-cloud-more-resources]").addEventListener("click", () => run(() => loadResources(true)));
    shell.querySelector("[data-cloud-more-history]").addEventListener("click", () => run(() => loadHistory(true)));
    shell.querySelector("[data-cloud-more-assets]").addEventListener("click", () => run(() => loadAssets(true)));
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
    await run(async () => {
      await Promise.all([loadResources(), loadHistory(), loadAssets(), loadCollections()]);
    });
  }

  // Profile > 创作资源 > 我的图库: private user-owned assets from the same
  // API as Skill synchronization and Account > 个人云空间.
  async function mountGallery(container, api) {
    if (!container || typeof api !== "function") return;
    let items = [], cursor = null, category = "all", busy = false;
    const cats = [["all","全部素材"],["characters","角色"],["props","道具"],["scenes","场景"],["other","其他"]];
    const catNames = Object.fromEntries(cats);
    container.innerHTML =
      '<section class="hw-personal-gallery" aria-label="我的图库">' +
        '<div class="hw-personal-gallery-intro"><div><h3>我的图库</h3>' +
          '<p>私人素材仅自己可见。与 Skill 自建图库双向同步，也可以在这里直接添加图片。</p></div>' +
          '<label class="btn btn-primary btn-sm">添加图片' +
            '<input data-gallery-file type="file" accept="image/png,image/jpeg,image/webp" hidden /></label></div>' +
        '<div class="hw-personal-gallery-controls"><div class="hw-pills-row" aria-label="图库分类">' +
          cats.map(function (c) {
            return '<button type="button" class="hw-pill" data-gallery-category="' + c[0] +
              '">' + c[1] + '</button>';
          }).join("") +
          '</div><span data-gallery-message role="status" aria-live="polite"></span></div>' +
        '<div class="hw-personal-gallery-grid" data-gallery-cards></div>' +
        '<div class="hw-personal-gallery-footer"><button type="button" class="btn btn-sm" data-gallery-more hidden>加载更多素材</button></div>' +
      '</section>';
    const cards = container.querySelector("[data-gallery-cards]");
    const more = container.querySelector("[data-gallery-more]");
    const fileInput = container.querySelector("[data-gallery-file]");
    function message(msg, error) {
      const node = container.querySelector("[data-gallery-message]");
      if (node) {
        node.textContent = msg;
        node.style.color = error ? "var(--vermilion)" : "var(--ink-muted)";
      }
    }
    function render() {
      if (!container.isConnected) return;
      container.querySelectorAll("[data-gallery-category]").forEach(function (btn) {
        const selected = btn.dataset.galleryCategory === category;
        btn.classList.toggle("is-active", selected);
        btn.setAttribute("aria-pressed", String(selected));
      });
      const visible = items.filter(function (item) {
        return category === "all" || item.cat === category;
      });
      cards.innerHTML = visible.length ? visible.map(function (item) {
        // The scoped image endpoint checks the logged-in owner's identity.
        const img = safeImage(item.imageUrl);
        return '<article class="hw-personal-gallery-card">' +
          '<div class="hw-personal-gallery-image">' +
            (img ? '<img loading="lazy" src="' + escapeHtml(img) +
              '" alt="' + escapeHtml(item.name || "我的图片") + '" />'
              : '<span>暂无预览</span>') + '</div>' +
          '<div class="hw-personal-gallery-card-body"><strong>' +
            escapeHtml(item.name || "未命名素材") + '</strong>' +
            '<small>' + escapeHtml(catNames[item.cat] || "其他") + ' · ' +
              (item.origin === "skill" ? "Skill 同步" : "网站素材") + '</small>' +
            '<div class="hw-personal-gallery-actions">' +
              (img ? '<a class="btn btn-sm" href="' + escapeHtml(img) +
                '" target="_blank" rel="noopener noreferrer">查看原图</a>' : '') +
              '<button class="btn btn-sm" type="button" data-gallery-delete="' +
                escapeHtml(item.uid) + '">删除</button>' +
            '</div></div></article>';
      }).join("") : '<div class="hw-detail-section-card hw-personal-gallery-empty">' +
        (items.length ? "此分类暂无素材" : "图库暂无图片。可从 Skill 自建图库同步，或点击「添加图片」。") +
        '</div>';
      more.hidden = !cursor;
      more.disabled = busy;
    }
    async function load(append) {
      if (busy) return;
      busy = true;
      message("正在加载素材…");
      try {
        const res = await api("/api/library/assets?limit=100" +
          (append && cursor ? "&since=" + encodeURIComponent(cursor) : ""));
        if (!container.isConnected) return;
        const byId = new Map((append ? items : []).map(function (row) { return [row.uid, row]; }));
        (res.items || []).forEach(function (row) {
          if (row.deletedAt) byId.delete(row.uid);
          else byId.set(row.uid, row);
        });
        items = Array.from(byId.values());
        cursor = res.hasMore ? res.nextCursor : null;
        message("已加载 " + items.length + " 张私人素材");
      } catch (err) {
        message("图库加载失败：" + (err.message || "请重试"), true);
      } finally {
        busy = false;
        render();
      }
    }
    container.querySelectorAll("[data-gallery-category]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        category = btn.dataset.galleryCategory || "all";
        render();
      });
    });
    more.addEventListener("click", function () { load(true); });
    cards.addEventListener("click", async function (event) {
      const button = event.target.closest("[data-gallery-delete]");
      if (!button || busy) return;
      const found = items.find(function (i) { return i.uid === button.dataset.galleryDelete; });
      if (!found) return;
      if (typeof window.confirm === "function" &&
          !window.confirm("删除素材「" + (found.name || "未命名") + "」？这会同步删除状态到 Skill。")) return;
      busy = true;
      button.disabled = true;
      try {
        await api("/api/library/assets/" + encodeURIComponent(found.uid) +
          "?baseRevision=" + encodeURIComponent(found.revision), {method:"DELETE"});
        items = items.filter(function (i) { return i.uid !== found.uid; });
        message("已删除素材");
      } catch (err) {
        message("删除失败：" + (err.message || "请重试"), true);
      } finally {
        busy = false;
        render();
      }
    });
    fileInput.addEventListener("change", async function () {
      const file = fileInput.files && fileInput.files[0];
      fileInput.value = "";
      if (!file || busy) return;
      if (!["image/png","image/jpeg","image/webp"].includes(file.type) ||
          file.size > 15 * 1024 * 1024) {
        message("只支持 15 MB 以内的 PNG、JPEG、WebP 图片", true);
        return;
      }
      const uid = window.crypto && window.crypto.randomUUID && window.crypto.randomUUID();
      if (!uid) { message("浏览器不支持安全素材 ID，请更新浏览器", true); return; }
      busy = true;
      fileInput.disabled = true;
      message("正在上传私人素材…");
      try {
        const dataUrl = await new Promise(function (resolve, reject) {
          const reader = new FileReader();
          reader.onload = function () { resolve(reader.result); };
          reader.onerror = function () { reject(new Error("图片读取失败")); };
          reader.readAsDataURL(file);
        });
        await api("/api/library/assets/" + uid, {method:"PUT",body:{
          uid: uid, cat: category === "all" ? "other" : category,
          name: file.name.replace(/\.[^.]+$/, "") || "我的素材",
          dataUrl: dataUrl, origin: "web"
        }});
        busy = false;
        await load(false);
        message("添加成功，Skill 同步后即可使用");
      } catch (err) {
        message("添加失败：" + (err.message || "请重试"), true);
      } finally {
        busy = false;
        fileInput.disabled = false;
        render();
      }
    });
    await load(false);
  }
  window.HandrawCloudCenter = { mount, mountGallery };
})();
