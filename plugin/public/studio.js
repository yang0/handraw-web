"use strict";

window.HandrawStudio = ({
  state,
  el,
  button,
  modal,
  api,
  tell,
  share,
  market,
}) => {
  const $ = (query) => document.querySelector(query);
  const base = new URL(
    ".",
    document.querySelector('script[src*="/studio.js"]').src,
  );
  let resources,
    options,
    draft,
    timer,
    pollTimer,
    version = 0,
    root,
    preview,
    submit,
    history;
  let client,
    previewPlans = [],
    remaining,
    active = false,
    language = "zh",
    outputKind = "prompt";
  const historyRows = new Map();
  let appliedQuery;
  const defaults = () => ({
    mode: "pure",
    theme: "",
    style: "FA-001",
    layout: "",
    color: "",
    ratio: "3:4",
    mood: "",
    whitespace: "normal",
    fusion: false,
    character_style: "",
    scene_style: "",
    tones: [],
    asset_refs: [],
    references: [],
    audience: "",
    channel: "",
    shoot_type: "",
    extra: "",
    quality: "auto",
    batch: false,
    count: 3,
    themes: [],
    layouts: [],
    mix_layouts: false,
    layout_variant: 1,
  });
  const text = (value) => el("p", { class: "hw-help" }, value);
  const field = (label, control) =>
    el("label", { class: "hw-studio-field" }, el("span", {}, label), control);
  const close = () => $("#modal").close();
  const find = (id) =>
    id === "realistic"
      ? { id, name: "写实", kind: "style" }
      : resources.find((item) => item.id === id);
  const name = (id) => find(id)?.name || id || "不指定";
  const normalize = (item) => ({
    ...item,
    id:
      item.source === "community"
        ? item.ref || `community:${item.id}`
        : item.id,
    name: item.name || item.title,
    image: item.image || item.cover_url,
  });
  function stop() {
    clearTimeout(timer);
    clearTimeout(pollTimer);
    version++;
  }
  function save() {
    sessionStorage.setItem("handraw-create-draft", JSON.stringify(draft));
  }
  function change(key, value) {
    draft[key] = value;
    save();
    refresh();
  }
  function input(key, label, placeholder = "", area = false) {
    const n = el(area ? "textarea" : "input", {
      "aria-label": label,
      placeholder,
      rows: area ? 3 : null,
      maxlength: key === "theme" ? 20000 : key === "extra" ? 4000 : 200,
      type: area ? null : "text",
    });
    n.value = draft[key] || "";
    n.addEventListener("input", () => change(key, n.value));
    return n;
  }
  function select(key, label, items) {
    const n = el(
      "select",
      { "aria-label": label },
      ...items.map(([value, title]) => el("option", { value }, title)),
    );
    n.value = String(draft[key]);
    n.addEventListener("change", () => change(key, n.value));
    return n;
  }
  function check(label, key, callback = () => {}) {
    const n = el("input", { type: "checkbox" });
    n.checked = !!draft[key];
    n.addEventListener("change", () => {
      change(key, n.checked);
      callback();
    });
    return el("label", { class: "hw-check" }, n, label);
  }
  function command() {
    let result = window.HandrawComposerCommand(
      draft,
      resources,
      options,
      language,
    );
    if (draft.extra)
      result += `\n${language === "en" ? "Additional requirements" : "补充要求"}：${draft.extra}`;
    if (draft.layout === "SC-021")
      result += `\n转译类型：${draft.layout_variant} · ${options.sc021_types[Number(draft.layout_variant) - 1]}`;
    if (draft.batch && (draft.themes.some(Boolean) || draft.layouts.length))
      result +=
        "\n" +
        Array.from(
          { length: Number(draft.count) },
          (_, i) =>
            `${i + 1}. ${draft.themes[i] || draft.theme}${draft.mix_layouts && draft.layouts.length ? ` · ${name(draft.layouts[i % draft.layouts.length])}` : ""}`,
        ).join("\n");
    return result;
  }
  function showOutput() {
    if (!preview) return;
    preview.value =
      outputKind === "command"
        ? command()
        : previewPlans
            .map(
              (p, i) =>
                `${previewPlans.length > 1 ? `第 ${i + 1} 张\n` : ""}${p.prompt}`,
            )
            .join("\n\n────────\n\n");
  }
  function updateSubmit() {
    if (!submit) return;
    submit.disabled =
      !!state.boot.user &&
      (!state.boot.generation?.available ||
        active ||
        !previewPlans.length ||
        (remaining !== undefined &&
          remaining < (draft.batch ? Number(draft.count) : 1)));
    submit.textContent = !state.boot.user
      ? "登录后在线生成"
      : active
        ? "任务进行中…"
        : draft.batch
          ? `开始生成 ${draft.count} 张`
          : "生成图片";
  }
  function refresh() {
    const current = ++version;
    clearTimeout(timer);
    previewPlans = [];
    showOutput();
    updateSubmit();
    const status = $("#studio-preview-status");
    if (!draft.theme.trim()) {
      if (status)
        status.textContent = "填写主题后，可预览实际发送给图片模型的提示词。";
      return;
    }
    if (status) status.textContent = "正在更新提示词…";
    timer = setTimeout(async () => {
      try {
        const result = await api("/creation/resolve", {
          method: "POST",
          body: JSON.stringify({ creation: draft }),
        });
        if (current !== version || !root?.isConnected) return;
        previewPlans = result.plans || [result];
        showOutput();
        if (status)
          status.textContent = `已就绪 · ${previewPlans.length} 张 · 提示词由服务端解析所选画风与图型。`;
      } catch (error) {
        if (current === version && status) status.textContent = error.message;
      }
      if (current === version) updateSubmit();
    }, 450);
  }
  async function picker(kind, onSelect, selected = [], multi = false) {
    let source = "official",
      category = "",
      query = "",
      page = 1,
      limit = 12,
      values = [],
      hasMore = false;
    const chosen = new Map(
      selected.filter(Boolean).map((id) => [id, find(id) || { id, name: id }]),
    );
    const grid = el("div", { class: "hw-picker-grid hw-studio-picker" }),
      status = text("");
    const search = el("input", {
      type: "search",
      "aria-label": "搜索名称、编号或关键词",
      class: "hw-library-search",
      placeholder: "名称、编号或关键词",
    });
    const sourceSelect = el(
      "select",
      { "aria-label": "资源来源" },
      ...["official", "community", "mine"].map((v, i) =>
        el("option", { value: v }, ["官方", "社区", "我的创作"][i]),
      ),
    );
    const categories = el(
      "select",
      { "aria-label": "资源分类" },
      el("option", { value: "" }, "全部分类"),
      ...Array.from(
        new Set(resources.filter((r) => r.kind === kind).map((r) => r.group)),
      ).map((g) => el("option", { value: g }, g)),
    );
    const more = button(
      "继续加载 ↓",
      async () => {
        limit += 12;
        if (source === "community" && hasMore && values.length < limit) {
          page++;
          const result = await api(
            `/assets?kind=${kind}&source=community&page=${page}`,
          );
          values.push(...result.assets.map(normalize));
          hasMore = result.assets.length === 20;
        }
        draw();
      },
      true,
    );
    function draw() {
      const filtered = values.filter(
        (v) =>
          (!category || v.group === category) &&
          `${v.id} ${v.name} ${v.description || v.summary || ""}`
            .toLowerCase()
            .includes(query),
      );
      grid.replaceChildren(
        ...filtered.slice(0, limit).map((item) => {
          const usable = item.source !== "community" || item.unlocked;
          const choose = button(
            `${multi && chosen.has(item.id) ? "✓ " : ""}${item.name}${usable ? "" : ` · ${item.price}积分，先解锁`}`,
            () => {
              if (multi) {
                chosen.has(item.id)
                  ? chosen.delete(item.id)
                  : chosen.set(item.id, item);
                draw();
              } else {
                onSelect(item);
                close();
              }
            },
            true,
          );
          choose.disabled = !usable;
          if (item.image)
            choose.prepend(el("img", { src: item.image, alt: item.name }));
          return el(
            "div",
            {},
            choose,
            !usable
              ? button("查看与解锁", () => market.assetDetail(item.id), true)
              : null,
          );
        }),
      );
      more.hidden = filtered.length <= limit && !hasMore;
      status.textContent = multi
        ? `已选择 ${chosen.size} 项`
        : `找到 ${filtered.length} 项`;
    }
    async function load() {
      page = 1;
      limit = 12;
      hasMore = false;
      if (source === "official")
        values = resources.filter((r) => r.kind === kind);
      else if (source === "mine") {
        if (!state.boot.user) throw Error("请先登录查看个人创作");
        values = (await api("/library")).owned
          .filter((r) => r.kind === kind)
          .map((r) => normalize({ ...r, source: "community", unlocked: true }));
      } else {
        const result = await api(`/assets?kind=${kind}&source=community`);
        values = result.assets.map(normalize);
        hasMore = result.assets.length === 20;
      }
      if (kind === "style" && source === "official")
        values = [{ id: "realistic", name: "写实", kind: "style" }, ...values];
      draw();
    }
    search.addEventListener("input", () => {
      query = search.value.trim().toLowerCase();
      limit = 12;
      draw();
    });
    categories.addEventListener("change", () => {
      category = categories.value;
      draw();
    });
    sourceSelect.addEventListener("change", () => {
      source = sourceSelect.value;
      categories.hidden = source !== "official";
      category = "";
      load().catch((e) => (status.textContent = e.message));
    });
    modal(
      `选择${{ style: "画风", layout: "图型", color: "配色" }[kind]}`,
      search,
      el("div", { class: "hw-actions" }, sourceSelect, categories),
      status,
      button(
        "不指定",
        () => {
          onSelect(multi ? [] : null);
          close();
        },
        true,
      ),
      grid,
      more,
      multi
        ? button("确认选择", () => {
            if (chosen.size > 5) throw Error("最多选择五个图型");
            onSelect([...chosen.values()]);
            close();
          })
        : null,
    );
    await load();
  }
  async function create() {
    stop();
    if (!resources) {
      const [data, settings] = await Promise.all([
        fetch(new URL("catalog.json", base)).then((r) => r.json()),
        fetch(new URL("studio-options.json", base)).then((r) => r.json()),
      ]);
      resources = data.resources;
      options = settings;
    }
    draft = { ...defaults(), ...(draft || {}) };
    if (!draft.loaded) {
      try {
        const saved = JSON.parse(
          sessionStorage.getItem("handraw-create-draft") || "null",
        );
        if (saved) Object.assign(draft, saved);
      } catch (_) {}
      draft.loaded = true;
    }
    const params = new URLSearchParams(location.search);
    if (appliedQuery !== location.search) {
      appliedQuery = location.search;
      for (const key of [
        "style",
        "layout",
        "color",
        "character_style",
        "scene_style",
      ])
        if (params.has(key)) draft[key] = params.get(key);
      if (params.has("fusion"))
        draft.fusion = ["1", "true"].includes(params.get("fusion"));
      if (options.modes.some((m) => m.value === params.get("mode")))
        draft.mode = params.get("mode");
      if (params.has("ratio")) draft.ratio = params.get("ratio");
      const template = state.boot.editorial.templates.find(
        (t) => t.id === params.get("template"),
      );
      if (template) Object.assign(draft, { ...template, loaded: true });
    }
    const context = el("div", { class: "hw-studio-context" }),
      visual = el("div", { class: "hw-studio-visual" }),
      references = el("div", { class: "hw-studio-references" }),
      batch = el("div", {});
    const theme = input(
      "theme",
      "画面主题或文章内容",
      "描述你想画的主体、动作和场景；文章模式可粘贴正文。",
      true,
    );
    theme.rows = 5;
    const readFile = el("input", {
      type: "file",
      accept: ".txt,.md,text/plain,text/markdown",
      "aria-label": "导入文章 TXT 或 Markdown",
    });
    readFile.addEventListener("change", async () => {
      const f = readFile.files[0];
      if (!f) return;
      try {
        if (f.size > 100000) throw Error("请使用十万字节以内的文本文件");
        const text = await f.text();
        if (text.length > 20000) throw Error("文章超过两万字，请选取需要配图的段落后导入");
        theme.value = text;
        change("theme", theme.value);
      } catch (error) {
        tell(error.message);
      } finally {
        readFile.value = "";
      }
    });
    function drawContext() {
      context.replaceChildren();
      if (draft.mode === "poster")
        context.append(
          field("受众", input("audience", "受众", "例如：年轻白领、亲子家庭")),
          field(
            "投放渠道",
            input("channel", "投放渠道", "例如：小红书、公众号、线下立牌"),
          ),
        );
      if (draft.mode === "photo")
        context.append(
          field(
            "拍摄类型",
            input("shoot_type", "拍摄类型", "可点选，也可自行填写"),
          ),
          el(
            "div",
            { class: "hw-studio-presets" },
            ...options.shoot_types.map((p) =>
              button(
                p.label,
                () => {
                  draft.shoot_type = p.value;
                  drawContext();
                  save();
                  refresh();
                },
                true,
              ),
            ),
          ),
        );
      readFile.closest("label").hidden = ![
        "article-illust",
        "article-cover",
      ].includes(draft.mode);
    }
    function drawVisual() {
      const slots = draft.fusion
        ? [
            ["character_style", "角色画风", "style"],
            ["scene_style", "场景画风", "style"],
          ]
        : [["style", "画风", "style"]];
      if (!["article-illust", "article-cover"].includes(draft.mode))
        slots.push(["layout", "图型", "layout"]);
      slots.push(["color", "配色", "color"]);
      visual.replaceChildren(
        ...slots.map(([key, label, kind]) => {
          const selected = find(draft[key]);
          const node = button(
            "",
            () =>
              picker(kind, (item) => {
                const value = item?.id || "";
                if (
                  draft.fusion &&
                  value &&
                  (key === "character_style"
                    ? draft.scene_style
                    : key === "scene_style"
                      ? draft.character_style
                      : null) === value
                )
                  throw Error("请选择两个不同画风");
                if (item && !find(value)) resources.push(item);
                draft[key] = value;
                drawVisual();
                save();
                refresh();
              }),
            true,
          );
          node.className = "hw-studio-slot";
          node.append(
            el("span", { class: "hw-help" }, label),
            selected?.image
              ? el("img", { src: selected.image, alt: selected.name })
              : el("span", { class: "hw-studio-no-image" }, "+"),
            el(
              "strong",
              {},
              selected?.name || (draft[key] ? "已选社区资产" : "由模型选择"),
            ),
            el("small", {}, "选择 / 更换"),
          );
          if (!selected && draft[key]?.startsWith("community:"))
            api(`/assets/${encodeURIComponent(draft[key])}`)
              .then((item) => {
                resources.push(normalize(item));
                if (root.isConnected) drawVisual();
              })
              .catch((e) => tell(e.message));
          return node;
        }),
      );
      if (draft.layout === "SC-021")
        visual.append(
          field(
            "双拼转译类型",
            select(
              "layout_variant",
              "双拼转译类型",
              options.sc021_types.map((v, i) => [
                i + 1,
                `${String(i + 1).padStart(2, "0")} · ${v}`,
              ]),
            ),
          ),
        );
    }
    function drawReferences() {
      references.replaceChildren(
        ...draft.references.map((ref, i) =>
          el(
            "div",
            { class: "hw-studio-reference" },
            el("img", {
              src: `/studio/api/private-images/${ref.id}`,
              alt: ref.name,
            }),
            el("span", {}, ref.name),
            (() => {
              const s = el(
                "select",
                { "aria-label": `${ref.name} 的参考用途` },
                ...Object.entries({
                  redraw: "照片转绘",
                  characters: "角色",
                  props: "道具",
                  scenes: "场景",
                  style: "只参考画风",
                }).map(([v, t]) => el("option", { value: v }, t)),
              );
              s.value = ref.role;
              s.onchange = () => {
                ref.role = s.value;
                save();
                refresh();
              };
              return s;
            })(),
            button(
              "移除",
              () => {
                draft.references.splice(i, 1);
                drawReferences();
                save();
                refresh();
              },
              true,
            ),
          ),
        ),
      );
      for (const id of draft.asset_refs) {
        const item = options.assets.find((a) => a.id === id);
        if (item)
          references.append(
            el(
              "div",
              { class: "hw-studio-reference" },
              el("img", { src: item.image, alt: item.name }),
              el("span", {}, item.name),
              button(
                "移除",
                () => {
                  draft.asset_refs = draft.asset_refs.filter((v) => v !== id);
                  drawReferences();
                  save();
                  refresh();
                },
                true,
              ),
            ),
          );
      }
    }
    const upload = el("input", {
      type: "file",
      accept: "image/png,image/jpeg,image/webp",
      multiple: true,
      "aria-label": "添加私人参考图片",
    });
    const uploadStatus = text("上传到本人私有空间；不会随作品自动公开。");
    upload.addEventListener("change", async () => {
      if (!state.boot.user) {
        tell("请登录后添加参考图片");
        return;
      }
      try {
        for (const file of upload.files) {
          if (draft.references.length + draft.asset_refs.length >= 6)
            throw Error("最多六张参考图");
          if (file.size > 10 * 1024 * 1024) throw Error("单张图片最多 10 MB");
          uploadStatus.textContent = `正在保存 ${file.name}…`;
          const csrf = await fetch("/session/csrf.json", {
            credentials: "same-origin",
          }).then((r) => r.json());
          const form = new FormData();
          form.append("file", file);
          const result = await fetch("/studio/api/private-images", {
            method: "POST",
            credentials: "same-origin",
            headers: { "X-CSRF-Token": csrf.csrf },
            body: form,
          });
          const data = await result.json();
          if (!result.ok)
            throw Error(data.errors?.join("；") || "图片保存失败");
          draft.references.push({
            id: data.url.split("/").pop(),
            role: "redraw",
            name: file.name,
          });
          drawReferences();
          save();
          refresh();
        }
        uploadStatus.textContent = "参考图已保存，仅本人可见。";
      } catch (error) {
        uploadStatus.textContent = error.message;
      } finally {
        upload.value = "";
      }
    });
    function drawBatch() {
      batch.hidden = !draft.batch;
      if (!draft.batch) return;
      const count = select(
        "count",
        "批量张数",
        [1, 2, 3, 4, 5].map((n) => [n, `${n} 张`]),
      );
      count.addEventListener("change", drawBatch);
      const lines = el("textarea", {
        "aria-label": "逐张主题，一行一张",
        rows: 4,
        placeholder: "选填：每行一张的主题。留空则沿用主主题生成不同版本。",
      });
      lines.value = draft.themes.join("\n");
      lines.oninput = () =>
        change("themes", lines.value.split("\n").slice(0, 5));
      const selected = text(
        `图型：${draft.layouts.map(name).join("、") || "沿用当前图型"}`,
      );
      batch.replaceChildren(
        field("张数", count),
        field("逐张主题", lines),
        check("混合多种图型", "mix_layouts"),
        button(
          "选择本批次图型",
          () =>
            picker(
              "layout",
              (items) => {
                for (const item of items)
                  if (!find(item.id)) resources.push(item);
                change(
                  "layouts",
                  items.map((i) => i.id),
                );
                drawBatch();
              },
              draft.layouts,
              true,
            ),
          true,
        ),
        selected,
        text(
          "每张计入每日额度，前一张结束后才提交下一张。可取消尚未开始的任务。",
        ),
      );
    }
    const modeTabs = el("div", {
      class: "hw-studio-modes",
      role: "group",
      "aria-label": "创作类型",
    });
    function drawModes() {
      modeTabs.replaceChildren(
        ...options.modes.map((p) => {
          const n = button(
            p.label,
            () => {
              draft.mode = p.value;
              draft.ratio = {
                pure: "3:4",
                "graphic-text": "3:4",
                poster: "9:16",
                "article-cover": "2.35:1",
                "article-illust": "4:3",
                photo: "3:4",
              }[p.value];
              if (["article-cover", "article-illust"].includes(p.value))
                draft.layout = "";
              drawModes();
              drawContext();
              drawVisual();
              ratio.value = draft.ratio;
              save();
              refresh();
            },
            true,
          );
          n.setAttribute("aria-pressed", String(draft.mode === p.value));
          return n;
        }),
      );
    }
    const ratio = input(
      "ratio",
      "画幅比例",
      "可手填，例如 5:2、2.35:1；留空自动",
    );
    const mood = input("mood", "情绪", "可多选，也可自行输入");
    const tones = el(
      "div",
      { class: "hw-studio-tones" },
      ...options.tones.map((t) => {
        const n = el("input", { type: "checkbox" });
        n.checked = draft.tones.includes(t.id);
        n.onchange = () => {
          draft.tones = n.checked
            ? [...draft.tones, t.id]
            : draft.tones.filter((id) => id !== t.id);
          save();
          refresh();
        };
        return el(
          "label",
          { title: t.desc_zh },
          n,
          `${t.name_zh} · ${t.desc_zh}`,
        );
      }),
    );
    preview = el("textarea", {
      class: "hw-studio-prompt",
      readonly: true,
      "aria-label": "提示词预览",
      rows: 12,
    });
    const tabs = el(
      "div",
      { class: "hw-studio-output-tabs" },
      ...[
        ["prompt", "实际生图提示词"],
        ["command", "Skill 指令"],
      ].map(([key, title]) =>
        button(
          title,
          () => {
            outputKind = key;
            showOutput();
          },
          true,
        ),
      ),
      button(
        "中文 / English",
        () => {
          language = language === "zh" ? "en" : "zh";
          outputKind = "command";
          showOutput();
        },
        true,
      ),
    );
    submit = el("button", { type: "button", class: "hw-button" }, "生成图片");
    submit.addEventListener("click", async () => {
      if (submit.disabled) return;
      try {
        if (!state.boot.user) {
          save();
          location.href = "/login";
          return;
        }
        if (!previewPlans.length)
          throw Error("请先完善选项，等待提示词预览就绪");
        const fingerprint = JSON.stringify(draft);
        if (client?.fingerprint !== fingerprint)
          client = { fingerprint, id: crypto.randomUUID() };
        submit.disabled = true;
        active = true;
        await api("/generations", {
          method: "POST",
          body: JSON.stringify({ client_id: client.id, creation: draft }),
        });
        await loadHistory(true);
      } catch (error) {
        tell(error.message);
        await loadHistory(true);
      } finally {
        updateSubmit();
      }
    });
    history = el(
      "div",
      { class: "hw-studio-history", "aria-live": "polite" },
      el("div", { class: "hw-studio-canvas" }, text("生成结果会显示在这里。")),
    );
    root = el(
      "div",
      { class: "hw-studio" },
      el(
        "section",
        { class: "hw-studio-settings" },
        el(
          "div",
          { class: "hw-studio-toolbar" },
          el("strong", {}, "提示词拼装器"),
          button(
            "随机组合",
            () => {
              const styles = resources.filter(
                (r) => r.kind === "style" && r.source !== "community",
              );
              const pick = (a) => a[Math.floor(Math.random() * a.length)];
              if (draft.fusion) {
                draft.character_style = pick(styles).id;
                draft.scene_style = pick(
                  styles.filter((s) => s.id !== draft.character_style),
                ).id;
              } else draft.style = pick(styles).id;
              draft.color = pick(
                resources.filter((r) => r.kind === "color"),
              ).id;
              if (!["article-cover", "article-illust"].includes(draft.mode))
                draft.layout = pick(
                  resources.filter((r) => r.kind === "layout"),
                ).id;
              drawVisual();
              save();
              refresh();
            },
            true,
          ),
          button(
            "重置",
            () => {
              draft = defaults();
              save();
              create();
            },
            true,
          ),
        ),
        modeTabs,
        field("01 / 主题与内容", theme),
        field("导入文章", readFile),
        context,
        el("h3", {}, "02 / 画风与图型"),
        check("风格融合 · 角色画风 × 场景画风", "fusion", () => {
          if (draft.fusion && !draft.character_style)
            draft.character_style = draft.style;
          drawVisual();
          save();
          refresh();
        }),
        visual,
        el(
          "div",
          { class: "hw-studio-pair" },
          field(
            "留白",
            select("whitespace", "留白", [
              ["normal", "正常"],
              ["moderate", "适中 · 大量留白"],
              ["high", "多 · 只显示必要场景"],
            ]),
          ),
          field(
            "画质",
            select("quality", "画质", [
              ["auto", "自动"],
              ["low", "快速"],
              ["medium", "标准"],
              ["high", "精细"],
            ]),
          ),
        ),
        field("画幅比例", ratio),
        el(
          "div",
          { class: "hw-studio-presets" },
          ...options.ratios.map((p) =>
            button(
              p.label,
              () => {
                ratio.value = p.value;
                change("ratio", p.value);
              },
              true,
            ),
          ),
          button(
            "16:9",
            () => {
              ratio.value = "16:9";
              change("ratio", "16:9");
            },
            true,
          ),
        ),
        field("情绪", mood),
        el(
          "div",
          { class: "hw-studio-presets" },
          ...options.moods.map((p) =>
            button(
              p.label,
              () => {
                const values = new Set(
                  draft.mood.split(/[、,，]/).filter(Boolean),
                );
                values.has(p.value)
                  ? values.delete(p.value)
                  : values.add(p.value);
                mood.value = [...values].join("、");
                change("mood", mood.value);
              },
              true,
            ),
          ),
        ),
        el(
          "details",
          { class: "hw-studio-detail" },
          el("summary", {}, "影调 · 16 种，可多选"),
          tones,
        ),
        el(
          "details",
          { class: "hw-studio-detail" },
          el("summary", {}, "角色、道具、场景与照片转绘"),
          text("给每张参考图指定用途，生成时会实际附图。"),
          upload,
          uploadStatus,
          button(
            "选择官方角色",
            () =>
              modal(
                "官方角色",
                ...options.assets.map((a) =>
                  button(
                    `${a.id} · ${a.name}`,
                    () => {
                      if (!draft.asset_refs.includes(a.id)) {
                        if (
                          draft.references.length + draft.asset_refs.length >=
                          6
                        )
                          throw Error("最多六张参考图");
                        draft.asset_refs.push(a.id);
                      }
                      drawReferences();
                      save();
                      refresh();
                      close();
                    },
                    true,
                  ),
                ),
              ),
            true,
          ),
          references,
        ),
        check("批量出图", "batch", drawBatch),
        batch,
        field(
          "补充要求",
          input(
            "extra",
            "补充要求",
            "例如：需要出现的文字、人物约束或具体修改要求",
            true,
          ),
        ),
        text(
          "草稿保存在本次浏览器会话中。上传参考图和生成结果默认仅本人可见。",
        ),
      ),
      el(
        "section",
        { class: "hw-studio-result" },
        el(
          "div",
          { class: "hw-studio-toolbar" },
          el("h3", {}, "生成与预览"),
          el(
            "span",
            { id: "studio-quota", class: "hw-help" },
            state.boot.user
              ? "正在读取额度…"
              : "登录并验证账号后，每天可生成五张",
          ),
        ),
        submit,
        text("GPT Image 2 · 不扣社区积分"),
        state.boot.user
          ? button("刷新任务状态", () => loadHistory(true), true)
          : null,
        history,
        el(
          "details",
          { class: "hw-studio-detail", open: true },
          el("summary", {}, "查看提示词与导出"),
          tabs,
          el("p", {
            id: "studio-preview-status",
            class: "hw-help",
            role: "status",
          }),
          preview,
          el(
            "div",
            { class: "hw-actions" },
            button(
              "复制当前内容",
              async (node) => {
                if (!preview.value) throw Error("请先填写主题");
                await navigator.clipboard.writeText(preview.value);
                node.textContent = "已复制 ✓";
              },
              true,
            ),
            button(
              "导出创作记录",
              () => {
                const blob = new Blob(
                  [
                    JSON.stringify(
                      {
                        creation: draft,
                        command: command(),
                        prompts: previewPlans.map((p) => p.prompt),
                      },
                      null,
                      2,
                    ),
                  ],
                  { type: "application/json" },
                );
                const url = URL.createObjectURL(blob);
                const a = el("a", {
                  href: url,
                  download: "handraw-creation.json",
                });
                a.click();
                setTimeout(() => URL.revokeObjectURL(url), 1000);
              },
              true,
            ),
          ),
        ),
      ),
    );
    $("#content").replaceChildren(root);
    drawModes();
    drawContext();
    drawVisual();
    drawReferences();
    drawBatch();
    refresh();
    await loadHistory();
  }
  async function loadHistory(poll = false) {
    clearTimeout(pollTimer);
    if (!root?.isConnected || !state.boot.user) return;
    try {
      const data = await api(`/generations${poll ? "?refresh=1" : ""}`);
      if (!root.isConnected) return;
      remaining = data.remaining;
      active = data.tasks.some((t) =>
        ["queued", "running", "waiting"].includes(t.status),
      );
      $("#studio-quota").textContent =
        `今日剩余 ${remaining} 张${active ? " · 当前任务进行中" : ""}`;
      if (
        client &&
        data.tasks.some(
          (t) =>
            t.client_id === client.id &&
            ["success", "error"].includes(t.status),
        )
      )
        client = null;
      updateSubmit();
      if (data.tasks.length)
        history.replaceChildren(
          ...data.tasks.slice(0, 10).map((task) => {
            const fingerprint = JSON.stringify([
              task.title,
              task.status,
              task.message,
              task.images,
            ]);
            const existing = historyRows.get(task.id);
            if (existing?.fingerprint === fingerprint) return existing.row;
            const row = el(
              "article",
              { class: "hw-studio-task" },
              el(
                "div",
                { class: "hw-studio-task-heading" },
                el("strong", {}, task.title),
                el(
                  "span",
                  { class: `hw-task-status hw-task-${task.status}` },
                  {
                    waiting: "等待前一张完成",
                    queued: "排队 / 等待确认",
                    running: "正在绘制",
                    success: "已完成",
                    error: "未完成",
                  }[task.status] || task.status,
                ),
              ),
              task.batch_total
                ? text(`本批第 ${task.batch_position} / ${task.batch_total} 张`)
                : null,
              task.message ? text(task.message) : null,
            );
            if (task.status === "queued" && task.message)
              row.append(
                button(
                  "确认原任务状态",
                  async () => {
                    await api(`/generations/${task.id}/retry`, {
                      method: "POST",
                      body: "{}",
                    });
                    await loadHistory(true);
                  },
                  true,
                ),
              );
            if (task.batch_id && task.status === "waiting")
              row.append(
                button(
                  "取消本批尚未开始的任务",
                  async () => {
                    await api(`/generation-batches/${task.batch_id}/cancel`, {
                      method: "POST",
                      body: "{}",
                    });
                    await loadHistory();
                  },
                  true,
                ),
              );
            for (const [index, src] of task.images.entries())
              row.append(
                el("img", {
                  src,
                  alt: task.title,
                  class: "hw-studio-generated",
                }),
                el(
                  "div",
                  { class: "hw-actions" },
                  el(
                    "a",
                    {
                      href: src,
                      download: `handraw-${task.id}-${index}.png`,
                      class: "hw-text-link",
                    },
                    "保存图片 ↓",
                  ),
                  button(
                    "分享这张图",
                    async () => {
                      const response = await fetch(src, {
                        credentials: "same-origin",
                      });
                      if (!response.ok) throw Error("图片暂时无法读取");
                      const blob = await response.blob();
                      const detail = await api(
                        `/generations/${task.id}/content`,
                      );
                      await share("work", {
                        title: task.title,
                        summary: "在手绘风创作台完成的作品。",
                        prompt: detail.prompt,
                        parameters: Object.fromEntries(
                          Object.entries(detail.creation?.parameters || {}).filter(
                            ([key]) => key !== "references",
                          ),
                        ),
                        assets: detail.creation?.assets || [],
                        image: new File([blob], `handraw-${task.id}.png`, {
                          type: blob.type,
                        }),
                      });
                    },
                    true,
                  ),
                ),
              );
            row.append(
              button(
                "载入这次选项继续创作",
                () => {
                  Object.assign(
                    draft,
                    defaults(),
                    task.creation?.parameters || {},
                    { theme: task.creation?.parameters?.theme || task.title },
                  );
                  save();
                  create();
                },
                true,
              ),
            );
            historyRows.set(task.id, { fingerprint, row });
            return row;
          }),
        );
      if (active)
        pollTimer = setTimeout(() => {
          if (root.isConnected)
            loadHistory(document.visibilityState === "visible");
        }, 15000);
    } catch (error) {
      tell(error.message);
    }
  }
  return { create, stop };
};
