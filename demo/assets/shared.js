/* Shared State, Cross-Subdomain Sync, Header, Auth Gate, Share & Asset Picker Modals */
(function () {
  const STORAGE_KEY = "handraw_web_v2_demo_state";

  const EXTRA_WORKS = [
    {
      id: "work_126",
      title: "初试手绘：窗台多肉与手冲壶的周日晨光笔记",
      author: "sprout_xia",
      authorName: "小夏初学手绘",
      createdAt: "6 分钟前",
      isNewRelease: true,
      cheers: 14,
      images: ["/images/individual/FB/FB-001.webp"],
      styles: ["FB-001"],
      layout: "SC-001",
      color: "C-10",
      tone: "T-01",
      ratio: "3:4",
      mode: "graphic-text",
      mood: "治愈",
      price: 0,
      likes: 18,
      favorites: 12,
      forks: 4,
      prompt: "首次尝试 #FB-001 轻透水彩手账画风 + SC-001 社媒卡结构：阳光洒在木质窗台的３盆小多肉与玻璃分享壶上，顶部手写标题『周日慢下来』，留白 55%。",
      notes: "第一次在社区发作品！没想到水彩边缘这么自然，求前辈们多多鼓励指点～",
      comments: []
    },
    {
      id: "work_123",
      title: "烟雨西湖手摇船 · 江南梅雨淡墨新画风首测",
      author: "su_editorial",
      authorName: "苏苏的纸上茶馆",
      createdAt: "15 分钟前",
      isNewRelease: true,
      cheers: 39,
      images: ["/images/individual/FB/FB-002.webp", "/images/poster-demo-autumn-equinox.webp"],
      styles: ["USR-S05"],
      layout: "SC-024",
      color: "C-10",
      tone: "T-13",
      ratio: "3:4",
      mode: "poster",
      mood: "诗意",
      price: 0,
      likes: 62,
      favorites: 48,
      forks: 19,
      prompt: "采用刚贡献的新画风 #USR-S05 江南梅雨季宣纸淡墨小景 + SC-024 图下文上留白卡。细雨笼罩青石拱桥与一叶乌篷船，船头置一把油纸伞，上方宣纸留白题字『听雨眠』。",
      notes: "刚入库的 USR-S05 首张实测样张，免费开放给大家做节气茶饮海报！",
      comments: []
    },
    {
      id: "work_124",
      title: "飞天琵琶藻井纹样 · 敦煌青绿岩彩书签组图",
      author: "lin_sketch",
      authorName: "林默 · 独立插画师",
      createdAt: "36 分钟前",
      isNewRelease: true,
      cheers: 47,
      images: ["/images/individual/FE/FE-002.webp", "/images/individual/FE/FE-001.webp"],
      styles: ["USR-S03"],
      layout: "LX-001",
      color: "C-17",
      tone: "T-14",
      ratio: "3:4",
      mode: "poster",
      mood: "庄严",
      price: 0,
      likes: 84,
      favorites: 71,
      forks: 28,
      prompt: "文博特展海报（3:4）。采用社区新发画风 #USR-S03 敦煌矿物青绿岩彩绘本风 + LX-001 杂志封面排版，石青石绿粗颗粒矿物层次配朱膘云纹。",
      notes: "矿物颗粒感在 3:4 竖版海报里细节拉满。",
      comments: []
    },
    {
      id: "work_125",
      title: "独立书店藏书票：夜航灯塔与旧钢笔木刻实验",
      author: "yang0",
      authorName: "Yang · 创作者",
      createdAt: "48 分钟前",
      isNewRelease: true,
      cheers: 31,
      images: ["/images/individual/FH/FH-002.webp"],
      styles: ["USR-S04"],
      layout: "SC-019",
      color: "C-15",
      tone: "T-05",
      ratio: "3:4",
      mode: "poster",
      mood: "复古",
      price: 0,
      likes: 53,
      favorites: 42,
      forks: 15,
      prompt: "藏书票海报（SC-019 居中结构）。采用 #USR-S04 暖调木刻藏书票手绘版画，松烟褐排刀刻画海浪中的孤岛灯塔，朱砂红细框压印 EX LIBRIS。",
      notes: "自己提炼的木刻藏书票画风实测，印在棉纸明信片上非常有质感！",
      comments: []
    },
    {
      id: "work_121",
      title: "冷脸猫咪的周三下午茶罢工宣言",
      author: "momo_design",
      authorName: "沫沫视觉实验室",
      createdAt: "1 天前",
      cheers: 94,
      images: ["/images/individual/FA/FA-002.webp"],
      styles: ["FA-001"],
      layout: "SC-025",
      color: "C-21",
      tone: "T-01",
      ratio: "3:4",
      mode: "graphic-text",
      mood: "幽默",
      price: 0,
      likes: 136,
      favorites: 109,
      forks: 29,
      prompt: "漫画气泡社媒卡（SC-025）。采用 #FA-001 Gemma Correll 怪萌冷脸涂鸦，画一只趴在键盘上拒绝挪窝的三花猫，头顶三个手写气泡：『需求改第8版了』『本喵建议重开』『小鱼干结一下』。",
      notes: "FA-001 画宠物职场嘴替百试百灵。",
      comments: []
    },
    {
      id: "work_122",
      title: "京都鸭川傍晚跳乌龟石 · 视线锚点跨界续绘双拼",
      author: "su_editorial",
      authorName: "苏苏的纸上茶馆",
      createdAt: "2 天前",
      cheers: 168,
      images: ["/images/individual/FB/FB-003.webp"],
      styles: ["FB-022", "FX-001"],
      layout: "SC-021",
      sc021Type: "视线锚点跨界续绘型",
      color: "C-08",
      tone: "T-13",
      ratio: "3:4",
      mode: "graphic-text",
      mood: "诗意",
      price: 0,
      likes: 228,
      favorites: 195,
      forks: 73,
      prompt: "SC-021 自适应双拼（类型 01 · 视线锚点跨界续绘型）。上方真实摄影拍摄傍晚鸭川水面跳石；河水波纹跨过中线直接流淌进下方暖宣纸世界，化作 #FX-001 与 #FB-022 笔下的水彩溪流与提灯笼小狐狸，四周 60% 留白。",
      notes: "01 跨界续绘型让上下两半连成同一个故事，评论区全在问怎么做到的！",
      comments: []
    },
    {
      id: "work_127",
      title: "谷雨新茶 · 手绘节气风物图鉴折页",
      author: "su_editorial",
      authorName: "苏苏的纸上茶馆",
      createdAt: "2 天前",
      cheers: 142,
      images: ["/images/individual/FA/FA-003.webp"],
      styles: ["FA-003", "FX-001"],
      layout: "SC-006",
      color: "C-10",
      tone: "T-13",
      ratio: "3:4",
      mode: "graphic-text",
      mood: "松弛",
      price: 0,
      likes: 194,
      favorites: 166,
      forks: 58,
      prompt: "节气茶事散点图鉴（SC-006）。采用 #FA-003 桑贝细钢笔淡彩结合 #FX-001 宣纸底纹，绘白瓷茶海、竹编茶则、明前嫩芽与春笋小碟。",
      notes: "茶馆春季菜单直接用了这套手绘折页。",
      comments: []
    },
    {
      id: "work_128",
      title: "山茶花庭院午睡橘猫 · 钢笔淡彩明信片",
      author: "su_editorial",
      authorName: "苏苏的纸上茶馆",
      createdAt: "3 天前",
      cheers: 126,
      images: ["/images/individual/FB/FB-031.webp"],
      styles: ["FB-031"],
      layout: "SC-024",
      color: "C-15",
      tone: "T-10",
      ratio: "4:3",
      mode: "article-illust",
      mood: "治愈",
      price: 0,
      likes: 172,
      favorites: 148,
      forks: 46,
      prompt: "绘本明信片（4:3）。#FB-031 诗意水彩晕染盛开的山茶花丛，竹藤椅上蜷睡一只胖橘猫，留足上方纸白印短句。",
      notes: "随茶礼附赠的节气明信片，好评率 100%。",
      comments: []
    },
    {
      id: "work_129",
      title: "胡同老书摊黄昏速写 · 人物群像叙事长卷",
      author: "lin_sketch",
      authorName: "林默 · 独立插画师",
      createdAt: "2 天前",
      cheers: 135,
      images: ["/images/individual/FD/FD-001.webp"],
      styles: ["USR-S01", "FA-003"],
      layout: "LX-002",
      color: "C-27",
      tone: "T-14",
      ratio: "3:4",
      mode: "poster",
      mood: "温暖",
      price: 0,
      likes: 188,
      favorites: 159,
      forks: 51,
      prompt: "长卷分镜故事图（LX-002）。用 #USR-S01 炭精淡彩描绘胡同槐树下的旧书摊、戴老花镜的摊主与蹲着看连环画的放学小孩。",
      notes: "USR-S01 叠 LX-002 讲烟火气城市故事特别打动人。",
      comments: []
    },
    {
      id: "work_130",
      title: "威士忌爵士夜 · 双色丝网错版演出现场招贴",
      author: "lin_sketch",
      authorName: "林默 · 独立插画师",
      createdAt: "3 天前",
      cheers: 118,
      images: ["/images/individual/FH/FH-001.webp"],
      styles: ["FX-002"],
      layout: "SC-023",
      color: "C-04",
      tone: "T-06",
      ratio: "3:4",
      mode: "poster",
      mood: "复古",
      price: 0,
      likes: 165,
      favorites: 141,
      forks: 44,
      prompt: "独立演出招贴（SC-023）。#FX-002 普鲁士蓝与朱砂橙双色孔版错位套印，小号手剪影化作流动音符。",
      notes: "双色丝网印刷风成本低、视觉冲击力极强。",
      comments: []
    },
    {
      id: "work_131",
      title: "复古黑胶播客封面：深夜电台第 42 期失眠歌单",
      author: "momo_design",
      authorName: "沫沫视觉实验室",
      createdAt: "1 天前",
      cheers: 109,
      images: ["/images/individual/FC/FC-002.webp"],
      styles: ["USR-S02"],
      layout: "USR-L03",
      color: "C-28",
      tone: "T-05",
      ratio: "3:4",
      mode: "poster",
      mood: "松弛",
      price: 0,
      likes: 158,
      favorites: 133,
      forks: 39,
      prompt: "播客金句页签（#USR-L03）+ #USR-S02 酸性复古黑胶涂鸦：戴大耳机的黑猫漂浮在旋转黑胶唱片星环上，下方排印 02:14 时间轴金句。",
      notes: "用自己贡献的 USR-S02 + USR-L03 双自研配方组合！",
      comments: []
    },
    {
      id: "work_132",
      title: "野生甜品店『榴莲千层真香定律』四格反差漫",
      author: "momo_design",
      authorName: "沫沫视觉实验室",
      createdAt: "3 天前",
      cheers: 96,
      images: ["/images/layouts/comic-storyboards/SB-002.webp"],
      styles: ["FA-017"],
      layout: "SB-002",
      color: "C-26",
      tone: "T-01",
      ratio: "1:1",
      mode: "graphic-text",
      mood: "幽默",
      price: 0,
      likes: 144,
      favorites: 120,
      forks: 37,
      prompt: "四格反差漫画（SB-002）+ #FA-017 黑白圆眼反应漫：前三格捂鼻子摆手拒绝榴莲，第四格抱着空盘子舔叉子热泪盈眶。",
      notes: "甜品店朋友圈投放转化率超高的一张四格。",
      comments: []
    },
    {
      id: "work_133",
      title: "AI 产品需求优先级四象限手绘白板卡",
      author: "pm_chen",
      authorName: "阿陈做产品",
      createdAt: "1 天前",
      cheers: 112,
      images: ["/images/layouts/infographics/IG-004.webp"],
      styles: ["FC-029"],
      layout: "USR-L02",
      color: "C-01",
      tone: "T-01",
      ratio: "3:4",
      mode: "graphic-text",
      mood: "松弛",
      price: 0,
      likes: 161,
      favorites: 147,
      forks: 63,
      prompt: "采用新贡献的 #USR-L02 方法论四象限手绘拆解矩阵 + #FC-029 清透现代扁平插画，清晰拆解『高频刚需 / 低成本惊喜 / 资源黑洞 / 伪需求』四象限。",
      notes: "产品周会汇报与小红书职场干货通吃！",
      comments: []
    },
    {
      id: "work_134",
      title: "新消费燕麦奶『痛点三连问』首发种草封面",
      author: "brand_zhou",
      authorName: "周周品牌提案室",
      createdAt: "1 天前",
      cheers: 88,
      images: ["/images/layouts/social-cards/SC-024.webp"],
      styles: ["FA-001"],
      layout: "USR-L04",
      color: "C-26",
      tone: "T-01",
      ratio: "3:4",
      mode: "graphic-text",
      mood: "活力",
      price: 0,
      likes: 139,
      favorites: 118,
      forks: 45,
      prompt: "采用 #USR-L04 痛点三连问封面爆款钩子卡 + #FA-001 冷脸涂鸦：顶部三枚气泡追问乳糖不耐痛点，中央画快乐举杯的小牛与燕麦穗。",
      notes: "USR-L04 实测小红书封面点击率 14.8%！",
      comments: []
    }
  ];

  const STYLE_GROUPS = [
    { key: "ALL", label: "全部画风" },
    { key: "NEW_RELEASE", label: "🌱 新发扶持" },
    { key: "COMMUNITY", label: "✨ 社区共创" },
    { key: "EXCLUSIVE", label: "🔒 在线独占" },
    { key: "HAS_WORKS", label: "🔥 有作品" },
    { key: "FA", label: "FA 社论幽默" },
    { key: "FB", label: "FB 绘本水彩" },
    { key: "FC", label: "FC 现代几何" },
    { key: "FD", label: "FD 日系插画" },
    { key: "FE", label: "FE 概念厚涂" },
    { key: "FF", label: "FF 潮玩立体手作" },
    { key: "FG", label: "FG 动漫分镜" },
    { key: "FH", label: "FH 独立印刷媒介" },
    { key: "FI", label: "FI 大师摄影电影" }
  ];

  const LAYOUT_GROUPS = [
    { key: "ALL", label: "全部图型" },
    { key: "NEW_RELEASE", label: "🌱 新发扶持" },
    { key: "COMMUNITY", label: "✨ 社区共创" },
    { key: "EXCLUSIVE", label: "🔒 在线独占" },
    { key: "HAS_WORKS", label: "🔥 有作品" },
    { key: "social-card", label: "SC 小红书社媒卡" },
    { key: "infographic", label: "IG 知识信息图" },
    { key: "comic-storyboard", label: "SB 漫画分镜" },
    { key: "ip-character", label: "IP 角色设定" },
    { key: "ecommerce", label: "EC 商业电商" }
  ];

  const SAMPLE_UPLOAD_IMAGES = [
    { label: "节气茶会海报", url: "/images/poster-demo-autumn-equinox.webp" },
    { label: "扁平知识卡片", url: "/images/graphic-text-mode-demo.webp" },
    { label: "胶片人物摄影", url: "/images/realistic.webp" },
    { label: "双拼转译样张", url: "/images/layouts/social-cards/SC-021.webp" },
    { label: "黑猫侍者角色", url: "/images/characters/CH-001.webp" },
    { label: "绘本森林水彩", url: "/images/individual/FB/FB-031.webp" }
  ];

  const App = {
    channel: "main", // 'main' | 'studio' | 'forum'
    view: "styles",
    catalogRaw: null,
    options: null,
    state: null,
    styles: [],
    layouts: [],
    colors: [],
    resourceMap: new Map(),
    listeners: [],
    bootError: null
  };

  function esc(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function safeHref(u) {
    if (!u || typeof u !== "string") return "";
    const s = u.trim();
    if (/[\x00-\x1f\x7f]/.test(s)) return "";
    if (/^[/\\]{2,}|^\/\\/.test(s)) return "";
    if (/^(?:https?:\/\/|mailto:)/i.test(s)) return s;
    if (/^(\/(?![/\\])|#)/.test(s)) return s;
    return "";
  }

  function safeMediaUrl(u, opts = {}) {
    if (!u || typeof u !== "string") return "";
    const s = u.trim();
    if (/[\x00-\x1f\x7f]/.test(s)) return "";
    if (/^[/\\]{2,}|^\/\\/.test(s)) return "";
    if (opts.allowData && /^data:image\/(?:png|jpeg|jpg|webp|gif);base64,[A-Za-z0-9+/=\r\n]+$/i.test(s)) {
      return s;
    }
    if (/^https?:\/\//i.test(s)) return s;
    if (/^\/(?![/\\])/.test(s)) return s;
    return "";
  }

  function stripHtmlToSnippet(html, maxLen = 140) {
    if (!html) return "";
    const raw = String(html);
    let text = "";
    if (typeof DOMParser !== "undefined") {
      try {
        const doc = new DOMParser().parseFromString(raw, "text/html");
        const bad = doc.querySelectorAll("script, style, svg, math, iframe, object, embed, .hw-intext-del-btn, .btn, figcaption, .hw-honor-badge");
        bad.forEach((el) => el.remove());
        text = (doc.body.textContent || "").replace(/\s+/g, " ").trim();
      } catch (_) {
        text = "";
      }
    }
    if (!text && raw) {
      let s = raw.replace(/<\s*(script|style|iframe|object|embed|svg|math)[^>]*>[\s\S]*?(?:<\s*\/\s*\1\s*>|$)/gi, "");
      s = s.replace(/<\/?[a-zA-Z][^>]*>/g, " ");
      s = s.replace(/<[a-zA-Z][^<]*$/g, " ");
      text = s.replace(/\s+/g, " ").trim();
    }
    return text.length > maxLen ? text.slice(0, maxLen) + "…" : text;
  }

  function normalizeTopicImages(t) {
    if (!t) return [];
    let list = t.images;
    if ((!list || !list.length) && t.images_json) {
      try {
        list = typeof t.images_json === "string" ? JSON.parse(t.images_json) : t.images_json;
      } catch (_) {
        list = [];
      }
    }
    if ((!list || !list.length) && t.workId) {
      const works = (App && App.state && App.state.works) || (typeof window !== "undefined" && window.App && window.App.state && window.App.state.works);
      if (Array.isArray(works)) {
        const w = works.find((x) => x && x.id === t.workId);
        if (w && Array.isArray(w.images) && w.images.length) {
          list = w.images;
        }
      }
    }
    if (!Array.isArray(list)) list = [];
    return list
      .map((im) =>
        typeof im === "string" ? { url: im, tag: "" } : { url: (im && im.url) || "", tag: (im && im.tag) || "" }
      )
      .filter((im) => Boolean(im.url));
  }

  function toast(message) {
    let stack = document.getElementById("hw-toast-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.id = "hw-toast-stack";
      stack.className = "hw-toast-stack";
      document.body.appendChild(stack);
    }
    const item = document.createElement("div");
    item.className = "hw-toast";
    item.textContent = message;
    stack.appendChild(item);
    setTimeout(() => {
      item.style.opacity = "0";
      item.style.transition = "opacity 0.25s";
      setTimeout(() => item.remove(), 260);
    }, 2800);
  }

  function channelUrl(targetChannel, paramsObj) {
    // All public resource links have one canonical forum destination.
    if (targetChannel === "main" && ["topics", "works"].includes(paramsObj?.tab) && ["asset", "work"].includes(paramsObj?.view)) {
      const { view, id, tab, panel } = paramsObj;
      const item = App.resourceMap?.get(String(id || "").toUpperCase());
      targetChannel = "forum";
      paramsObj = { view: "related", kind: view === "work" ? "work" : item?.kind || "asset", id, tab };
      if (panel === 'report' || tab === 'report') paramsObj.panel = 'report';
    } else if (targetChannel === "main" && ["asset", "work"].includes(paramsObj?.view)) {
      const { id, tab, focus, panel } = paramsObj;
      const extra = {};
      if (focus || tab === "comments") extra.focus = "comment";
      if (panel === "report" || tab === "report") extra.panel = "report";
      const qs = new URLSearchParams(extra).toString();
      const suffix = qs ? `?${qs}` : "";
      const ref = encodeURIComponent(id || "");
      const host = window.location.hostname.toLowerCase();
      const proto = window.location.protocol;
      if (host.endsWith("handraw-style.com")) {
        const rootDomain = "handraw-style.com";
        const portPart = window.location.port ? `:${window.location.port}` : "";
        return `${proto}//forum.${rootDomain}${portPart}/t/${ref}${suffix}`;
      }
      if (host.endsWith(".localhost")) {
        const portPart = window.location.port ? `:${window.location.port}` : "";
        return `${proto}//forum.localhost${portPart}/t/${ref}${suffix}`;
      }
      return `/t/${ref}${suffix}`;
    }
    const host = window.location.hostname.toLowerCase();
    const proto = window.location.protocol;
    const qs = paramsObj ? new URLSearchParams(paramsObj).toString() : "";
    const suffix = qs ? `?${qs}` : "";

    if (host.endsWith("handraw-style.com")) {
      const rootDomain = "handraw-style.com";
      const portPart = window.location.port ? `:${window.location.port}` : "";
      if (targetChannel === "studio") return `${proto}//studio.${rootDomain}${portPart}/${suffix}`;
      if (targetChannel === "forum") return `${proto}//forum.${rootDomain}${portPart}/${suffix}`;
      if (targetChannel === "admin") return `${proto}//admin.${rootDomain}${portPart}/${suffix}`;
      return `${proto}//${rootDomain}${portPart}/${suffix}`;
    }

    if (host.endsWith(".localhost")) {
      const portPart = window.location.port ? `:${window.location.port}` : "";
      if (targetChannel === "studio") return `${proto}//studio.localhost${portPart}/${suffix}`;
      if (targetChannel === "forum") return `${proto}//forum.localhost${portPart}/${suffix}`;
      if (targetChannel === "admin") return `${proto}//admin.localhost${portPart}/${suffix}`;
      return `${proto}//localhost${portPart}/${suffix}`;
    }

    const paths = { main: "/", studio: "/studio/", forum: "/forum/", admin: "/admin/" };
    return `${paths[targetChannel] || "/"}${suffix}`;
  }

  async function apiJson(url, opts = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    const fetchOpts = Object.assign({ credentials: "include" }, opts, { headers });
    if (fetchOpts.body && typeof fetchOpts.body === "object" && !(fetchOpts.body instanceof FormData)) {
      fetchOpts.body = JSON.stringify(fetchOpts.body);
    }
    const res = await fetch(url, fetchOpts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      const err = new Error(data.error || `请求失败 (${res.status})`);
      err.status = res.status;
      err.code = data.code || "";
      throw err;
    }
    return data;
  }

  function computeAssetCounts(works) {
    const counts = {};
    for (const w of works || []) {
      for (const sid of w.styles || []) {
        counts[sid] = (counts[sid] || 0) + 1;
      }
      if (w.layout) {
        counts[w.layout] = (counts[w.layout] || 0) + 1;
      }
    }
    return counts;
  }

  function resourceLabel(item) {
    if (!item) return "";
    const chinese = /[\u3400-\u9fff]/;
    const named = [item.nameZh, item.name_zh, item.name].find(x => chinese.test(String(x || "")));
    if (named) return String(named);
    const phrase = String(item.description || "").replace(/2D/g, "二维").replace(/3D/g, "立体")
      .split(/[，。；、\n]/).find(x => chinese.test(x) && !/^\s*(参考|灵感来源|作者)/.test(x));
    const label = phrase && phrase.match(/[\u3400-\u9fff][\u3400-\u9fff\d\s（）「」“”·-]*/);
    return label ? label[0].trim().slice(0, 24) : item.group
      ? resourceGroupLabel(item.group, item.kind).replace(/^[A-Z]{2}\s*/, "")
      : item.kind === "layout" ? "图型参考" : "画风参考";
  }

  function resourceSearchText(item) {
    return `${item.id} ${item.legacy || ""} ${item.name || ""} ${item.nameZh || item.name_zh || ""} ${item.originalName || ""} ${item.description || item.desc_zh || ""} ${item.group || ""} ${item.authorName || ""}`.toLowerCase();
  }

  function resourceMatchesGroup(item, key) {
    if (key === "ALL") return true;
    if (key === "FAV") return isCollected(item.kind === "layout" ? "layouts" : "styles", item.id);
    if (key === "NEW_RELEASE") return isFreshRelease(item);
    if (key === "EXCLUSIVE") return item.sourceType === "exclusive";
    if (key === "COMMUNITY") return item.sourceType === "community";
    if (key === "HAS_WORKS") return getAssetWorkCount(item.id) > 0;
    return item.group === key || (item.kind === "style" && item.id.startsWith(key + "-"));
  }

  function resourceGroupLabel(key, kind) {
    const groups = kind === "layout" ? LAYOUT_GROUPS : STYLE_GROUPS;
    const found = groups.find(g => g.key === key || (kind === "style" && key.startsWith(g.key + " ")));
    const plain = String(key).split("/")[0].trim();
    return found ? found.label : /[\u3400-\u9fff]/.test(plain) ? plain : kind === "layout" ? "其他图型" : "其他画风";
  }

  function visibleResourceGroups(list, groups, query = "") {
    const matched = list.filter(item => resourceSearchText(item).includes(query.trim().toLowerCase()));
    return groups.map(g => ({ ...g, count: matched.filter(item => resourceMatchesGroup(item, g.key)).length })).filter(g => g.count > 0);
  }

  function rebuildResourceIndexes() {
    App.resourceMap.clear();
    App.styles = [];
    App.layouts = [];
    App.colors = [];

    const overridesList = (App.state && App.state.officialOverrides) || [];
    const overrideMap = new Map(overridesList.map((o) => [o.id, o]));

    // An explicitly supplied empty list is meaningful in normal mode: it means
    // the server has no exclusive resources, not that we should silently seed
    // the catalog with demo-only records.  Only the explicit demo state may use
    // the legacy mock list when the boot payload omits the field entirely.
    const hasExclusiveList = Boolean(App.state && Array.isArray(App.state.exclusiveResources));
    const exclusiveList = hasExclusiveList
      ? App.state.exclusiveResources
      : (App.state && App.state.demoMode === true && window.HANDRAW_MOCK && window.HANDRAW_MOCK.EXCLUSIVE_RESOURCES) || [];

    const officialMerged = [];
    for (const r of (App.catalogRaw && App.catalogRaw.resources) || []) {
      const ov = overrideMap.get(r.id);
      if (ov && ov.status && ov.status !== "published") continue;
      officialMerged.push({
        ...r,
        sourceType: "official",
        tier: (ov && ov.tier) || "free",
        unlockCost: Number((ov && ov.unlockCost) || 0),
        name: (ov && ov.name) || r.name,
        group: (ov && ov.group) || r.group,
        image: (ov && ov.image) || r.image,
        description: (ov && ov.description) || r.description,
        definition: (ov && ov.definition) || r.definition,
        featured: Boolean(ov && ov.featured),
        isNewRelease: ov && ov.isNewRelease !== undefined ? Boolean(ov.isNewRelease) : Boolean(r.isNewRelease),
        publishedAtMs: Number((ov && ov.publishedAtMs) || r.publishedAtMs || 0)
      });
    }

    const officialResourcesList = ((App.state && App.state.officialResources) || []).map((r) => ({
      ...r,
      sourceType: "official"
    }));

    const all = [
      ...exclusiveList,
      ...((App.state && App.state.communityResources) || []),
      ...officialMerged,
      ...officialResourcesList,
      ...((App.state && App.state.myResources) || []),
      ...((App.state && App.state.pendingResources) || [])
    ];

    for (const item of all) {
      if (!item || !item.id || App.resourceMap.has(item.id)) continue;
      // Local display aliases leave the source catalog and generation definition intact.
      const shown = ["style", "layout"].includes(item.kind)
        ? { ...item, originalName: item.originalName || item.name, name: resourceLabel(item) }
        : item;
      App.resourceMap.set(shown.id, shown);
      if (shown.kind === "style") App.styles.push(shown);
      else if (shown.kind === "layout") App.layouts.push(shown);
      else if (shown.kind === "color") App.colors.push(shown);
    }
  }

  function notifyAll() {
    renderChrome();
    for (const fn of App.listeners) {
      try {
        fn(App.state);
      } catch (err) {
        console.error(err);
      }
    }
  }

  function normalizeSocialAndBoardState(st) {
    if (!st) return;
    st.likedIds = Array.isArray(st.likedIds) ? st.likedIds : [];
    st.forumBoards = Array.isArray(st.forumBoards) && st.forumBoards.length
      ? st.forumBoards
      : [
          { id: "tuning", label: "🎯 作品求调优 / 悬赏", shortLabel: "求调优/悬赏", desc: "发实测原图求改词建议，支持积分悬赏采纳" },
          { id: "experience", label: "📘 实战经验与变现", shortLabel: "实战与变现", desc: "小红书/公众号/电商图文排版与接单复盘" },
          { id: "assets", label: "🎨 画风与图型专区", shortLabel: "画风与图型", desc: "围绕具体 #FA / #SC / #IG 编号的测评与拆解" },
          { id: "tools", label: "🛠️ 工具流与问答", shortLabel: "工具流问答", desc: "无限画布节点流、Skill 插件与 API 排障交流" }
        ];
    st.forumModerators = Array.isArray(st.forumModerators) ? st.forumModerators : [];
    st.assetComments = st.assetComments && typeof st.assetComments === "object" ? st.assetComments : {};
    st.assetSeedMetrics = st.assetSeedMetrics && typeof st.assetSeedMetrics === "object" ? st.assetSeedMetrics : {};
    st.assetLiveLikes = st.assetLiveLikes && typeof st.assetLiveLikes === "object" ? st.assetLiveLikes : {};
    st.assetLiveFavorites = st.assetLiveFavorites && typeof st.assetLiveFavorites === "object" ? st.assetLiveFavorites : {};
  }

  function applyBootState(boot) {
    if (!boot) return;
    normalizeSocialAndBoardState(boot);
    App.state = boot;
    rebuildResourceIndexes();
    notifyAll();
  }

  async function refreshFromServer() {
    try {
      const boot = await apiJson("/api/boot", { method: "GET" });
      if (boot && boot.serverBacked) {
        applyBootState(boot);
        return boot;
      }
    } catch (err) {
      console.warn("refreshFromServer error:", err);
    }
    return App.state;
  }

  async function saveState() {
    if (App.state && App.state.serverBacked) {
      if (Array.isArray(App.state.works) && App.state.works.length) {
        App.state.assetCounts = computeAssetCounts(App.state.works);
      }
      notifyAll();
      return;
    }
    App.state.assetCounts = computeAssetCounts(App.state.works);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(App.state));
    } catch (_) {}
    try {
      await fetch("/__demo_state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(App.state)
      });
    } catch (_) {}
    notifyAll();
  }

  async function initApp(channelName, onChange) {
    App.channel = channelName;
    if (onChange) App.listeners.push(onChange);

    let catRes;
    let optRes;
    let bootRes;
    try {
      const responses = await Promise.all([
        fetch("/data/catalog.json"),
        fetch("/data/options.json"),
        fetch("/api/boot", { credentials: "include" })
      ]);
      if (!responses[0].ok || !responses[1].ok || !responses[2].ok) {
        const bad = responses.find((r) => !r.ok);
        throw new Error(`启动接口失败（HTTP ${bad ? bad.status : "未知"}）`);
      }
      [catRes, optRes, bootRes] = await Promise.all(responses.map((r) => r.json()));
    } catch (err) {
      App.bootError = {
        channel: channelName,
        message: `无法连接 Handraw 服务：${err && err.message ? err.message : "启动接口不可用"}`,
        retry: () => initApp(channelName, onChange)
      };
      throw new Error(App.bootError.message);
    }

    App.catalogRaw = catRes;
    App.options = optRes;

    if (bootRes && bootRes.serverBacked) {
      App.bootError = null;
      normalizeSocialAndBoardState(bootRes);
      App.state = bootRes;
      rebuildResourceIndexes();
      notifyAll();
      return App;
    }

    const demoMode = new URLSearchParams(window.location.search || "").get("demo_mode");
    if (demoMode !== "1" && demoMode !== "true") {
      App.bootError = {
        channel: channelName,
        message: "Handraw 服务未返回有效启动状态。请检查本地服务后重试。",
        retry: () => initApp(channelName, onChange)
      };
      throw new Error(App.bootError.message);
    }

    // Only an explicit demo_mode URL may use the static demo fixture.
    const loaded = window.HANDRAW_MOCK.createInitialState();
    loaded.demoMode = true;
    ensureCommunityEcosystemData(loaded);
    normalizeSocialAndBoardState(loaded);
    App.bootError = null;
    App.state = loaded;
    rebuildResourceIndexes();
    return App;
  }

  function ensureCommunityEcosystemData(st) {
    if (!st) return;
    st.communityResources = Array.isArray(st.communityResources) ? st.communityResources : [];
    st.myResources = Array.isArray(st.myResources) ? st.myResources : [];
    st.pendingResources = Array.isArray(st.pendingResources) ? st.pendingResources : [];
    st.works = Array.isArray(st.works) ? st.works : [];
    st.cheeredIds = Array.isArray(st.cheeredIds) ? st.cheeredIds : [];

    // Sync seed community resources (including newly published USR-S03..05 & USR-L02..04)
    const seedResList = window.HANDRAW_MOCK.COMMUNITY_RESOURCES || [];
    const existingResMap = new Map(st.communityResources.map((r) => [r.id, r]));
    const freshPrepends = [];
    for (const sr of seedResList) {
      const ex = existingResMap.get(sr.id);
      if (!ex) {
        freshPrepends.push(JSON.parse(JSON.stringify(sr)));
      } else {
        if (ex.cheers == null) ex.cheers = sr.cheers || 24;
        if (!ex.createdAt) ex.createdAt = sr.createdAt || "2 天前";
        if (ex.isNewRelease === undefined) ex.isNewRelease = Boolean(sr.isNewRelease);
        if (sr.image && (ex.image === "/images/D_083-098.webp" || ex.image === "/images/C_055-070.webp")) {
          ex.image = sr.image;
        }
      }
    }
    if (freshPrepends.length) {
      // Preserve any custom user-submitted items created at runtime ("刚刚") at the very top
      const runtimeUserRes = st.communityResources.filter((r) => !seedResList.some((s) => s.id === r.id));
      const keptSeedRes = st.communityResources.filter((r) => seedResList.some((s) => s.id === r.id));
      st.communityResources = [...runtimeUserRes, ...freshPrepends, ...keptSeedRes];
    }

    // Sync extra community works (fresh newcomer/new-release works at top, veteran portfolio works appended)
    const existingWorkMap = new Map(st.works.map((w) => [w.id, w]));
    const freshTopWorks = [];
    const extraTailWorks = [];
    for (const ew of EXTRA_WORKS) {
      const exW = existingWorkMap.get(ew.id);
      if (!exW) {
        if (ew.isNewRelease) freshTopWorks.push(JSON.parse(JSON.stringify(ew)));
        else extraTailWorks.push(JSON.parse(JSON.stringify(ew)));
      } else {
        if (exW.cheers == null) exW.cheers = ew.cheers || Math.max(8, Math.round((exW.likes || 16) * 0.72));
        if (ew.image || (ew.images && ew.images[0] && (exW.images?.[0] === "/images/A_001-016.webp" || exW.images?.[0] === "/images/B_036-048.webp"))) {
          exW.images = [...ew.images];
        }
      }
    }
    if (freshTopWorks.length || extraTailWorks.length) {
      const runtimeWorks = st.works.filter((w) => String(w.id).startsWith("work_17") || w.createdAt === "刚刚");
      const restWorks = st.works.filter((w) => !(String(w.id).startsWith("work_17") || w.createdAt === "刚刚"));
      st.works = [...runtimeWorks, ...freshTopWorks, ...restWorks, ...extraTailWorks];
    }

    for (const w of st.works) {
      if (w.cheers == null) {
        w.cheers = Math.max(6, Math.round((w.likes || 15) * 0.74));
      }
    }
  }

  async function resetDemoState() {
    if (App.state && App.state.serverBacked) {
      try {
        const res = await apiJson("/api/dev/reset", { method: "POST", body: {} });
        if (res.boot) applyBootState(res.boot);
        toast("↺ 已重置全站数据库种子数据、积分账本与超管登录态");
        return;
      } catch (err) {
        toast(`重置失败：${err.message}`);
        return;
      }
    }
    const fresh = window.HANDRAW_MOCK.createInitialState();
    ensureCommunityEcosystemData(fresh);
    App.state = fresh;
    rebuildResourceIndexes();
    await saveState();
    toast("已重置全部演示数据、积分与默认登录态");
  }

  function addLedger(reason, delta) {
    App.state.credits = Math.max(0, (App.state.credits || 0) + delta);
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    App.state.ledger = App.state.ledger || [];
    App.state.ledger.unshift({
      id: "led_" + Date.now() + "_" + Math.random().toString(36).slice(2, 6),
      time: `今天 ${hh}:${mm}`,
      reason,
      delta
    });
  }

  const _socialInFlight = new Set();

  function syncTopbarCollectionsBadge() {
    const s = App.state;
    if (!s) return;
    const totalFavs =
      ((s.collections && s.collections.styles) || []).length +
      ((s.collections && s.collections.layouts) || []).length +
      ((s.collections && s.collections.works) || []).length +
      ((s.collections && s.collections.topics) || []).length +
      ((s.collections && s.collections.generations) || []).length;
    const el = document.getElementById("hw-dropdown-collections");
    if (el) {
      const span = el.querySelector("span:last-child");
      if (span) span.textContent = `我的云端收藏 (${totalFavs})`;
    }
  }

  function syncWalletCredits(credits) {
    if (credits == null || !App.state) return;
    App.state.credits = Number(credits);
    const dropWallet = document.querySelector(".hw-dropdown-wallet strong");
    if (dropWallet) dropWallet.textContent = `${App.state.credits} ✦`;
    const profWalBtn = document.querySelector("#prof-go-wallet-btn");
    if (profWalBtn) profWalBtn.textContent = `✦ 积分钱包 (${App.state.credits}✦)`;
  }

  function updateSocialDom(detail) {
    if (!detail || typeof document === "undefined") return;
    const { action, targetType, targetId, liked, likes, collected, favorites, credits, inFlight } = detail;
    const cleanId = String(targetId || "").trim();
    if (!cleanId) return;

    if (credits != null) {
      syncWalletCredits(credits);
    }

    // 1. Update Like elements
    if (action === "like" || liked !== undefined || likes !== undefined) {
      const likeSelectors = [
        `[data-social-action="like"][data-social-id="${cleanId}"]`,
        `[data-wb-like="${cleanId}"]`,
        `[data-like-asset="${cleanId}"]`,
        `[data-like-topic="${cleanId}"]`,
      ];
      const likeButtons = Array.from(document.querySelectorAll(likeSelectors.join(",")));
      const topicPageLike = document.getElementById("topic-page-like");
      if (topicPageLike && targetType === "topic" && !likeButtons.includes(topicPageLike)) {
        likeButtons.push(topicPageLike);
      }
      likeButtons.forEach((btn) => {
        if (liked !== undefined) {
          btn.classList.toggle("btn-primary", !!liked);
          btn.classList.toggle("is-active", !!liked);
          btn.setAttribute("aria-pressed", liked ? "true" : "false");
          const ariaLabel = btn.getAttribute("aria-label");
          if (ariaLabel && likes !== undefined) {
            btn.setAttribute("aria-label", `${liked ? "取消点赞" : "点赞"} ${likes}`);
          }
        }
        if (btn.hasAttribute("data-like-topic") || btn.id === "topic-page-like") {
          const isL = liked !== undefined ? liked : btn.classList.contains("btn-primary");
          const c = likes !== undefined ? likes : (btn.textContent.match(/\d+/) || [0])[0];
          btn.textContent = `👍 ${isL ? "已赞" : "点赞"} (${c})`;
        } else if (likes !== undefined) {
          const cntEl = btn.querySelector(".hw-social-count");
          if (cntEl) {
            cntEl.textContent = String(likes);
          } else {
            const textNodes = Array.from(btn.childNodes).filter((n) => n.nodeType === 3);
            if (textNodes.length) {
              const last = textNodes[textNodes.length - 1];
              last.nodeValue = last.nodeValue.replace(/\d+/, String(likes));
            }
          }
        }
        if (inFlight !== undefined) {
          btn.disabled = inFlight;
          btn.classList.toggle("is-pending", inFlight);
          if (inFlight) btn.setAttribute("aria-busy", "true");
          else btn.removeAttribute("aria-busy");
        }
      });

      const genModalLikeBtn = document.getElementById("gen-modal-like-btn");
      if (genModalLikeBtn && targetType === "generation") {
        if (liked !== undefined) {
          genModalLikeBtn.classList.toggle("btn-primary", !!liked);
          genModalLikeBtn.classList.toggle("is-active", !!liked);
          const txt = document.getElementById("gen-modal-like-text");
          if (txt) txt.textContent = liked ? "已点赞" : "点赞";
        }
        if (likes !== undefined) {
          const cnt = document.getElementById("gen-modal-like-count");
          if (cnt) cnt.textContent = String(likes);
        }
        if (inFlight !== undefined) genModalLikeBtn.disabled = inFlight;
      }
    }

    // 2. Update Collect elements
    if (action === "collect" || collected !== undefined || favorites !== undefined) {
      const collectSelectors = [
        `[data-social-action="collect"][data-social-id="${cleanId}"]`,
        `[data-wb-fav="${cleanId}"]`,
        `[data-fav-asset="${cleanId}"]`,
        `[data-fav-topic="${cleanId}"]`,
      ];
      const collectButtons = Array.from(document.querySelectorAll(collectSelectors.join(",")));
      const topicPageCollect = document.getElementById("topic-page-collect");
      if (topicPageCollect && targetType === "topic" && !collectButtons.includes(topicPageCollect)) {
        collectButtons.push(topicPageCollect);
      }
      collectButtons.forEach((btn) => {
        const isIconOnly = btn.classList.contains("hw-card-fav-btn") || btn.getAttribute("data-social-role") === "icon-only";
        if (isIconOnly) {
          if (collected !== undefined) {
            btn.classList.toggle("is-collected", !!collected);
            btn.textContent = collected ? "♥" : "♡";
          }
        } else {
          if (collected !== undefined) {
            btn.classList.toggle("btn-primary", !!collected);
            btn.classList.toggle("is-active", !!collected);
            btn.setAttribute("aria-pressed", collected ? "true" : "false");
            const iconEl = btn.querySelector(".hw-fav-icon");
            if (iconEl) iconEl.textContent = collected ? "♥" : "♡";
            const ariaLabel = btn.getAttribute("aria-label");
            if (ariaLabel && favorites !== undefined) {
              btn.setAttribute("aria-label", `${collected ? "取消收藏" : "收藏"} ${favorites}`);
            }
          }
          if (btn.hasAttribute("data-fav-topic") || btn.id === "topic-page-collect") {
            const isC = collected !== undefined ? collected : btn.classList.contains("btn-primary");
            const c = favorites !== undefined ? favorites : (btn.textContent.match(/\d+/) || [0])[0];
            btn.textContent = `⭐️ ${isC ? "已收藏" : "收藏"} (${c})`;
          } else if (favorites !== undefined) {
            const cntEl = btn.querySelector(".hw-social-count");
            if (cntEl) {
              cntEl.textContent = String(favorites);
            } else {
              const textNodes = Array.from(btn.childNodes).filter((n) => n.nodeType === 3);
              if (textNodes.length) {
                const last = textNodes[textNodes.length - 1];
                last.nodeValue = last.nodeValue.replace(/\d+/, String(favorites));
              }
            }
          }
        }
        if (inFlight !== undefined) {
          btn.disabled = inFlight;
          btn.classList.toggle("is-pending", inFlight);
          if (inFlight) btn.setAttribute("aria-busy", "true");
          else btn.removeAttribute("aria-busy");
        }
      });

      const genModalFavBtn = document.getElementById("gen-modal-fav-btn");
      if (genModalFavBtn && targetType === "generation") {
        if (collected !== undefined) {
          genModalFavBtn.classList.toggle("btn-primary", !!collected);
          genModalFavBtn.classList.toggle("is-active", !!collected);
          const txt = document.getElementById("gen-modal-fav-text");
          if (txt) txt.textContent = collected ? "已收藏" : "收藏";
        }
        if (favorites !== undefined) {
          const cnt = document.getElementById("gen-modal-fav-count");
          if (cnt) cnt.textContent = String(favorites);
        }
        if (inFlight !== undefined) genModalFavBtn.disabled = inFlight;
      }

      const topicCountsEl = document.getElementById("topic-counts");
      if (topicCountsEl && targetType === "topic") {
        const curL = likes !== undefined ? likes : (topicCountsEl.textContent.match(/点赞\s*(\d+)/) || [0, 0])[1];
        const curF = favorites !== undefined ? favorites : (topicCountsEl.textContent.match(/收藏\s*(\d+)/) || [0, 0])[1];
        topicCountsEl.textContent = `点赞 ${curL} · 收藏 ${curF}`;
      }

      if (collected === false && App.channel === "main" && App.view === "collections") {
        const cardSelectors = [
          `article[data-fav-item="${cleanId}"]`,
          `div[data-fav-item="${cleanId}"]`,
          `article[data-asset-card="${cleanId}"]`,
          `article[data-wb-work="${cleanId}"]`,
        ];
        let card = null;
        for (const sel of cardSelectors) {
          try {
            card = document.querySelector(sel);
            if (card) break;
          } catch (_e) {}
        }
        if (!card) {
          const unfavBtn = document.querySelector(`[data-unfav="${cleanId}"], [data-unfav-gen="${cleanId}"]`);
          if (unfavBtn) card = unfavBtn.closest(".hw-card, .forum-topic-card");
        }
        if (card) {
          const parentGrid = card.parentElement;
          card.remove();
          const ftab = (typeof UI !== "undefined" && UI.favTab) || detail.bucket;
          const tabBtn = document.querySelector(`[data-ftab="${ftab}"]`);
          if (tabBtn && App.state && App.state.collections) {
            const list = App.state.collections[ftab] || [];
            const labels = {
              styles: "🎨 画风",
              layouts: "📐 图型",
              works: "🖼️ 作品与提示词",
              topics: "💬 实战帖",
              generations: "⚡ 生图历史"
            };
            if (labels[ftab]) {
              tabBtn.textContent = `${labels[ftab]} (${list.length})`;
            }
          }
          if (parentGrid && parentGrid.querySelectorAll(".hw-card, .forum-topic-card").length === 0) {
            const emptyMsgs = {
              styles: "暂未收藏该类资产，去库里点亮 ♡ 吧！",
              layouts: "暂未收藏该类资产，去库里点亮 ♡ 吧！",
              works: "暂未收藏作品",
              topics: "暂未收藏论坛好帖",
              generations: "暂无生图历史收藏"
            };
            const ftab = (typeof UI !== "undefined" && UI.favTab) || "styles";
            parentGrid.innerHTML = `<div style="padding:40px;text-align:center;color:var(--ink-muted);">${emptyMsgs[ftab] || "暂无收藏内容"}</div>`;
          }
        }
      }
    }
  }

  function dispatchSocialUpdate(detail) {
    updateSocialDom(detail);
    if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
      try {
        window.dispatchEvent(new CustomEvent("hw:social-updated", { detail: { ...detail, _fromUpdateSocialDom: true } }));
      } catch (_e) {}
    }
  }

  if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
    window.addEventListener("hw:social-updated", (e) => {
      if (e && e.detail && !e.detail._fromUpdateSocialDom) {
        updateSocialDom(e.detail);
      }
    });
  }

  function isCollected(bucket, id) {
    const list = (App.state && App.state.collections && App.state.collections[bucket]) || [];
    if (list.includes(id)) return true;
    const sId = String(id || "").trim();
    if (list.includes(sId)) return true;
    if (bucket === "styles" || bucket === "layouts") {
      const up = sId.toUpperCase().replace(/^#/, "");
      return list.includes(up) || list.some((x) => String(x).toUpperCase().replace(/^#/, "") === up);
    }
    return list.some((x) => String(x) === sId);
  }

  function toggleCollect(bucket, id, titleLabel) {
    if (!App.state || !App.state.loggedIn) {
      openLoginModal("登录后即可永久云端同步收藏夹（画风 / 图型 / 作品 / 帖子），并与创作台打通一键调用！");
      return false;
    }
    const rawId = typeof id === "object" && id ? id.id : id;
    const cleanId = (bucket === "styles" || bucket === "layouts")
      ? String(rawId || "").trim().toUpperCase().replace(/^#/, "")
      : String(rawId || "").trim();
    if (!cleanId) return false;

    const cleanType = bucket === "styles" ? "style" : (bucket === "layouts" ? "layout" : (bucket === "works" ? "work" : (bucket === "topics" ? "topic" : "generation")));
    const lockKey = `collect:${bucket}:${cleanId}`;
    if (_socialInFlight.has(lockKey)) return false;
    _socialInFlight.add(lockKey);

    const arr = App.state.collections[bucket] || (App.state.collections[bucket] = []);
    const idx = arr.indexOf(cleanId) >= 0 ? arr.indexOf(cleanId) : (rawId ? arr.indexOf(rawId) : -1);
    const wasRemoving = idx >= 0;
    const newCollected = !wasRemoving;
    const delta = wasRemoving ? -1 : 1;
    const prevCount = getFavoriteCount(cleanType, id);
    const newCount = Math.max(0, prevCount + delta);

    if (wasRemoving) {
      arr.splice(idx, 1);
      const idx2 = arr.indexOf(rawId);
      if (idx2 >= 0) arr.splice(idx2, 1);
    } else {
      arr.unshift(cleanId);
    }

    if (bucket === "works") {
      const w = (App.state.works || []).find((x) => String(x.id) === String(cleanId));
      if (w) w.favorites = newCount;
    } else if (bucket === "topics") {
      const t = (App.state.topics || []).find((x) => String(x.id) === String(cleanId));
      if (t) t.favorites = newCount;
    } else if (bucket === "generations") {
      if (typeof id === "object" && id) {
        id.favorites = newCount;
        id.favorited = newCollected;
      }
    } else if (bucket === "styles" || bucket === "layouts") {
      App.state.assetLiveFavorites = App.state.assetLiveFavorites || {};
      App.state.assetLiveFavorites[cleanId] = Math.max(0, Number(App.state.assetLiveFavorites[cleanId] || 0) + delta);
    }

    syncTopbarCollectionsBadge();
    dispatchSocialUpdate({ action: "collect", targetType: cleanType, targetId: cleanId, bucket, collected: newCollected, favorites: newCount, inFlight: true });

    if (App.state.serverBacked) {
      apiJson("/api/collections/toggle", {
        method: "POST",
        body: { bucket, id: cleanId, title: titleLabel || cleanId, action: newCollected ? "set" : "unset" }
      })
        .then((res) => {
          _socialInFlight.delete(lockKey);
          const serverFavorites = res.favorites != null ? res.favorites : newCount;
          const serverCollected = res.collected != null ? res.collected : newCollected;

          if (bucket === "works") {
            const w = (App.state.works || []).find((x) => String(x.id) === String(cleanId));
            if (w) w.favorites = serverFavorites;
          } else if (bucket === "topics") {
            const t = (App.state.topics || []).find((x) => String(x.id) === String(cleanId));
            if (t) t.favorites = serverFavorites;
          } else if (bucket === "generations") {
            if (typeof id === "object" && id) {
              id.favorites = serverFavorites;
              id.favorited = serverCollected;
            }
          }

          if (res.credits != null) syncWalletCredits(res.credits);
          syncTopbarCollectionsBadge();

          if (!serverCollected) {
            toast(`已从收藏夹移除：${titleLabel || cleanId}`);
          } else if (res.rewarded > 0) {
            toast(`♥ 已收藏「${titleLabel || cleanId}」！触发首次云端收藏活跃激励 +${res.rewarded} 积分`);
          } else {
            toast(`♥ 已收藏「${titleLabel || cleanId}」，可在创作台与收藏夹随时调用`);
          }

          dispatchSocialUpdate({ action: "collect", targetType: cleanType, targetId: cleanId, bucket, collected: serverCollected, favorites: serverFavorites, credits: res.credits, inFlight: false });
        })
        .catch((err) => {
          _socialInFlight.delete(lockKey);
          if (wasRemoving) {
            arr.unshift(cleanId);
          } else {
            const curIdx = arr.indexOf(cleanId);
            if (curIdx >= 0) arr.splice(curIdx, 1);
          }
          if (bucket === "works") {
            const w = (App.state.works || []).find((x) => String(x.id) === String(cleanId));
            if (w) w.favorites = prevCount;
          } else if (bucket === "topics") {
            const t = (App.state.topics || []).find((x) => String(x.id) === String(cleanId));
            if (t) t.favorites = prevCount;
          } else if (bucket === "generations") {
            if (typeof id === "object" && id) {
              id.favorites = prevCount;
              id.favorited = wasRemoving;
            }
          } else if (bucket === "styles" || bucket === "layouts") {
            App.state.assetLiveFavorites = App.state.assetLiveFavorites || {};
            App.state.assetLiveFavorites[cleanId] = Math.max(0, Number(App.state.assetLiveFavorites[cleanId] || 0) - delta);
          }
          syncTopbarCollectionsBadge();
          toast(`收藏操作失败：${err.message}`);
          dispatchSocialUpdate({ action: "collect", targetType: cleanType, targetId: cleanId, bucket, collected: wasRemoving, favorites: prevCount, inFlight: false });
        });
      return true;
    }

    _socialInFlight.delete(lockKey);
    if (!newCollected) {
      toast(`已从收藏夹移除：${titleLabel || cleanId}`);
    } else if (!App.state._firstCollectRewarded) {
      App.state._firstCollectRewarded = true;
      addLedger(`首次使用云端收藏夹激励（${titleLabel || cleanId}）`, +2);
      toast(`♥ 已收藏「${titleLabel || cleanId}」！触发活跃激励 +2 积分`);
    } else {
      toast(`♥ 已收藏「${titleLabel || cleanId}」，可在创作台与收藏夹随时调用`);
    }
    saveState();
    dispatchSocialUpdate({ action: "collect", targetType: cleanType, targetId: cleanId, bucket, collected: newCollected, favorites: newCount, inFlight: false });
    return true;
  }

  function _defaultAssetBaseline(code) {
    // Unknown assets must not receive fabricated engagement metrics. Real
    // counts come from the server seed/live fields or remain zero.
    return { likes: 0, favorites: 0 };
  }

  function _normalizeSocialTarget(targetType, idOrItem) {
    const rawType = String(targetType || "work").trim().toLowerCase().replace(/^like_/, "");
    const cleanType = ["work", "topic", "style", "layout", "generation"].includes(rawType) ? rawType : "work";
    const rawId = typeof idOrItem === "object" && idOrItem ? idOrItem.id : idOrItem;
    const cleanId =
      cleanType === "style" || cleanType === "layout"
        ? String(rawId || "").trim().toUpperCase().replace(/^#/, "")
        : String(rawId || "").trim();
    return { cleanType, cleanId, key: `like_${cleanType}:${cleanId}` };
  }

  function isLiked(targetType, idOrItem) {
    const { cleanType, cleanId, key } = _normalizeSocialTarget(targetType, idOrItem);
    if (!App.state || !Array.isArray(App.state.likedIds)) return false;
    const shortKey = `${cleanType}:${cleanId}`;
    return App.state.likedIds.includes(key) || App.state.likedIds.includes(shortKey) || App.state.likedIds.includes(cleanId);
  }

  function getLikeCount(targetType, itemOrId) {
    const { cleanType, cleanId } = _normalizeSocialTarget(targetType, itemOrId);
    if (cleanType === "work") {
      const w =
        typeof itemOrId === "object" && itemOrId
          ? itemOrId
          : ((App.state && App.state.works) || []).find((x) => x.id === cleanId);
      return Math.max(0, Number((w && w.likes) || 0));
    }
    if (cleanType === "topic") {
      const t =
        typeof itemOrId === "object" && itemOrId
          ? itemOrId
          : ((App.state && App.state.topics) || []).find((x) => x.id === cleanId);
      return Math.max(0, Number((t && t.likes) || 0));
    }
    if (cleanType === "generation") {
      const g = typeof itemOrId === "object" && itemOrId ? itemOrId : null;
      return Math.max(0, Number((g && g.likes) || 0));
    }
    if (!cleanId) return 0;
    const seed = App.state && App.state.assetSeedMetrics && App.state.assetSeedMetrics[cleanId];
    const baseLikes = seed && seed.likes != null ? Number(seed.likes) : _defaultAssetBaseline(cleanId).likes;
    const liveLikes = Number((App.state && App.state.assetLiveLikes && App.state.assetLiveLikes[cleanId]) || 0);
    return Math.max(0, baseLikes + liveLikes);
  }

  function getFavoriteCount(targetType, itemOrId) {
    const { cleanType, cleanId } = _normalizeSocialTarget(targetType, itemOrId);
    if (cleanType === "work") {
      const w =
        typeof itemOrId === "object" && itemOrId
          ? itemOrId
          : ((App.state && App.state.works) || []).find((x) => x.id === cleanId);
      return Math.max(0, Number((w && w.favorites) || 0));
    }
    if (cleanType === "topic") {
      const t =
        typeof itemOrId === "object" && itemOrId
          ? itemOrId
          : ((App.state && App.state.topics) || []).find((x) => x.id === cleanId);
      return Math.max(0, Number((t && t.favorites) || 0));
    }
    if (cleanType === "generation" || cleanType === "generations") {
      const g = typeof itemOrId === "object" && itemOrId ? itemOrId : null;
      return Math.max(0, Number((g && g.favorites) || 0));
    }
    if (!cleanId) return 0;
    const seed = App.state && App.state.assetSeedMetrics && App.state.assetSeedMetrics[cleanId];
    const baseFavs = seed && seed.favorites != null ? Number(seed.favorites) : _defaultAssetBaseline(cleanId).favorites;
    const liveFavs = Number((App.state && App.state.assetLiveFavorites && App.state.assetLiveFavorites[cleanId]) || 0);
    return Math.max(0, baseFavs + liveFavs);
  }

  function toggleLike(targetType, idOrItem, labelText) {
    if (!App.state || !App.state.loggedIn) {
      openLoginModal("登录后即可为喜欢的画风、图型、作品、帖子或生图历史点赞！");
      return false;
    }
    const { cleanType, cleanId, key } = _normalizeSocialTarget(targetType, idOrItem);
    if (!cleanId) return false;

    if (cleanType === "generation" && typeof idOrItem === "object" && idOrItem && idOrItem.author && App.state.user && idOrItem.author === App.state.user.username) {
      toast("不能为自己的生图历史点赞");
      return false;
    }

    const lockKey = `like:${cleanType}:${cleanId}`;
    if (_socialInFlight.has(lockKey)) return false;
    _socialInFlight.add(lockKey);

    const prevLiked = isLiked(cleanType, idOrItem);
    const prevCount = getLikeCount(cleanType, idOrItem);
    const newLiked = !prevLiked;
    const delta = newLiked ? 1 : -1;
    const newCount = Math.max(0, prevCount + delta);

    // Apply memory update
    App.state.likedIds = Array.isArray(App.state.likedIds) ? App.state.likedIds : [];
    const shortKey = `${cleanType}:${cleanId}`;
    if (!newLiked) {
      App.state.likedIds = App.state.likedIds.filter((x) => x !== key && x !== shortKey && x !== cleanId);
    } else {
      if (!App.state.likedIds.includes(key)) App.state.likedIds.push(key);
      if (!App.state.likedIds.includes(shortKey)) App.state.likedIds.push(shortKey);
    }

    if (cleanType === "work") {
      const w = (App.state.works || []).find((x) => String(x.id) === String(cleanId));
      if (w) w.likes = newCount;
    } else if (cleanType === "topic") {
      const t = (App.state.topics || []).find((x) => String(x.id) === String(cleanId));
      if (t) t.likes = newCount;
    } else if (cleanType === "generation") {
      if (typeof idOrItem === "object" && idOrItem) {
        idOrItem.likes = newCount;
        idOrItem.liked = newLiked;
      }
    } else {
      App.state.assetLiveLikes = App.state.assetLiveLikes || {};
      App.state.assetLiveLikes[cleanId] = Math.max(0, Number(App.state.assetLiveLikes[cleanId] || 0) + delta);
    }

    dispatchSocialUpdate({ action: "like", targetType: cleanType, targetId: cleanId, liked: newLiked, likes: newCount, inFlight: true });

    if (App.state.serverBacked) {
      apiJson("/api/interactions/like", {
        method: "POST",
        body: { targetType: cleanType, id: cleanId, action: newLiked ? "set" : "unset" }
      })
        .then((res) => {
          _socialInFlight.delete(lockKey);
          const serverLikes = res.likes != null ? res.likes : newCount;
          const serverLiked = res.liked != null ? res.liked : newLiked;
          if (cleanType === "work") {
            const w = (App.state.works || []).find((x) => String(x.id) === String(cleanId));
            if (w) w.likes = serverLikes;
          } else if (cleanType === "topic") {
            const t = (App.state.topics || []).find((x) => String(x.id) === String(cleanId));
            if (t) t.likes = serverLikes;
          } else if (cleanType === "generation") {
            if (typeof idOrItem === "object" && idOrItem) {
              idOrItem.likes = serverLikes;
              idOrItem.liked = serverLiked;
            }
          }
          if (res.credits != null) syncWalletCredits(res.credits);
          if (res.rewarded > 0) {
            toast(`👍 已点赞「${labelText || cleanId}」！触发首次点赞激励 +${res.rewarded} 积分`);
          } else {
            toast(serverLiked ? `👍 已点赞「${labelText || cleanId}」` : `已取消点赞「${labelText || cleanId}」`);
          }
          dispatchSocialUpdate({ action: "like", targetType: cleanType, targetId: cleanId, liked: serverLiked, likes: serverLikes, credits: res.credits, inFlight: false });
        })
        .catch((err) => {
          _socialInFlight.delete(lockKey);
          if (prevLiked) {
            if (!App.state.likedIds.includes(key)) App.state.likedIds.push(key);
            if (!App.state.likedIds.includes(shortKey)) App.state.likedIds.push(shortKey);
          } else {
            App.state.likedIds = App.state.likedIds.filter((x) => x !== key && x !== shortKey && x !== cleanId);
          }
          if (cleanType === "work") {
            const w = (App.state.works || []).find((x) => String(x.id) === String(cleanId));
            if (w) w.likes = prevCount;
          } else if (cleanType === "topic") {
            const t = (App.state.topics || []).find((x) => String(x.id) === String(cleanId));
            if (t) t.likes = prevCount;
          } else if (cleanType === "generation") {
            if (typeof idOrItem === "object" && idOrItem) {
              idOrItem.likes = prevCount;
              idOrItem.liked = prevLiked;
            }
          } else {
            App.state.assetLiveLikes = App.state.assetLiveLikes || {};
            App.state.assetLiveLikes[cleanId] = Math.max(0, Number(App.state.assetLiveLikes[cleanId] || 0) - delta);
          }
          toast(`点赞失败：${err.message}`);
          dispatchSocialUpdate({ action: "like", targetType: cleanType, targetId: cleanId, liked: prevLiked, likes: prevCount, inFlight: false });
        });
      return true;
    }

    _socialInFlight.delete(lockKey);
    saveState();
    dispatchSocialUpdate({ action: "like", targetType: cleanType, targetId: cleanId, liked: newLiked, likes: newCount, inFlight: false });
    toast(!newLiked ? `已取消点赞「${labelText || cleanId}」` : `👍 已点赞「${labelText || cleanId}」`);
    return true;
  }

  function getAssetComments(assetCode) {
    const code = String(assetCode || "").trim().toUpperCase().replace(/^#/, "");
    if (!code || !App.state || !App.state.assetComments) return [];
    const list = App.state.assetComments[code];
    return Array.isArray(list) ? list : [];
  }

  async function submitAssetComment(assetCode, assetKind, text) {
    const code = String(assetCode || "").trim().toUpperCase().replace(/^#/, "");
    const clean = String(text || "").trim();
    if (!clean) {
      toast("请先输入评论内容");
      return null;
    }
    if (!App.state || !App.state.loggedIn) {
      openLoginModal("登录后即可在画风与图型下发表实测评论！");
      return null;
    }
    if (App.state.serverBacked) {
      const res = await apiJson(`/api/assets/${encodeURIComponent(code)}/comments`, {
        method: "POST",
        body: { text: clean, kind: assetKind || "" }
      });
      App.state.assetComments = App.state.assetComments || {};
      App.state.assetComments[code] = App.state.assetComments[code] || [];
      if (res.comment) App.state.assetComments[code].push(res.comment);
      await refreshFromServer();
      toast(`💬 已在 #${code} 发表评论！`);
      return res.comment;
    }
    const fallbackComment = {
      id: "ac_" + Date.now(),
      user: (App.state.user && App.state.user.username) || "guest",
      name: (App.state.user && App.state.user.name) || "创作者",
      text: clean,
      time: "刚刚"
    };
    App.state.assetComments = App.state.assetComments || {};
    App.state.assetComments[code] = App.state.assetComments[code] || [];
    App.state.assetComments[code].push(fallbackComment);
    await saveState();
    toast(`💬 已在 #${code} 发表评论！`);
    return fallbackComment;
  }

  function getBoardModerators(category = "all") {
    const list = (App.state && Array.isArray(App.state.forumModerators) ? App.state.forumModerators : []);
    if (!category || category === "all") return list;
    return list.filter((m) => m.category === "all" || m.category === category);
  }

  function getUserModeratorBadges(username, category = "") {
    if (!username) return [];
    const u = String(username).trim().toLowerCase();
    const list = (App.state && Array.isArray(App.state.forumModerators) ? App.state.forumModerators : []).filter(
      (m) => String(m.username || "").toLowerCase() === u
    );
    if (!category || category === "all") return list;
    return list.filter((m) => m.category === "all" || m.category === category);
  }

  function canModerateForumBoard(category = "") {
    if (!App.state || !App.state.loggedIn || !App.state.user) return false;
    const role = App.state.user.role || "user";
    if (role === "admin" || role === "operator" || role === "reviewer") return true;
    const boards = Array.isArray(App.state.user.moderatedBoards) ? App.state.user.moderatedBoards : [];
    if (boards.includes("all")) return true;
    if (category && category !== "all" && boards.includes(category)) return true;
    return getUserModeratorBadges(App.state.user.username, category || "all").some(
      (m) => m.category === "all" || (category && category !== "all" && m.category === category)
    );
  }

  function isStaff(u) {
    const user = u || (App.state && App.state.user);
    if (!user || !user.loggedIn) return false;
    const r = user.role || "user";
    return r === "admin" || r === "operator" || r === "reviewer";
  }

  function isAdmin(u) {
    const user = u || (App.state && App.state.user);
    return Boolean(user && user.loggedIn && user.role === "admin");
  }

  function canManageGlobal(u) {
    return isStaff(u);
  }

  function canDeleteTopic(topic, u) {
    const user = u || (App.state && App.state.user);
    if (!user || !user.loggedIn || !topic) return false;
    if (topic.author === user.username) return true;
    return canModerateForumBoard(topic.category);
  }

  function canDeleteReply(reply, topic, u) {
    const user = u || (App.state && App.state.user);
    if (!user || !user.loggedIn || !reply) return false;
    const rAuthor = reply.authorUsername || reply.user || reply.author;
    if (rAuthor === user.username) return true;
    const cat = topic ? topic.category : "";
    return canModerateForumBoard(cat);
  }

  function canDeleteWork(work, u) {
    const user = u || (App.state && App.state.user);
    if (!user || !user.loggedIn || !work) return false;
    if (work.author === user.username) return true;
    return canManageGlobal(user);
  }

  function canModerateWork(work, u) {
    return canManageGlobal(u);
  }

  function canDeleteComment(comment, u) {
    const user = u || (App.state && App.state.user);
    if (!user || !user.loggedIn || !comment) return false;
    const cAuthor = comment.user || comment.authorUsername || comment.author;
    if (cAuthor === user.username) return true;
    return canManageGlobal(user);
  }

  window.HandrawPerms = {
    isStaff,
    isAdmin,
    canManageGlobal,
    canModerateForumBoard,
    canDeleteTopic,
    canDeleteReply,
    canDeleteWork,
    canModerateWork,
    canDeleteComment,
  };

  function isUnlocked(id, itemObj) {
    if (!itemObj) return true;
    const cost = itemObj.unlockCost || itemObj.price || 0;
    if (cost <= 0) return true;
    if (App.state && App.state.user && itemObj.author && itemObj.author === App.state.user.username) {
      return true;
    }
    return ((App.state && App.state.unlockedIds) || []).includes(id);
  }

  function unlockWithCredits(id, cost, label, authorName, onUnlocked) {
    if (!App.state.loggedIn) {
      openLoginModal(`登录后可使用积分解锁「${label}」（新用户注册立赠 20 积分）`);
      return false;
    }
    if ((App.state.unlockedIds || []).includes(id)) {
      if (onUnlocked) onUnlocked();
      return true;
    }
    if ((App.state.credits || 0) < cost) {
      toast(`积分不足（需 ${cost} 积分，当前 ${App.state.credits} 积分），快去分享、兑换或签到赚积分吧！`);
      return false;
    }

    App.state.unlockedIds.push(id);
    if (App.state.serverBacked) {
      App.state.credits = Math.max(0, (App.state.credits || 0) - cost);
      const wTarget = (App.state.works || []).find((w) => w.id === id);
      const tTarget = (App.state.topics || []).find((t) => t.id === id);
      const aTarget = App.resourceMap.get(id);
      if (wTarget && !wTarget.prompt) wTarget.prompt = "⏳ 正在从云端加载已解锁配方…";
      if (tTarget && !tTarget.lockedBody) tTarget.lockedBody = "⏳ 正在从云端加载已解锁正文…";
      notifyAll();

      apiJson("/api/unlocks", {
        method: "POST",
        body: { targetId: id }
      })
        .then(async (res) => {
          App.state.credits = res.credits;
          const unlockedText = res.unlockedContent || "";
          if (res.targetType === "work" && wTarget) {
            wTarget.prompt = unlockedText;
            wTarget.promptLocked = false;
          } else if (res.targetType === "topic" && tTarget) {
            tTarget.lockedBody = unlockedText;
          } else if (res.targetType === "asset" && aTarget) {
            aTarget.definition = unlockedText;
            aTarget.definitionLocked = false;
          }
          toast(`✨ 解锁成功！已扣除 ${res.cost ?? cost} 积分${authorName ? "（80% 已实时分账原作者）" : ""}`);
          await refreshFromServer();
          if (onUnlocked) onUnlocked(unlockedText);
        })
        .catch((err) => {
          const i = App.state.unlockedIds.indexOf(id);
          if (i >= 0) App.state.unlockedIds.splice(i, 1);
          toast(`解锁失败：${err.message}`);
          refreshFromServer();
        });
      return true;
    }

    addLedger(
      `解锁${authorName ? ` @${authorName} 的` : ""}「${label}」${authorName ? "（80% 积分已实时分账原作者）" : ""}`,
      -cost
    );
    saveState();
    toast(`✨ 解锁成功！已扣除 ${cost} 积分`);
    if (onUnlocked) onUnlocked();
    return true;
  }

  function getAssetWorks(assetId) {
    return ((App.state && App.state.works) || []).filter(
      (w) => (w.styles && w.styles.includes(assetId)) || w.layout === assetId
    );
  }

  function getAssetWorkCount(assetId) {
    if (!App.state) return 0;
    if (Array.isArray(App.state.works) && App.state.works.length > 0) {
      return getAssetWorks(assetId).length;
    }
    return Number((App.state.assetCounts && App.state.assetCounts[assetId]) || 0);
  }

  function getAssetTopics(assetId) {
    return ((App.state && App.state.topics) || []).filter(
      (t) => (t.styles && t.styles.includes(assetId)) || t.layout === assetId || (t.submissions || []).some(s => s.targetId === assetId) || t.resourceDiscussion?.targetId === assetId
    );
  }

  function groupShortLabel(item) {
    if (!item) return "";
    if (item.sourceType === "exclusive") return "在线独占";
    if (item.sourceType === "community") return "社区共创";
    if (item.kind === "style") {
      return (item.group || "").split("/")[0].trim();
    }
    const map = {
      "social-card": "SC 社媒卡",
      infographic: "IG 信息图",
      "comic-storyboard": "SB 漫画分镜",
      "ip-character": "IP 角色设定",
      ecommerce: "EC 商业电商"
    };
    return map[item.group] || item.group || "";
  }

  /* ======================== CREATOR HONOR, NEW-RELEASE EXPOSURE & ENCOURAGEMENT ENGINE ======================== */
  const CREATOR_HONOR_TIERS = [
    {
      tier: 4,
      minCount: 6,
      key: "hall",
      badge: "👑 殿堂共创官",
      shortBadge: "👑 殿堂",
      boost: 1.45,
      boostText: "1.45× 优先曝光",
      sealClass: "honor-hall",
      nextAt: null,
      nextTitle: "",
      desc: "累计分享 ≥6 项 · 享首页殿堂主理人联展席位与瀑布流 1.45× 优先曝光加权"
    },
    {
      tier: 3,
      minCount: 3,
      key: "gold",
      badge: "🏅 金牌主理人",
      shortBadge: "🏅 金牌",
      boost: 1.25,
      boostText: "1.25× 曝光加权",
      sealClass: "honor-gold",
      nextAt: 6,
      nextTitle: "👑 殿堂共创官",
      desc: "累计分享 3~5 项 · 入选高产共创荣誉榜并享全站 1.25× 曝光加权"
    },
    {
      tier: 2,
      minCount: 2,
      key: "pioneer",
      badge: "🌟 先锋开荒者",
      shortBadge: "🌟 先锋",
      boost: 1.12,
      boostText: "1.12× 曝光加权",
      sealClass: "honor-pioneer",
      nextAt: 3,
      nextTitle: "🏅 金牌主理人",
      desc: "累计分享 2 项 · 点亮先锋认证徽章并享 1.12× 推荐曝光加权"
    },
    {
      tier: 1,
      minCount: 1,
      key: "rookie",
      badge: "🌱 新锐创作者",
      shortBadge: "🌱 新锐",
      boost: 1.08,
      boostText: "新秀首曝扶持",
      sealClass: "honor-rookie",
      nextAt: 2,
      nextTitle: "🌟 先锋开荒者",
      desc: "发布首项分享 · 自动进入新秀破冰曝光席，收获社区第一声鼓励"
    },
    {
      tier: 0,
      minCount: 0,
      key: "member",
      badge: "✨ 灵感探索者",
      shortBadge: "探索者",
      boost: 1.0,
      boostText: "首发即享必曝",
      sealClass: "honor-member",
      nextAt: 1,
      nextTitle: "🌱 新锐创作者",
      desc: "首次分享画风、图型或作品即可点亮荣誉徽章并进入首发曝光席"
    }
  ];

  function getCreatorHonorTier(totalPublished, honorOverrideKey) {
    if (honorOverrideKey) {
      const ov = CREATOR_HONOR_TIERS.find((t) => t.key === honorOverrideKey);
      if (ov) return ov;
    }
    const cnt = Math.max(0, Number(totalPublished) || 0);
    for (const t of CREATOR_HONOR_TIERS) {
      if (cnt >= t.minCount) return t;
    }
    return CREATOR_HONOR_TIERS[CREATOR_HONOR_TIERS.length - 1];
  }

  function isFreshRelease(item, nowMs = Date.now()) {
    if (!item) return false;
    const raw = item.publishedAtMs ?? item.published_at_ms ?? item.createdAtMs ?? item.created_at_ms;
    const timestamp = Number(raw);
    if (Number.isFinite(timestamp) && timestamp > 0) {
      const now = Number(nowMs);
      if (!Number.isFinite(now) || now < timestamp) return false;
      return now - timestamp <= 72 * 60 * 60 * 1000;
    }
    // Payloads without an absolute timestamp (legacy fixtures) fall back to the
    // server-computed window flag so the badge and the block never disagree.
    return item.isNewRelease === true || item.is_new_release === true;
  }

  const RANK_PERIODS = [
    {
      key: "week",
      label: "📅 周榜",
      fullLabel: "📅 周榜 · 近7天",
      shortPrefix: "本周",
      days: 7,
      desc: "统计近 7 天新发布与互动热度（不叠加历史殿堂加权，新人新作公平冲榜）"
    },
    {
      key: "month",
      label: "🗓️ 月榜",
      fullLabel: "🗓️ 月榜 · 近30天",
      shortPrefix: "本月",
      days: 30,
      desc: "统计近 30 天持续活跃创作者与高人气作品"
    },
    {
      key: "all",
      label: "🏛️ 总榜",
      fullLabel: "🏛️ 总榜 · 历史累计",
      shortPrefix: "累计",
      days: null,
      desc: "统计创站以来全部历史沉淀作品、共创资产与殿堂荣誉"
    }
  ];

  function getRecencyMinutes(item) {
    if (!item) return 999999;
    const pubMs = Number(item.publishedAtMs ?? item.published_at_ms ?? 0);
    if (Number.isFinite(pubMs) && pubMs > 0) {
      // Prefer the absolute timestamp so a stale text label can never outrank
      // genuinely recent items inside the new-release block.
      return Math.max(0, Math.round((Date.now() - pubMs) / 60000));
    }
    const t = String(item.createdAt || "").trim();
    if (!t) return 999999;
    if (t.includes("刚刚")) return 0;
    const mm = t.match(/(\d+)\s*分钟前/);
    if (mm) return Number(mm[1]);
    const hm = t.match(/(\d+)\s*小时前/);
    if (hm) return Number(hm[1]) * 60;
    if (t.includes("昨天")) return 1440;
    if (t.includes("前天")) return 2880;
    const dm = t.match(/(\d+)\s*天前/);
    if (dm) return Number(dm[1]) * 1440;
    const wm = t.match(/(\d+)\s*周前/);
    if (wm) return Number(wm[1]) * 10080;
    const mo = t.match(/(\d+)\s*个月前/);
    if (mo) return Number(mo[1]) * 43200;
    return 999999;
  }

  function isWithinRankPeriod(item, period = "all") {
    if (!item || !period || period === "all") return true;
    const days = period === "week" ? 7 : period === "month" ? 30 : null;
    if (!days) return true;
    const windowMs = days * 86400 * 1000;
    const pubMs = Number(item.publishedAtMs || 0);
    if (pubMs > 0) {
      return Math.max(0, Date.now() - pubMs) <= windowMs;
    }
    return getRecencyMinutes(item) * 60000 <= windowMs;
  }

  function compareByRecency(a, b) {
    const pa = Number(a && a.publishedAtMs) || 0;
    const pb = Number(b && b.publishedAtMs) || 0;
    if (pa !== pb) return pb - pa;
    const ma = getRecencyMinutes(a);
    const mb = getRecencyMinutes(b);
    if (ma !== mb) return ma - mb;
    return Number((b && b.cheers) || 0) - Number((a && a.cheers) || 0);
  }

  function getCreatorStatsMap() {
    const map = new Map();
    const s = App.state;
    if (!s) return map;

    const publicMap = new Map(((s.publicCreators && Array.isArray(s.publicCreators)) ? s.publicCreators : []).map((pc) => [pc.username, pc]));

    function ensureAuthor(username, authorName) {
      if (!username || username === "guest") return null;
      let rec = map.get(username);
      if (!rec) {
        const pc = publicMap.get(username);
        const cleanName = authorName || (pc && pc.authorName) || username;
        const firstChar = cleanName.replace(/^[@\s]+/, "").charAt(0).toUpperCase() || "绘";
        rec = {
          username,
          authorName: cleanName,
          avatarChar: firstChar,
          avatarUrl: (s.creatorAvatars && s.creatorAvatars[username]) || (pc && pc.avatarUrl) ||
            (s.user && s.user.username === username && s.user.avatarUrl) || "/assets/avatar-default.svg",
          bio: (pc && pc.bio) || "",
          styles: [],
          layouts: [],
          works: [],
          topics: [],
          publicWorksCount: pc ? Number(pc.worksCount || 0) : 0,
          honorOverride: pc ? pc.honorOverride || null : null,
          hasPublicFresh: Boolean(pc && pc.hasFresh),
          totalPublished: 0,
          totalCheers: 0,
          totalFavorites: 0,
          totalForks: 0,
          honor: CREATOR_HONOR_TIERS[4],
          exposureScore: 0
        };
        map.set(username, rec);
      } else if (authorName && rec.authorName === rec.username) {
        rec.authorName = authorName;
      }
      return rec;
    }

    if (s.user && s.user.username && s.user.username !== "guest") {
      const me = ensureAuthor(s.user.username, s.user.name);
      if (me) {
        if (s.user.honorOverride) me.honorOverride = s.user.honorOverride;
        if (s.user.bio) me.bio = s.user.bio;
      }
    }

    for (const pc of publicMap.values()) {
      ensureAuthor(pc.username, pc.authorName);
    }

    for (const res of s.communityResources || []) {
      const rec = ensureAuthor(res.author, res.authorName);
      if (!rec) continue;
      if (res.kind === "layout") rec.layouts.push(res);
      else rec.styles.push(res);
      rec.totalCheers += Number(res.cheers ?? 0);
    }

    for (const w of s.works || []) {
      const rec = ensureAuthor(w.author, w.authorName);
      if (!rec) continue;
      rec.works.push(w);
      rec.totalCheers += Number(w.cheers || 0) + Math.round(Number(w.likes || 0) * 0.35);
      rec.totalFavorites += Number(w.favorites || 0);
      rec.totalForks += Number(w.forks || 0);
    }

    for (const tp of s.topics || []) {
      const rec = ensureAuthor(tp.author, tp.authorName);
      if (!rec) continue;
      rec.topics.push(tp);
    }

    for (const rec of map.values()) {
      const pc = publicMap.get(rec.username);
      const effectiveWorksCnt = !s.loggedIn && pc ? Number(pc.worksCount || 0) : rec.works.length;
      rec.publicWorksCount = effectiveWorksCnt;
      if (!s.loggedIn && pc) {
        rec.totalCheers = Number(pc.totalCheers || rec.totalCheers);
        rec.totalFavorites = Number(pc.totalFavorites || 0);
        rec.totalForks = Number(pc.totalForks || 0);
      }
      rec.totalPublished = rec.styles.length + rec.layouts.length + effectiveWorksCnt;
      rec.honor = getCreatorHonorTier(rec.totalPublished, rec.honorOverride);
      rec.exposureScore =
        rec.totalPublished * 85 +
        (rec.styles.length + rec.layouts.length) * 35 +
        rec.totalCheers * 0.6 +
        rec.totalFavorites * 0.35;
    }

    return map;
  }

  function getCreatorProfile(username) {
    if (!username) return null;
    const map = getCreatorStatsMap();
    return (
      map.get(username) || {
        username,
        authorName: username,
        avatarChar: String(username).charAt(0).toUpperCase() || "绘",
        avatarUrl: (App.state?.creatorAvatars && App.state.creatorAvatars[username]) ||
          "/assets/avatar-default.svg",
        styles: [],
        layouts: [],
        works: [],
        topics: [],
        publicWorksCount: 0,
        totalPublished: 0,
        totalCheers: 0,
        totalFavorites: 0,
        totalForks: 0,
        honor: getCreatorHonorTier(0),
        exposureScore: 0
      }
    );
  }

  function creatorAvatarHtml(profile, size = "sm") {
    const p = profile || {};
    const uname = p.username || p.author || "";
    const src = (App.state?.creatorAvatars && App.state.creatorAvatars[uname]) ||
      p.avatarUrl || "/assets/avatar-default.svg";
    const legalSize = ["sm", "md", "lg", "xl"].includes(size) ? size : "sm";
    return '<img class="hw-creator-avatar-' + legalSize + ' hw-creator-avatar-image" ' +
      'src="' + esc(src) + '" alt="' + esc(p.authorName || p.name || uname || "创作者") +
      '的头像" loading="lazy" decoding="async" />';
  }

  function getTopCreators(limit = 6, mode = "prolific", period = "all") {
    const baseAll = Array.from(getCreatorStatsMap().values()).filter((c) => c.totalPublished > 0);
    const normPeriod = period === "week" || period === "month" ? period : "all";

    const projected = baseAll.map((c) => {
      if (normPeriod === "all") {
        return {
          ...c,
          period: "all",
          periodStyles: c.styles,
          periodLayouts: c.layouts,
          periodWorks: c.works,
          periodPublished: c.totalPublished,
          periodCheers: c.totalCheers,
          periodFavorites: c.totalFavorites,
          periodForks: c.totalForks,
          periodScore: c.exposureScore
        };
      }
      const pStyles = c.styles.filter((x) => isWithinRankPeriod(x, normPeriod));
      const pLayouts = c.layouts.filter((x) => isWithinRankPeriod(x, normPeriod));
      const pWorks = c.works.filter((x) => isWithinRankPeriod(x, normPeriod));
      const pPub = pStyles.length + pLayouts.length + pWorks.length;
      let pCheers = 0;
      let pFavs = 0;
      let pForks = 0;
      for (const a of [...pStyles, ...pLayouts]) {
        pCheers += Number(a.cheers ?? 0);
      }
      for (const w of pWorks) {
        pCheers += Number(w.cheers || 0) + Math.round(Number(w.likes || 0) * 0.35);
        pFavs += Number(w.favorites || 0);
        pForks += Number(w.forks || 0);
      }
      // Fair period score: based strictly on this period's output & engagement (no veteran honor multiplier)
      const pScore = pPub * 95 + (pStyles.length + pLayouts.length) * 30 + pCheers * 0.85 + pForks * 1.1 + pFavs * 0.4;
      return {
        ...c,
        period: normPeriod,
        periodStyles: pStyles,
        periodLayouts: pLayouts,
        periodWorks: pWorks,
        periodPublished: pPub,
        periodCheers: pCheers,
        periodFavorites: pFavs,
        periodForks: pForks,
        periodScore: pScore
      };
    });

    let list = normPeriod === "all" ? projected : projected.filter((c) => c.periodPublished > 0);
    if (!list.length) list = projected;

    if (mode === "rising") {
      const rookies = list.filter((c) => c.totalPublished >= 1 && c.totalPublished <= 3);
      if (rookies.length) list = rookies;
      list.sort((a, b) => {
        const aFresh = [...a.periodWorks, ...a.periodStyles, ...a.periodLayouts].some(isFreshRelease) ? 1 : 0;
        const bFresh = [...b.periodWorks, ...b.periodStyles, ...b.periodLayouts].some(isFreshRelease) ? 1 : 0;
        if (bFresh !== aFresh) return bFresh - aFresh;
        return b.periodCheers - a.periodCheers || b.periodPublished - a.periodPublished;
      });
    } else if (mode === "cheers") {
      list.sort((a, b) => {
        if (b.periodCheers !== a.periodCheers) return b.periodCheers - a.periodCheers;
        return b.periodPublished - a.periodPublished;
      });
    } else {
      list.sort((a, b) => {
        if (b.periodPublished !== a.periodPublished) return b.periodPublished - a.periodPublished;
        return b.periodScore - a.periodScore;
      });
    }
    return list.slice(0, limit);
  }

  // Single popularity formula per object type, mirroring backend/ranking.py.
  // Weights encode effort: a fork is real reuse, favouriting means planning to
  // reuse, likes and cheers are light acknowledgement.  Honour boosts and
  // freshness bonuses are gone so ranking reflects only real interaction.
  function popularScore(kind, item) {
    if (!item) return 0;
    if (kind === "work") {
      // Mirrors backend/ranking.py: forks weigh 1, not 3, because the counter
      // can be moved by spending free generation quota.
      return (
        Number(item.likes || 0) +
        2 * Number(item.favorites || 0) +
        Number(item.forks || 0)
      );
    }
    if (kind === "topic") {
      const replies = Array.isArray(item.replies)
        ? item.replies.length
        : Number(item.replyCount || 0);
      return replies + Number(item.likes || 0) + 2 * Number(item.favorites || 0);
    }
    // styles and layouts: how many published works reference them
    return Number(item.usageCount || 0);
  }

  function getWorkCompositeScore(work, statsMap, period = "feed") {
    return popularScore("work", work);
  }

  function getRankedWorks(limit = 15, mode = "composite", period = "all") {
    const allWorks = [...(App.state?.works || [])];
    const normPeriod = period === "week" || period === "month" ? period : "all";
    let works = normPeriod === "all" ? allWorks : allWorks.filter((w) => isWithinRankPeriod(w, normPeriod));
    if (!works.length) works = allWorks;

    if (mode === "rising") {
      const freshList = works.filter(isFreshRelease);
      const target = freshList.length ? freshList : works;
      target.sort(compareByRecency);
      return target.slice(0, limit);
    }
    if (mode === "forks") {
      works.sort((a, b) => (b.forks || 0) - (a.forks || 0) || (b.favorites || 0) - (a.favorites || 0));
      return works.slice(0, limit);
    }
    // "composite", legacy "cheers" and "popular" all resolve to the one formula.
    works.sort((a, b) => popularScore("work", b) - popularScore("work", a));
    return works.slice(0, limit);
  }

  function getRankedAssets(limit = 12, period = "all") {
    const normPeriod = period === "week" || period === "month" ? period : "all";
    const statsMap = getCreatorStatsMap();
    const allWorks = (App.state && App.state.works) || [];
    const periodWorks = normPeriod === "all" ? allWorks : allWorks.filter((w) => isWithinRankPeriod(w, normPeriod));

    const periodCountByAsset = new Map();
    for (const w of periodWorks) {
      for (const sid of w.styles || []) {
        if (sid) periodCountByAsset.set(sid, (periodCountByAsset.get(sid) || 0) + 1);
      }
      if (w.layout) {
        periodCountByAsset.set(w.layout, (periodCountByAsset.get(w.layout) || 0) + 1);
      }
    }

    const candidates = [...App.styles, ...App.layouts]
      .map((a) => {
        const totalWorkCnt = getAssetWorkCount(a.id);
        const pWorkCnt = normPeriod === "all" ? totalWorkCnt : periodCountByAsset.get(a.id) || 0;
        const isPeriodCoCreated = a.sourceType === "community" && isWithinRankPeriod(a, normPeriod);
        let rankScore = 0;
        if (normPeriod === "all") {
          const prof = a.author ? statsMap.get(a.author) : null;
          const boost = prof ? prof.honor.boost : 1.0;
          const commBonus = a.sourceType === "community" ? 42 : a.sourceType === "exclusive" ? 55 : 0;
          rankScore = Math.round((totalWorkCnt * 36 + commBonus) * boost);
        } else {
          rankScore =
            pWorkCnt * 52 +
            (isPeriodCoCreated ? 70 : 0) +
            (isFreshRelease(a) ? 45 : 0);
        }
        return {
          asset: a,
          totalWorkCnt,
          periodWorkCnt: pWorkCnt,
          isPeriodCoCreated,
          rankScore
        };
      })
      .filter((entry) =>
        normPeriod === "all"
          ? entry.asset.sourceType === "community" || entry.totalWorkCnt > 0
          : entry.periodWorkCnt > 0 || entry.isPeriodCoCreated
      );

    candidates.sort((a, b) => b.rankScore - a.rankScore || b.totalWorkCnt - a.totalWorkCnt);
    return candidates.slice(0, limit);
  }

  const DEFAULT_STAMP_BASES = {
    惊艳神图: 6,
    配方超稳: 8,
    构图绝妙: 4,
    超实用配方: 5,
    审美在线: 4
  };

  function getStampCount(item, stampLabel) {
    if (!item || !stampLabel) return 0;
    if (item.stampCounts && item.stampCounts[stampLabel] !== undefined) {
      const count = Number(item.stampCounts[stampLabel]);
      return Number.isFinite(count) ? Math.max(0, count) : 0;
    }
    return 0;
  }

  function isCheered(id, stampLabel = "") {
    if (!App.state || !Array.isArray(App.state.cheeredIds)) return false;
    const key = stampLabel ? `${id}::${stampLabel}` : id;
    return App.state.cheeredIds.includes(key);
  }

  function toggleCheerItem(targetType, id, stampLabel = "") {
    if (!App.state) return false;
    if (!App.state.loggedIn) {
      openLoginModal("登录后即可为喜爱的创作者送上鼓励掌声，首次友善互动立赠 +2 积分！");
      return false;
    }
    const cheeredList = App.state.cheeredIds || (App.state.cheeredIds = []);
    let targetObj = null;
    if (targetType === "work") {
      targetObj = (App.state.works || []).find((w) => w.id === id);
    } else {
      targetObj =
        (App.state.communityResources || []).find((r) => r.id === id) || App.resourceMap.get(id);
    }
    if (!targetObj) return false;

    const key = stampLabel ? `${id}::${stampLabel}` : id;
    const already = cheeredList.includes(key);
    const authorLabel = targetObj.authorName ? `@${targetObj.authorName}` : "创作者";
    const itemTitle = targetObj.title || `${targetObj.id} ${targetObj.name || ""}`;

    if (already && stampLabel) {
      toast(`👏 你已经为 ${authorLabel} 送上过「${stampLabel}」鼓励啦！`);
      return true;
    }

    if (App.state.serverBacked) {
      if (already && !stampLabel) {
        cheeredList.splice(cheeredList.indexOf(key), 1);
        targetObj.cheers = Math.max(0, (targetObj.cheers || 1) - 1);
      } else {
        cheeredList.push(key);
        if (!cheeredList.includes(id)) cheeredList.push(id);
        targetObj.cheers = (targetObj.cheers || 0) + 1;
        if (stampLabel) {
          targetObj.stampCounts = targetObj.stampCounts || {};
          targetObj.stampCounts[stampLabel] = getStampCount(targetObj, stampLabel) + 1;
        }
      }
      notifyAll();

      apiJson("/api/interactions/cheer", {
        method: "POST",
        body: {
          targetType: targetType === "work" ? "work" : "asset",
          targetId: id,
          stampLabel: stampLabel || ""
        }
      })
        .then((res) => {
          App.state.credits = res.credits;
          targetObj.cheers = res.cheers;
          if (!res.cheered) {
            toast(`已取消对《${itemTitle}》的鼓励`);
          } else if (res.rewarded > 0) {
            toast(`👏 已为 ${authorLabel} 送上鼓励${stampLabel ? `「${stampLabel}」` : ""}！首次互动奖励 +${res.rewarded}✦`);
          } else {
            toast(`👏 已为 ${authorLabel} 送上鼓励${stampLabel ? `「${stampLabel}」` : ""}！作品曝光权重已提升`);
          }
          refreshFromServer();
        })
        .catch((err) => {
          toast(`操作失败：${err.message}`);
          refreshFromServer();
        });
      return !(already && !stampLabel);
    }

    if (already && !stampLabel) {
      cheeredList.splice(cheeredList.indexOf(key), 1);
      targetObj.cheers = Math.max(0, (targetObj.cheers || 1) - 1);
      saveState();
      toast(`已取消对《${itemTitle}》的鼓励`);
      return false;
    }

    cheeredList.push(key);
    if (!cheeredList.includes(id)) cheeredList.push(id);
    targetObj.cheers = (targetObj.cheers || 0) + 1;
    if (targetType === "work") {
      targetObj.likes = (targetObj.likes || 0) + 1;
    }
    if (stampLabel) {
      targetObj.stampCounts = targetObj.stampCounts || {};
      const prevCnt = getStampCount(targetObj, stampLabel);
      targetObj.stampCounts[stampLabel] = prevCnt + 1;
    }

    if (App.state.loggedIn && !App.state._firstCheerRewarded) {
      App.state._firstCheerRewarded = true;
      addLedger(`友善社区互动：首次为 ${authorLabel} 送上作品鼓励`, +2);
      toast(`👏 已为 ${authorLabel} 送上鼓励${stampLabel ? `「${stampLabel}」` : ""}！作品曝光热度 +1，互动奖励 +2✦`);
    } else {
      toast(`👏 已为 ${authorLabel} 送上鼓励${stampLabel ? `「${stampLabel}」` : ""}！该作品/资产曝光权重已提升`);
    }
    saveState();
    return true;
  }

  function openTipModal({
    targetType,
    targetId,
    title,
    authorName,
    authorUsername,
    isOfficial = false,
    onSuccess
  } = {}) {
    if (!App.state.loggedIn) {
      if (App.channel === "forum" && typeof window.HANDRAW_FORUM_OPEN_AUTH === "function") {
        window.HANDRAW_FORUM_OPEN_AUTH("登录后即可赞赏支持！");
      } else {
        openLoginModal("登录后可使用积分为喜爱的创作者赞赏加油（新用户注册立赠 20 积分）！");
      }
      return;
    }

    if (!isOfficial && authorUsername && App.state.user && authorUsername === App.state.user.username) {
      toast("不能给自己赞赏积分哦～");
      return;
    }

    const tTitle = title || targetId || "精选内容";
    const authorLabel = authorName || authorUsername || "创作者";
    const payeeDisplay = isOfficial
      ? "官方运营账户（支持模型与资源维护）"
      : `@${esc(authorLabel)}（100% 直达作者）`;
    const curCredits = Number(App.state.credits != null ? App.state.credits : (App.state.user?.credits || 0));

    let selectedAmount = 2;

    const modalHtml = `
      <div class="hw-tip-modal-body">
        <div class="hw-tip-info-card">
          <div class="hw-tip-info-item">
            <span class="hw-tip-info-label">赞赏目标</span>
            <span class="hw-tip-info-value" id="hw-tip-target-display" title="${esc(tTitle)}">《${esc(tTitle)}》</span>
          </div>
          <div class="hw-tip-info-item">
            <span class="hw-tip-info-label">收款方</span>
            <span class="hw-tip-info-value" id="hw-tip-payee-display">${payeeDisplay}</span>
          </div>
          <div class="hw-tip-info-item">
            <span class="hw-tip-info-label">当前余额</span>
            <span class="hw-tip-info-value" id="hw-tip-balance-display">${curCredits}✦</span>
          </div>
        </div>

        <div>
          <div class="hw-tip-section-title">选择赞赏额度</div>
          <div class="hw-tip-tier-grid" id="hw-tip-tiers">
            <button type="button" class="hw-tip-tier-btn is-active" data-tip-amount="2">2✦</button>
            <button type="button" class="hw-tip-tier-btn" data-tip-amount="5">5✦</button>
            <button type="button" class="hw-tip-tier-btn" data-tip-amount="10">10✦</button>
            <button type="button" class="hw-tip-tier-btn" data-tip-amount="20">20✦</button>
          </div>
        </div>

        <div class="hw-tip-custom-row">
          <label for="hw-tip-custom-input" class="hw-tip-section-title" style="margin-bottom:0;">自定义额度</label>
          <div class="hw-tip-input-wrap">
            <input type="number" id="hw-tip-custom-input" min="1" max="50" step="1" placeholder="1–50✦ 整数" value="2" />
            <span class="hw-tip-input-unit">✦</span>
          </div>
          <div class="hw-tip-input-hint" id="hw-tip-input-hint" style="font-size:12px;color:var(--ink-muted);margin-top:2px;">
            ${isOfficial ? "可选 1–50✦ 整数，赞赏将入账官方运营账户" : "可选 1–50✦ 整数，100% 直达作者"}
          </div>
        </div>

        <div class="hw-tip-summary-row">
          <span class="hw-tip-summary-label">本次金额</span>
          <span class="hw-tip-summary-val" id="hw-tip-amount-display">2✦</span>
        </div>

        <button type="button" class="btn btn-primary hw-tip-confirm-btn" id="hw-tip-confirm-btn">
          确认赞赏 2✦
        </button>
      </div>
    `;

    openModal({
      title: "🎁 赞赏支持",
      sizeClass: "hw-tip-modal",
      html: modalHtml,
      onMount(modalRoot) {
        const tierBtns = modalRoot.querySelectorAll(".hw-tip-tier-btn");
        const customInput = modalRoot.querySelector("#hw-tip-custom-input");
        const amountDisplay = modalRoot.querySelector("#hw-tip-amount-display");
        const confirmBtn = modalRoot.querySelector("#hw-tip-confirm-btn");
        const hintEl = modalRoot.querySelector("#hw-tip-input-hint");

        function updateSelected(amt, fromInput = false) {
          selectedAmount = amt;
          if (!fromInput && customInput) {
            customInput.value = amt;
          }
          if (amountDisplay) {
            amountDisplay.textContent = `${amt}✦`;
          }
          if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.textContent = `确认赞赏 ${amt}✦`;
          }
          if (hintEl) {
            hintEl.textContent = isOfficial ? "可选 1–50✦ 整数，赞赏将入账官方运营账户" : "可选 1–50✦ 整数，100% 直达作者";
            hintEl.style.color = "var(--ink-muted)";
          }
          tierBtns.forEach((btn) => {
            const bAmt = Number(btn.getAttribute("data-tip-amount"));
            if (bAmt === amt) {
              btn.classList.add("is-active");
            } else {
              btn.classList.remove("is-active");
            }
          });
        }

        tierBtns.forEach((btn) => {
          btn.onclick = () => {
            const val = Number(btn.getAttribute("data-tip-amount"));
            updateSelected(val, false);
          };
        });

        if (customInput) {
          customInput.oninput = () => {
            const raw = customInput.value.trim();
            if (!raw) {
              if (confirmBtn) confirmBtn.disabled = true;
              if (amountDisplay) amountDisplay.textContent = "-✦";
              if (hintEl) {
                hintEl.textContent = "请输入 1–50✦ 之间的整数";
                hintEl.style.color = "var(--vermilion, #cf4627)";
              }
              tierBtns.forEach((b) => b.classList.remove("is-active"));
              return;
            }
            const num = Number(raw);
            if (!Number.isInteger(num) || num < 1 || num > 50) {
              if (confirmBtn) confirmBtn.disabled = true;
              if (amountDisplay) amountDisplay.textContent = `${raw}✦`;
              if (hintEl) {
                hintEl.textContent = "赞赏金额必须为 1–50✦ 之间的整数";
                hintEl.style.color = "var(--vermilion, #cf4627)";
              }
              tierBtns.forEach((b) => b.classList.remove("is-active"));
              return;
            }
            updateSelected(num, true);
          };
        }

        if (confirmBtn) {
          confirmBtn.onclick = () => {
            if (!Number.isInteger(selectedAmount) || selectedAmount < 1 || selectedAmount > 50) {
              toast("赞赏金额必须为 1–50✦ 整数");
              return;
            }
            const latestCredits = Number(App.state.credits != null ? App.state.credits : (App.state.user?.credits || 0));
            if (latestCredits < selectedAmount) {
              toast(`当前积分不足（需 ${selectedAmount}✦，可用 ${latestCredits}✦），先去签到或创作赚积分吧！`);
              return;
            }

            confirmBtn.disabled = true;
            confirmBtn.setAttribute("aria-busy", "true");
            confirmBtn.textContent = "赞赏处理中...";

            const reqId = `tip_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
            apiJson("/api/interactions/tip", {
              method: "POST",
              body: {
                targetType: targetType === "work" ? "work" : targetType === "topic" ? "topic" : "asset",
                targetId,
                amount: selectedAmount,
                requestId: reqId
              }
            })
              .then((res) => {
                if (res && res.credits != null) {
                  App.state.credits = res.credits;
                  if (App.state.user) App.state.user.credits = res.credits;
                }
                const succMsg = isOfficial
                  ? `🎁 赞赏成功！感谢对官方资源的支持，已送出 ${selectedAmount}✦ 积分`
                  : `🎁 赞赏成功！已向 @${authorLabel} 送出 ${selectedAmount}✦ 积分（100% 直达作者）`;
                toast(succMsg);
                closeModal();
                if (typeof onSuccess === "function") {
                  onSuccess({ amount: selectedAmount, res });
                }
              })
              .catch((err) => {
                const errMsg = (err && err.message) || String(err);
                toast(`赞赏失败：${errMsg}`);
                confirmBtn.disabled = false;
                confirmBtn.removeAttribute("aria-busy");
                confirmBtn.textContent = `确认赞赏 ${selectedAmount}✦`;
              });
          };
        }
      }
    });
  }

  function sendEncourageTip(targetType, id, amount = null) {
    let targetObj =
      targetType === "work"
        ? (App.state.works || []).find((w) => w.id === id)
        : (App.state.communityResources || []).find((r) => r.id === id) || App.resourceMap.get(id);

    if (amount == null) {
      const isOfficial = targetObj ? (targetObj.sourceType === "official" || !targetObj.author) : false;
      openTipModal({
        targetType,
        targetId: id,
        title: targetObj ? (targetObj.title || targetObj.name || id) : id,
        authorName: targetObj ? (targetObj.authorName || targetObj.author || "") : "",
        authorUsername: targetObj ? (targetObj.author || targetObj.author_username || "") : "",
        isOfficial,
        onSuccess: ({ amount: tippedAmt }) => {
          if (targetObj) {
            targetObj.tips = (targetObj.tips || 0) + tippedAmt;
            targetObj.cheers = (targetObj.cheers || 0) + 3;
          }
          if (typeof refreshFromServer === "function") {
            refreshFromServer();
          }
        }
      });
      return true;
    }

    if (!App.state.loggedIn) {
      openLoginModal("登录后可使用积分为喜爱的创作者赞赏加油（新用户注册立赠 20 积分）！");
      return false;
    }
    if (!targetObj) return false;
    if (targetObj.author && App.state.user && targetObj.author === App.state.user.username) {
      toast("不能给自己赞赏积分哦～");
      return false;
    }
    if ((App.state.credits || 0) < amount) {
      toast(`当前积分不足 ${amount} 积分，先去签到或创作赚积分吧！`);
      return false;
    }
    const authorLabel = targetObj.authorName || "社区创作者";
    const itemTitle = targetObj.title || `${targetObj.id} ${targetObj.name || ""}`;

    if (App.state.serverBacked) {
      App.state.credits = Math.max(0, (App.state.credits || 0) - amount);
      targetObj.cheers = (targetObj.cheers || 0) + 3;
      targetObj.tips = (targetObj.tips || 0) + amount;
      notifyAll();

      const reqId = `tip_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      apiJson("/api/interactions/tip", {
        method: "POST",
        body: {
          targetType: targetType === "work" ? "work" : targetType === "topic" ? "topic" : "asset",
          targetId: id,
          amount,
          requestId: reqId
        }
      })
        .then((res) => {
          App.state.credits = res.credits;
          toast(`🎁 已向 @${authorLabel} 赞赏 +${amount}✦ 积分鼓励（100% 直达作者）！热度值 +3`);
          refreshFromServer();
        })
        .catch((err) => {
          toast(`赞赏失败：${err.message}`);
          refreshFromServer();
        });
      return true;
    }

    addLedger(`🎁 赞赏鼓励 @${authorLabel} 的《${itemTitle}》（100% 直达创作者）`, -amount);
    targetObj.cheers = (targetObj.cheers || 0) + 3;
    targetObj.tips = (targetObj.tips || 0) + amount;
    if (!App.state.cheeredIds.includes(id)) App.state.cheeredIds.push(id);
    saveState();
    toast(`🎁 已向 @${authorLabel} 赞赏 +${amount}✦ 积分鼓励！热度值 +3`);
    return true;
  }

  /* ======================== STANDALONE PAGE NAVIGATION HELPERS (ZERO POPUP MODALS) ======================== */
  function goToCreatorProfile(username, ptab = "works") {
    closeModal();
    const targetUser = String(username || (App.state && App.state.user && App.state.user.username) || "").trim();
    if (!targetUser || targetUser === "guest") {
      openLoginModal("登录后即可查看与管理你的个人主页");
      return;
    }
    const cleanTab = ptab === "assets" ? "styles" : ptab || "works";
    if (App.channel === "main" && typeof window.HANDRAW_MAIN_OPEN_PROFILE === "function") {
      window.HANDRAW_MAIN_OPEN_PROFILE(targetUser, cleanTab);
      return;
    }
    const params = { view: "profile", user: targetUser };
    if (cleanTab && cleanTab !== "works") params.ptab = cleanTab;
    window.location.href = channelUrl("main", params);
  }

  function goToAccountPage() {
    closeModal();
    if (!App.state || !App.state.loggedIn || !App.state.user) {
      openLoginModal("请先登录账号以管理个人资料与安全设置");
      return;
    }
    if (App.channel === "main" && typeof window.HANDRAW_MAIN_SWITCH_VIEW === "function") {
      window.HANDRAW_MAIN_SWITCH_VIEW("account");
    } else {
      window.location.href = channelUrl("main", { view: "account", section: "profile" });
    }
  }

  function goToAssetPage(assetId, subTab = "") {
    closeModal();
    const id = String(assetId || "").trim().toUpperCase().replace(/^#/, "");
    if (id) window.location.href = channelUrl("main", {view:"asset", id, tab:subTab});
  }

  function goToWorkPage(workId, focusComment = false) {
    closeModal();
    const id = String(workId || "").trim();
    if (!id) return;
    const disc = (App.state && App.state.discussions && App.state.discussions[id]) || null;
    const tid = disc ? disc.topicId : null;
    if (tid) {
      goToTopicPage(tid);
    } else {
      window.location.href = `/t/work-${encodeURIComponent(id)}${focusComment ? "?focus=comment" : ""}`;
    }
  }

  function goToTopicPage(topicId) {
    closeModal();
    const tid = String(topicId || "").trim();
    if (!tid) return;
    if (App.channel === "forum" && typeof window.HANDRAW_FORUM_OPEN_TOPIC === "function") {
      window.HANDRAW_FORUM_OPEN_TOPIC(tid, 0);
      return;
    }
    window.location.href = channelUrl("forum", { view: "topic", id: tid });
  }

  function goToSkillPage() {
    closeModal();
    if (App.channel === "main" && typeof window.HANDRAW_MAIN_SWITCH_VIEW === "function") {
      window.HANDRAW_MAIN_SWITCH_VIEW("skill");
      return;
    }
    window.location.href = channelUrl("main", { view: "skill" });
  }

  function openCreatorProfileModal(username, _handlers = {}) {
    // Personal Homepages are strictly standalone full pages, never popup modals
    goToCreatorProfile(username, "works");
  }

  async function sandboxSwitchPersona(targetUsername) {
    if (App.state && App.state.serverBacked) {
      try {
        const res = await apiJson("/api/auth/sandbox-switch", {
          method: "POST",
          body: { username: targetUsername }
        });
        if (res.boot) applyBootState(res.boot);
        if (!targetUsername || targetUsername === "guest") {
          toast("🌐 已切换为【未登录游客】视角：可公开浏览画风、图型、作品广场与榜单（互动/收藏/付费解锁将引导登录）");
        } else {
          const roleTag =
            res.boot?.user?.role === "admin"
              ? "👑 超级管理员"
              : res.boot?.user?.role === "reviewer"
              ? "🛡️ 内容审核员"
              : "🎨 社区创作者";
          toast(`✅ 已切换为 ${roleTag} @${res.boot?.user?.username || targetUsername}（全频道共享 Cookie 会话）`);
        }
        return;
      } catch (err) {
        toast(`切换视角失败：${err.message}`);
        return;
      }
    }

    if (!targetUsername || targetUsername === "guest") {
      App.state.loggedIn = false;
      saveState();
      toast("已切换为【未登录游客】视角");
    } else {
      App.state.loggedIn = true;
      saveState();
      toast("已切换为【登录用户】视角");
    }
  }

  async function performServerCheckin() {
    if (!App.state.loggedIn) {
      openLoginModal("登录后即可每日打卡领取 +5 积分并重置 3 次免费生图额度！");
      return false;
    }
    if (App.state.dailyCheckedIn) {
      toast("今日已完成打卡签到，明天再来吧！");
      return false;
    }
    if (App.state.serverBacked) {
      try {
        const res = await apiJson("/api/wallet/checkin", { method: "POST", body: {} });
        App.state.dailyCheckedIn = true;
        App.state.credits = res.credits;
        App.state.freeQuotaRemaining = res.freeQuotaRemaining;
        toast(`🎉 签到成功！获得 +${res.bonus || 5} 积分，今日免费在线生图额度已满格 (${res.freeQuotaRemaining}/${res.freeQuotaMax})`);
        await refreshFromServer();
        return true;
      } catch (err) {
        toast(err.message || "签到失败");
        return false;
      }
    }
    App.state.dailyCheckedIn = true;
    addLedger("每日社区创作打卡奖励", +5);
    saveState();
    toast("🎉 签到成功！获得 +5 积分，今日免费在线生图额度已满格 (3/3)");
    return true;
  }

  /* ======================== CHROME (SANDBOX BAR + TOPBAR + ANNOUNCEMENT) ======================== */
  function renderChrome() {
    let sandbox = document.getElementById("hw-sandbox-mount");
    if (!sandbox) {
      sandbox = document.createElement("div");
      sandbox.id = "hw-sandbox-mount";
      document.body.prepend(sandbox);
    }

    const domainMap = {
      main: { prod: "handraw-style.com", desc: "主站：画风库 · 图型库 · 作品广场 · 统一认证钱包" },
      studio: { prod: "studio.handraw-style.com", desc: "独立二级域名：无限画布节点创作工坊 & 云端黑盒拼装引擎" },
      forum: { prod: "forum.handraw-style.com", desc: "独立二级域名：深度定制社区论坛 · 悬赏与配方挂载" },
      admin: { prod: "admin.handraw-style.com", desc: "独立二级域名：全站运营审核与风控管理后台" }
    };
    const dm = domainMap[App.channel] || domainMap.main;
    const s = App.state || {};
    const showDemoControls = s.demoMode === true;
    const curUser = (s && s.user) || { username: "guest", role: "guest" };
    const mgmtRole =
      curUser.managementRole ||
      (["admin", "operator", "reviewer"].includes(curUser.role)
        ? curUser.role
        : (curUser.moderatedBoards && curUser.moderatedBoards.length) || getUserModeratorBadges(curUser.username).length
        ? "moderator"
        : "none");
    const canAccessAdmin = Boolean(s && s.loggedIn && mgmtRole !== "none");
    const adminNavMeta =
      mgmtRole === "admin"
        ? { label: "👑 超管后台", sub: "全权限" }
        : mgmtRole === "operator"
        ? { label: "🧭 运营后台", sub: "增长运营" }
        : mgmtRole === "reviewer"
        ? { label: "🛡️ 审核后台", sub: "内容风控" }
        : { label: "🏛️ 版主后台", sub: "板块版务" };

    sandbox.innerHTML = showDemoControls ? `
      <details class="hw-product-demo-tools">
        <summary>演示环境 · 展开测试工具</summary>
      <div class="demo-sandbox-bar">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
          <span class="demo-domain-pill">
            <span class="demo-domain-dot"></span>
            当前模拟域名：<strong>${esc(dm.prod)}</strong>
          </span>
          <span style="color:#bfb6aa;">${esc(dm.desc)}</span>
        </div>
        <div class="demo-switcher-group">
          <span style="color:#bfb6aa;">多角色秒切验权：</span>
          <button type="button" class="demo-chip-btn ${s.loggedIn && curUser.username === "yang0" ? "is-active" : ""}" id="sandbox-btn-user" title="切换超级管理员 yang0（全站7模块最高权限）">
            👑 超管
          </button>
          <button type="button" class="demo-chip-btn ${s.loggedIn && (curUser.username === "ops_lin" || curUser.username === "reviewer_su") ? "is-active" : ""}" id="sandbox-btn-operator" title="切换运营审查员 ops_lin（整合运营增长与内容安全巡检）">
            🧭 运营审查
          </button>
          <button type="button" class="demo-chip-btn ${s.loggedIn && curUser.username === "momo_design" ? "is-active" : ""}" id="sandbox-btn-moderator" title="切换论坛板块版主 momo_design（仅限画风与图型专区版务）">
            🏛️ 版主
          </button>
          <button type="button" class="demo-chip-btn ${s.loggedIn && curUser.username === "su_editorial" ? "is-active" : ""}" id="sandbox-btn-creator" title="切换普通创作者 su_editorial（仅可管理本人内容）">
            🎨 创作者
          </button>
          <button type="button" class="demo-chip-btn ${!s.loggedIn ? "is-active" : ""}" id="sandbox-btn-guest">
            🌐 游客
          </button>
          <a class="demo-chip-btn" href="${esc(channelUrl("admin", { module: "users" }))}" id="sandbox-btn-users-admin" style="text-decoration:none;">
            👥 用户管理 ↗
          </a>
          <a class="demo-chip-btn" href="${esc(channelUrl("admin"))}" id="sandbox-btn-admin" style="text-decoration:none;">
            ⚙️ 管理后台 ↗
          </a>
          <button type="button" class="demo-chip-btn" id="sandbox-btn-skill">
            🧭 本地扩展
          </button>
          <button type="button" class="demo-chip-btn" id="sandbox-btn-reset">
            ↺ 重置
          </button>
        </div>
      </div>
      </details>
    ` : "";

    if (showDemoControls) {
      document.getElementById("sandbox-btn-user").onclick = () => sandboxSwitchPersona("yang0");
      document.getElementById("sandbox-btn-operator").onclick = () => sandboxSwitchPersona("ops_lin");
      document.getElementById("sandbox-btn-moderator").onclick = () => sandboxSwitchPersona("momo_design");
      document.getElementById("sandbox-btn-creator").onclick = () => sandboxSwitchPersona("su_editorial");
      document.getElementById("sandbox-btn-guest").onclick = () => sandboxSwitchPersona("guest");
      document.getElementById("sandbox-btn-skill").onclick = () => openSkillFunnelPreviewModal();
      document.getElementById("sandbox-btn-reset").onclick = () => resetDemoState();
    }

    // Global Topbar
    let topbar = document.getElementById("hw-topbar-mount");
    if (!topbar) {
      topbar = document.createElement("header");
      topbar.id = "hw-topbar-mount";
      topbar.className = "hw-topbar";
      sandbox.insertAdjacentElement("afterend", topbar);
    }

    const totalFavs =
      ((s.collections && s.collections.styles) || []).length +
      ((s.collections && s.collections.layouts) || []).length +
      ((s.collections && s.collections.works) || []).length +
      ((s.collections && s.collections.topics) || []).length +
      ((s.collections && s.collections.generations) || []).length;

    const worksNavCount = s.loggedIn ? (s.works || []).length : Number(s.totalWorksCount || (s.works || []).length || 0);
    const activeView = App.channel === "main" ? App.view : App.channel;
    const userProf = getCreatorProfile(curUser.username);

    topbar.innerHTML = `
      <div class="hw-topbar-inner">
        <a class="hw-brand" href="${esc(channelUrl("main", { view: "discover" }))}" id="nav-brand-link">
          <span class="hw-brand-seal">绘</span>
          <span class="hw-brand-title">手绘风创作社区</span>
        </a>

        <nav class="hw-nav-links" aria-label="主频道导航">
          <a class="hw-nav-item ${["discover", "works", "work"].includes(activeView) ? "is-active" : ""}" href="${esc(channelUrl("main", { view: "discover" }))}" data-main-view="discover">
            发现
          </a>
          <a class="hw-nav-item ${activeView === "styles" ? "is-active" : ""}" href="${esc(channelUrl("main", { view: "styles" }))}" data-main-view="styles">画风</a>
          <a class="hw-nav-item ${activeView === "layouts" ? "is-active" : ""}" href="${esc(channelUrl("main", { view: "layouts" }))}" data-main-view="layouts">图型</a>
          <a class="hw-nav-item ${App.channel === "studio" ? "is-active" : ""}" href="${esc(channelUrl("studio", { entry: "quick" }))}">
            创作台
          </a>
          <a class="hw-nav-item ${App.channel === "forum" ? "is-active" : ""}" href="${esc(channelUrl("forum"))}">
            社区
          </a>
        </nav>

        <div class="hw-topbar-right">
          <form class="hw-global-search" id="hw-global-search-form">
            <input type="search" id="hw-global-search-input" placeholder="搜索画风/图型编号或关键词…" />
          </form>

          ${
            s.loggedIn
              ? `
                <div class="hw-user-dropdown-wrap" id="hw-user-dropdown-wrap">
                  <button type="button" class="hw-user-avatar-btn" id="hw-user-avatar-btn" aria-haspopup="true" aria-expanded="false" title="@${esc(curUser.name || curUser.username)} · 点击展开个人菜单">
                    <img src="${esc(curUser.avatarUrl || userProf.avatarUrl || "/assets/avatar-default.svg")}" class="hw-user-avatar-circle-img" alt="${esc(curUser.name || curUser.username)}" onerror="this.style.display='none';if(this.nextElementSibling)this.nextElementSibling.style.display='flex';" />
                    <span class="hw-creator-avatar-sm ${esc(userProf.honor.sealClass)}" style="display:none;border-radius:50%;">${esc(userProf.avatarChar)}</span>
                    ${canAccessAdmin && s.user && s.user.openReportsCount > 0 ? `<span class="hw-avatar-dot-badge" title="有待办事项"></span>` : ""}
                  </button>
                  <div class="hw-user-dropdown-menu" id="hw-user-dropdown-menu">
                    <div class="hw-dropdown-header">
                      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
                        <img src="${esc(curUser.avatarUrl || userProf.avatarUrl || "/assets/avatar-default.svg")}" class="hw-user-avatar-circle-img hw-avatar-dropdown-lg" alt="${esc(curUser.name || curUser.username)}" onerror="this.style.display='none';if(this.nextElementSibling)this.nextElementSibling.style.display='flex';" />
                        <span class="hw-creator-avatar-md ${esc(userProf.honor.sealClass)}" style="display:none;border-radius:50%;">${esc(userProf.avatarChar)}</span>
                        <div style="min-width:0;flex:1;">
                          <div style="font-weight:800;font-size:14.2px;color:var(--ink-strong);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                            @${esc(curUser.name || curUser.username)}
                          </div>
                          <div style="font-size:11.8px;color:var(--ink-muted);">ID: ${esc(curUser.username)}</div>
                        </div>
                      </div>
                      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
                        <span class="hw-honor-badge ${esc(userProf.honor.sealClass)}" style="font-size:11px;padding:1px 6px;">${esc(userProf.honor.badge)}</span>
                        ${
                          canAccessAdmin
                            ? `<span class="hw-honor-badge" style="font-size:11px;padding:1px 6px;background:rgba(31,95,139,0.12);color:#1f5f8b;border:1px solid rgba(31,95,139,0.3);">
                                ${adminNavMeta.label}
                              </span>`
                            : ""
                        }
                      </div>
                    </div>

                    <div class="hw-dropdown-wallet">
                      <div>
                        <div style="font-size:11.5px;color:var(--ink-muted);">可用积分余额</div>
                        <strong style="font-size:15px;color:var(--vermilion);">${s.credits || 0} ✦</strong>
                      </div>
                      ${
                        !s.dailyCheckedIn
                          ? `<button type="button" class="btn btn-sm btn-gold" id="hw-dropdown-btn-checkin" style="font-size:11.5px;padding:3px 8px;">📅 签到 +5</button>`
                          : `<span style="font-size:11px;color:var(--jade);font-weight:700;">✅ 今日已签到</span>`
                      }
                    </div>

                    <div style="display:grid;gap:2px;">
                      <a class="hw-dropdown-item" href="${esc(channelUrl("main", { view: "profile", user: curUser.username }))}" id="hw-dropdown-profile">
                        <span>🏠</span> <span>我的个人主页</span>
                      </a>
                      <a class="hw-dropdown-item" href="${esc(channelUrl("main", { view: "profile", user: curUser.username, ptab: "collections" }))}" id="hw-dropdown-collections">
                        <span>♥</span> <span>收藏夹 (${totalFavs})</span>
                      </a>
                      <a class="hw-dropdown-item" href="${esc(channelUrl("main", { view: "wallet" }))}" data-main-view="wallet" id="hw-dropdown-wallet">
                        <span>✦</span> <span>积分中心与创作密钥</span>
                      </a>
                      <a class="hw-dropdown-item" href="${esc(channelUrl("main", { view: "account", section: "profile" }))}" id="hw-dropdown-account">
                        <span>⚙️</span> <span>账号资料与安全设置</span>
                      </a>

                      ${
                        canAccessAdmin
                          ? `
                            <div class="hw-dropdown-divider"></div>
                            <div class="hw-dropdown-section-title">🛡️ 前台管理就地工具</div>
                            <button type="button" class="hw-dropdown-item" id="hw-dropdown-staff-reports">
                              <span>🚨</span> <span>社区待办举报${s.user && s.user.openReportsCount > 0 ? ` (${s.user.openReportsCount})` : ""}</span>
                            </button>
                            <button type="button" class="hw-dropdown-item" id="hw-dropdown-staff-codes">
                              <span>🎟️</span> <span>运营兑换码发放</span>
                            </button>
                            <button type="button" class="hw-dropdown-item" id="hw-dropdown-staff-ann">
                              <span>✏️</span> <span>修改全站公告横幅</span>
                            </button>
                            <a class="hw-dropdown-item" href="${esc(channelUrl("admin"))}" id="hw-dropdown-staff-admin">
                              <span>🏛️</span> <span>完整后台控制台 ↗</span>
                            </a>
                          `
                          : ""
                      }

                      <div class="hw-dropdown-divider"></div>
                      <button type="button" class="hw-dropdown-item" id="hw-dropdown-logout" style="color:var(--vermilion);">
                        <span>🚪</span> <span>退出登录</span>
                      </button>
                    </div>
                  </div>
                </div>
              `
              : `
                <button type="button" class="btn btn-primary" id="hw-btn-login">
                  🔑 登录 / 注册
                </button>
              `
          }
        </div>
      </div>
    `;

    // Site-wide announcement banner (managed in Admin Module 7 or in-place by staff)
    let annEl = document.getElementById("hw-announcement-mount");
    const ann = s.siteSettings && s.siteSettings.announcement;
    const canManageAnn = s.loggedIn && (curUser.role === "admin" || curUser.role === "operator" || curUser.role === "reviewer");
    if (App.channel !== "studio") {
      if (ann && ann.enabled && ann.text) {
        if (!annEl) {
          annEl = document.createElement("div");
          annEl.id = "hw-announcement-mount";
          topbar.insertAdjacentElement("afterend", annEl);
        }
        annEl.innerHTML = `
          <div style="background:var(--gold-wash);border-bottom:1px solid var(--gold-border);padding:7px 22px;font-size:12.8px;color:var(--ink-strong);display:flex;justify-content:center;align-items:center;gap:12px;flex-wrap:wrap;">
            <span>📣 <strong>社区公告：</strong>${esc(ann.text)}</span>
            ${ann.link ? `<a href="${esc(ann.link)}" style="color:var(--vermilion);font-weight:800;text-decoration:underline;">立即查看 →</a>` : ""}
            ${canManageAnn ? `<button type="button" id="hw-btn-edit-announcement" style="background:#fff;border:1px solid var(--gold-border);border-radius:4px;cursor:pointer;color:var(--vermilion);font-size:11.5px;font-weight:700;padding:2px 8px;margin-left:6px;">✏️ 编辑公告</button>` : ""}
          </div>
        `;
      } else if (canManageAnn) {
        if (!annEl) {
          annEl = document.createElement("div");
          annEl.id = "hw-announcement-mount";
          topbar.insertAdjacentElement("afterend", annEl);
        }
        annEl.innerHTML = `
          <div style="background:#fcf9f2;border-bottom:1px dashed #e2d7c5;padding:4px 22px;font-size:12px;color:#8a7968;display:flex;justify-content:center;align-items:center;gap:10px;">
            <span>📣 社区公告当前处于关闭状态</span>
            <button type="button" id="hw-btn-edit-announcement" style="background:#fff;border:1px solid #d8caa7;border-radius:4px;cursor:pointer;color:var(--vermilion);font-size:11px;font-weight:700;padding:1px 8px;">✏️ 开启/编辑公告</button>
          </div>
        `;
      } else if (annEl) {
        annEl.remove();
      }
    }

    // Intercept SPA navigation when already on main channel
    if (App.channel === "main") {
      topbar.querySelectorAll("[data-main-view]").forEach((el) => {
        el.addEventListener("click", (e) => {
          const targetView = el.getAttribute("data-main-view");
          if (targetView && window.HANDRAW_MAIN_SWITCH_VIEW) {
            e.preventDefault();
            window.HANDRAW_MAIN_SWITCH_VIEW(targetView);
          }
        });
      });
      const brand = document.getElementById("nav-brand-link");
      if (brand && window.HANDRAW_MAIN_SWITCH_VIEW) {
        brand.addEventListener("click", (e) => {
          e.preventDefault();
          window.HANDRAW_MAIN_SWITCH_VIEW("discover");
        });
      }
    }

    const searchForm = document.getElementById("hw-global-search-form");
    searchForm.onsubmit = (e) => {
      e.preventDefault();
      const q = document.getElementById("hw-global-search-input").value.trim();
      if (!q) return;
      const upper = q.toUpperCase().replace(/^#/, "");
      if (App.resourceMap.has(upper)) {
        goToAssetPage(upper);
        return;
      }
      if (App.channel === "main" && window.HANDRAW_MAIN_GLOBAL_SEARCH) {
        window.HANDRAW_MAIN_GLOBAL_SEARCH(q);
      } else {
        window.location.href = channelUrl("main", { view: "styles", q });
      }
    };

    // User Avatar Dropdown Toggle (Folded Personal Info)
    const avatarBtn = document.getElementById("hw-user-avatar-btn");
    const menu = document.getElementById("hw-user-dropdown-menu");
    if (avatarBtn && menu) {
      avatarBtn.onclick = (e) => {
        e.stopPropagation();
        const isOpen = menu.classList.contains("is-open");
        if (isOpen) {
          menu.classList.remove("is-open");
          avatarBtn.classList.remove("is-active");
          avatarBtn.setAttribute("aria-expanded", "false");
        } else {
          menu.classList.add("is-open");
          avatarBtn.classList.add("is-active");
          avatarBtn.setAttribute("aria-expanded", "true");
        }
      };

      document.addEventListener("click", (e) => {
        if (!e.target.closest("#hw-user-dropdown-wrap")) {
          menu.classList.remove("is-open");
          avatarBtn.classList.remove("is-active");
          avatarBtn.setAttribute("aria-expanded", "false");
        }
      });
    }

    const dropdownCheckinBtn = document.getElementById("hw-dropdown-btn-checkin");
    if (dropdownCheckinBtn) {
      dropdownCheckinBtn.onclick = () => performServerCheckin();
    }

    const dropdownProfile = document.getElementById("hw-dropdown-profile");
    if (dropdownProfile) {
      dropdownProfile.onclick = (e) => {
        e.preventDefault();
        goToCreatorProfile(curUser.username, "works");
      };
    }

    const dropdownCollections = document.getElementById("hw-dropdown-collections");
    if (dropdownCollections) {
      dropdownCollections.onclick = (e) => {
        e.preventDefault();
        if (menu) {
          menu.classList.remove("is-open");
          if (avatarBtn) {
            avatarBtn.classList.remove("is-active");
            avatarBtn.setAttribute("aria-expanded", "false");
          }
        }
        goToCreatorProfile(curUser.username, "collections");
      };
    }

    const dropdownAccount = document.getElementById("hw-dropdown-account");
    if (dropdownAccount) {
      dropdownAccount.onclick = (e) => {
        e.preventDefault();
        goToAccountPage();
      };
    }

    const dropdownStaffReports = document.getElementById("hw-dropdown-staff-reports");
    if (dropdownStaffReports) {
      dropdownStaffReports.onclick = () => {
        if (menu) menu.classList.remove("is-open");
        openFrontReportsModal();
      };
    }

    const dropdownStaffCodes = document.getElementById("hw-dropdown-staff-codes");
    if (dropdownStaffCodes) {
      dropdownStaffCodes.onclick = () => {
        if (menu) menu.classList.remove("is-open");
        openFrontRedeemCodesModal();
      };
    }

    const dropdownStaffAnn = document.getElementById("hw-dropdown-staff-ann");
    if (dropdownStaffAnn) {
      dropdownStaffAnn.onclick = () => {
        if (menu) menu.classList.remove("is-open");
        openFrontAnnouncementEditorModal();
      };
    }

    const dropdownLogout = document.getElementById("hw-dropdown-logout");
    if (dropdownLogout) {
      dropdownLogout.onclick = async () => {
        if (App.state.serverBacked) {
          try {
            const res = await apiJson("/api/auth/logout", { method: "POST", body: {} });
            if (res.boot) applyBootState(res.boot);
            toast("已安全退出登录，当前为未登录游客视角");
            return;
          } catch (err) {
            toast(`退出失败：${err.message}`);
            return;
          }
        }
        App.state.loggedIn = false;
        saveState();
      };
    }

    const loginBtn = document.getElementById("hw-btn-login");
    if (loginBtn) {
      loginBtn.onclick = () => openLoginModal();
    }

    const annEditBtn = document.getElementById("hw-btn-edit-announcement");
    if (annEditBtn) {
      annEditBtn.onclick = () => openFrontAnnouncementEditorModal();
    }
  }

  /* ======================== MODAL HELPER ======================== */
  function openModal({ title, sizeClass = "", html, onMount }) {
    closeModal();
    const backdrop = document.createElement("div");
    backdrop.id = "hw-active-modal";
    backdrop.className = "hw-backdrop";
    backdrop.innerHTML = `
      <div class="hw-modal-panel ${sizeClass}" role="dialog" aria-modal="true">
        <div class="hw-modal-header">
          <h2>${esc(title)}</h2>
          <button type="button" class="hw-close-btn" id="hw-modal-close-x" aria-label="关闭">×</button>
        </div>
        <div class="hw-modal-body" id="hw-modal-body-root">
          ${html}
        </div>
      </div>
    `;
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) closeModal();
    });
    document.body.appendChild(backdrop);
    document.getElementById("hw-modal-close-x").onclick = closeModal;

    const escHandler = (e) => {
      if (e.key === "Escape") {
        closeModal();
        window.removeEventListener("keydown", escHandler);
      }
    };
    window.addEventListener("keydown", escHandler);

    if (onMount) onMount(document.getElementById("hw-modal-body-root"));
  }

  function closeModal() {
    const existing = document.getElementById("hw-active-modal");
    if (existing) existing.remove();
  }

  /* ======================== ARTICLE MANAGEMENT ======================== */
  async function deleteArticle(articleId, opts = {}) {
    const aid = String(articleId || "").trim();
    if (!aid) return Promise.reject(new Error("文章编号不能为空"));

    const title = opts.articleTitle || opts.title || "未命名文章";
    const onSuccess = opts.onSuccess;

    return new Promise((resolve, reject) => {
      openModal({
        title: "删除文章",
        sizeClass: "modal-narrow",
        html: `
          <div style="padding:16px 4px 8px;display:flex;flex-direction:column;gap:16px;">
            <p style="margin:0;font-size:14px;line-height:1.6;color:var(--ink-base);">
              确定要删除文章<strong>《${esc(title)}》</strong>吗？
            </p>
            <p style="margin:0;font-size:13px;color:#dc2626;background:#fef2f2;border:1px solid #fee2e2;padding:8px 12px;border-radius:6px;">
              ⚠️ 删除后不可恢复，请谨慎操作。
            </p>
            <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:8px;">
              <button type="button" class="btn" id="hw-del-art-cancel-btn">取消</button>
              <button type="button" class="btn btn-danger" id="hw-del-art-confirm-btn" style="background:#dc2626;color:#fff;border-color:#b91c1c;">确认删除</button>
            </div>
          </div>
        `,
        onMount(modalRoot) {
          const cancelBtn = modalRoot.querySelector("#hw-del-art-cancel-btn");
          const confirmBtn = modalRoot.querySelector("#hw-del-art-confirm-btn");

          if (cancelBtn) {
            cancelBtn.onclick = () => {
              closeModal();
              resolve({ ok: false, cancelled: true });
            };
          }

          if (confirmBtn) {
            confirmBtn.onclick = async () => {
              confirmBtn.disabled = true;
              confirmBtn.textContent = "正在删除…";
              try {
                const res = await apiJson(`/api/studio/articles/${encodeURIComponent(aid)}`, {
                  method: "DELETE"
                });
                closeModal();
                toast("🗑️ 文章已删除");
                if (typeof onSuccess === "function") {
                  try {
                    onSuccess(res);
                  } catch (e) {
                    console.error("deleteArticle onSuccess handler error:", e);
                  }
                }
                resolve(res);
              } catch (err) {
                confirmBtn.disabled = false;
                confirmBtn.textContent = "确认删除";
                toast(`删除文章失败：${err.message || err}`);
                reject(err);
              }
            };
          }
        }
      });
    });
  }

  /* ======================== 1. UNIFIED AUTH PASS (STANDALONE PAGE ON MAIN & FORUM) ======================== */
  function mountAuthPassStage(container, { reasonText = "", onSuccess, onCancel } = {}) {
    let authTab = "login";
    const urlRef = new URLSearchParams(window.location.search).get("ref") || "";
    const oauthError = new URLSearchParams(window.location.search).get("oauth_error") || "";
    const oauthErrorMessages = {
      oauth_state_invalid: "GitHub 授权已过期或浏览器验证不匹配，请重新尝试。",
      oauth_link_required: "这个邮箱已有 Handraw 账号，请先用密码登录，再到账号安全页面绑定 GitHub。",
      oauth_verified_email_required: "GitHub 主要邮箱尚未验证，请先在 GitHub 验证邮箱后重试。",
      oauth_provider_unavailable: "GitHub 服务暂不可用，请稍后重试或使用账号密码。",
      oauth_already_linked: "该 GitHub 身份已绑定其他 Handraw 账号。",
      oauth_account_inactive: "关联账号当前无法登录，请联系管理员。",
      oauth_denied: "GitHub 授权没有完成，请重试。",
      bad_request: "GitHub 登录未能完成，请重新授权。"
    };

    container.innerHTML = `
      <div style="background:var(--vermilion-wash);border:1px solid var(--vermilion-border);border-radius:10px;padding:11px 14px;margin-bottom:14px;font-size:13.2px;color:var(--ink-strong);">
        <strong>✨ ${esc(reasonText || "登录即享每日免费在线生图额度、云端收藏同步、互动鼓励与积分激励")}</strong>
      </div>

      <div class="hw-segmented" style="width:100%;margin-bottom:14px;" id="auth-mode-tabs">
        <button type="button" class="hw-seg-btn is-active" data-atab="login" style="flex:1;">🔑 账号登录</button>
        <button type="button" class="hw-seg-btn" data-atab="register" style="flex:1;">✨ 新用户注册 (+20✦)</button>
      </div>

      <div id="auth-form-stage"></div>
    `;

    const stage = container.querySelector("#auth-form-stage");
    const tabBtns = container.querySelectorAll("[data-atab]");
    const authDrafts = { login: {}, register: {} };
    function rememberAuthDraft() {
      stage.querySelectorAll("input").forEach((field) => {
        if (field.id) authDrafts[authTab][field.id] = field.value;
      });
    }
    function restoreAuthDraft() {
      stage.querySelectorAll("input").forEach((field) => {
        if (field.id && Object.prototype.hasOwnProperty.call(authDrafts[authTab], field.id)) {
          field.value = authDrafts[authTab][field.id];
        }
      });
    }
    stage.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.isComposing || event.target.tagName !== "INPUT") return;
      event.preventDefault();
      stage.querySelector(authTab === "login" ? "#login-confirm-btn" : "#reg-confirm-btn")?.click();
    });
    function authError(message, field) {
      const el = stage.querySelector("#auth-inline-error");
      if (el) el.textContent = message || "";
      if (field) stage.querySelector(field)?.focus();
    }
    function bindAuthClear() {
      stage.querySelectorAll("input").forEach((input) => {
        input.addEventListener("input", () => authError(""));
      });
    }

    const trackAuthEvent = (eventName) => {
      if (App.state?.serverBacked) {
        apiJson("/api/auth/funnel-event", {method:"POST",body:{event:eventName}}).catch(() => {});
      }
    };
    function renderGithubAuth() {
      const slot = stage.querySelector("#github-auth-entry");
      if (!slot || !App.state?.serverBacked) return;
      apiJson("/api/auth/github/status").then(status => {
        if (!slot.isConnected || !status.githubEnabled) return;
        const a = document.createElement("a");
        a.href = "/api/auth/github/start?mode=login";
        a.className = "btn";
        a.style.display = "inline-flex";
        a.style.justifyContent = "center";
        a.style.width = "100%";
        a.textContent = "使用 GitHub 账号继续";
        slot.append(a);
      }).catch(() => {});
    }
    function renderStage() {
      tabBtns.forEach((b) => b.classList.toggle("is-active", b.getAttribute("data-atab") === authTab));
      if (authTab === "login") {
        stage.innerHTML = `
          <div style="display:grid;gap:10px;margin-bottom:12px;">
            <input class="hw-input" id="login-demo-account" value="" autocomplete="username" placeholder="用户名或注册邮箱" />
            <input class="hw-input" id="login-demo-password" type="password" value="" autocomplete="current-password" placeholder="登录密码" />
          </div>
          <div style="margin:-4px 0 14px;font-size:12.4px;"><a href="?view=recovery" data-account-recovery>忘记密码</a></div>
          <div style="display:grid;gap:6px;margin-bottom:14px;font-size:12.4px;color:var(--ink-muted);">
            <div>✦ 登录后立享全站实测大图、完整提示词、每日 3 次免费生图与跨子域名收藏夹</div>
            <div>✦ 原 Discourse 老论坛迁移账号支持原邮箱/用户名直接登录并自动升级加密</div>
          </div>
          <p id="auth-inline-error" role="alert" style="color:var(--vermilion);font-size:13px;margin:0 0 10px;"></p>
          <div id="github-auth-entry" style="margin-bottom:12px;"></div>
          <div style="display:flex;gap:10px;justify-content:flex-end;">
            <button type="button" class="btn" id="login-cancel-btn">暂以游客浏览</button>
            <button type="button" class="btn btn-primary" id="login-confirm-btn">⚡ 登录并解锁全部内容</button>
          </div>
        `;
        restoreAuthDraft();
        bindAuthClear();
        if (oauthError) authError(oauthErrorMessages[oauthError] || "GitHub 授权未完成，请重新尝试。");
        trackAuthEvent("login_view");
        renderGithubAuth();
        stage.querySelector("#login-cancel-btn").onclick = () => {
          if (onCancel) onCancel();
        };
        stage.querySelector("#login-confirm-btn").onclick = async () => {
          const identifier = stage.querySelector("#login-demo-account").value.trim();
          const password = stage.querySelector("#login-demo-password").value;
          if (!identifier) { authError("请输入用户名或邮箱", "#login-demo-account"); return; }
          if (!password) { authError("请输入登录密码", "#login-demo-password"); return; }
          const btn = stage.querySelector("#login-confirm-btn");
          btn.disabled = true;
          btn.textContent = "正在登录…";
          authError("");
          try {
            if (App.state && App.state.serverBacked) {
              const res = await apiJson("/api/auth/login", {
                method: "POST", body: { identifier, password }
              });
              if (res.boot) applyBootState(res.boot);
              toast(`欢迎回来 @${res.boot?.user?.name || identifier}！`);
            } else {
              App.state.loggedIn = true;
              saveState();
              toast("已登录账号");
            }
            if (onSuccess) onSuccess();
          } catch (err) {
            authError(err.message || "登录失败，请检查账号和密码");
          } finally {
            if (btn.isConnected) { btn.disabled = false; btn.textContent = "登录"; }
          }
        };
      } else {
        stage.innerHTML = `
          <div style="display:grid;gap:10px;margin-bottom:14px;">
            <input class="hw-input" id="reg-email" type="email" autocomplete="email" required placeholder="邮箱（用于登录和找回密码）" />
            <input class="hw-input" id="reg-username" autocomplete="username" placeholder="用户名（2～32 位字母/数字/下划线/连字符）" />
            <input class="hw-input" id="reg-password" type="password" autocomplete="new-password" minlength="8" placeholder="设置密码（至少 8 位）" />
            <input class="hw-input" id="reg-confirm-password" type="password" autocomplete="new-password" minlength="8" placeholder="确认密码" />
            <details class="hw-account-register-optional" ${urlRef ? "open" : ""}>
              <summary>注册昵称与邀请码（选填）</summary>
              <div style="display:grid;gap:10px;margin-top:12px;">
                <input class="hw-input" id="reg-display-name" maxlength="40" placeholder="创作者昵称（注册后无法修改）" />
                <span class="hw-account-help">注册完成后昵称不可修改；留空时默认使用用户名作为昵称。</span>
                <input class="hw-input" id="reg-invite-code" value="${esc(urlRef)}" placeholder="好友邀请码（选填）" />
              </div>
            </details>
          </div>
          <p id="auth-inline-error" role="alert" style="color:var(--vermilion);font-size:13px;margin:0 0 10px;"></p>
          <div id="github-auth-entry" style="margin-bottom:12px;"></div>
          <div style="display:flex;gap:10px;justify-content:flex-end;">
            <button type="button" class="btn" id="reg-cancel-btn">返回</button>
            <button type="button" class="btn btn-primary" id="reg-confirm-btn">🎉 立即注册领 +20 积分</button>
          </div>
        `;
        restoreAuthDraft();
        bindAuthClear();
        trackAuthEvent("signup_view");
        renderGithubAuth();
        stage.querySelector("#reg-cancel-btn").onclick = () => {
          if (onCancel) onCancel();
        };
        stage.querySelector("#reg-confirm-btn").onclick = async () => {
          trackAuthEvent("signup_submit");
          const username = stage.querySelector("#reg-username").value.trim();
          const displayName = stage.querySelector("#reg-display-name").value.trim();
          const email = stage.querySelector("#reg-email").value.trim();
          const password = stage.querySelector("#reg-password").value;
          const confirmed = stage.querySelector("#reg-confirm-password").value;
          if (!/^[a-zA-Z0-9_-]{2,32}$/.test(username)) {
            authError("用户名需为 2～32 位字母、数字、下划线或连字符", "#reg-username"); return;
          }
          if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            authError("请填写有效的邮箱地址", "#reg-email"); return;
          }
          if (password.length < 8) {
            authError("登录密码至少 8 位", "#reg-password"); return;
          }
          if (password !== confirmed) {
            authError("两次输入的密码不一致", "#reg-confirm-password"); return;
          }
          const inviteCode = stage.querySelector("#reg-invite-code").value.trim();
          const btn = stage.querySelector("#reg-confirm-btn");
          btn.disabled = true;
          btn.textContent = "正在创建账号…";
          authError("");
          try {
            if (App.state && App.state.serverBacked) {
              const res = await apiJson("/api/auth/register", {
                method: "POST", body: { username, displayName, email, password, inviteCode }
              });
              if (res.boot) applyBootState(res.boot);
              toast(`注册成功！欢迎 @${res.boot?.user?.name || username}`);
            } else {
              App.state.loggedIn = true;
              addLedger("新用户注册欢迎礼", +20);
              saveState();
              toast("注册成功");
            }
            if (onSuccess) onSuccess();
          } catch (err) {
            authError(err.message || "注册失败，请稍后重试");
          } finally {
            if (btn.isConnected) { btn.disabled = false; btn.textContent = "立即注册"; }
          }
        };
      }
    }

    tabBtns.forEach((b) => {
      b.onclick = () => {
        if (authTab === b.getAttribute("data-atab")) return;
        rememberAuthDraft();
        authTab = b.getAttribute("data-atab");
        renderStage();
      };
    });
    renderStage();
  }

  function openLoginModal(reasonText, onSuccess) {
    if (App.channel === "main" && typeof window.HANDRAW_MAIN_OPEN_AUTH === "function") {
      window.HANDRAW_MAIN_OPEN_AUTH(reasonText || "", onSuccess || null);
      return;
    }
    if (App.channel === "forum" && typeof window.HANDRAW_FORUM_OPEN_AUTH === "function") {
      window.HANDRAW_FORUM_OPEN_AUTH(reasonText || "", onSuccess || null);
      return;
    }
    openModal({
      title: "登录 / 注册 Handraw 统一通行证",
      sizeClass: "modal-narrow",
      html: `<div id="modal-auth-mount"></div>`,
      onMount(root) {
        mountAuthPassStage(root.querySelector("#modal-auth-mount"), {
          reasonText,
          onCancel: closeModal,
          onSuccess() {
            closeModal();
            if (onSuccess) onSuccess();
          }
        });
      }
    });
  }

  /* ======================== 2. INLINE NON-MODAL SHARE & REPORT DRAWERS ======================== */
  function renderInlineSharePanelHtml(itemType, item) {
    const typeNames = { style: "画风", layout: "图型", work: "作品", topic: "实战帖" };
    const tName = typeNames[itemType] || "内容";
    const code = (item && item.id) || "";
    const title = (item && (item.title || `${item.id} ${item.name || ""}`)) || "Handraw 精选";
    const img = (item && ((item.images && item.images[0]) || item.image)) || "/images/poster-demo-autumn-equinox.webp";
    const workCount = item && (itemType === "style" || itemType === "layout") ? getAssetWorkCount(item.id) : null;
    const invCode = (App.state && App.state.user && App.state.user.inviteCode) || "handraw";
    const shareUrl =
      itemType === "topic"
        ? `https://handraw-style.com/t/${encodeURIComponent(code)}?ref=${encodeURIComponent(invCode)}`
        : `https://handraw-style.com/?target=${encodeURIComponent(code)}&ref=${encodeURIComponent(invCode)}`;
    const shareCopy =
      itemType === "topic"
        ? `在 Handraw 论坛看到一篇精彩实战帖《${title}》，来聊聊你的创作心得 👉 ${shareUrl}`
        : workCount !== null
        ? `推荐一个超稳的手绘画风/图型【${title}】！社区里已经有 ${workCount} 个作品和现成提示词配方，点链接登录就能直接抄作业 👉 ${shareUrl}`
        : `在 Handraw 手绘风社区挖到宝了：《${title}》，附完整画风+图型配方，一键就能在创作台复刻同款 👉 ${shareUrl}`;

    return `
      <div class="hw-inline-drawer" data-inline-share-panel="1">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
          <strong style="font-size:13.8px;color:var(--gold);">📤 便捷分享${esc(tName)} · 每邀 1 位新画友得 +15✦ 积分</strong>
          <button type="button" class="btn btn-sm" data-close-inline-share="1">收起 ×</button>
        </div>
        <div style="display:grid;grid-template-columns:120px 1fr;gap:14px;align-items:start;">
          <div style="background:#fff;border:1px solid var(--line-soft);border-radius:8px;padding:6px;text-align:center;">
            <div class="hw-share-thumb-wrap">
              <img src="${esc(img)}" alt="" />
            </div>
            <div style="font-size:11px;color:var(--ink-muted);">邀请码：<strong>${esc(invCode)}</strong></div>
          </div>
          <div style="display:flex;flex-direction:column;gap:8px;">
            <textarea class="hw-textarea" rows="3" data-share-copy-textarea="1" readonly style="font-size:12.5px;">${esc(shareCopy)}</textarea>
            <div class="hw-inline-share-actions">
              <button type="button" class="btn btn-sm btn-primary hw-btn-copy-share" data-btn-copy-share="1">📋 复制分享口令</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function bindInlineSharePanel(root, itemType, item, onClose) {
    const panel = root.querySelector("[data-inline-share-panel]");
    if (!panel) return;

    const closeBtn = panel.querySelector("[data-close-inline-share]");
    if (closeBtn && onClose) closeBtn.onclick = onClose;

    const copyBtn = panel.querySelector("[data-btn-copy-share]");
    if (copyBtn) {
      copyBtn.onclick = async () => {
        const text = panel.querySelector("[data-share-copy-textarea]").value;
        try {
          await navigator.clipboard.writeText(text);
        } catch (_) {}
        toast("✅ 分享口令与追踪链接已复制到剪贴板！");
      };
    }

    // The "simulate a friend signing up" button was removed: it called the real
    // registration endpoint with a fixed password and credited the inviter, so
    // any signed-in user could mint accounts and points indefinitely.
  }

  function openSharePosterModal(itemType, item) {
    if (App.channel === "main" && typeof window.HANDRAW_MAIN_SWITCH_VIEW === "function") {
      window.HANDRAW_MAIN_SWITCH_VIEW("wallet", { shareItem: { itemType, item } });
      return;
    }
    window.location.href = channelUrl("main", { view: "wallet" });
  }

  function renderInlineReportPanelHtml(targetType, targetId, titleLabel) {
    return `
      <div class="hw-inline-drawer" data-inline-report-panel="1" style="border-color:var(--vermilion-border);background:var(--vermilion-wash);">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
          <strong style="font-size:13.5px;color:var(--vermilion);">🚩 内容治理举报：${esc(titleLabel || targetId)}</strong>
          <button type="button" class="btn btn-sm" data-close-inline-report="1">取消 ×</button>
        </div>
        <div style="display:grid;gap:8px;">
          <select class="hw-select" data-rep-reason="1" style="width:100%;">
            <option value="提示词货不对板 / 虚假付费配方">提示词货不对板 / 虚假付费配方</option>
            <option value="疑似搬运抄袭他人原创作品">疑似搬运抄袭他人原创作品</option>
            <option value="恶意广告引流 / 无关灌水内容">恶意广告引流 / 无关灌水内容</option>
            <option value="不当或违规图文内容">不当或违规图文内容</option>
          </select>
          <textarea class="hw-textarea" rows="2" data-rep-detail="1" placeholder="补充具体问题说明（选填，便于审核员快速核查）…"></textarea>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
            <span style="font-size:11.8px;color:var(--ink-muted);">🛡️ 达到阈值将自动保护性暂停并转交审核队列</span>
            <button type="button" class="btn btn-sm btn-primary" data-submit-inline-report="1">提交举报工单</button>
          </div>
        </div>
      </div>
    `;
  }

  function bindInlineReportPanel(root, targetType, targetId, onClose) {
    const panel = root.querySelector("[data-inline-report-panel]");
    if (!panel) return;
    const closeBtn = panel.querySelector("[data-close-inline-report]");
    if (closeBtn && onClose) closeBtn.onclick = onClose;

    const submitBtn = panel.querySelector("[data-submit-inline-report]");
    if (submitBtn) {
      submitBtn.onclick = async () => {
        if (!App.state.loggedIn) {
          openLoginModal("登录后即可参与社区内容自治举报反馈");
          return;
        }
        const reason = panel.querySelector("[data-rep-reason]").value;
        const detail = panel.querySelector("[data-rep-detail]").value.trim();
        if (App.state.serverBacked) {
          try {
            const res = await apiJson("/api/reports", {
              method: "POST",
              body: { targetType, targetId, reason, detail }
            });
            if (onClose) onClose();
            if (res.autoPaused) {
              toast("🛡️ 举报已提交！该内容累计举报已触发阈值，系统已自动保护性暂停展示并转交后台复核");
            } else {
              toast("✅ 举报工单已提交至后台审核队列，感谢共同维护手绘社区生态！");
            }
            await refreshFromServer();
          } catch (err) {
            toast(`提交失败：${err.message}`);
          }
          return;
        }
        if (onClose) onClose();
        toast("✅ 举报反馈已提交");
      };
    }
  }

  function openReportModal(targetType, targetId, _titleLabel) {
    if (!App.state.loggedIn) {
      openLoginModal("登录后即可参与社区内容自治举报反馈");
      return;
    }
    if (targetType === "asset") goToAssetPage(targetId, "report");
    else if (targetType === "work") window.location.href=channelUrl('main',{view:'work',id:targetId,panel:'report'});
    else if (targetType === "topic") goToTopicPage(targetId);
  }

  /* ======================== 3. SKILL GALLERY FUNNEL STANDALONE REDIRECT ======================== */
  function openSkillFunnelPreviewModal() {
    goToSkillPage();
  }

  /* ======================== 4. CATEGORIZED ASSET PICKER MODAL ======================== */
  function openAssetPickerModal({ kind = "style", currentId = "", onSelect }) {
    const isStyle = kind === "style";
    const isLayout = kind === "layout";
    const list = isStyle ? App.styles : isLayout ? App.layouts : App.colors;
    const groups = isStyle
      ? [{ key: "FAV", label: "♥ 我的收藏" }, ...STYLE_GROUPS]
      : isLayout
      ? [{ key: "FAV", label: "♥ 我的收藏" }, ...LAYOUT_GROUPS]
      : [{ key: "ALL", label: "全部 36 色" }];

    let activeGroup = "ALL";
    let query = "";

    openModal({
      title: isStyle ? "🎨 选择画风（可随时清空，支持官方 / 独占 / 社区）" : isLayout ? "📐 选择图型（可随时清空）" : "🎨 选择主题色",
      html: `
        <div style="display:flex;flex-direction:column;gap:12px;">
          <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:space-between;">
            <input class="hw-input" id="picker-search-input" style="min-width:260px;" placeholder="搜索编号（如 FA-001 / SC-021）或中文关键词…" />
            <button type="button" class="btn btn-sm" id="picker-clear-slot">× 不指定此项（留空）</button>
          </div>
          <div class="hw-pills-row" id="picker-group-pills"></div>
          <div id="picker-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:12px;max-height:56vh;overflow-y:auto;padding:4px 2px;"></div>
        </div>
      `,
      onMount(root) {
        const pillsEl = root.querySelector("#picker-group-pills");
        const gridEl = root.querySelector("#picker-grid");
        const searchEl = root.querySelector("#picker-search-input");

        function renderPills() {
          const visible = visibleResourceGroups(list, groups, query);
          if (!visible.some(g => g.key === activeGroup)) activeGroup = "ALL";
          pillsEl.innerHTML = visible
            .map(
              (g) =>
                `<button type="button" class="hw-pill ${activeGroup === g.key ? "is-active" : ""}" data-g="${esc(g.key)}">${esc(g.label)} <span class="hw-pill-count">${g.count}</span></button>`
            )
            .join("");
          pillsEl.querySelectorAll("[data-g]").forEach((b) => {
            b.onclick = () => {
              activeGroup = b.getAttribute("data-g");
              renderPills();
              renderGrid();
            };
          });
        }

        function renderGrid() {
          const q = query.trim().toLowerCase();
          const filtered = list.filter((item) => {
            return resourceMatchesGroup(item, activeGroup) && resourceSearchText(item).includes(q);
          });

          const shown = filtered.slice(0, 96);
          if (!shown.length) {
            gridEl.innerHTML = `<div style="grid-column:1/-1;padding:32px;text-align:center;color:var(--ink-muted);">没有找到匹配项，试试其他分组或关键词</div>`;
            return;
          }

          gridEl.innerHTML = shown
            .map((item) => {
              const wCount = getAssetWorkCount(item.id);
              const selected = item.id === currentId;
              const badge =
                item.sourceType === "exclusive"
                  ? item.tier === "pro_credit" && !isUnlocked(item.id, item)
                    ? `<span class="hw-card-badge-tl badge-exclusive-pro">💎 ${item.unlockCost}积分</span>`
                    : `<span class="hw-card-badge-tl badge-exclusive-free">🔒 独占</span>`
                  : item.sourceType === "community"
                  ? `<span class="hw-card-badge-tl badge-community">✨ 共创</span>`
                  : "";
              return `
                <div class="hw-card" data-pick-id="${esc(item.id)}" style="margin:0;cursor:pointer;${selected ? "border:2px solid var(--vermilion);" : ""}">
                  <div class="hw-picker-card-media">
                    ${badge}
                    <img data-hw-src="${esc(item.image)}" alt="${esc(item.name)}" loading="lazy" />
                    ${wCount > 0 ? `<span class="hw-card-workcount">${wCount} 作品</span>` : ""}
                  </div>
                  <div style="padding:8px 10px;">
                    <div style="font-size:11.5px;font-weight:800;color:var(--vermilion);">${esc(item.id)}</div>
                    <div style="font-size:12.5px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(item.name)}</div>
                  </div>
                </div>
              `;
            })
            .join("");

          gridEl.querySelectorAll("[data-pick-id]").forEach((card) => {
            card.onclick = () => {
              const pickedId = card.getAttribute("data-pick-id");
              closeModal();
              if (onSelect) onSelect(pickedId);
            };
          });
        }

        searchEl.oninput = () => {
          query = searchEl.value;
          renderPills();
          renderGrid();
        };

        root.querySelector("#picker-clear-slot").onclick = () => {
          closeModal();
          if (onSelect) onSelect("");
        };

        renderPills();
        renderGrid();
      }
    });
  }

  /* ======================== 4.2 CARD PICKER MODAL (STYLE / LAYOUT / WORK) ======================== */
  function openSharedCardPickerModal({ kind = "style", onSelect } = {}) {
    let currentKind = ["style", "layout", "work"].includes(kind) ? kind : "style";
    let query = "";

    openModal({
      title: "📎 选择要附加分享到论坛的卡片（画风 / 图型 / 作品）",
      html: `
        <div style="display:flex;flex-direction:column;gap:12px;">
          <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:space-between;">
            <div class="hw-segmented" id="card-picker-tabs">
              <button type="button" class="hw-seg-btn ${currentKind === "style" ? "is-active" : ""}" data-card-kind="style">🎨 画风卡片 (${(App.styles || []).length})</button>
              <button type="button" class="hw-seg-btn ${currentKind === "layout" ? "is-active" : ""}" data-card-kind="layout">📐 图型卡片 (${(App.layouts || []).length})</button>
              <button type="button" class="hw-seg-btn ${currentKind === "work" ? "is-active" : ""}" data-card-kind="work">🖼️ 作品卡片 (${(App.state.works || []).length})</button>
            </div>
            <input class="hw-input" id="card-picker-search" style="min-width:220px;font-size:12.5px;" placeholder="按名称 / 关键词搜索…" />
          </div>
          <div id="card-picker-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px;max-height:56vh;overflow-y:auto;padding:4px 2px;"></div>
        </div>
      `,
      onMount(root) {
        const gridEl = root.querySelector("#card-picker-grid");
        const searchEl = root.querySelector("#card-picker-search");

        function renderList() {
          const q = query.trim().toLowerCase();
          let items = [];
          if (currentKind === "style") {
            items = (App.styles || []).filter((s) => !q || resourceSearchText(s).includes(q));
          } else if (currentKind === "layout") {
            items = (App.layouts || []).filter((l) => !q || resourceSearchText(l).includes(q));
          } else {
            items = (App.state.works || []).filter((w) => !q || `${w.title} ${w.authorName || ""} ${w.notes || ""}`.toLowerCase().includes(q));
          }

          if (items.length === 0) {
            gridEl.innerHTML = `<div style="grid-column:1/-1;padding:36px;text-align:center;color:var(--ink-muted);font-size:13px;">未找到匹配的内容</div>`;
            return;
          }

          gridEl.innerHTML = items
            .slice(0, 48)
            .map((it) => {
              const isWork = currentKind === "work";
              const title = isWork ? it.title : it.name;
              const img = isWork ? (it.images && it.images[0]) || "" : it.image;
              const author = isWork ? it.authorName || it.author : it.authorName || "Handraw 官方";
              const badge = isWork ? "🖼️ 作品" : currentKind === "layout" ? "📐 图型" : "🎨 画风";
              return `
                <div class="hw-card" data-pick-card-id="${esc(it.id)}" style="cursor:pointer;padding:8px;border:1px solid var(--line-soft);transition:transform 0.15s,box-shadow 0.15s;">
                  <div class="hw-picker-card-media" style="margin-bottom:6px;">
                    <img data-hw-src="${esc(img)}" alt="${esc(title)}" loading="lazy" />
                    <span style="position:absolute;top:5px;left:5px;font-size:10px;font-weight:800;background:rgba(20,17,15,0.7);color:#fff;padding:1px 6px;border-radius:4px;z-index:2;">${badge}</span>
                  </div>
                  <div style="font-weight:800;font-size:13px;line-height:1.35;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:2px;">
                    ${esc(title)}
                  </div>
                  <div style="font-size:11.5px;color:var(--ink-muted);display:flex;justify-content:space-between;align-items:center;">
                    <span>@${esc(author)}</span>
                    <span style="color:var(--vermilion);font-weight:750;">点击附加 +</span>
                  </div>
                </div>
              `;
            })
            .join("");

          gridEl.querySelectorAll("[data-pick-card-id]").forEach((el) => {
            el.onclick = () => {
              const cid = el.getAttribute("data-pick-card-id");
              let card = null;
              if (currentKind === "work") {
                const w = (App.state.works || []).find((x) => x.id === cid);
                if (w) {
                  card = {
                    kind: "work",
                    id: w.id,
                    title: w.title,
                    image: (w.images && w.images[0]) || "",
                    authorName: w.authorName || w.author || "",
                    desc: w.notes || w.prompt || ""
                  };
                }
              } else if (currentKind === "layout") {
                const l = (App.layouts || []).find((x) => x.id === cid);
                if (l) {
                  card = {
                    kind: "layout",
                    id: l.id,
                    title: l.name,
                    image: l.image,
                    authorName: l.authorName || "Handraw 官方",
                    desc: l.description || ""
                  };
                }
              } else {
                const s = (App.styles || []).find((x) => x.id === cid);
                if (s) {
                  card = {
                    kind: "style",
                    id: s.id,
                    title: s.name,
                    image: s.image,
                    authorName: s.authorName || "Handraw 官方",
                    desc: s.description || ""
                  };
                }
              }
              closeModal();
              if (card && onSelect) onSelect(card);
            };
          });
        }

        root.querySelectorAll("[data-card-kind]").forEach((btn) => {
          btn.onclick = () => {
            currentKind = btn.getAttribute("data-card-kind");
            root.querySelectorAll("[data-card-kind]").forEach((b) => b.classList.toggle("is-active", b === btn));
            renderList();
          };
        });

        searchEl.oninput = () => {
          query = searchEl.value;
          renderList();
        };

        renderList();
      }
    });
  }

  /* ======================== 5. STANDALONE FORUM POST NAVIGATION & PERSONAL ACCOUNT MANAGEMENT ======================== */
  async function goToForumCompose(prefill = {}) {
    let sharedCard = prefill.sharedCard || null;
    const styleCode = String(prefill.style1 || prefill.style || (sharedCard?.kind === "style" ? sharedCard.id : "")).trim().toUpperCase().replace(/^#/, "");
    const layoutCode = String(prefill.layout || (sharedCard?.kind === "layout" ? sharedCard.id : "")).trim().toUpperCase().replace(/^#/, "");
    const workId = String(prefill.workId || (sharedCard?.kind === "work" ? sharedCard.id : "")).trim();

    if (!sharedCard) {
      if (workId) {
        const w = (App.state.works || []).find((x) => x.id === workId);
        if (w) {
          sharedCard = {
            kind: "work",
            id: w.id,
            title: w.title,
            image: (w.images && w.images[0]) || "",
            authorName: w.authorName || w.author || "",
            desc: w.notes || w.prompt || ""
          };
        }
      } else if (styleCode) {
        const st = App.resourceMap.get(styleCode);
        if (st) {
          sharedCard = {
            kind: "style",
            id: st.id,
            title: st.name,
            image: st.image,
            authorName: st.authorName || "Handraw 官方",
            desc: st.description || ""
          };
        }
      } else if (layoutCode) {
        const lt = App.resourceMap.get(layoutCode);
        if (lt) {
          sharedCard = {
            kind: "layout",
            id: lt.id,
            title: lt.name,
            image: lt.image,
            authorName: lt.authorName || "Handraw 官方",
            desc: lt.description || ""
          };
        }
      }
    }

    const category =
      prefill.category && ["tuning", "experience", "assets", "tools"].includes(prefill.category)
        ? prefill.category
        : sharedCard?.kind === "work"
        ? "tuning"
        : styleCode || layoutCode
        ? "assets"
        : "experience";
    const title = String(prefill.topicTitle || prefill.title || "").trim();
    const body = String(prefill.topicBody || prefill.body || prefill.prompt || "").trim();
    const format = String(prefill.format || "").trim();

    let rawImgs = [];
    if (Array.isArray(prefill.topicImages) && prefill.topicImages.length) {
      rawImgs = prefill.topicImages.map((it, idx) =>
        typeof it === "string"
          ? { url: it, tag: `配图 P${idx + 1}` }
          : { url: String(it.url || it.src || ""), tag: String(it.tag || it.caption || `配图 P${idx + 1}`) }
      );
    } else if (Array.isArray(prefill.images) && prefill.images.length) {
      rawImgs = prefill.images.map((u, idx) =>
        typeof u === "string"
          ? { url: u, tag: `配图 P${idx + 1}` }
          : { url: String(u.url || u.src || ""), tag: String(u.tag || `配图 P${idx + 1}`) }
      );
    } else if (prefill.image) {
      rawImgs = [{ url: String(prefill.image), tag: "实测配图" }];
    }
    rawImgs = rawImgs.filter((x) => x.url);

    // Inside Forum channel: switch directly to standalone compose view (NEVER open any modal)
    if (App.channel === "forum" && typeof window.HANDRAW_FORUM_OPEN_COMPOSE === "function") {
      window.HANDRAW_FORUM_OPEN_COMPOSE({
        category,
        style1: styleCode,
        layout: layoutCode,
        workId,
        sharedCard,
        title,
        body,
        format,
        images: rawImgs,
        subject: prefill.subject || "",
        generationId: prefill.generationId || "",
        itemId: prefill.itemId || "",
        isCustomTitle: Boolean(prefill.isCustomTitle || prefill.titleSource === "manual"),
        titleSource: prefill.titleSource || (prefill.isCustomTitle ? "manual" : "auto")
      });
      return;
    }

    // Upload any data:image/* Base64 image before cross-origin navigation so URL stays short
    const cleanImgs = [];
    for (let i = 0; i < Math.min(rawImgs.length, 6); i++) {
      const entry = rawImgs[i];
      if (entry.url.startsWith("data:image/")) {
        if (App.state && App.state.loggedIn && App.state.serverBacked) {
          try {
            const up = await apiJson("/api/uploads", {
              method: "POST",
              body: { dataUrl: entry.url, nameZh: entry.tag || `发帖配图-${i + 1}`, cat: "forum" }
            });
            if (up && up.url) cleanImgs.push({ url: up.url, tag: entry.tag });
          } catch (_) {}
        }
      } else {
        cleanImgs.push({ url: entry.url, tag: entry.tag });
      }
    }

    const params = { view: "compose", category };
    if (sharedCard) {
      try {
        params.card = JSON.stringify(sharedCard);
      } catch (_) {}
    }
    if (workId) params.work = workId;
    if (styleCode) params.style = styleCode;
    if (layoutCode) params.layout = layoutCode;
    if (title) params.title = title.slice(0, 120);
    if (body) params.body = body.slice(0, 900);
    if (format) params.format = format;
    if (cleanImgs.length) params.imgs = JSON.stringify(cleanImgs);
    if (prefill.subject) params.subject = String(prefill.subject).slice(0, 120);
    if (prefill.generationId) params.generationId = String(prefill.generationId);
    if (prefill.itemId) params.itemId = String(prefill.itemId);
    if (prefill.isCustomTitle || prefill.titleSource === "manual") params.customTitle = "1";

    window.location.href = channelUrl("forum", params);
  }

  async function goToCurationShare(prefill = {}) {
    if (!App.state?.loggedIn) {
      openLoginModal("登录后分享投稿", () => goToCurationShare(prefill));
      return;
    }
    const user = App.state.user.username;
    // Works are created by successful public generations, not manual forum posting.
    if (prefill.kind === "work") {
      window.location.href = channelUrl("studio", {entry: "quick"});
      return;
    }
    const kind = ["style", "layout"].includes(prefill.kind) ? prefill.kind : "style";
    try {
      const payload = Object.assign({}, prefill, {kind, styles: prefill.styles || (prefill.style1 ? [prefill.style1] : [])});
      if (prefill.subject != null) payload.subject = String(prefill.subject);
      if (prefill.workId) payload.workId = String(prefill.workId);
      if (prefill.generationId) payload.generationId = String(prefill.generationId);
      if (prefill.itemId) payload.itemId = String(prefill.itemId);
      const saved = await apiJson("/api/curation/drafts", {method:"POST", body:{payload}});
      if (App.state.user.username !== user) return;
      window.location.href = channelUrl("forum", {view:"curation", tab:"share",kind,draft:saved.id});
    } catch (err) { toast(`打开投稿失败：${err.message}`); }
  }

  function openQuickPublishModal(_initialTab = "topic", prefill = {}) {
    // Posting is strictly limited to Forum Posts on a dedicated standalone page (never a popup modal)
    if (["style","layout","work"].includes(_initialTab)) goToCurationShare(Object.assign({},prefill,{kind:_initialTab}));
    else goToForumCompose(prefill || {});
  }

  function renderAccountSettingsFormHtml() {
    if (!App.state || !App.state.loggedIn || !App.state.user) return "";
    const u = App.state.user;
    const modBadges = getUserModeratorBadges(u.username);
    const mgmtRole =
      u.managementRole ||
      (["admin", "operator", "reviewer"].includes(u.role)
        ? u.role
        : modBadges.length
        ? "moderator"
        : "none");
    const roleLabelMap = {
      admin: "👑 超级管理员 (全站最高权限)",
      operator: "🧭 运营管理员 (增长·兑换码·公告·悬赏)",
      reviewer: "🛡️ 内容审核员 (内容风控·举报裁定·禁自审)",
      moderator: "🏛️ 论坛板块版主 (所辖板块专属治理)",
      none: "🎨 社区创作者"
    };

    return `
      <div class="hw-detail-section-card" id="standalone-account-settings-form" style="display:grid;gap:16px;">
        <div style="border-bottom:1px solid var(--line-soft);padding-bottom:12px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
          <div>
            <h2 style="margin:0 0 4px;font-size:19px;font-family:var(--font-serif);">我的账号</h2>
            <div style="font-size:12.5px;color:var(--ink-muted);">当前身份：<strong>${esc(roleLabelMap[mgmtRole] || roleLabelMap.none)}</strong></div>
          </div>
          ${
            mgmtRole !== "none"
              ? `<a class="btn btn-sm btn-primary" href="${esc(channelUrl("admin", mgmtRole === "admin" ? { module: "users" } : {}))}">🏛️ 进入我的专属管理后台 ↗</a>`
              : ""
          }
        </div>

        ${
          modBadges.length
            ? `<div style="background:rgba(31,95,139,0.08);border:1px solid rgba(31,95,139,0.25);border-radius:10px;padding:10px 14px;font-size:12.8px;color:#1f5f8b;">
                <strong>🛡️ 当前担任论坛板块版主：</strong>
                ${modBadges.map((m) => `<span style="margin-right:8px;font-weight:800;">${esc(m.boardLabel || m.shortBoardLabel)} · ${esc(m.title)}</span>`).join("")}
              </div>`
            : ""
        }

        <section data-account-panel="profile" class="hw-account-identity-row" aria-label="头像和创作者身份">
          <img class="hw-account-avatar-preview" src="${esc(u.avatarUrl || "/assets/avatar-default.svg")}" alt="我的创作者头像" />
          <div class="hw-account-identity-actions">
            <strong>${esc(u.displayName || u.name || u.username)}</strong>
            <span style="font-size:12px;color:var(--ink-muted);">公开头像 · 支持 JPG、PNG、WebP，原始图片最大 3 MB；裁剪后再上传</span>
            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
              <label class="btn btn-sm" for="acc-avatar-file" style="cursor:pointer;">选择头像</label>
              <input type="file" id="acc-avatar-file" accept="image/jpeg,image/png,image/webp" style="position:absolute;width:1px;height:1px;opacity:0;" />
              <button type="button" class="btn btn-sm" id="acc-avatar-reset">恢复默认头像</button>
            </div>
            <div id="acc-avatar-preview-stage" hidden>
              <p class="hw-account-help">拖动图片调整头像位置，或用滑块缩放，确认后再上传。</p>
              <canvas id="acc-avatar-upload-preview" width="320" height="320" role="img" aria-label="可拖动调整裁剪位置的头像预览" tabindex="0" style="width:224px;height:224px;max-width:100%;border-radius:50%;border:2px solid var(--line-soft);display:block;cursor:grab;touch-action:none;user-select:none;"></canvas>
              <div class="hw-account-help">拖动头像或使用方向键移动，预览中的圆形区域就是最终头像。</div>
              <button type="button" class="btn btn-sm" id="acc-avatar-center">恢复居中</button>
              <label class="hw-account-help" for="acc-avatar-zoom">裁剪缩放</label>
              <input type="range" id="acc-avatar-zoom" min="1" max="3" step="0.1" value="1" aria-label="头像裁剪缩放" />
              <div style="display:flex;gap:8px;margin-top:8px;">
                <button type="button" class="btn btn-sm btn-primary" id="acc-avatar-confirm">确认上传</button>
                <button type="button" class="btn btn-sm" id="acc-avatar-cancel">取消</button>
              </div>
            </div>
            <div id="acc-avatar-feedback" role="status" aria-live="polite" aria-atomic="true" style="font-size:13px;line-height:1.5;font-weight:600;min-height:20px;" hidden></div>
          </div>
        </section>
        <div data-account-panel="profile" class="hw-account-form-grid">
          <div>
            <div style="font-size:12.5px;font-weight:750;margin-bottom:5px;">创作者昵称</div>
            <div style="font-weight:700;">${esc(u.displayName || u.name || u.username)}</div>
            <div class="hw-account-help">注册后创作者昵称不可修改。</div>
            <div class="hw-account-help">用户名：@${esc(u.username)}（不可修改）</div>
          </div>

        </div>

        <div data-account-panel="profile">
          <label style="font-size:12.5px;font-weight:750;display:block;margin-bottom:5px;">个人创作简介（展示在你的公开个人主页顶部）</label>
          <textarea class="hw-textarea" rows="2" id="acc-bio" placeholder="一句话介绍你的擅长画风、版式方向或主理专栏…">${esc(u.bio || "")}</textarea>
        </div>

        <section data-account-panel="security" class="hw-account-security-panel">
          <h3>🔑 修改密码</h3>
          <p class="hw-account-help">修改成功后，当前浏览器继续登录，其他登录会话将退出。新密码至少 8 位。</p>
          <div class="hw-account-form-grid">
            <label>当前密码<input class="hw-input" type="password" id="acc-cur-pw" autocomplete="current-password" /></label>
            <label>新密码<input class="hw-input" type="password" id="acc-new-pw" minlength="8" maxlength="128" autocomplete="new-password" /></label>
            <label>确认新密码<input class="hw-input" type="password" id="acc-confirm-pw" minlength="8" maxlength="128" autocomplete="new-password" /></label>
          </div>
          <div style="margin-top:12px;"><button type="button" class="btn btn-sm" id="acc-password-save">修改密码</button></div>
          <div id="acc-password-feedback" class="hw-account-help" role="status" aria-live="polite"></div>
        </section>
        <section data-account-panel="email" class="hw-account-security-panel">
          <h3>✉️ 邮箱与验证</h3>
          <div style="font-size:13px;">当前绑定邮箱：<strong style="overflow-wrap:anywhere;">${esc(u.email || "尚未绑定")}</strong></div>
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:12px 0 18px;padding:12px;border:1px solid var(--line-soft);border-radius:10px;">
            <div id="acc-email-verify-status" role="status" aria-live="polite" style="font-size:13px;font-weight:700;flex:1;min-width:160px;">正在检查邮箱验证状态…</div>
            <button type="button" class="btn btn-sm btn-primary" id="acc-send-email-verification" disabled>验证当前邮箱</button>
          </div>
          <h4 style="font-size:14px;margin:0 0 6px;">更换绑定邮箱</h4>
          <p class="hw-account-help">输入新邮箱与当前密码。验证链接会发送到新邮箱，确认前原邮箱继续有效；链接 30 分钟内有效、只能用一次。</p>
          <div class="hw-account-form-grid">
            <input class="hw-input" id="acc-new-email" type="email" autocomplete="email" placeholder="新邮箱地址" />
            <input class="hw-input" id="acc-email-password" type="password" autocomplete="current-password" placeholder="当前登录密码（用于安全验证）" />
          </div>
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:12px;">
            <button type="button" class="btn btn-sm" id="acc-change-email">发送新邮箱验证链接</button>
          </div>
          <span id="acc-email-feedback" role="status" aria-live="polite" class="hw-account-help"></span>
          <p class="hw-account-help">忘记密码请从退出登录后的登录页进入「忘记密码」流程；安全验证邮件会发送到当前或新邮箱。</p>
        </section>

        <section data-account-panel="security" class="hw-account-security-panel">
          <h3>我的数据导出</h3>
          <p class="hw-account-help">可以下载个人资料、作品与帖子、收藏、创作记录、积分记录和站内通知。导出文件可能包含私人创作内容，请妥善保管。此操作不会停用或删除账号。</p>
          <button class="btn btn-sm" type="button" id="acc-export-data">下载我的账号数据（JSON）</button>
          <p id="acc-export-feedback" class="hw-account-help" role="status" aria-live="polite"></p>
        </section>
        <section data-account-panel="security" class="hw-account-security-panel">
          <h3>关联的第三方登录</h3>
          <p class="hw-account-help">GitHub 身份按平台用户 ID 关联，不会自动按邮箱合并其他账号。解绑需要当前登录密码。</p>
          <div id="acc-github-status" role="status" aria-live="polite" class="hw-account-help">正在检查 GitHub 登录状态…</div>
          <div id="acc-github-actions"></div>
        </section>
        <section data-account-panel="security" class="hw-account-security-panel">
          <h3>登录设备</h3>
          <p class="hw-account-help">可以查看当前网页登录会话，并通过密码退出其他设备。</p>
          <div id="acc-session-list" class="hw-account-help">正在读取…</div>
          <div class="hw-account-form-grid">
            <label>当前密码<input class="hw-input" id="acc-session-password" type="password" placeholder="验证账号身份" autocomplete="current-password" /></label>
            <button class="btn btn-sm" type="button" id="acc-revoke-other-sessions">退出其他设备</button>
          </div>
          <div id="acc-session-feedback" class="hw-account-help" role="status" aria-live="polite"></div>
        </section>
        <div data-account-panel="devices" style="background:var(--paper-bg);border:1px solid var(--line-soft);border-radius:12px;padding:12px 16px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
          <div style="font-size:12.8px;color:var(--ink-body);">
            <strong>已授权设备与客户端：</strong> <span>管理已授权的 Skill 插件与终端应用</span>
          </div>
          <div>
            <a class="btn btn-sm" href="/?view=devices">管理已授权设备</a>
          </div>
        </div>

        <div data-account-panel="profile" style="display:flex;justify-content:flex-end;align-items:center;gap:10px;flex-wrap:wrap;">
          <span class="hw-account-help" id="acc-profile-feedback" role="status" aria-live="polite"></span>
          <button type="button" class="btn btn-primary" id="acc-save-btn">保存个人资料</button>
        </div>
      </div>
    `;
  }

  function bindAccountSettingsForm(root, onSaved) {
    const formEl = root.querySelector("#standalone-account-settings-form");
    if (!formEl || !App.state || !App.state.user) return;
    const u = App.state.user;

    const emailStatus = formEl.querySelector("#acc-email-verify-status");
    const verifyEmailBtn = formEl.querySelector("#acc-send-email-verification");
    const readEmailStatus = async () => {
      if (!emailStatus || !App.state.serverBacked) return;
      try {
        const status = await apiJson("/api/account/status");
        if (!emailStatus.isConnected) return;
        emailStatus.textContent =
          (status.emailVerified ? "✓ 已验证邮箱" : "尚未验证邮箱") +
          (status.mailEnabled ? "" : " · 站点尚未配置邮件服务，验证与换绑暂不可用");
        if (verifyEmailBtn) {
          verifyEmailBtn.hidden = Boolean(status.emailVerified);
          verifyEmailBtn.disabled = !status.mailEnabled || Boolean(status.emailVerified);
        }
      } catch (err) {
        if (emailStatus.isConnected) emailStatus.textContent = "暂时无法读取邮箱验证状态";
      }
    };
    if (verifyEmailBtn) verifyEmailBtn.onclick = async () => {
      verifyEmailBtn.disabled = true;
      emailStatus.textContent = "正在发送验证邮件…";
      try {
        const res = await apiJson("/api/auth/send-verification", {method:"POST",body:{}});
        emailStatus.textContent = res.message || "请打开当前邮箱，点击验证链接";
      } catch (err) {
        emailStatus.textContent = err.message || "发送失败，请稍后重试";
      } finally { verifyEmailBtn.disabled = false; }
    };
    readEmailStatus();

    const avatarInput = formEl.querySelector("#acc-avatar-file");
    const avatarFeedback = formEl.querySelector("#acc-avatar-feedback");
    const setAvatarFeedback = (message, kind = "info") => {
      if (!avatarFeedback) return;
      avatarFeedback.textContent = message;
      avatarFeedback.hidden = !message;
      avatarFeedback.setAttribute("role", kind === "error" ? "alert" : "status");
      avatarFeedback.dataset.state = kind;
      avatarFeedback.style.color = kind === "error" ? "var(--vermilion, #a43529)" : "var(--ink-body)";
      avatarFeedback.style.background = kind === "error" ? "var(--vermilion-wash, #fff0ea)" : "transparent";
      avatarFeedback.style.borderRadius = "8px";
      avatarFeedback.style.padding = kind === "error" ? "9px 12px" : "0";
    };
    const avatarPreviewStage = formEl.querySelector("#acc-avatar-preview-stage");
    const avatarPreview = formEl.querySelector("#acc-avatar-upload-preview");
    let pendingAvatar = null;
    let decodedAvatar = null;
    let selectionId = 0;
    let avatarPanX = 0;
    let avatarPanY = 0;
    let avatarDrag = null;
    const avatarZoom = formEl.querySelector("#acc-avatar-zoom");
    const avatarConfirm = formEl.querySelector("#acc-avatar-confirm");
    const avatarCenter = formEl.querySelector("#acc-avatar-center");
    function drawAvatarPreview() {
      if (!decodedAvatar || !avatarPreview) return;
      const ctx = avatarPreview.getContext("2d");
      if (!ctx) throw new Error("当前浏览器不支持头像裁剪，请更新浏览器");
      const w = decodedAvatar.naturalWidth || decodedAvatar.width;
      const h = decodedAvatar.naturalHeight || decodedAvatar.height;
      if (!w || !h) throw new Error("图片尺寸无效，请选择其他图片");
      const side = Math.min(w, h) / Number(avatarZoom?.value || 1);
      const limitX = (w - side) / 2;
      const limitY = (h - side) / 2;
      avatarPanX = Math.max(-limitX, Math.min(limitX, avatarPanX));
      avatarPanY = Math.max(-limitY, Math.min(limitY, avatarPanY));
      const sx = limitX - avatarPanX;
      const sy = limitY - avatarPanY;
      ctx.clearRect(0, 0, 320, 320);
      ctx.drawImage(decodedAvatar, sx, sy, side, side, 0, 0, 320, 320);
    }
    function panAvatar(dx, dy) {
      if (!decodedAvatar) return;
      const w = decodedAvatar.naturalWidth || decodedAvatar.width;
      const h = decodedAvatar.naturalHeight || decodedAvatar.height;
      const side = Math.min(w, h) / Number(avatarZoom?.value || 1);
      // Pointer and keyboard movement is measured in displayed preview pixels.
      avatarPanX += dx * side / avatarPreview.getBoundingClientRect().width;
      avatarPanY += dy * side / avatarPreview.getBoundingClientRect().height;
      drawAvatarPreview();
    }
    if (avatarPreview) {
      avatarPreview.addEventListener("pointerdown", (event) => {
        if (!decodedAvatar || event.button !== 0) return;
        avatarDrag = { id: event.pointerId, x: event.clientX, y: event.clientY };
        avatarPreview.setPointerCapture(event.pointerId);
        avatarPreview.style.cursor = "grabbing";
      });
      avatarPreview.addEventListener("pointermove", (event) => {
        if (!avatarDrag || event.pointerId !== avatarDrag.id) return;
        const dx = event.clientX - avatarDrag.x;
        const dy = event.clientY - avatarDrag.y;
        avatarDrag.x = event.clientX;
        avatarDrag.y = event.clientY;
        panAvatar(dx, dy);
      });
      const stopAvatarDrag = (event) => {
        if (!avatarDrag || event.pointerId !== avatarDrag.id) return;
        avatarDrag = null;
        avatarPreview.style.cursor = "grab";
        if (avatarPreview.hasPointerCapture(event.pointerId)) avatarPreview.releasePointerCapture(event.pointerId);
      };
      avatarPreview.addEventListener("pointerup", stopAvatarDrag);
      avatarPreview.addEventListener("pointercancel", stopAvatarDrag);
      avatarPreview.addEventListener("lostpointercapture", () => {
        avatarDrag = null;
        avatarPreview.style.cursor = "grab";
      });
      avatarPreview.addEventListener("keydown", (event) => {
        const step = event.shiftKey ? 24 : 8;
        const move = { ArrowLeft: [step, 0], ArrowRight: [-step, 0],
                       ArrowUp: [0, step], ArrowDown: [0, -step] }[event.key];
        if (!move || !decodedAvatar) return;
        event.preventDefault();
        panAvatar(move[0], move[1]);
      });
    }
    if (avatarCenter) avatarCenter.onclick = () => {
      avatarPanX = 0;
      avatarPanY = 0;
      if (avatarZoom) avatarZoom.value = "1";
      drawAvatarPreview();
    };
    if (avatarZoom) avatarZoom.oninput = () => {
      try { drawAvatarPreview(); }
      catch (err) { setAvatarFeedback(err.message || "裁剪预览失败，请重新选择图片", "error"); }
    };
    function clearAvatarPreview() {
      selectionId++;
      pendingAvatar = null;
      avatarDrag = null;
      avatarPanX = 0;
      avatarPanY = 0;
      if (decodedAvatar && typeof decodedAvatar.close === "function") decodedAvatar.close();
      decodedAvatar = null;
      if (avatarInput) avatarInput.value = "";
      if (avatarPreviewStage) avatarPreviewStage.hidden = true;
      if (avatarZoom) avatarZoom.value = "1";
      if (avatarConfirm) avatarConfirm.disabled = true;
      if (avatarPreview) avatarPreview.getContext("2d")?.clearRect(0, 0, 320, 320);
    }
    if (avatarInput) avatarInput.addEventListener("change", async () => {
      const file = avatarInput.files?.[0];
      clearAvatarPreview();
      if (!file) return;
      const ext = String(file.name || "").split(".").pop().toLowerCase();
      const allowedType = ["image/jpeg", "image/png", "image/webp"].includes(file.type)
        || (!file.type && ["png", "jpg", "jpeg", "webp"].includes(ext));
      if (!allowedType) {
        setAvatarFeedback("图片格式不支持。请选择 JPG、PNG 或 WebP 格式。", "error");
        return;
      }
      // Check the ORIGINAL source size, not only the compressed crop.
      if (!file.size || file.size > 3 * 1024 * 1024) {
        setAvatarFeedback("图片大小为 " + (file.size / (1024 * 1024)).toFixed(2) + " MB，原始文件不能超过 3 MB。请压缩或缩小图片后重试。", "error");
        return;
      }
      pendingAvatar = file;
      const requestId = selectionId;
      avatarPreviewStage.hidden = false;
      avatarConfirm.disabled = true;
      setAvatarFeedback("已选择 " + file.name + "，正在生成头像预览…");
      const showDecodedImage = (image) => {
        if (requestId !== selectionId) {
          if (typeof image.close === "function") image.close();
          return;
        }
        try {
          const w = image.naturalWidth || image.width;
          const h = image.naturalHeight || image.height;
          if (w < 32 || h < 32 || w * h > 16000000) {
            throw new Error("图片需至少 32×32 像素，且不超过 1600 万像素");
          }
          decodedAvatar = image;
          drawAvatarPreview();
          avatarConfirm.disabled = false;
          setAvatarFeedback("头像预览已完成，调整缩放后点击确认上传", "success");
        } catch (err) {
          setAvatarFeedback(err.message || "预览失败，请尝试重新导出图片", "error");
        }
      };
      const fallbackToImage = () => {
        const reader = new FileReader();
        reader.onerror = () => {
          if (requestId === selectionId) setAvatarFeedback("图片读取失败，请重新选择。如果持续失败，请尝试另存为 JPG 或 PNG。", "error");
        };
        reader.onload = () => {
          if (requestId !== selectionId) return;
          const image = new Image();
          image.onload = () => showDecodedImage(image);
          image.onerror = () => {
            if (requestId === selectionId) setAvatarFeedback("图片解码失败，请重新导出为标准 PNG、JPG 或 WebP 后再试。", "error");
          };
          image.src = String(reader.result || "");
        };
        try { reader.readAsDataURL(file); }
        catch (err) { if (requestId === selectionId) setAvatarFeedback("无法读取图片：" + (err.message || "请更换图片"), "error"); }
      };
      // Blob-aware decode avoids huge PNG data URLs. Older browsers fall back
      // to FileReader + Image without silently failing.
      if (typeof createImageBitmap === "function") {
        try {
          const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
          showDecodedImage(bitmap);
        } catch (err) {
          if (requestId === selectionId) fallbackToImage();
        }
      } else {
        fallbackToImage();
      }
    });
    const cancelAvatar = formEl.querySelector("#acc-avatar-cancel");
    if (cancelAvatar) cancelAvatar.onclick = () => { clearAvatarPreview(); setAvatarFeedback("已取消上传"); };
    const confirmAvatar = formEl.querySelector("#acc-avatar-confirm");
    if (confirmAvatar) confirmAvatar.onclick = async () => {
      if (!pendingAvatar || !decodedAvatar) {
        setAvatarFeedback("图片尚未准备好，请先选择有效图片并等待预览完成。", "error");
        return;
      }
      if (pendingAvatar.size > 3 * 1024 * 1024) {
        setAvatarFeedback("原始图片超过 3 MB，请重新选择更小的图片。", "error");
        return;
      }
      confirmAvatar.disabled = true;
      setAvatarFeedback("正在上传头像，请勿关闭页面…");
      try {
        // Send exactly the crop the user approved, not the uncropped original.
        const dataUrl = avatarPreview.toDataURL("image/png");
        await apiJson("/api/account/avatar", { method: "POST", body: { dataUrl } });
        clearAvatarPreview();
        await refreshFromServer();
        setAvatarFeedback("头像已成功更新", "success");
        toast("头像已保存，各页面将同步显示");
        if (onSaved) onSaved();
      } catch (err) {
        setAvatarFeedback("头像上传失败：" + (err.message || "请检查网络后重试"), "error");
      } finally { if (confirmAvatar.isConnected) confirmAvatar.disabled = false; }
    };
    const resetAvatar = formEl.querySelector("#acc-avatar-reset");
    if (resetAvatar) resetAvatar.onclick = async () => {
      resetAvatar.disabled = true;
      try {
        await apiJson("/api/account/avatar/reset", {method:"POST", body:{}});
        await refreshFromServer();
        toast("已恢复默认头像");
        if (onSaved) onSaved();
      } catch (err) { toast(err.message); }
      finally { resetAvatar.disabled = false; }
    };

    const changeEmailBtn = formEl.querySelector("#acc-change-email");
    if (changeEmailBtn) changeEmailBtn.onclick = async () => {
      const email = formEl.querySelector("#acc-new-email").value.trim();
      const currentPassword = formEl.querySelector("#acc-email-password").value;
      const status = formEl.querySelector("#acc-email-feedback");
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || !currentPassword) {
        status.textContent = "请输入有效的新邮箱地址及当前登录密码";
        return;
      }
      changeEmailBtn.disabled = true;
      status.textContent = "正在发送验证邮件…";
      try {
        const result = await apiJson("/api/auth/change-email", {
          method:"POST", body:{email, currentPassword}
        });
        status.textContent = result.message || "请查看新邮箱，验证前原邮箱保持不变";
        formEl.querySelector("#acc-email-password").value = "";
      } catch (err) { status.textContent = err.message || "换绑请求失败"; }
      finally { changeEmailBtn.disabled = false; }
    };

    const githubStatus = formEl.querySelector("#acc-github-status");
    const githubActions = formEl.querySelector("#acc-github-actions");
    if (githubStatus && githubActions) {
      apiJson("/api/auth/github/status").then(status => {
        if (!githubStatus.isConnected) return;
        githubActions.replaceChildren();
        githubStatus.textContent = status.githubLinked
          ? "已绑定 GitHub：" + (status.githubLogin || "已认证账号")
          : status.githubEnabled ? "尚未绑定 GitHub" : "当前未启用第三方登录";
        if (status.githubEnabled && !status.githubLinked) {
          const link = document.createElement("a");
          link.href = "/api/auth/github/start?mode=link";
          link.className = "btn btn-sm";
          link.textContent = "绑定 GitHub";
          githubActions.append(link);
        }
        if (status.githubLinked) {
          const wrap = document.createElement("div");
          wrap.style.cssText = "display:flex;gap:8px;flex-wrap:wrap;align-items:center;";
          const pw = document.createElement("input");
          pw.type = "password";
          pw.className = "hw-input";
          pw.placeholder = "输入当前密码确认解绑";
          pw.autocomplete = "current-password";
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "btn btn-sm";
          btn.textContent = "解除 GitHub 绑定";
          btn.onclick = async () => {
            if (!pw.value) { githubStatus.textContent = "请输入当前密码后再解绑"; pw.focus(); return; }
            if (!window.confirm("解除绑定后将无法使用 GitHub 登录。确认继续？")) return;
            btn.disabled = true;
            try {
              const result = await apiJson("/api/auth/github/unlink", {method:"POST",
                body:{currentPassword:pw.value}});
              githubStatus.textContent = result.message || "已解除 GitHub 绑定";
              githubActions.replaceChildren();
              pw.value = "";
            } catch (err) {
              githubStatus.textContent = err.message || "解绑失败";
              btn.disabled = false;
            }
          };
          wrap.append(pw, btn);
          githubActions.append(wrap);
        }
      }).catch(() => { if (githubStatus.isConnected) githubStatus.textContent = "暂时无法读取第三方身份状态"; });
    }

    const sessionsMount = formEl.querySelector("#acc-session-list");
    const readSessions = async () => {
      if (!sessionsMount || !App.state.serverBacked) return;
      try {
        const result = await apiJson("/api/account/sessions");
        sessionsMount.replaceChildren();
        if (!result.items.length) sessionsMount.textContent = "没有活动中的浏览器登录会话";
        for (const item of result.items) {
          const line = document.createElement("p");
          line.className = "hw-account-session-row";
          const agent = String(item.device || "");
          const platform = /Windows/i.test(agent) ? "Windows" : /Macintosh|Mac OS X/i.test(agent) ? "macOS" : /Android/i.test(agent) ? "Android" : /iPhone|iPad/i.test(agent) ? "iOS" : /Linux/i.test(agent) ? "Linux" : "未知系统";
          const browser = /Edg\//i.test(agent) ? "Edge" : /Firefox\//i.test(agent) ? "Firefox" : /Chrome\//i.test(agent) ? "Chrome" : /Safari\//i.test(agent) ? "Safari" : "浏览器";
          const stamp = Number(item.createdAt);
          const date = Number.isFinite(stamp) && stamp > 0 ? new Date(stamp < 1e12 ? stamp * 1000 : stamp).toLocaleString("zh-CN") : String(item.createdAt || "");
          line.textContent = (item.current ? "● 当前浏览器 · " : "") + platform + " / " + browser + (date ? " · 登录于 " + date : "");
          if (item.current) line.style.fontWeight = "700";
          sessionsMount.append(line);
        }
      } catch (err) { sessionsMount.textContent = err.message || "无法读取登录设备"; }
    };
    readSessions();
    const revokeBtn = formEl.querySelector("#acc-revoke-other-sessions");
    if (revokeBtn) revokeBtn.onclick = async () => {
      const pwInput = formEl.querySelector("#acc-session-password");
      const status = formEl.querySelector("#acc-session-feedback");
      if (!pwInput.value) { status.textContent = "请输入当前密码后再继续"; pwInput.focus(); return; }
      if (!window.confirm("确认退出其他所有浏览器登录会话？当前浏览器将保持登录。")) return;
      revokeBtn.disabled = true;
      status.textContent = "正在撤销其他登录会话…";
      try {
        const res = await apiJson("/api/account/sessions/revoke-others", {
          method: "POST", body: { currentPassword: pwInput.value }
        });
        pwInput.value = "";
        status.textContent = "已退出其他 " + res.revoked + " 个登录会话";
        toast(status.textContent);
        await readSessions();
      } catch (err) { status.textContent = err.message || "操作失败，请重试"; }
      finally { revokeBtn.disabled = false; }
    };

    const exportBtn = formEl.querySelector("#acc-export-data");
    if (exportBtn) exportBtn.onclick = async () => {
      const feedback = formEl.querySelector("#acc-export-feedback");
      if (!App.state.serverBacked) {
        feedback.textContent = "演示模式不支持下载真实账号数据";
        return;
      }
      exportBtn.disabled = true;
      feedback.textContent = "正在准备数据导出…";
      try {
        const keys = ["works", "forumTopics", "collections", "studioGenerations", "walletHistory", "notifications"];
        let data = { exportedAt: new Date().toISOString(), items: {} };
        keys.forEach(key => { data.items[key] = []; });
        let page = 0;
        while (page < 1000) {
          feedback.textContent = "正在下载账号资料，第 " + (page + 1) + " 页…";
          const result = await apiJson("/api/account/export?page=" + page);
          if (page === 0) {
            data.profile = result.profile;
            data.wallet = result.wallet;
            data.verifiedEmailAt = result.verifiedEmailAt;
            data.linkedProviders = result.linkedProviders;
            data.note = result.note;
          }
          keys.forEach(key => {
            if (Array.isArray(result[key])) data.items[key].push(...result[key]);
          });
          if (result.nextPage == null) break;
          if (result.nextPage !== page + 1) throw new Error("导出分页异常，请重新尝试");
          page++;
        }
        if (page >= 1000) throw new Error("导出数据超过当前浏览器限制，请联系管理员");
        const blob = new Blob([JSON.stringify(data, null, 2)], {type:"application/json"});
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "handraw-account-" + String(u.username).replace(/[^a-zA-Z0-9_-]/g, "") + ".json";
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 60000);
        feedback.textContent = "账号数据已整理完毕，正在下载，请妥善保管";
      } catch (err) {
        feedback.textContent = err.message || "导出失败，请稍后重试";
      } finally { exportBtn.disabled = false; }
    };

    const profileFeedback = formEl.querySelector("#acc-profile-feedback");
    const saveBtn = formEl.querySelector("#acc-save-btn");
    if (saveBtn) saveBtn.onclick = async () => {
      const bio = formEl.querySelector("#acc-bio").value.trim();
      const payload = { bio };
      saveBtn.disabled = true;
      profileFeedback.textContent = "正在保存个人资料…";
      try {
        if (App.state.serverBacked) {
          const res = await apiJson("/api/auth/profile", { method: "POST", body: payload });
          if (res.boot) applyBootState(res.boot);
        } else {
          u.bio = bio;
          saveState();
        }
        profileFeedback.textContent = "个人资料已保存";
        toast("个人资料已保存");
        if (onSaved) onSaved();
      } catch (err) {
        profileFeedback.textContent = err.message || "保存失败，请重试";
      } finally { saveBtn.disabled = false; }
    };

    const passwordBtn = formEl.querySelector("#acc-password-save");
    if (passwordBtn) passwordBtn.onclick = async () => {
      const oldField = formEl.querySelector("#acc-cur-pw");
      const newField = formEl.querySelector("#acc-new-pw");
      const confirmField = formEl.querySelector("#acc-confirm-pw");
      const status = formEl.querySelector("#acc-password-feedback");
      const currentPassword = oldField.value;
      const newPassword = newField.value;
      if (!currentPassword) {
        status.textContent = "请输入当前密码";
        oldField.focus();
        return;
      }
      if (newPassword.length < 8 || newPassword.length > 128) {
        status.textContent = "新密码需为 8～128 个字符";
        newField.focus();
        return;
      }
      if (newPassword !== confirmField.value) {
        status.textContent = "两次输入的新密码不一致";
        confirmField.focus();
        return;
      }
      if (!App.state.serverBacked) {
        status.textContent = "演示模式不支持修改真实密码";
        return;
      }
      passwordBtn.disabled = true;
      status.textContent = "正在修改密码…";
      try {
        const res = await apiJson("/api/auth/profile", {
          method: "POST", body: { currentPassword, newPassword }
        });
        if (res.boot) applyBootState(res.boot);
        oldField.value = "";
        newField.value = "";
        confirmField.value = "";
        status.textContent = "密码已修改，其他登录设备已退出";
        toast("密码已修改，其他登录设备已退出");
      } catch (err) {
        status.textContent = err.message || "修改密码失败，请重试";
      } finally { passwordBtn.disabled = false; }
    };
  }

  function openAccountSettingsModal() {
    // Account Settings is strictly a standalone page tab inside the Personal Homepage, never a popup modal
    goToAccountPage();
  }

  function openFrontAnnouncementEditorModal() {
    const ann = (App.state && App.state.siteSettings && App.state.siteSettings.announcement) || {};
    let modal = document.getElementById("hw-front-announcement-modal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "hw-front-announcement-modal";
      modal.className = "hw-auth-modal-backdrop";
      document.body.appendChild(modal);
    }
    modal.style.display = "flex";
    modal.innerHTML = `
      <div class="hw-auth-modal" style="max-width:540px;width:90%;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;border-bottom:1px solid var(--paper-line);padding-bottom:10px;">
          <h3 style="margin:0;font-size:17px;font-family:var(--font-display);display:flex;align-items:center;gap:8px;">
            <span>📣</span> <span>全站社区公告前台配置</span>
          </h3>
          <button type="button" class="btn btn-sm" id="hw-btn-close-ann-modal" style="padding:2px 8px;">✕</button>
        </div>
        <div style="display:grid;gap:12px;margin-bottom:18px;">
          <label style="display:flex;align-items:center;gap:8px;font-size:13.5px;cursor:pointer;font-weight:700;">
            <input type="checkbox" id="front-ann-enabled" ${ann.enabled ? "checked" : ""} />
            <span>启用全站顶部社区横幅公告</span>
          </label>
          <div>
            <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:700;">公告正文内容：</label>
            <input class="hw-input" id="front-ann-text" value="${esc(ann.text || "")}" placeholder="例如：Handraw Web 2.0 独立多端全新上线！登录即享画风实测大图与提示词" style="width:100%;box-sizing:border-box;" />
          </div>
          <div>
            <label style="display:block;font-size:12.5px;color:var(--ink-muted);margin-bottom:4px;font-weight:700;">点击跳转链接（可选）：</label>
            <input class="hw-input" id="front-ann-link" value="${esc(ann.link || "")}" placeholder="例如：/forum?id=topic_201 或外部完整URL" style="width:100%;box-sizing:border-box;" />
          </div>
          <div style="font-size:12px;color:var(--ink-muted);background:var(--paper-wash);padding:8px 12px;border-radius:4px;">
            ✦ 运营审查员或超级管理员可在前台随时更新公告，修改后即刻生效并同步至全站所有访问者。
          </div>
        </div>
        <div style="display:flex;gap:10px;justify-content:flex-end;">
          <button type="button" class="btn" id="hw-btn-cancel-ann-modal">取消</button>
          <button type="button" class="btn btn-primary" id="hw-btn-save-ann-modal">💾 保存并立即生效</button>
        </div>
      </div>
    `;

    const close = () => { modal.style.display = "none"; };
    document.getElementById("hw-btn-close-ann-modal").onclick = close;
    document.getElementById("hw-btn-cancel-ann-modal").onclick = close;
    document.getElementById("hw-btn-save-ann-modal").onclick = async () => {
      const enabled = document.getElementById("front-ann-enabled").checked;
      const text = document.getElementById("front-ann-text").value.trim();
      const link = document.getElementById("front-ann-link").value.trim();
      if (enabled && !text) {
        toast("请填写公告正文内容，或取消勾选启用", "warning");
        return;
      }
      try {
        const res = await apiJson("/api/admin/settings", {
          method: "POST",
          body: { section: "announcement", values: { enabled, text, link } },
        });
        if (!res.ok) throw new Error(res.error || "保存失败");
        if (!App.state.siteSettings) App.state.siteSettings = {};
        App.state.siteSettings.announcement = { enabled, text, link };
        toast("全站公告已成功保存并立即生效！", "success");
        close();
        renderChrome();
      } catch (err) {
        toast("保存公告失败：" + (err.message || err), "error");
      }
    };
  }

  async function openFrontReportsModal() {
    let modal = document.getElementById("hw-front-reports-modal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "hw-front-reports-modal";
      modal.className = "hw-auth-modal-backdrop";
      document.body.appendChild(modal);
    }
    modal.style.display = "flex";

    let reports = [];
    try {
      if (App.state && App.state.serverBacked) {
        const res = await apiJson("/api/admin/reports?status=open");
        reports = (res && res.reports) || [];
      }
    } catch (err) {
      console.warn("fetch open reports error:", err);
    }

    const renderReportsStage = () => {
      modal.innerHTML = `
        <div class="hw-auth-modal" style="max-width:680px;width:94%;max-height:85vh;overflow-y:auto;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;border-bottom:1px solid var(--paper-line);padding-bottom:10px;">
            <h3 style="margin:0;font-size:17.5px;font-family:var(--font-display);display:flex;align-items:center;gap:8px;">
              <span>🚨</span> <span>社区违规举报就地处置 (${reports.length})</span>
            </h3>
            <button type="button" class="btn btn-sm" id="hw-btn-close-reports-modal" style="padding:2px 8px;">✕</button>
          </div>

          ${
            reports.length === 0
              ? `<div style="padding:36px;text-align:center;color:var(--ink-muted);background:var(--paper-bg);border-radius:10px;">🎉 当前暂无待处理的违规举报，社区风清气正！</div>`
              : `
                <div style="display:grid;gap:10px;">
                  ${reports
                    .map(
                      (r) => `
                        <div style="background:var(--paper-bg);border:1px solid var(--paper-line);border-radius:10px;padding:12px 14px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
                          <div style="flex:1;min-width:200px;">
                            <div style="display:flex;gap:6px;align-items:center;margin-bottom:4px;flex-wrap:wrap;">
                              <span class="hw-card-code">${esc(r.targetType || "作品")}</span>
                              <strong style="font-size:13.8px;color:var(--ink-strong);">${esc(r.targetTitle || r.targetId)}</strong>
                              <span style="font-size:12px;color:var(--vermilion);font-weight:750;">[${esc(r.reason || "违规")}]</span>
                            </div>
                            <div style="font-size:12px;color:var(--ink-muted);">
                              举报者: @${esc(r.reporter || "社区画友")} · 时间: ${esc(r.createdAt || "刚刚")} · 说明: ${esc(r.details || "无附言")}
                            </div>
                          </div>
                          <div style="display:flex;gap:6px;align-items:center;">
                            <button type="button" class="btn btn-sm btn-primary" data-rep-resolve="${esc(r.id)}">✅ 标记已处理</button>
                            <button type="button" class="btn btn-sm" data-rep-hide="${esc(r.targetId)}" data-rep-type="${esc(r.targetType)}" style="color:var(--vermilion);">🙈 违规下架</button>
                          </div>
                        </div>
                      `
                    )
                    .join("")}
                </div>
              `
          }

          <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;border-top:1px solid var(--paper-line);padding-top:10px;">
            <button type="button" class="btn btn-sm" id="hw-btn-cancel-reports">关闭</button>
          </div>
        </div>
      `;

      const closeReports = () => {
        modal.style.display = "none";
      };
      modal.querySelector("#hw-btn-close-reports-modal").onclick = closeReports;
      modal.querySelector("#hw-btn-cancel-reports").onclick = closeReports;

      modal.querySelectorAll("[data-rep-resolve]").forEach((btn) => {
        btn.onclick = async () => {
          const rid = btn.getAttribute("data-rep-resolve");
          try {
            if (App.state && App.state.serverBacked) {
              await apiJson(`/api/admin/reports/${encodeURIComponent(rid)}/resolve`, { method: "POST", body: {} });
            }
            reports = reports.filter((r) => String(r.id) !== String(rid));
            toast("✅ 举报已标记为已处理！");
            renderReportsStage();
            await refreshFromServer();
          } catch (err) {
            toast(`操作失败：${err.message}`);
          }
        };
      });

      modal.querySelectorAll("[data-rep-hide]").forEach((btn) => {
        btn.onclick = async () => {
          const tid = btn.getAttribute("data-rep-hide");
          const ttype = btn.getAttribute("data-rep-type");
          if (!confirm(`确定要违规下架该内容 [${tid}] 吗？`)) return;
          try {
            if (App.state && App.state.serverBacked) {
              if (ttype === "work" || ttype === "作品") {
                await apiJson(`/api/works/${encodeURIComponent(tid)}/moderate`, { method: "POST", body: { action: "hide" } });
              } else if (ttype === "topic" || ttype === "帖子") {
                await apiJson(`/api/topics/${encodeURIComponent(tid)}/moderate`, { method: "POST", body: { action: "hide" } });
              }
            }
            toast("🙈 违规内容已下架隐藏！");
            await refreshFromServer();
          } catch (err) {
            toast(`下架失败：${err.message}`);
          }
        };
      });
    };

    renderReportsStage();
  }

  async function openFrontRedeemCodesModal() {
    let modal = document.getElementById("hw-front-redeem-modal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "hw-front-redeem-modal";
      modal.className = "hw-auth-modal-backdrop";
      document.body.appendChild(modal);
    }
    modal.style.display = "flex";

    let codes = [];
    try {
      if (App.state && App.state.serverBacked) {
        const res = await apiJson("/api/admin/redeem-codes");
        codes = (res && res.codes) || [];
      }
    } catch (err) {
      console.warn("fetch redeem codes error:", err);
    }

    const renderRedeemStage = () => {
      modal.innerHTML = `
        <div class="hw-auth-modal" style="max-width:650px;width:94%;max-height:85vh;overflow-y:auto;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;border-bottom:1px solid var(--paper-line);padding-bottom:10px;">
            <h3 style="margin:0;font-size:17.5px;font-family:var(--font-display);display:flex;align-items:center;gap:8px;">
              <span>🎟️</span> <span>运营兑换码快速发放与管理</span>
            </h3>
            <button type="button" class="btn btn-sm" id="hw-btn-close-codes-modal" style="padding:2px 8px;">✕</button>
          </div>

          <div style="background:var(--paper-bg);border:1px solid var(--paper-line);border-radius:10px;padding:12px 14px;margin-bottom:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
            <input type="text" class="hw-input" id="front-modal-code-input" placeholder="兑换券码 (例: SPRING2026)" style="flex:2;min-width:140px;" />
            <input type="number" class="hw-input" id="front-modal-code-credits" placeholder="积分面额" value="50" style="flex:1;min-width:80px;" />
            <input type="number" class="hw-input" id="front-modal-code-max" placeholder="最大次数" value="100" style="flex:1;min-width:80px;" />
            <button type="button" class="btn btn-primary" id="front-modal-btn-create-code" style="white-space:nowrap;">✨ 生成兑换码</button>
          </div>

          <div style="overflow-x:auto;">
            <table class="table" style="width:100%;font-size:12.8px;">
              <thead>
                <tr>
                  <th>券码</th>
                  <th>面额</th>
                  <th>进度</th>
                  <th>创建者</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                ${
                  codes.length === 0
                    ? `<tr><td colspan="6" style="text-align:center;color:var(--ink-muted);padding:20px;">暂无兑换券码，可在上方快速生成</td></tr>`
                    : codes
                        .map(
                          (c) => `
                            <tr>
                              <td><code>${esc(c.code)}</code></td>
                              <td><strong>${c.credits}✦</strong></td>
                              <td>${c.usedCount || 0} / ${c.maxUses || "∞"}</td>
                              <td>@${esc(c.createdBy || "系统")}</td>
                              <td><span class="hw-pill" style="font-size:11px;">${c.status === "active" ? "✅ 生效中" : "⏸️ 已停用"}</span></td>
                              <td>
                                <button type="button" class="btn btn-sm" data-code-toggle="${esc(c.code)}" data-code-status="${esc(c.status)}">
                                  ${c.status === "active" ? "⏸️ 停用" : "▶️ 启用"}
                                </button>
                              </td>
                            </tr>
                          `
                        )
                        .join("")
                }
              </tbody>
            </table>
          </div>

          <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;border-top:1px solid var(--paper-line);padding-top:10px;">
            <button type="button" class="btn btn-sm" id="hw-btn-cancel-codes">关闭</button>
          </div>
        </div>
      `;

      const closeCodes = () => {
        modal.style.display = "none";
      };
      modal.querySelector("#hw-btn-close-codes-modal").onclick = closeCodes;
      modal.querySelector("#hw-btn-cancel-codes").onclick = closeCodes;

      const createBtn = modal.querySelector("#front-modal-btn-create-code");
      if (createBtn) {
        createBtn.onclick = async () => {
          const codeVal = modal.querySelector("#front-modal-code-input").value.trim().toUpperCase();
          const credVal = parseInt(modal.querySelector("#front-modal-code-credits").value, 10);
          const maxVal = parseInt(modal.querySelector("#front-modal-code-max").value, 10);
          if (!codeVal) {
            toast("请输入兑换券码");
            return;
          }
          try {
            if (App.state && App.state.serverBacked) {
              await apiJson("/api/admin/redeem-codes", {
                method: "POST",
                body: { code: codeVal, credits: credVal || 50, maxUses: maxVal || 100 }
              });
              const res = await apiJson("/api/admin/redeem-codes");
              codes = (res && res.codes) || [];
            }
            toast(`✨ 兑换码 ${codeVal} 已生成成功！`);
            renderRedeemStage();
          } catch (err) {
            toast(`生成失败：${err.message}`);
          }
        };
      }

      modal.querySelectorAll("[data-code-toggle]").forEach((btn) => {
        btn.onclick = async () => {
          const code = btn.getAttribute("data-code-toggle");
          const curStatus = btn.getAttribute("data-code-status");
          const nextStatus = curStatus === "active" ? "paused" : "active";
          try {
            if (App.state && App.state.serverBacked) {
              await apiJson(`/api/admin/redeem-codes/${encodeURIComponent(code)}`, {
                method: "PATCH",
                body: { status: nextStatus }
              });
              const res = await apiJson("/api/admin/redeem-codes");
              codes = (res && res.codes) || [];
            }
            toast(`兑换码状态已切换为 ${nextStatus}！`);
            renderRedeemStage();
          } catch (err) {
            toast(`操作失败：${err.message}`);
          }
        };
      });
    };

    renderRedeemStage();
  }

  function renderMasonry(cardHtmlList, density = "standard") {
    const colCount = density === "compact" ? 8 : density === "large" ? 3 : 5;
    const cols = Array.from({ length: colCount }, () => []);
    cardHtmlList.forEach((html, idx) => {
      cols[idx % colCount].push(html);
    });
    return `<div class="hw-waterfall density-${esc(density)}">${cols
      .map((c) => `<div class="hw-wf-col">${c.join("")}</div>`)
      .join("")}</div>`;
  }

  const KNOWN_SKILL_INSTRUCTION_RE = /【\s*如果主题直白包含画面元素那就按主题出图[，,]\s*文案由你来升华[，,]\s*但是不要直接描述画面[。.]\s*如果主题比较概念化[，,]\s*那么文案和主题尽量保持一致[，,]\s*如果文案较长由你提炼[，,]\s*由你先设计画面隐喻[（(]人类和非人类都行[）)]\s*再出图\s*[。.]\s*文字参与构图[，,]\s*图文一体\s*】/g;

  function filterDisplayPrompt(text) {
    if (!text || typeof text !== "string") return "";
    return text.replace(KNOWN_SKILL_INSTRUCTION_RE, "").replace(/\n{3,}/g, "\n\n").trim();
  }

  const PLACEHOLDER_TOPIC_TITLES = [
    "图文模式",
    "纯图模式",
    "纯图",
    "生成结果",
    "当前工作流",
    "未命名",
    "无标题",
    "默认草稿",
    "画布创作",
    "云端生图",
    "生图结果",
    "图片展示",
    "作品展示"
  ];

  function validateTopicTitle(title) {
    const raw = String(title || "").trim();
    const nonWs = raw.replace(/\s+/g, "");
    if (nonWs.length < 4) {
      return "帖子标题至少需要 4 个非空白字符";
    }

    const strippedPlaceholder = raw.replace(/[\s\-_+|｜·#/\\#()（）\[\]【】\d+＋]+/g, "");
    for (let i = 0; i < PLACEHOLDER_TOPIC_TITLES.length; i++) {
      const p = PLACEHOLDER_TOPIC_TITLES[i];
      if (raw === p || nonWs === p || strippedPlaceholder === p) {
        return "标题不能使用默认占位词，请填写具体的主题或说明";
      }
    }

    const residual = raw.replace(/(?:USR-)?[A-Z]{1,4}-[A-Z0-9]+/gi, "");
    const residualMeaningful = residual.replace(/[\s\-_+|｜·#/\\#()（）\[\]【】\d+＋]+/g, "");
    if (!residualMeaningful) {
      return "标题不能仅由编号组成，请添加具体的主题或说明";
    }

    return "";
  }

  window.HANDRAW_SHARED = {
    filterDisplayPrompt,
    PLACEHOLDER_TOPIC_TITLES,
    validateTopicTitle,
    App,
    STYLE_GROUPS,
    LAYOUT_GROUPS,
    SAMPLE_UPLOAD_IMAGES,
    CREATOR_HONOR_TIERS,
    RANK_PERIODS,
    esc,
    safeHref,
    safeMediaUrl,
    stripHtmlToSnippet,
    normalizeTopicImages,
    resourceLabel,
    resourceSearchText,
    resourceMatchesGroup,
    resourceGroupLabel,
    visibleResourceGroups,
    toast,
    apiJson,
    channelUrl,
    renderMasonry,
    renderChrome,
    initApp,
    saveState,
    refreshFromServer,
    applyBootState,
    resetDemoState,
    performServerCheckin,
    sandboxSwitchPersona,
    addLedger,
    isCollected,
    toggleCollect,
    isLiked,
    getLikeCount,
    getFavoriteCount,
    toggleLike,
    updateSocialDom,
    dispatchSocialUpdate,
    syncTopbarCollectionsBadge,
    syncWalletCredits,
    getAssetComments,
    submitAssetComment,
    getBoardModerators,
    getUserModeratorBadges,
    canModerateForumBoard,
    isUnlocked,
    unlockWithCredits,
    getAssetWorks,
    getAssetWorkCount,
    getAssetTopics,
    groupShortLabel,
    getCreatorHonorTier,
    isFreshRelease,
    getRecencyMinutes,
    isWithinRankPeriod,
    compareByRecency,
    getCreatorStatsMap,
    getCreatorProfile,
    getTopCreators,
    popularScore,
    getWorkCompositeScore,
    getRankedWorks,
    getRankedAssets,
    getStampCount,
    isCheered,
    toggleCheerItem,
    sendEncourageTip,
    openTipModal,
    goToCreatorProfile,
    goToAccountPage,
    goToAssetPage,
    goToWorkPage,
    goToTopicPage,
    goToSkillPage,
    mountAuthPassStage,
    renderInlineSharePanelHtml,
    bindInlineSharePanel,
    renderInlineReportPanelHtml,
    bindInlineReportPanel,
    renderAccountSettingsFormHtml,
    bindAccountSettingsForm,
    creatorAvatarHtml,
    openCreatorProfileModal,
    openModal,
    closeModal,
    openLoginModal,
    openSharePosterModal,
    openReportModal,
    openAssetPickerModal,
    openSharedCardPickerModal,
    goToForumCompose,
    goToCurationShare,
    openQuickPublishModal,
    openAccountSettingsModal,
    openFrontAnnouncementEditorModal,
    openFrontReportsModal,
    openFrontRedeemCodesModal,
    isStaff,
    isAdmin,
    canManageGlobal,
    canDeleteTopic,
    canDeleteReply,
    canDeleteWork,
    canModerateWork,
    canDeleteComment,
    deleteArticle
  };

  window.deleteArticle = deleteArticle;

  if (!window.Handraw) window.Handraw = {};
  window.Handraw.openFrontAnnouncementEditorModal = openFrontAnnouncementEditorModal;
  window.Handraw.openFrontReportsModal = openFrontReportsModal;
  window.Handraw.openFrontRedeemCodesModal = openFrontRedeemCodesModal;
})();
