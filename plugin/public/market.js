"use strict";

window.HandrawMarket = ({
  state,
  el,
  button,
  modal,
  tell,
  api,
  navigate,
  card,
  select,
  refreshAccount = async () => {},
}) => {
  const $ = select || ((query) => document.querySelector(query));
  const names = {
    work: "作品",
    experience: "经验",
    style: "画风",
    layout: "图型",
  };
  const assetRef = (item) =>
    item.ref ||
    (item.source === "community"
      ? `community:${item.id}`
      : `official:${item.id}`);
  const login = () => {
    if (!state.boot.user) {
      location.href = "/login";
      return false;
    }
    return true;
  };
  const image = (src, alt, cls = "hw-detail-image") =>
    src ? el("img", { src, alt, class: cls }) : null;
  const append = (node, ...children) =>
    node.append(
      ...children
        .flat()
        .filter((child) => child !== null && child !== undefined),
    );
  const link = (text, view, params = {}) =>
    el(
      "a",
      {
        href: `/studio?${new URLSearchParams({ view, ...params })}`,
        "data-view": view,
        class: "hw-text-link",
      },
      text,
    );
  function field(label, name, value = "", type = "text", required = false) {
    const node = el(type === "textarea" ? "textarea" : "input", {
      name,
      type: type === "textarea" ? null : type,
      required,
      id: `market-${name}`,
    });
    if (type !== "file") node.value = value;
    if (type === "file") node.accept = "image/png,image/jpeg,image/webp";
    return el(
      "label",
      { class: "hw-market-field" },
      el("span", {}, label),
      node,
    );
  }
  async function upload(file, privateImage = false) {
    const data = new FormData();
    data.append("file", file);
    if (privateImage)
      return (await api("/private-images", { method: "POST", body: data })).url;
    data.append("type", "composer");
    data.append("synchronous", "true");
    const csrf = await fetch("/session/csrf.json", {
      credentials: "same-origin",
    }).then((r) => r.json());
    const response = await fetch("/uploads.json", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-CSRF-Token": csrf.csrf,
        "X-Requested-With": "XMLHttpRequest",
      },
      body: data,
    });
    const result = await response.json();
    if (!response.ok || !result.url)
      throw new Error(result.errors?.join("；") || "图片上传失败");
    return result.url.startsWith("//") ? `https:${result.url}` : result.url;
  }

  async function assetPicker(kind, onSelect, onlyUsable = false) {
    let page = 1,
      count = 12,
      source = "",
      query = "";
    let assets = [];
    const search = el("input", {
      type: "search",
      placeholder: "名称或编号",
      "aria-label": `查找${names[kind]}`,
    });
    const grid = el("div", { class: "hw-picker-grid" });
    const sources = el(
      "select",
      { "aria-label": "资产来源" },
      ...[
        ["", "全部来源"],
        ["official", "官方"],
        ["community", "社区"],
      ].map(([value, title]) => el("option", { value }, title)),
    );
    const more = button(
      "继续看 ↓",
      async () => {
        count += 12;
        if (source === "community") {
          page += 1;
          assets.push(
            ...(
              await api(
                `/assets?kind=${kind}&source=community&page=${page}&q=${encodeURIComponent(query)}`,
              )
            ).assets,
          );
        }
        draw();
      },
      true,
    );
    async function load() {
      assets = (
        await api(
          `/assets?kind=${kind}&source=${source}&q=${encodeURIComponent(query)}`,
        )
      ).assets;
      page = 1;
      count = 12;
      draw();
    }
    function draw() {
      const filtered = assets.filter(
        (item) =>
          !onlyUsable ||
          item.source === "official" ||
          item.unlocked ||
          (!item.paid && item.tradable),
      );
      grid.replaceChildren(
        ...filtered.slice(0, count).map((item) =>
          el(
            "button",
            {
              type: "button",
              onclick: () => {
                $("#modal").close();
                onSelect(item);
              },
            },
            image(
              item.image || item.cover_url,
              item.name || item.title,
              "hw-picker-image",
            ),
            el("strong", {}, item.name || item.title),
            el(
              "small",
              {},
              `${item.source === "official" ? "官方" : item.author?.name || item.author?.username || "社区"} · ${item.price ? `${item.price} 积分` : "免费"}`,
            ),
          ),
        ),
      );
      if (!filtered.length)
        grid.append(
          el(
            "p",
            {},
            onlyUsable
              ? "暂无可用内容，可先到探索页收藏或解锁。"
              : "没有找到对应内容。",
          ),
        );
      more.hidden = source !== "community" && filtered.length <= count;
    }
    let searchTimer;
    search.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        query = search.value.trim();
        load().catch((e) => tell(e.message));
      }, 450);
    });
    sources.addEventListener("change", () => {
      source = sources.value;
      load().catch((e) => tell(e.message));
    });
    modal(
      `选择${names[kind]}`,
      el("div", { class: "hw-actions" }, search, sources),
      grid,
      more,
    );
    await load();
  }

  async function share(kind, initial = {}) {
    if (!kind)
      return modal(
        "分享什么？",
        el("p", {}, "分享一次创作，或让你的画风与图型被更多人使用。"),
        el(
          "div",
          { class: "hw-share-choices" },
          ...Object.entries(names).map(([value, title]) =>
            button(`分享${title}`, () => share(value), true),
          ),
        ),
      );
    if (!login()) return;
    if (!state.boot.participant) return tell("请完成账号验证后再发布。");
    const editing = !!initial.id;
    let protectedData = initial.content || {};
    if (editing && !initial.content)
      protectedData = (await api(`/entries/${initial.id}/content`)).content;
    const form = el("form", { class: "hw-share-form hw-market-form" });
    const title = field(
      `${names[kind]}标题`,
      "title",
      initial.title || "",
      "text",
      true,
    );
    title.querySelector("input").minLength = state.boot.min_title_length || 5;
    const summary = field(
      kind === "experience" ? "公开试读" : "一句话介绍（公开）",
      "summary",
      initial.summary || "",
      "textarea",
      kind !== "work",
    );
    const cover = field(
      kind === "work" ? "作品图片" : "封面或效果图",
      "cover",
      "",
      "file",
      kind === "work" && !initial.cover_url && !initial.image,
    );
    form.append(title, summary, cover);
    if (initial.topic_id)
      form.append(
        el(
          "p",
          { class: "hw-help" },
          "原帖已公开部分保持公开；收费部分请填写新增、尚未公开的方法与内容。",
        ),
      );
    if (initial.image) cover.append(el("small", {}, "已附上刚生成的图片。"));
    else if (initial.cover_url)
      cover.append(image(initial.cover_url, initial.title, "hw-form-preview"));
    const contentKey = {
      work: "prompt",
      experience: "body",
      style: "definition_zh",
      layout: "definition_zh",
    }[kind];
    const contentLabel = {
      work: "完整提示词",
      experience: "完整经验正文（支持 Markdown）",
      style: "可复用画风定义",
      layout: "可复用图型定义",
    }[kind];
    const content = field(
      contentLabel,
      "content",
      protectedData[contentKey] || initial.prompt || "",
      "textarea",
      true,
    );
    content.querySelector("textarea").minLength = 10;
    content.append(
      el(
        "small",
        {},
        kind === "experience"
          ? "收费时，仅已解锁用户能阅读这里的内容。公开试读请写在上方。"
          : kind === "work"
            ? "写下这张图的实际完整提示词。"
            : "描述可以跨主题复用的视觉语言或布局，不要只写一个具体场景。",
      ),
    );
    form.append(content);
    if (kind === "experience") {
      const privateFile = el("input", {
        type: "file",
        accept: "image/png,image/jpeg,image/webp",
        "aria-label": "插入正文私有图片",
      });
      privateFile.addEventListener("change", async () => {
        if (!privateFile.files[0]) return;
        privateFile.disabled = true;
        try {
          const url = await upload(privateFile.files[0], true);
          content.querySelector("textarea").value +=
            `\n\n![正文配图](${url})\n`;
        } catch (error) {
          tell(error.message);
        } finally {
          privateFile.disabled = false;
          privateFile.value = "";
        }
      });
      form.append(
        el(
          "label",
          { class: "hw-market-field" },
          "正文配图（随正文鉴权）",
          privateFile,
        ),
      );
    }
    const advanced = el(
      "details",
      { class: "hw-advanced" },
      el("summary", {}, "补充说明与授权"),
    );
    const license = field(
      "使用范围与授权",
      "license",
      initial.license || "供学习参考；其他用途与转载请联系原作者。",
      "textarea",
    );
    advanced.append(license);
    let parameters, definitionEn, instructions, version;
    if (kind === "work") {
      parameters = field(
        "生成参数（JSON，可选）",
        "parameters",
        JSON.stringify(
          protectedData.parameters || initial.parameters || {},
          null,
          2,
        ),
        "textarea",
      );
      advanced.append(parameters);
    }
    const resource = ["style", "layout"].includes(kind);
    const samples = [];
    if (resource) {
      definitionEn = field(
        "英文定义（选填）",
        "definition_en",
        protectedData.definition_en || "",
        "textarea",
      );
      instructions = field(
        "怎样替换主题或填写内容？",
        "instructions",
        protectedData.instructions || "",
        "textarea",
      );
      version = field("版本", "version", initial.version || "1.0.0");
      advanced.append(definitionEn, instructions, version);
      const examples = el(
        "details",
        { class: "hw-advanced" },
        el(
          "summary",
          {},
          `复用示例（收费审核需${kind === "style" ? "三" : "两"}个不同内容）`,
        ),
      );
      for (let i = 0; i < (kind === "style" ? 3 : 2); i++) {
        const old = protectedData.examples?.[i] || initial.examples?.[i] || {};
        const theme = field(
          `示例 ${i + 1} 的主题或内容`,
          `sample-theme-${i}`,
          old.theme || "",
        );
        const file = field(
          `示例 ${i + 1} 的图片`,
          `sample-file-${i}`,
          "",
          "file",
        );
        if (old.image)
          file.append(image(old.image, old.theme, "hw-form-preview"));
        examples.append(theme, file);
        samples.push({ theme, file, old });
      }
      form.append(examples);
    }
    let refs = Array.from(initial.assets || []);
    const associationBox = el("div", { class: "hw-asset-relations" });
    if (!resource) {
      const drawRefs = () =>
        associationBox.replaceChildren(
          el(
            "span",
            { class: "hw-help" },
            "关联画风与图型（最多两个画风、一个图型，可不选）",
          ),
          ...refs.map((ref) =>
            button(
              `${ref.name || ref.ref} ×`,
              () => {
                refs = refs.filter((x) => x !== ref);
                drawRefs();
              },
              true,
            ),
          ),
          ...["style", "layout"].map((type) =>
            button(
              `＋关联${names[type]}`,
              () =>
                assetPicker(type, (item) => {
                  modal(`${editing ? "编辑" : "分享"}${names[kind]}`, form);
                  const ref = assetRef(item);
                  if (refs.some((x) => x.ref === ref))
                    return tell("这份资产已经关联。");
                  if (
                    refs.filter((x) => x.kind === type).length >=
                    (type === "style" ? 2 : 1)
                  )
                    return tell("最多两个画风、一个图型。");
                  refs.push({
                    ref,
                    kind: type,
                    role: type,
                    name: item.name || item.title,
                  });
                  drawRefs();
                  modal(`${editing ? "编辑" : "分享"}${names[kind]}`, form);
                }),
              true,
            ),
          ),
        );
      drawRefs();
      form.append(associationBox);
    }
    const price = el("select", { name: "price", "aria-label": "积分价格" });
    if (resource)
      price.append(
        el("option", { value: 0 }, "免费分享"),
        el("option", { value: 10 }, "申请系统动态定价 · 初始 10 分"),
      );
    else
      for (let i = 0; i <= (state.boot.fixed_price_max || 100); i += 5)
        price.append(el("option", { value: i }, i ? `${i} 积分` : "免费分享"));
    price.value = initial.paid ? (resource ? 10 : initial.price) : 0;
    form.append(
      el(
        "label",
        { class: "hw-market-field" },
        resource ? "发布方式" : "作者固定价格",
        price,
      ),
      el(
        "small",
        {},
        resource
          ? "收费前由版主检查复用效果。价格由系统按有效交易与使用反馈调整。"
          : "可免费分享，也可设置固定积分；系统不会自动修改。",
      ),
      advanced,
      el(
        "label",
        { class: "hw-check" },
        el("input", { type: "checkbox", required: true }),
        "我有权分享图片、提示词和正文，授权说明真实。",
      ),
    );
    const error = el("p", { class: "hw-form-error", role: "alert" });
    const submit = el(
      "button",
      { type: "submit", class: "hw-button" },
      editing ? "保存修改" : "发布分享",
    );
    form.append(error, submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      try {
        const photo = cover.querySelector("input").files[0] || initial.image;
        const coverUrl = photo ? await upload(photo) : initial.cover_url || "";
        const data = {
          [contentKey]: content.querySelector("textarea").value.trim(),
        };
        if (parameters)
          data.parameters = JSON.parse(
            parameters.querySelector("textarea").value || "{}",
          );
        if (definitionEn)
          data.definition_en = definitionEn.querySelector("textarea").value;
        if (instructions)
          data.instructions = instructions.querySelector("textarea").value;
        if (resource) {
          data.examples = [];
          for (const row of samples) {
            const file = row.file.querySelector("input").files[0];
            const theme = row.theme.querySelector("input").value;
            const src = file ? await upload(file) : row.old.image || "";
            if (theme || src) data.examples.push({ theme, image: src });
          }
        }
        const payload = {
          kind,
          title: title.querySelector("input").value,
          summary: summary.querySelector("textarea").value,
          cover_url: coverUrl,
          license: license.querySelector("textarea").value,
          content: data,
          assets: refs,
          price: Number(price.value),
          paid_opt_in: resource && Number(price.value) > 0,
        };
        if (version) payload.version = version.querySelector("input").value;
        if (initial.topic_id) payload.topic_id = initial.topic_id;
        const result = await api(
          editing ? `/entries/${initial.id}` : "/entries",
          {
            method: editing ? "PATCH" : "POST",
            body: JSON.stringify({ entry: payload }),
          },
        );
        $("#modal").close();
        tell(
          result.review_pending
            ? "已发布预览，版主审核通过后开放积分交易。"
            : "内容已保存。",
        );
        await openEntry(result.id);
      } catch (e) {
        error.textContent = e.message;
      } finally {
        submit.disabled = false;
      }
    });
    modal(`${editing ? "编辑" : "分享"}${names[kind]}`, form);
  }

  function relations(entry) {
    return el(
      "div",
      { class: "hw-asset-relations" },
      ...(entry.assets || []).map((asset) =>
        asset.available
          ? button(
              `${names[asset.kind]} · ${asset.name || asset.ref}`,
              () => assetDetail(asset.ref),
              true,
            )
          : el("span", { class: "hw-help" }, "关联资产暂不可用"),
      ),
    );
  }
  async function openEntry(id) {
    const entry = await api(`/entries/${id}`);
    if (state.boot.user && state.boot.user.id !== entry.author.id)
      api(`/entries/${id}/events`, {
        method: "POST",
        body: JSON.stringify({ kind: "detail" }),
      }).catch(() => {});
    const body = el(
      "div",
      { class: "hw-market-detail" },
      image(entry.cover_url, entry.title),
      el(
        "p",
        { class: "hw-help" },
        `${names[entry.kind]} · ${entry.author.name || entry.author.username} · v${entry.version}${entry.featured ? " · 精选" : ""}${entry.verified ? " · 复用已验证" : ""}`,
      ),
      el("p", { class: "hw-detail-text" }, entry.summary),
      relations(entry),
    );
    const actions = el("div", { class: "hw-actions" });
    actions.append(
      button(
        entry.collected ? "已收藏 ♥" : "收藏 ♡",
        async (node) => {
          if (!login()) return;
          await api(`/entries/${id}/collection`, {
            method: entry.collected ? "DELETE" : "POST",
          });
          entry.collected = !entry.collected;
          node.textContent = entry.collected ? "已收藏 ♥" : "收藏 ♡";
          tell("收藏已更新，解锁资格不受影响。");
        },
        true,
      ),
    );
    const protectedBody = el("div", { class: "hw-protected-content" });
    async function loadContent() {
      const result = await api(`/entries/${id}/content`);
      const data = result.content;
      protectedBody.replaceChildren(
        el(
          "h3",
          {},
          {
            work: "完整提示词",
            experience: "完整经验",
            style: "画风定义",
            layout: "图型定义",
          }[entry.kind],
        ),
      );
      if (data.body_html) {
        const article = el("article", { class: "hw-experience-body cooked" });
        article.innerHTML = data.body_html;
        protectedBody.append(article);
      } else
        protectedBody.append(
          el(
            "pre",
            { class: "hw-prompt-text" },
            data.prompt || data.definition_zh || "",
          ),
        );
      if (data.instructions)
        protectedBody.append(el("p", {}, data.instructions));
      if (data.parameters && Object.keys(data.parameters).length)
        protectedBody.append(
          el(
            "details",
            { class: "hw-advanced" },
            el("summary", {}, "生成参数"),
            el("pre", {}, JSON.stringify(data.parameters, null, 2)),
          ),
        );
      if (!data.body)
        protectedBody.append(
          button(
            "复制完整内容",
            async (node) => {
              await navigator.clipboard.writeText(
                data.prompt || data.definition_zh || "",
              );
              node.textContent = "已复制 ✓";
            },
            true,
          ),
        );
      if (["style", "layout"].includes(entry.kind))
        protectedBody.append(
          link(`使用此${names[entry.kind]} →`, "create", {
            [entry.kind]: `community:${id}`,
          }),
          button(
            "加入个人库",
            async (node) => {
              if (!login()) return;
              if (state.boot.user.id !== entry.author.id)
                await api(`/entries/${id}/collection`, { method: "POST" });
              node.textContent = "已加入个人库 ✓";
              tell("可在我的创作中查找；Skill 可按指令同步并离线使用。");
            },
            true,
          ),
        );
    }
    if (entry.market && entry.content_available) {
      if (entry.unlocked) await loadContent();
      else if (entry.review_pending)
        protectedBody.append(
          el("p", {}, "画风／图型正在等待复用审核，暂不收取积分。"),
        );
      else
        actions.append(
          button(`${entry.price} 积分解锁`, async () => {
            if (!login()) return;
            modal(
              "确认积分解锁",
              el("h3", {}, entry.title),
              el(
                "p",
                {},
                `${names[entry.kind]} · ${entry.price} 积分 · 作者 ${entry.author.name || entry.author.username}`,
              ),
              el(
                "p",
                { class: "hw-help" },
                "一次解锁，同一内容及后续更新无需重复购买。关联画风和图型单独解锁。",
              ),
              el("p", { class: "hw-form-error", role: "alert" }),
              button(`确认使用 ${entry.price} 积分`, async () => {
                await api(`/entries/${id}/unlock`, {
                  method: "POST",
                  body: JSON.stringify({
                    price: entry.price,
                    price_revision: entry.price_revision,
                  }),
                });
                await refreshAccount();
                await openEntry(id);
                tell("已解锁 ✓");
              }),
              button("返回预览", () => openEntry(id), true),
            );
          }),
        );
    } else
      protectedBody.append(
        el(
          "p",
          { class: "hw-help" },
          "这份内容来自原有公开分享，可前往原帖阅读。",
        ),
      );
    if (state.boot.user?.id === entry.author.id && entry.market)
      actions.append(
        button("编辑内容与价格", () => share(entry.kind, entry), true),
      );
    actions.append(
      el("a", { class: "hw-text-link", href: entry.topic_url }, "原帖与讨论 →"),
    );
    append(
      body,
      actions,
      entry.paid
        ? el(
            "p",
            { class: "hw-help" },
            `${entry.price_reason} · ${entry.pricing_mode === "fixed" ? "作者固定价" : "系统动态价"}`,
          )
        : null,
      protectedBody,
    );
    for (const sample of entry.examples || [])
      append(
        body,
        image(sample.image, sample.theme),
        el("small", {}, sample.theme),
      );
    if (state.boot.user && state.boot.user.id !== entry.author.id)
      body.append(
        el(
          "div",
          { class: "hw-actions" },
          ...(entry.market && !entry.unlocked
            ? []
            : [
                ["useful", "使用后觉得有用"],
                ["not_useful", "使用后不太有用"],
              ]
          ).map(([kind, text]) =>
            button(
              text,
              async () => {
                await api(`/entries/${id}/events`, {
                  method: "POST",
                  body: JSON.stringify({ kind }),
                });
                tell("使用反馈已记录。");
              },
              true,
            ),
          ),
          button(
            "报告问题",
            () => {
              const reason = field(
                "请说明内容、提示词或授权问题",
                "report",
                "",
                "textarea",
                true,
              );
              modal(
                "报告问题",
                reason,
                button("提交给版主", async () => {
                  await api(`/entries/${id}/report`, {
                    method: "POST",
                    body: JSON.stringify({
                      reason: reason.querySelector("textarea").value,
                    }),
                  });
                  $("#modal").close();
                  tell("问题已提交。");
                }),
              );
            },
            true,
          ),
        ),
      );
    body.append(el("p", { class: "hw-license" }, `授权：${entry.license}`));
    modal(entry.title, body);
    if (["style", "layout"].includes(entry.kind))
      await appendRelated(body, `community:${id}`);
  }
  async function appendRelated(body, ref) {
    const related = await api(`/assets/${encodeURIComponent(ref)}/related`);
    if (!body.isConnected) return;
    body.append(el("h3", {}, "相关作品"));
    const works = el(
      "div",
      { class: "hw-related-works" },
      ...related.works.map(card),
    );
    append(
      body,
      works,
      related.works.length
        ? null
        : el(
            "p",
            { class: "hw-help" },
            "还没有关联作品，欢迎成为第一位分享者。",
          ),
      el("h3", {}, "教程与经验"),
      ...related.experiences.map((entry) =>
        button(entry.title, () => openEntry(entry.id), true),
      ),
      related.experiences.length
        ? null
        : el("p", { class: "hw-help" }, "使用过程与方法会沉淀在这里。"),
    );
  }
  async function assetDetail(ref) {
    const asset = await api(`/assets/${encodeURIComponent(ref)}`);
    if (asset.source === "community") return openEntry(asset.id);
    const kind = asset.kind;
    const body = el(
      "div",
      {},
      image(asset.image, asset.name),
      el("p", { class: "hw-help" }, `官方${names[kind]} · ${asset.id} · 免费`),
      el("p", {}, asset.description),
      el(
        "div",
        { class: "hw-actions" },
        link(`使用此${names[kind]} →`, "create", { [kind]: asset.id }),
        button(
          asset.collected ? "已收藏 ♥" : "收藏到个人库",
          async (node) => {
            if (!login()) return;
            await api(`/assets/${encodeURIComponent(ref)}/collection`, {
              method: asset.collected ? "DELETE" : "POST",
            });
            asset.collected = !asset.collected;
            node.textContent = asset.collected ? "已收藏 ♥" : "收藏到个人库";
          },
          true,
        ),
        button(
          "复制定义",
          async (node) => {
            const result = await api(
              `/assets/${encodeURIComponent(ref)}/content`,
            );
            await navigator.clipboard.writeText(result.resource.prompt_zh);
            node.textContent = "已复制 ✓";
          },
          true,
        ),
      ),
      el("p", { class: "hw-license" }, asset.license),
    );
    modal(asset.name, body);
    await appendRelated(body, ref);
  }
  function assetCard(item) {
    const ref = assetRef(item);
    return el(
      "article",
      { class: "hw-library-card" },
      el(
        "button",
        {
          class: "hw-library-card__image",
          type: "button",
          onclick: () => assetDetail(ref),
          "aria-label": `查看${item.name || item.title}`,
        },
        image(
          item.image || item.cover_url,
          item.name || item.title,
          "hw-library-image",
        ),
      ),
      el(
        "p",
        { class: "hw-library-card__label" },
        `${item.source === "official" ? "官方" : "社区"}${names[item.kind]} · ${item.price ? `${item.price} 积分` : "免费"}`,
      ),
      el(
        "h3",
        {},
        el(
          "button",
          { type: "button", onclick: () => assetDetail(ref) },
          item.name || item.title,
        ),
      ),
      el(
        "p",
        { class: "hw-library-card__description" },
        item.description || item.summary,
      ),
      item.review_pending
        ? el("small", {}, "收费审核中")
        : link(`使用此${names[item.kind]} ↗`, "create", {
            [item.kind]: item.source === "official" ? item.id : ref,
          }),
    );
  }
  async function explore() {
    const params = new URLSearchParams(location.search);
    let kind = params.get("type") === "layout" ? "layout" : "style";
    let source = params.get("source") || "",
      count = 12,
      page = 1,
      query = params.get("q") || "",
      assets = [];
    const tabs = el("div", {
      class: "hw-library-tabs",
      "aria-label": "探索类型",
    });
    const queryInput = el("input", {
      type: "search",
      class: "hw-library-search",
      placeholder: "搜索名称、编号或关键词",
      "aria-label": "搜索画风或图型",
      value: query,
    });
    const sourceInput = el(
      "select",
      { "aria-label": "资产来源", class: "hw-search" },
      ...[
        ["", "全部来源"],
        ["official", "官方"],
        ["community", "社区"],
      ].map(([value, name]) => el("option", { value }, name)),
    );
    sourceInput.value = source;
    const status = el("p", { class: "hw-help", "aria-live": "polite" });
    const grid = el("div", { class: "hw-library-grid" });
    const more = button(
      "继续看 12 个 ↓",
      async () => {
        count += 12;
        if (source === "community") {
          page += 1;
          assets.push(
            ...(
              await api(
                `/assets?kind=${kind}&source=community&page=${page}&q=${encodeURIComponent(query)}`,
              )
            ).assets,
          );
        }
        draw();
      },
      true,
    );
    function draw() {
      tabs.replaceChildren(
        ...["style", "layout"].map((value) =>
          el(
            "button",
            {
              type: "button",
              class: `hw-tab ${value === kind ? "is-active" : ""}`,
              "aria-pressed": String(value === kind),
              onclick: () => {
                kind = value;
                load().catch((e) => tell(e.message));
              },
            },
            names[value],
          ),
        ),
      );
      grid.replaceChildren(...assets.slice(0, count).map(assetCard));
      if (!assets.length)
        grid.append(el("p", { class: "hw-empty" }, "还没有找到对应资产。"));
      status.textContent = `${names[kind]} · 已显示 ${Math.min(count, assets.length)} 份 · 官方免费，社区按作者发布方式解锁`;
      more.hidden = source !== "community" && assets.length <= count;
    }
    async function load() {
      page = 1;
      count = 12;
      assets = (
        await api(
          `/assets?kind=${kind}&source=${source}&q=${encodeURIComponent(query)}`,
        )
      ).assets;
      draw();
    }
    let timer;
    queryInput.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        query = queryInput.value.trim();
        load().catch((e) => tell(e.message));
      }, 450);
    });
    sourceInput.addEventListener("change", () => {
      source = sourceInput.value;
      load().catch((e) => tell(e.message));
    });
    $("#content").replaceChildren(
      el(
        "p",
        { class: "hw-page-intro" },
        "找到一种画风，或一套适合内容的图型。从示例开始，把它用进自己的创作。",
      ),
      tabs,
      el("div", { class: "hw-actions" }, queryInput, sourceInput),
      status,
      grid,
      more,
    );
    $("#heading-actions").append(
      button("贡献画风或图型", () => share(kind), true),
    );
    await load();
    const ref = params.get("asset") || params.get("id");
    if (ref) await assetDetail(ref.includes(":") ? ref : `official:${ref}`);
  }
  return {
    share,
    openEntry,
    assetDetail,
    assetPicker,
    explore,
    assetCard,
    upload,
    relations,
  };
};
