/* Handraw Infinite Canvas Engine v4 — Unified Input/Output Node Architecture & Prompt Assembler
 *
 * Node Taxonomy:
 *   [输入节点 Input Nodes]
 *     1. skill_params ("风格参数"): 画风(支持画面融合双画风) / 图型 / 主题色(可多选) / 影调(可多选) / 情绪(可多选) / 留白 / 受众 / 业务场景
 *     2. asset        ("资产"):     图参输入（角色 / 道具 / 场景 / 其他 / 用户自建分类 / 本地上传图片，支持单选或多选）
 *     3. text_input   ("文本输入"): 提示词或长文正文输入（内置本地 .md / .txt 文件选择附带）
 *
 *   [输出节点 Output Nodes]
 *     4. output_control ("输出控制"): 创作模式（图文 / 纯图 / 海报 / 文章封面 / 文章配图 / 小红书组图，已移除摄影模式）、张数、比例、生成触发
 *     5. output_display ("输出显示"): 点击生成后自动在最右侧创建；重复点击生成时原地刷新图片与交付文件；历史版本归档至「历史记录」
 */
(function () {
  const COLOR_FAMILIES = [
    { key: "ALL", label: "全部配色", range: [1, 36] },
    { key: "blue", label: "经典蓝系", range: [1, 6] },
    { key: "green", label: "清新绿系", range: [7, 12] },
    { key: "red", label: "古典红绿", range: [13, 18] },
    { key: "purple", label: "浪漫粉紫", range: [19, 24] },
    { key: "warm", label: "暖阳大地", range: [25, 30] },
    { key: "neutral", label: "中性色系", range: [31, 36] }
  ];

  const TONE_FAMILIES = [
    { key: "ALL", label: "全部影调" },
    { key: "key", label: "明暗阶调" },
    { key: "contrast", label: "反差过渡" },
    { key: "atmosphere", label: "氛围风格" }
  ];

  const SC021_PLAYSTYLES = [
    "视线锚点跨界续绘型",
    "撕纸裂变第二世界型",
    "情绪镜像现实内心型",
    "跨时空前世今生型",
    "局部放大显微故事型",
    "手帐拍立得拼贴型",
    "多格情绪胶片叙事型"
  ];

  const WHITESPACE_OPTIONS = [
    { value: "", label: "不限", promptZh: "", promptEn: "" },
    { value: "normal", label: "正常", promptZh: "", promptEn: "" },
    { value: "moderate", label: "适中留白", promptZh: "【大量留白】", promptEn: "[Generous negative space]" },
    {
      value: "high",
      label: "大量留白",
      promptZh: "【大量留白，场景只显示必要部分，不要显示全】",
      promptEn: "[Extensive negative space: show only essential scene elements, do not render the full background]"
    }
  ];

  // Photography mode ("photo") excluded; "文章封面" + "文章插图" unified into "文章配图" (article-illust)
  const OUTPUT_MODES = [
    { id: "graphic-text", icon: "", label: "图文模式", desc: "社媒图文卡 / 知识信息图", defaultRatio: "3:4" },
    { id: "pure", icon: "", label: "纯图模式", desc: "纯画面叙事，不含说明杂字", defaultRatio: "3:4" },
    { id: "poster", icon: "", label: "海报模式", desc: "主副标题视觉海报 / 展架", defaultRatio: "9:16" },
    { id: "article-illust", icon: "", label: "文章配图", desc: "统一生成文章封面与各章节配图方案，支持宽屏拖拽与生图", defaultRatio: "4:3" },
    { id: "series", icon: "", label: "套图", desc: "自由设定张数，成套生成连贯系列图", defaultRatio: "3:4" }
  ];

  const LOOP_MODES = [
    { id: "prompts", icon: "", label: "多文案", desc: "每行一条主题或文案，逐条批量出图" },
    { id: "styles", icon: "", label: "多画风", desc: "固定主题与构图，遍历多款画风横评出图" },
    { id: "layouts", icon: "", label: "多图型", desc: "固定主题与画风，遍历多款图型版式出图" },
    { id: "assets", icon: "", label: "多图参", desc: "逐张遍历上游图片参数中的参考图批量出图" }
  ];

  const DEFAULT_LOOP_PROMPT_LINES = [
    "春分 · 龙井新茶与青团手绘节气卡",
    "夏至 · 冰镇杨梅饮与竹编团扇海报",
    "秋分 · 桂花乌龙慢煮手账插画",
    "冬至 · 围炉煮茶与柿子红泥小火炉"
  ];

  const FISSION_STRATEGIES = [
    { id: "daily_quote", icon: "", label: "系列日签", desc: "按日常情绪与生活切片扩写连续日签文案" },
    { id: "selling_points", icon: "", label: "卖点切角", desc: "围绕产品痛点、成分、场景与礼赠多维种草" },
    { id: "knowledge_cards", icon: "", label: "科普图鉴", desc: "把知识母题拆解为概念、原理、步骤与避坑图卡" },
    { id: "story_beats", icon: "", label: "连续分镜", desc: "按起承转合与时间推移生成连续叙事画面" }
  ];

  function generateFissionTopics(seedTopic = "", strategy = "daily_quote", count = 10, customStrategy = "") {
    const safeCount = Math.max(1, Math.min(200, Math.round(Number(count) || 10)));
    const cleanSeed = String(seedTopic || "都市青年反内卷治愈手绘日签").trim() || "都市青年反内卷治愈手绘日签";
    const shortSeed = cleanSeed.replace(/[。！!？?\n]+.*$/, "").slice(0, 22);
    const cleanCustom = String(customStrategy || "").trim();

    const banks = {
      daily_quote: {
        hooks: [
          "早八重启时刻：一杯热美式蒸汽里的微小秩序感",
          "准点下班看到的橘子海晚霞与单车后座微风",
          "允许自己今天只完成三件小事的留白哲学",
          "周末雨天窝在窗边翻完半本旧诗集的松弛午后",
          "把焦虑写进手账格子里再轻轻划掉的释然",
          "傍晚散步路过面包房闻到黄油麦香的治愈瞬间",
          "关掉消息免打扰后独享两小时慢煮乌龙茶",
          "办公桌角落新冒出一片嫩叶的绿萝生命力",
          "深夜台灯下用钢笔速写记录今天的小确幸",
          "不赶时间的周日菜市场人间烟火气巡礼",
          "在地铁摇晃车厢里戴上耳机进入自己的小宇宙",
          "立秋第一阵凉风吹过梧桐树梢的呼吸感"
        ],
        details: [
          "暖米宣纸底纹配松烟墨线",
          "水彩晕染光影与大量呼吸留白",
          "朱砂红印章点睛与手写感批注",
          "桑贝式微缩小人与开阔街景对比",
          "桌面俯拍手账拼贴与胶带肌理",
          "柔和暖黄台灯光晕与植物剪影"
        ]
      },
      selling_points: {
        hooks: [
          "核心痛点共鸣：为什么你试过很多方案依然容易半途而废",
          "原材溯源特写：看得见的天然肌理与严苛选材标准",
          "三秒极速上手：把繁琐步骤浓缩成随时随地的轻盈体验",
          "早八通勤场景：塞进随身托特包里的全天候能量补给",
          "下午茶搭档：0负担轻盈配方与精致办公桌美学",
          "细节控放大镜：包装触感、环保棉纸与东方器物巧思",
          "真实口碑切片：老客无限回购的三个高频心动瞬间",
          "横向对比图解：一眼看懂与传统普通方案的本质差异",
          "四季百搭指南：冷热双泡与不同生活节奏的灵感搭配",
          "节日伴手礼盒：体面又有温度的东方手绘礼赠仪式感"
        ],
        details: [
          "左右分栏卖点对照排版",
          "手绘放大镜细节标注箭头",
          "高颜值生活场景种草构图",
          "信息图步骤拆解与重点高亮",
          "温暖纸本底色突出产品主体"
        ]
      },
      knowledge_cards: {
        hooks: [
          "一图读懂底层核心概念：抛开晦涩术语看本质逻辑",
          "新手最容易踩的三大认知误区与纠偏指南",
          "黄金四步实操SOP：从零起步也能稳稳落地的路径",
          "关键参数对照表：不同阶段与场景下的最优配置区间",
          "经典正反案例拆解：高手做对了哪一个微小动作",
          "工具箱全景清单：提升十倍效率的必备器物与方法",
          "进阶跃迁心法：突破瓶颈期的结构化复盘框架",
          "常见疑难急诊室：遇到卡点时的三分钟自查流程图",
          "长期主义复利曲线：每天坚持十五分钟的半年变化",
          "全景知识脑图总结：一页收藏随时翻阅的行动卡片"
        ],
        details: [
          "手绘思维导图与清晰编号层级",
          "墨线流程图配暖色重点圈注",
          "图鉴式标本排列与简洁批注",
          "对比象限矩阵与视觉隐喻插画"
        ]
      },
      story_beats: {
        hooks: [
          "序幕开篇：清晨推开木门迎接第一缕阳光的期待",
          "偶遇插曲：街角屋檐下躲雨时遇见神秘同伴",
          "小小挑战：面对杂乱线索静下心来逐一梳理",
          "灵感闪现：翻开泛黄笔记本找到关键解谜钥匙",
          "并肩行动：分工协作把脑海构想一点点搭成现实",
          "转折微光：暮色四合时点亮温暖灯火迎来转机",
          "高光时刻：作品悄然绽放引来邻里驻足微笑",
          "余韵收尾：星空下围炉夜话珍藏这段奇妙旅程"
        ],
        details: [
          "电影感宽画幅叙事构图",
          "统一主角神态与连续光影推移",
          "绘本水彩笔触与细腻环境道具",
          "前后景深层次与情绪留白"
        ]
      }
    };

    const customAngles = [
      "切角一 · 反常识开篇提问与核心悬念",
      "切角二 · 高频真实痛点场景还原",
      "切角三 · 关键细节拆解与直观对照",
      "切角四 · 三步实操方法与避坑提醒",
      "切角五 · 情绪共鸣金句与生活切片",
      "切角六 · 前后状态反转对比特写",
      "切角七 · 进阶玩法灵感与器物搭配",
      "切角八 · 读者高频疑问一图直答",
      "切角九 · 长期复利变化与仪式感记录",
      "切角十 · 总结收藏清单与行动呼唤"
    ];

    if (cleanCustom) {
      const detPool = banks.daily_quote.details.concat(banks.knowledge_cards.details);
      const outCustom = [];
      for (let i = 0; i < safeCount; i++) {
        const numStr = String(i + 1).padStart(safeCount >= 100 ? 3 : 2, "0");
        const angle = customAngles[i % customAngles.length];
        const det = detPool[(i * 3 + Math.floor(i / customAngles.length)) % detPool.length];
        const cycleRound = Math.floor(i / customAngles.length);
        const suffix = cycleRound > 0 ? `（系列拓展 · 卷${cycleRound + 1}）` : "";
        outCustom.push(`#${numStr} 【${shortSeed}｜${cleanCustom}】${angle}${suffix}｜${det}`);
      }
      return outCustom;
    }

    const pack = banks[strategy] || banks.daily_quote;
    const out = [];
    for (let i = 0; i < safeCount; i++) {
      const numStr = String(i + 1).padStart(safeCount >= 100 ? 3 : 2, "0");
      const hook = pack.hooks[i % pack.hooks.length];
      const det = pack.details[(i * 3 + Math.floor(i / pack.hooks.length)) % pack.details.length];
      const cycleRound = Math.floor(i / pack.hooks.length);
      const variantSuffix =
        cycleRound === 0
          ? ""
          : cycleRound % 3 === 1
            ? "（晨间暖光视角）"
            : cycleRound % 3 === 2
              ? "（暮色街角特写）"
              : `（四季风物变奏 · 卷${cycleRound}）`;
      out.push(`#${numStr} 【${shortSeed}】${hook}${variantSuffix}｜${det}`);
    }
    return out;
  }

  const PRESET_WORKFLOW_DEFS = [
    {
      id: "preset_v24_single",
      blueprint: "single",
      title: "节气海报极速出图",
      scenarioBadge: "日常单图 · 3节点",
      scenarioDesc: "最常用的日常海报/图文工作流：仅用「风格参数 + 文本参数 → 生成设置」3 个核心节点，零冗余极速出图。"
    },
    {
      id: "preset_v24_loop100",
      blueprint: "loop_100",
      title: "百图矩阵批量生产（1母题→100张）",
      scenarioBadge: "百图批量 · 4节点",
      scenarioDesc: "演示如何输出 100 张图而不建 100 个节点：「AI 扩写主题」从 1 个母题生成 100 条日签 →「批量」驱动仅 1 个「生成设置」，结果自动收敛进 1 个分页「批量图集」节点。"
    },
    {
      id: "preset_v24_style_ab",
      blueprint: "style_ab",
      title: "同文案多画风横评比稿",
      scenarioBadge: "提案选风 · 3节点",
      scenarioDesc: "定好一句主文案，无需单独连风格参数，直接用「批量（多画风模式）」一次横评 4 款手绘风格快速定稿。"
    },
    {
      id: "preset_v24_ip_story",
      blueprint: "ip_story",
      title: "IP角色连续故事绘本",
      scenarioBadge: "角色一致性 · 4节点",
      scenarioDesc: "通过「图片参数」锁定原创角色与道具外观一致性，配合「套图模式」一次生成 4 幕连续故事分镜。"
    },
    {
      id: "preset_v24_omnimedia",
      blueprint: "omnimedia",
      title: "全媒体一稿三端宣发包",
      scenarioBadge: "多尺寸一分多 · 6节点",
      scenarioDesc: "新品发布标准链路：一套视觉与卖点经「多尺寸输出」同时分发给 3 个不同规格生成设置（2.35:1 公众号头图 + 3:4 种草套图 + 9:16 竖版海报）。"
    },
    {
      id: "preset_v24_article",
      blueprint: "article",
      title: "深度长文自动配图与排版",
      scenarioBadge: "专栏配图 · .md交付",
      scenarioDesc: "「文本参数」挂载 Markdown 长文，「生成设置」设为文章配图，自动拆解章节生成封面与正文插图并支持打包下载 ZIP。"
    },
    {
      id: "preset_v24_fusion",
      blueprint: "fusion",
      title: "跨媒介双画风融合实验",
      scenarioBadge: "双风碰撞 · 3节点",
      scenarioDesc: "开启「风格参数」双画风融合开关：主体采用手作插画肌理，场景环境采用纪实胶片/水墨山水，打造高辨识度跨次元视觉。"
    }
  ];

  const DEFAULT_MODE_RATIOS = {
    pure: "3:4",
    "graphic-text": "3:4",
    poster: "9:16",
    "article-illust": "4:3",
    series: "3:4"
  };

  const RATIO_PRESETS = ["3:4", "1:1", "4:3", "16:9", "9:16", "2.35:1"];

  // 受众与业务场景不设内置预置值，仅当用户填写过时由前端展示最近使用的最多 8 个选项
  const AUDIENCE_SUGGESTIONS = [];

  const BUSINESS_SCENE_SUGGESTIONS = [];

  const DEFAULT_MOOD_POOL = [
    "诗意",
    "治愈",
    "松弛",
    "温暖",
    "复古",
    "活力",
    "克制",
    "叙事感",
    "幽默",
    "烟火气",
    "哲思",
    "静谧"
  ];

  let _uidSeq = 200;
  function uid(prefix) {
    _uidSeq += 1;
    return `${prefix}_${Date.now().toString(36)}_${_uidSeq}`;
  }

  function colorMatchesFamily(colorId, familyKey) {
    if (!familyKey || familyKey === "ALL") return true;
    const m = /^C-(\d+)$/i.exec(String(colorId || "").trim());
    if (!m) return true;
    const num = Number(m[1]);
    const fam = COLOR_FAMILIES.find((f) => f.key === familyKey);
    if (!fam) return true;
    return num >= fam.range[0] && num <= fam.range[1];
  }

  /* ======================== CLEAN V4 NODE CONSTRUCTORS ======================== */

  function makeSkillParamsNode(x = 80, y = 72, overrides = {}) {
    return {
      id: overrides.id || uid("sp"),
      type: "skill_params",
      title: overrides.title || "风格参数",
      x,
      y,
      w: 336,
      h: 468,
      groupId: null,
      data: {
        fusion: Boolean(overrides.fusion),
        style1: overrides.style1 || "",
        style2: overrides.style2 || "",
        layout: overrides.layout || "",
        sc021Type: overrides.sc021Type || SC021_PLAYSTYLES[1],
        sc022Name: overrides.sc022Name || "林知夏",
        sc022Pinyin: overrides.sc022Pinyin || "LIN ZHIXIA",
        sc022Bg: overrides.sc022Bg || "深钴蓝",
        colors: Array.isArray(overrides.colors) ? [...overrides.colors] : overrides.color ? [overrides.color] : [],
        tones: Array.isArray(overrides.tones) ? [...overrides.tones] : overrides.tone ? [overrides.tone] : [],
        moods: Array.isArray(overrides.moods) ? [...overrides.moods] : overrides.mood ? [overrides.mood] : [],
        customMood: overrides.customMood || "",
        whitespace: overrides.whitespace ?? "",
        audience: overrides.audience || "",
        businessScene: overrides.businessScene || ""
      }
    };
  }

  function makeAssetNode(x = 80, y = 516, overrides = {}) {
    const items = Array.isArray(overrides.items) ? [...overrides.items] : [];
    if (!items.length && (overrides.refId || overrides.image)) {
      items.push({
        id: overrides.refId || uid("ast_item"),
        name: overrides.name || "参考图参",
        image: overrides.image || "",
        cat: overrides.cat || "other",
        catLabel: overrides.catLabel || "",
        custom: Boolean(overrides.custom)
      });
    }
    return {
      id: overrides.id || uid("ast"),
      type: "asset",
      title: overrides.title || "图片参数",
      x,
      y,
      w: 288,
      h: 206,
      groupId: null,
      data: {
        items
      }
    };
  }

  function makeTextInputNode(x = 80, y = 516, overrides = {}) {
    return {
      id: overrides.id || uid("txt"),
      type: "text_input",
      title: overrides.title || "文本参数",
      x,
      y,
      w: 336,
      h: 256,
      groupId: null,
      data: {
        text: overrides.text || "",
        fileName: overrides.fileName || "",
        fileContent: overrides.fileContent || "",
        fileSize: overrides.fileSize || 0,
        autoSpawned: Boolean(overrides.autoSpawned)
      }
    };
  }

  function makeBridgeNode(x = 468, y = 256, overrides = {}) {
    return {
      id: overrides.id || uid("brg"),
      type: "bridge",
      title: overrides.title || "桥接",
      x,
      y,
      w: 248,
      h: 168,
      groupId: null,
      data: {
        note: overrides.note || ""
      }
    };
  }

  function makeFissionNode(x = 64, y = 516, overrides = {}) {
    const validStrats = new Set(FISSION_STRATEGIES.map((s) => s.id));
    const strategy = validStrats.has(overrides.strategy) ? overrides.strategy : "daily_quote";
    const customStrategy = typeof overrides.customStrategy === "string" ? overrides.customStrategy.trim() : "";
    const seedTopic =
      typeof overrides.seedTopic === "string"
        ? overrides.seedTopic
        : "打工人反内卷治愈手绘日签";
    const targetCount = Math.max(1, Math.min(200, Math.round(Number(overrides.targetCount ?? overrides.count) || 10)));
    const generatedItems =
      Array.isArray(overrides.generatedItems) && overrides.generatedItems.length
        ? [...overrides.generatedItems]
        : generateFissionTopics(seedTopic, strategy, targetCount, customStrategy);

    return {
      id: overrides.id || uid("fis"),
      type: "fission",
      title: overrides.title || "选题裂变",
      x,
      y,
      w: 336,
      h: 320,
      groupId: null,
      data: {
        seedTopic,
        strategy,
        customStrategy,
        targetCount,
        generatedItems
      }
    };
  }

  function makeLoopNode(x = 468, y = 196, overrides = {}) {
    const validModes = new Set(["prompts", "styles", "layouts", "assets"]);
    const loopMode = validModes.has(overrides.loopMode) ? overrides.loopMode : "prompts";
    let promptListText = "";
    if (typeof overrides.promptListText === "string") {
      promptListText = overrides.promptListText;
    } else if (Array.isArray(overrides.promptItems)) {
      promptListText = overrides.promptItems.join("\n");
    } else {
      promptListText = DEFAULT_LOOP_PROMPT_LINES.slice(0, 3).join("\n");
    }
    return {
      id: overrides.id || uid("loop"),
      type: "loop",
      title: overrides.title || "循环批量",
      x,
      y,
      w: 336,
      h: 320,
      groupId: null,
      data: {
        loopMode,
        promptListText,
        styleIds: Array.isArray(overrides.styleIds) ? [...overrides.styleIds] : [],
        layoutIds: Array.isArray(overrides.layoutIds) ? [...overrides.layoutIds] : [],
        batchLayoutMode: overrides.batchLayoutMode || "fixed",
        batchSeed: overrides.batchSeed != null ? overrides.batchSeed : "",
        batchCount: Math.max(1, Math.min(20, Math.round(Number(overrides.batchCount) || 6))),
        batchLayoutReq: overrides.batchLayoutReq || "",
        batchRows: Array.isArray(overrides.batchRows) ? [...overrides.batchRows] : (overrides.batchRows || null),
        splitUpstreamText: overrides.splitUpstreamText !== false,
        maxIterations: Math.max(1, Math.min(200, Math.round(Number(overrides.maxIterations) || 200))),
        status: "idle",
        currentStep: 0,
        totalSteps: 0
      }
    };
  }

  function makeOutputControlNode(x = 512, y = 140, overrides = {}) {
    const rawM =
      overrides.mode === "xhs-batch"
        ? "series"
        : overrides.mode === "article-cover"
          ? "article-illust"
          : overrides.mode;
    const mode = rawM && rawM !== "photo" ? rawM : "graphic-text";
    const ratio = overrides.ratio || DEFAULT_MODE_RATIOS[mode] || "3:4";
    const defaultCount = mode === "series" ? 4 : 1;
    return {
      id: overrides.id || uid("ctrl"),
      type: "output_control",
      title: overrides.title || "输出控制",
      x,
      y,
      w: 344,
      h: 348,
      groupId: null,
      data: {
        mode,
        count: Math.max(1, Math.min(200, Math.round(Number(overrides.count) || defaultCount))),
        ratio,
        coverRatio: overrides.coverRatio || "2.35:1",
        inlineRatio: overrides.inlineRatio || "4:3",
        includeCover: overrides.includeCover !== false,
        mixLayouts: overrides.mixLayouts !== false,
        inlineTheme: overrides.inlineTheme || "",
        status: "idle",
        elapsedSec: 0
      }
    };
  }

  function makeArticlePlanNode(x = 936, y = 112, overrides = {}) {
    const cards = Array.isArray(overrides.cards) ? overrides.cards.map((c) => ({ ...c })) : [];
    return {
      id: overrides.id || uid("aplan"),
      type: "article_plan",
      title: overrides.title || "文章配图方案",
      x,
      y,
      w: 392,
      h: 368,
      groupId: null,
      data: {
        status: overrides.status || "ready",
        sourceControlId: overrides.sourceControlId || "",
        articleTitle: overrides.articleTitle || "文章配图方案",
        markdown: overrides.markdown || "",
        cards,
        updatedAt: overrides.updatedAt || "",
        runCount: overrides.runCount || 0,
        elapsedSec: 0
      }
    };
  }

  function makeOutputDisplayNode(x = 948, y = 112, overrides = {}) {
    const items = Array.isArray(overrides.items) ? overrides.items.slice(0, 1) : [];
    return {
      id: overrides.id || uid("disp"),
      type: "output_display",
      title: overrides.title || "图片显示",
      x,
      y,
      w: overrides.w || 308,
      h: overrides.h || 308,
      groupId: null,
      data: {
        status: overrides.status || (items.length ? "done" : "idle"),
        mode: overrides.mode || "graphic-text",
        kind: "single",
        slotIndex: typeof overrides.slotIndex === "number" ? overrides.slotIndex : 0,
        planCardId: overrides.planCardId || "",
        sourceNodeId: overrides.sourceNodeId || "",
        updatedAt: overrides.updatedAt || "",
        runCount: overrides.runCount || (items.length ? 1 : 0),
        markdown: overrides.markdown || "",
        items,
        activeIdx: 0,
        elapsedSec: 0
      }
    };
  }

  /* ======================== UPSTREAM RESOLUTION & BRIDGE FAN-OUT ======================== */

  function expandUpstreamNodes(graph, targetNodeId) {
    const nodes = graph.nodes || [];
    const edges = graph.edges || [];
    const result = [];
    const seenLeaves = new Set();
    const visitedHubs = new Set([targetNodeId]);
    const queue = [{ toId: targetNodeId, viaBridgeId: null }];

    while (queue.length > 0) {
      const { toId, viaBridgeId } = queue.shift();
      const incoming = edges.filter((e) => e.to === toId);

      for (const edge of incoming) {
        const src = nodes.find((n) => n.id === edge.from);
        if (!src) continue;

        if (src.type === "bridge") {
          if (!visitedHubs.has(src.id)) {
            visitedHubs.add(src.id);
            queue.push({ toId: src.id, viaBridgeId: src.id });
          }
        } else if (src.type === "loop" || src.type === "fission") {
          if (!seenLeaves.has(src.id)) {
            seenLeaves.add(src.id);
            result.push({ node: src, edgeId: edge.id, viaBridgeId });
          }
          if (!visitedHubs.has(src.id)) {
            visitedHubs.add(src.id);
            queue.push({ toId: src.id, viaBridgeId: viaBridgeId || src.id });
          }
        } else if (src.type === "group") {
          const children = nodes.filter((c) => c.groupId === src.id && c.id !== targetNodeId);
          for (const ch of children) {
            if (!seenLeaves.has(ch.id)) {
              seenLeaves.add(ch.id);
              result.push({ node: ch, edgeId: edge.id, viaBridgeId });
            }
          }
        } else if (!seenLeaves.has(src.id)) {
          seenLeaves.add(src.id);
          result.push({ node: src, edgeId: edge.id, viaBridgeId });
        }
      }
    }
    return result;
  }

  function resolveControlRecipe(graph, ctrlNode, catalog) {
    const cd = (ctrlNode && ctrlNode.data) || {};
    const upstream = ctrlNode ? expandUpstreamNodes(graph, ctrlNode.id) : [];

    let isFusion = false;
    let style1Id = "";
    let style2Id = "";
    let layoutId = "";
    let sc021Type = SC021_PLAYSTYLES[1];
    let sc022Name = "林知夏";
    let sc022Pinyin = "LIN ZHIXIA";
    let sc022Bg = "深钴蓝";
    const colorIds = [];
    const toneIds = [];
    const moods = [];
    const customMoods = [];
    let whitespace = "";
    let audience = "";
    let businessScene = "";

    const assetItems = [];
    const textEntries = [];
    const loopNodes = [];
    const fissionNodes = [];
    let skillNode = null;
    let textNode = null;
    let assetNode = null;
    let loopNode = null;
    let fissionNode = null;

    for (const item of upstream) {
      const n = item.node;
      const nd = n.data || {};

      if (n.type === "loop") {
        if (!loopNode) loopNode = n;
        if (!loopNodes.includes(n)) loopNodes.push(n);
        continue;
      }

      if (n.type === "fission") {
        if (!fissionNode) fissionNode = n;
        if (!fissionNodes.includes(n)) fissionNodes.push(n);
        continue;
      }

      if (n.type === "skill_params") {
        if (!skillNode) skillNode = n;
        if (nd.fusion) isFusion = true;
        if (nd.style1 && !style1Id) style1Id = nd.style1;
        if (nd.style2 && !style2Id) style2Id = nd.style2;
        if (nd.layout && !layoutId) {
          layoutId = nd.layout;
          sc021Type = nd.sc021Type || sc021Type;
          sc022Name = nd.sc022Name || sc022Name;
          sc022Pinyin = nd.sc022Pinyin || sc022Pinyin;
          sc022Bg = nd.sc022Bg || sc022Bg;
        }
        (nd.colors || []).forEach((cid) => {
          if (cid && !colorIds.includes(cid)) colorIds.push(cid);
        });
        (nd.tones || []).forEach((tid) => {
          if (tid && !toneIds.includes(tid)) toneIds.push(tid);
        });
        (nd.moods || []).forEach((m) => {
          const cleanM =
            typeof m === "string"
              ? m.trim()
              : m && typeof m === "object"
                ? String(m.label || m.value || m.name_zh || m.name || "").trim()
                : "";
          if (cleanM && cleanM !== "[object Object]" && !moods.includes(cleanM)) moods.push(cleanM);
        });
        if (String(nd.customMood || "").trim()) customMoods.push(String(nd.customMood).trim());
        if (nd.whitespace && !whitespace) whitespace = nd.whitespace;
        if (String(nd.audience || "").trim() && !audience) audience = String(nd.audience).trim();
        if (String(nd.businessScene || "").trim() && !businessScene) businessScene = String(nd.businessScene).trim();
      } else if (n.type === "asset") {
        if (!assetNode) assetNode = n;
        if (Array.isArray(nd.items) && nd.items.length) {
          for (const it of nd.items) {
            if (it && (it.id || it.image)) assetItems.push(it);
          }
        } else if (nd.refId || nd.image) {
          assetItems.push({
            id: nd.refId || "ASSET",
            name: nd.name || "参考图参",
            image: nd.image || "",
            cat: nd.cat || "other",
            catLabel: nd.catLabel || ""
          });
        }
      } else if (n.type === "text_input" || n.type === "prompt" || n.type === "splitter") {
        if (!textNode) textNode = n;
        const txt = String(nd.text || "").trim();
        const fContent = String(nd.fileContent || "").trim();
        if (txt || fContent || nd.fileName) {
          textEntries.push({
            node: n,
            text: txt,
            fileContent: fContent,
            fileName: nd.fileName || ""
          });
        }
      } else if (n.type === "output_display" && Array.isArray(nd.items) && nd.items.length > 0) {
        // Allows chaining an output_display image as image reference into another output_control if desired!
        const picked = nd.items[nd.activeIdx || 0] || nd.items[0];
        if (picked && picked.imageUrl) {
          assetItems.push({
            id: "EDIT-SRC",
            name: `上游成图 · ${picked.title || "结果"}`,
            image: picked.imageUrl,
            cat: "chained",
            catLabel: "上游成图"
          });
        }
      } else if (n.type === "style" && nd.refId) {
        if (!style1Id) style1Id = nd.refId;
        else if (!style2Id) {
          style2Id = nd.refId;
          isFusion = true;
        }
      } else if (n.type === "layout" && nd.refId && !layoutId) {
        layoutId = nd.refId;
      } else if (n.type === "color" && nd.refId && !colorIds.includes(nd.refId)) {
        colorIds.push(nd.refId);
      } else if (n.type === "tone" && nd.refId && !toneIds.includes(nd.refId)) {
        toneIds.push(nd.refId);
      }
    }

    const rMap = (catalog && catalog.resourceMap) || new Map();
    const tonesCatalog = (catalog && catalog.tones) || [];

    const style1Res = style1Id ? rMap.get(style1Id) || null : null;
    const style2Res = style2Id ? rMap.get(style2Id) || null : null;
    const layoutRes = layoutId ? rMap.get(layoutId) || null : null;
    const colorResources = colorIds.map((id) => ({ id, resource: rMap.get(id) })).filter((x) => x.resource);
    const toneResources = toneIds
      .map((id) => ({ id, resource: tonesCatalog.find((t) => t.id === id) }))
      .filter((x) => x.resource);

    const allMoods = [
      ...moods,
      ...customMoods
        .flatMap((s) => s.split(/[,，、\s]+/))
        .map((s) => s.trim())
        .filter(Boolean)
    ];

    // ``userNoteText`` is the short steer a user types ("暖一点", "放在海边").
    // When the text box holds the article itself — the common case for article
    // illustration — using it verbatim repeated the whole body in every card's
    // prompt, so keep only a compact excerpt here.
    const rawNote = textEntries.map((t) => t.text).filter(Boolean).join("\n") || String(cd.inlineTheme || "").trim();
    const userNoteText = rawNote.length > 160 ? rawNote.slice(0, 160).replace(/\s+/g, " ").trim() + "…" : rawNote;
    const attachedFileContent = textEntries.map((t) => t.fileContent).filter(Boolean).join("\n\n");
    // These two feed article parsing, which needs the whole body.
    const articleSource = attachedFileContent || rawNote;
    const combinedText = [rawNote, attachedFileContent].filter(Boolean).join("\n\n");
    const attachedFileName = textEntries.find((t) => t.fileName)?.fileName || "";

    return {
      upstream,
      skillNode,
      assetNode,
      textNode,
      loopNode,
      loopNodes,
      fissionNode,
      fissionNodes,
      isFusion: Boolean(isFusion && (style1Res || style2Res)),
      fusionToggleOn: Boolean(isFusion),
      style1Id,
      style2Id,
      style1Res,
      style2Res,
      layoutId,
      layoutRes,
      sc021Type,
      sc022Name,
      sc022Pinyin,
      sc022Bg,
      colorIds,
      colorResources,
      toneIds,
      toneResources,
      allMoods,
      whitespace,
      audience,
      businessScene,
      assetItems,
      textEntries,
      userNoteText,
      attachedFileContent,
      articleSource,
      combinedText,
      attachedFileName
    };
  }

  /* ======================== LOOP BATCH ITERATION RESOLVER ======================== */

  const MAX_MERGED_REFS = 7;

  function dedupeByIdOrImage(items) {
    if (!Array.isArray(items)) return [];
    const seen = new Set();
    const result = [];
    for (const item of items) {
      if (!item) continue;
      const key = item.image ? String(item.image).trim() : (item.id ? String(item.id).trim() : "");
      if (!key) continue;
      if (!seen.has(key)) {
        seen.add(key);
        result.push(item);
      }
    }
    return result;
  }

  function resolveLoopIterations(graph, loopNode, baseRec, catalog) {
    if (!loopNode || loopNode.type !== "loop") return [];
    const ld = loopNode.data || {};
    const mode = ld.loopMode || "prompts";
    const maxIter = Math.max(1, Math.min(200, Math.round(Number(ld.maxIterations) || 200)));
    const rec = baseRec || resolveControlRecipe(graph, loopNode, catalog);
    const rMap = (catalog && catalog.resourceMap) || new Map();

    if (mode === "styles") {
      const styleIds = (Array.isArray(ld.styleIds) ? ld.styleIds : []).filter(Boolean).slice(0, maxIter);
      return styleIds.map((sid, idx) => {
        const sRes = rMap.get(sid) || (catalog?.styles?.find((s) => s.id === sid)) || null;
        const sName = sRes ? sRes.name || sid : sid;
        return {
          index: idx,
          loopMode: "styles",
          itemKey: sid,
          shortLabel: `#${sid} ${sName}`.slice(0, 22),
          title: `循环 #${idx + 1} · 画风 #${sid} ${sName}`,
          style1: sid,
          layout: "",
          assetItems: null,
          theme: rec.combinedText
            ? rec.combinedText
                .replace(/\{\{?item\}?\}|\{主题\}|\{文案\}|\{画风\}/gi, `#${sid} ${sName}`)
                .replace(/\{\{?index\}?\}|\{序号\}/gi, String(idx + 1))
            : `手绘视觉创作（画风 #${sid} ${sName}）`,
          sampleImg: sRes?.image || ""
        };
      });
    }

    if (mode === "layouts") {
      const layoutIds = (Array.isArray(ld.layoutIds) ? ld.layoutIds : []).filter(Boolean).slice(0, maxIter);
      return layoutIds.map((lid, idx) => {
        const lRes = rMap.get(lid) || (catalog?.layouts?.find((l) => l.id === lid)) || null;
        const lName = lRes ? lRes.name || lid : lid;
        return {
          index: idx,
          loopMode: "layouts",
          itemKey: lid,
          shortLabel: `${lid} ${lName}`.slice(0, 22),
          title: `循环 #${idx + 1} · 图型 ${lid} ${lName}`,
          style1: "",
          layout: lid,
          assetItems: null,
          theme: rec.combinedText
            ? rec.combinedText
                .replace(/\{\{?item\}?\}|\{主题\}|\{文案\}|\{图型\}/gi, `${lid} ${lName}`)
                .replace(/\{\{?index\}?\}|\{序号\}/gi, String(idx + 1))
            : `手绘版式创作（图型 ${lid} ${lName}）`,
          sampleImg: lRes?.image || ""
        };
      });
    }

    if (mode === "assets") {
      const assets = (rec.assetItems || []).slice(0, maxIter);
      return assets.map((ast, idx) => {
        const aName = ast.name || ast.id || `图参 ${idx + 1}`;
        const baseTxt = rec.combinedText || "";
        const mergedTheme = baseTxt
          ? /\{\{?item\}?\}|\{图参\}/i.test(baseTxt)
            ? baseTxt
                .replace(/\{\{?item\}?\}|\{图参\}/gi, aName)
                .replace(/\{\{?index\}?\}|\{序号\}/gi, String(idx + 1))
            : `${baseTxt}（当前主角/主体：${aName}）`
          : `围绕参考图参「${aName}」进行手绘视觉创作`;
        return {
          index: idx,
          loopMode: "assets",
          itemKey: ast.id || `asset_${idx}`,
          shortLabel: `${ast.id || ""} ${aName}`.trim().slice(0, 22),
          title: `循环 #${idx + 1} · 图参 ${aName}`,
          style1: "",
          layout: "",
          assetItems: [ast],
          theme: mergedTheme,
          sampleImg: ast.image || ""
        };
      });
    }

    // Default: "prompts" mode — each non-empty line is 1 loop iteration
    // When ld.batchRows is provided (Phase 3b-4 Set Planning / AI Recommended Layouts), each row specifies theme + layout
    if (Array.isArray(ld.batchRows) && ld.batchRows.length > 0) {
      return ld.batchRows.slice(0, maxIter).map((row, idx) => {
        const rowTheme = typeof row === "string" ? row : (row && row.theme != null ? String(row.theme) : "");
        const rowLayout = (row && typeof row === "object" && row.layout) ? String(row.layout).trim() : "";
        const effLayout = rowLayout || rec.layoutId || "";
        const lRes = effLayout ? (rMap.get(effLayout) || (catalog?.layouts?.find((l) => l.id === effLayout))) || null : null;
        let mergedTheme = rowTheme;
        if (rec.combinedText) {
          if (/\{\{?item\}?\}|\{主题\}|\{文案\}/i.test(rec.combinedText)) {
            mergedTheme = rec.combinedText
              .replace(/\{\{?item\}?\}|\{主题\}|\{文案\}/gi, rowTheme)
              .replace(/\{\{?index\}?\}|\{序号\}/gi, String(idx + 1));
          } else {
            mergedTheme = `${rowTheme}\n（统一要求：${rec.combinedText}）`;
          }
        }
        const cleanShort = rowTheme.replace(/^#+\s*/, "").slice(0, 16);

        const rowRefs = (row && Array.isArray(row.assetItems))
          ? row.assetItems.filter((a) => a && (a.id || a.image))
          : [];
        const skipGlobal = Boolean(row && row.skipGlobalRefs);
        let iterAssetItems = null;
        if (rowRefs.length > 0 || skipGlobal) {
          const baseRefs = skipGlobal ? [] : (Array.isArray(rec.assetItems) ? rec.assetItems : []);
          iterAssetItems = dedupeByIdOrImage([...baseRefs, ...rowRefs]).slice(0, MAX_MERGED_REFS);
        }

        return {
          index: idx,
          loopMode: "prompts",
          itemKey: `row_${idx}`,
          shortLabel: cleanShort + (rowTheme.length > 16 ? "…" : ""),
          title: `循环 #${idx + 1} · ${cleanShort}${rowTheme.length > 16 ? "…" : ""}`,
          style1: "",
          layout: effLayout,
          assetItems: iterAssetItems,
          skipGlobalRefs: skipGlobal,
          theme: mergedTheme,
          sampleImg: lRes?.image || ""
        };
      });
    }

    // Priority: if an upstream "选题裂变" (fission) node is wired into this loop and loop has no custom override, stream fission's generatedItems!
    const directUpFission = (graph?.edges || [])
      .filter((e) => e.to === loopNode.id)
      .map((e) => (graph?.nodes || []).find((n) => n.id === e.from))
      .find((n) => n && n.type === "fission");
    const activeFission = directUpFission || rec.fissionNode || null;

    const rawList =
      typeof ld.promptListText === "string"
        ? ld.promptListText
        : Array.isArray(ld.promptItems)
          ? ld.promptItems.join("\n")
          : "";
    let lines = rawList
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
    let fromUpstreamSplit = false;

    if (activeFission && Array.isArray(activeFission.data?.generatedItems) && activeFission.data.generatedItems.length > 0 && !ld.manualOverrideFission) {
      lines = activeFission.data.generatedItems.map((s) => String(s || "").trim()).filter(Boolean);
    } else if (!lines.length && ld.splitUpstreamText !== false && rec.combinedText) {
      const upLines = rec.combinedText
        .split(/\r?\n/)
        .map((s) => s.replace(/^[-*•\d.、)）\s]+/, "").trim())
        .filter(Boolean);
      if (upLines.length >= 1) {
        lines = upLines;
        fromUpstreamSplit = true;
      }
    }

    const effFixedLayout = rec.layoutId || "";
    const fixedLayoutRes = effFixedLayout ? (rMap.get(effFixedLayout) || (catalog?.layouts?.find((l) => l.id === effFixedLayout))) || null : null;
    const fixedSampleImg = fixedLayoutRes?.image || "";

    return lines.slice(0, maxIter).map((lineText, idx) => {
      let mergedTheme = lineText;
      if (!fromUpstreamSplit && rec.combinedText) {
        if (/\{\{?item\}?\}|\{主题\}|\{文案\}/i.test(rec.combinedText)) {
          mergedTheme = rec.combinedText
            .replace(/\{\{?item\}?\}|\{主题\}|\{文案\}/gi, lineText)
            .replace(/\{\{?index\}?\}|\{序号\}/gi, String(idx + 1));
        } else {
          mergedTheme = `${lineText}\n（统一要求：${rec.combinedText}）`;
        }
      }
      const cleanShort = lineText.replace(/^#+\s*/, "").slice(0, 16);
      return {
        index: idx,
        loopMode: "prompts",
        itemKey: `line_${idx}`,
        shortLabel: cleanShort + (lineText.length > 16 ? "…" : ""),
        title: `循环 #${idx + 1} · ${cleanShort}${lineText.length > 16 ? "…" : ""}`,
        style1: "",
        layout: "",
        assetItems: null,
        theme: mergedTheme,
        sampleImg: fixedSampleImg
      };
    });
  }

  /* ======================== PROMPT ASSEMBLER (SKILL / CLOUD / EN) ======================== */

  function assembleControlPrompt(graph, ctrlNode, catalog, format = "skill", slotSpec = null) {
    const cd = (ctrlNode && ctrlNode.data) || {};
    const rec = resolveControlRecipe(graph, ctrlNode, catalog);

    const rawModeNorm = cd.mode === "xhs-batch" ? "series" : cd.mode || "graphic-text";
    const rawMode = (slotSpec && slotSpec.mode) || rawModeNorm;
    const effectiveMode = rawMode === "series" || rawMode === "xhs-batch" ? "graphic-text" : rawMode;
    const ratio = String((slotSpec && slotSpec.ratio) || cd.ratio || DEFAULT_MODE_RATIOS[rawMode] || "3:4").trim();
    const effectiveStyle1Id = (slotSpec && slotSpec.style1) || rec.style1Id || "";
    const effectiveStyle1Res =
      effectiveStyle1Id && catalog?.resourceMap ? catalog.resourceMap.get(effectiveStyle1Id) || null : rec.style1Res;
    const effectiveLayoutId = (slotSpec && slotSpec.layout) || rec.layoutId || "";
    const effectiveLayoutRes = effectiveLayoutId && catalog?.resourceMap ? catalog.resourceMap.get(effectiveLayoutId) : rec.layoutRes;
    const effectiveAssetItems =
      slotSpec && Array.isArray(slotSpec.assetItems) ? slotSpec.assetItems : rec.assetItems;
    const isArticleMode = effectiveMode === "article-illust" || effectiveMode === "article-cover";
    const forceLayout = Boolean(slotSpec && slotSpec.forceArticleLayout);

    const rawTheme = String((slotSpec && slotSpec.theme) != null ? slotSpec.theme : rec.combinedText || "").trim();
    const cleanTheme = rawTheme.replace(/@\[([^\]]+)\]/g, (_, label) => `「${label}」`);

    const count = Math.max(1, Math.min(200, Math.round(Number(cd.count) || (rawModeNorm === "series" ? 4 : 1))));
    const isBatch = rawMode === "article-illust" || rawMode === "series" || count > 1;

    /* ---------- 1) OFFICIAL HANDRAW SKILL COMMAND ---------- */
    if (format === "skill") {
      const parts = [];
      if (rec.fusionToggleOn) {
        parts.push("【风格融合设计】");
        if (effectiveMode === "poster") parts.push("海报模式");
        else if (effectiveMode === "graphic-text") parts.push("图文模式");
        else if (effectiveMode === "article-illust") parts.push("文章插图模式");
        else if (effectiveMode === "article-cover") parts.push("文章封面模式");
        else parts.push("纯图模式");
      } else {
        if (effectiveMode === "poster") parts.push("请帮我出海报提示词");
        else if (effectiveMode === "graphic-text") parts.push("图文模式");
        else if (effectiveMode === "article-illust") parts.push("文章插图模式");
        else if (effectiveMode === "article-cover") parts.push("请设计文章封面");
        else parts.push("纯图模式");
      }

      // Assets grouped by Characters / Props / Scenes / Other / Custom Categories
      if (effectiveAssetItems.length > 0) {
        const chars = [];
        const props = [];
        const scenes = [];
        const customBuckets = new Map();
        for (const a of effectiveAssetItems) {
          const aid = String(a.id || "");
          if (a.cat === "characters" || aid.startsWith("CH-")) chars.push(aid.startsWith("CH-") ? aid : `${a.name}(${aid})`);
          else if (a.cat === "props" || aid.startsWith("PR-")) props.push(aid.startsWith("PR-") ? aid : `${a.name}(${aid})`);
          else if (a.cat === "scenes" || aid.startsWith("SCN-")) scenes.push(aid.startsWith("SCN-") ? aid : `${a.name}(${aid})`);
          else {
            const label = a.cat === "chained" ? "参考图参" : a.cat === "other" ? "其他资产" : a.catLabel || "自建资产";
            if (!customBuckets.has(label)) customBuckets.set(label, []);
            customBuckets.get(label).push(a.name || aid);
          }
        }
        if (chars.length) parts.push(`角色：${chars.join("、")}`);
        if (props.length) parts.push(`道具：${props.join("、")}`);
        if (scenes.length) parts.push(`场景：${scenes.join("、")}`);
        for (const [label, vals] of customBuckets.entries()) {
          parts.push(`${label}：${vals.join("、")}`);
        }
      }

      // Layout
      if (effectiveLayoutId && (!isArticleMode || forceLayout)) {
        if (effectiveLayoutId === "SC-021") {
          parts.push(`图型：SC-021（玩法：${rec.sc021Type}）`);
        } else if (effectiveLayoutId === "SC-022") {
          parts.push(`图型：SC-022（姓名：${rec.sc022Name} / ${rec.sc022Pinyin}）`);
        } else {
          parts.push(`图型：${effectiveLayoutId}`);
        }
      }

      // Style(s)
      if (rec.fusionToggleOn) {
        if (effectiveStyle1Id) parts.push(`角色风格：${effectiveStyle1Id}`);
        if (rec.style2Id) parts.push(`场景风格：${rec.style2Id}`);
      } else if (effectiveStyle1Id) {
        parts.push(`风格：${effectiveStyle1Id}`);
      }

      // Multi-select Theme Colors!
      if (rec.colorIds.length > 0) {
        parts.push(`主题色：${rec.colorIds.join("、")}`);
      }

      // Multi-select Tones
      if (rec.toneResources.length > 0) {
        parts.push(`影调：${rec.toneResources.map((t) => `${t.resource.name_zh} (${t.id})`).join("、")}`);
      }

      // Ratio
      if (ratio) {
        parts.push(`画幅比例：${ratio}`);
      }

      // Multi-select Moods
      if (rec.allMoods.length > 0) {
        parts.push(`情绪：${rec.allMoods.join("、")}`);
      }

      // Whitespace
      const wsObj = WHITESPACE_OPTIONS.find((w) => w.value === rec.whitespace);
      if (wsObj && wsObj.promptZh) {
        parts.push(wsObj.promptZh);
      }

      // Audience & Business Scene
      if (rec.audience) {
        parts.push(`受众：${rec.audience}`);
      } else if (effectiveMode === "poster") {
        parts.push("受众：【可指定受众群体】");
      }

      if (rec.businessScene) {
        parts.push(`业务场景：${rec.businessScene}`);
      } else if (effectiveMode === "article-cover") {
        let autoScene = "公众号文章封面";
        if (ratio === "5:2" || ratio === "16:9") autoScene = "X文章封面";
        else if (ratio === "3:4") autoScene = "小红书封面";
        parts.push(`业务场景：${autoScene}`);
      } else if (effectiveMode === "poster") {
        parts.push("海报投放渠道：【可指定业务场景】");
      }

      // Fallback hint if style or color left open
      const missingStyleOrColor = rec.fusionToggleOn
        ? !effectiveStyle1Id || !rec.style2Id || rec.colorIds.length === 0
        : !effectiveStyle1Id || rec.colorIds.length === 0;
      if (missingStyleOrColor) {
        parts.push("未指定项由系统自动择优匹配");
      }

      // Content / File / Theme
      if (effectiveMode === "article-illust") {
        const compactDoc = !slotSpec && cleanTheme.length > 160 ? `${cleanTheme.slice(0, 150).replace(/\s+/g, " ")}…（共 ${cleanTheme.length} 字）` : cleanTheme;
        const srcDesc = rec.attachedFileName
          ? `[文件: ${rec.attachedFileName}] ${compactDoc || "按章节正文配图"}`
          : compactDoc || "【请在左侧文本参数节点选择 .md 文件或粘贴文章】";
        parts.push(`文章内容：${srcDesc}`);
      } else if (effectiveMode === "article-cover") {
        // Extract H1 title + lead paragraph if full Markdown is attached so cover prompt stays crisp
        let coverDigest = cleanTheme;
        if (cleanTheme.includes("\n## ")) {
          coverDigest = cleanTheme.split("\n## ")[0].replace(/^#\s+/m, "").replace(/\s+/g, " ").trim();
        }
        if (coverDigest.length > 140) coverDigest = `${coverDigest.slice(0, 140)}…`;
        parts.push(`文章标题或导语：${coverDigest || "【输入文章标题或导语】"}`);
      } else {
        parts.push(`主题：${cleanTheme || "【输入创作主题】"}`);
      }

      let assembled = parts.join("，");
      if (isBatch && !(slotSpec && slotSpec.fromLoop)) {
        assembled += ` | ${rawMode === "series" ? `系列套图 (${count}张)` : `批量出图 (${rawMode === "article-illust" ? "按文章章节" : `${count}张`})`}`;
        if (cd.mixLayouts && (rawMode === "series" || rawMode === "article-illust")) {
          assembled += " | 混合多种图型";
        }
      }
      return assembled;
    }

    /* ---------- 2) ENGLISH PROMPT ---------- */
    if (format === "en") {
      const lines = [
        `[Mode]: ${effectiveMode.toUpperCase()} · Ratio ${ratio || "3:4"}`,
        `[Subject & Copy]: ${cleanTheme || "Editorial hand-drawn visual storytelling."}`
      ];
      if (rec.fusionToggleOn) {
        if (effectiveStyle1Res) lines.push(`[Character Style #${effectiveStyle1Res.id}]: ${effectiveStyle1Res.name}`);
        if (rec.style2Res) lines.push(`[Scene Style #${rec.style2Res.id}]: ${rec.style2Res.name} (Cross-media contrast)`);
      } else if (effectiveStyle1Res) {
        lines.push(`[Style #${effectiveStyle1Res.id}]: ${effectiveStyle1Res.name} — ${effectiveStyle1Res.description || ""}`);
      }
      if (effectiveLayoutRes && (!isArticleMode || forceLayout)) {
        lines.push(`[Layout ${effectiveLayoutRes.id}]: ${effectiveLayoutRes.name}`);
      }
      if (rec.colorResources.length) {
        lines.push(`[Theme Colors]: ${rec.colorResources.map((c) => `${c.id} ${c.resource.name}`).join(" + ")}`);
      }
      if (rec.toneResources.length) {
        lines.push(`[Lighting & Tones]: ${rec.toneResources.map((t) => `${t.id} ${t.resource.name_en}`).join(", ")}`);
      }
      if (rec.allMoods.length) lines.push(`[Moods]: ${rec.allMoods.join(", ")}`);
      if (rec.audience) lines.push(`[Target Audience]: ${rec.audience}`);
      if (rec.businessScene) lines.push(`[Business Scenario]: ${rec.businessScene}`);
      const wsObj = WHITESPACE_OPTIONS.find((w) => w.value === rec.whitespace);
      if (wsObj && wsObj.promptEn) lines.push(wsObj.promptEn);
      return lines.join("\n");
    }

    /* ---------- 3) CLOUD EXPANDED FULL PROMPT ---------- */
    const lines = [];
    const modeLabels = {
      pure: "纯图叙事（不出现说明性杂字）",
      "graphic-text": "社媒图文信息卡",
      poster: "商业视觉海报",
      "article-illust": "深度文章正文插图",
      "article-cover": "文章高点击视觉隐喻封面"
    };
    lines.push(`【出图模式】：${modeLabels[effectiveMode] || effectiveMode}（画幅比例 ${ratio || "3:4"}）`);
    lines.push(`【核心画面与文案主题】：${cleanTheme || "自由视觉创作"}`);
    if (rec.audience || rec.businessScene) {
      lines.push(
        `【受众与业务场景】：${rec.audience ? `目标受众「${rec.audience}」` : ""}${rec.audience && rec.businessScene ? " · " : ""}${
          rec.businessScene ? `业务场景「${rec.businessScene}」` : ""
        }`
      );
    }
    if (rec.fusionToggleOn && (effectiveStyle1Res || rec.style2Res)) {
      const cs = effectiveStyle1Res;
      const ss = rec.style2Res;
      lines.push(
        `【跨媒介画面融合】：` +
          `${cs ? `角色采用 #${cs.id} ${cs.name}` : ""}` +
          `${cs && ss ? " × " : ""}` +
          `${ss ? `场景采用 #${ss.id} ${ss.name}` : ""}`
      );
    } else if (effectiveStyle1Res) {
      const s = effectiveStyle1Res;
      lines.push(`【锁定画风 #${s.id}】：${s.sourceType === "exclusive" ? `${s.name}（云端黑盒注入）` : s.definition || s.description || s.name}`);
    }
    if (effectiveLayoutRes && (!isArticleMode || forceLayout)) {
      lines.push(`【锁定图型 ${effectiveLayoutRes.id}】：${effectiveLayoutRes.name} —— ${effectiveLayoutRes.description || ""}`);
    }
    if (rec.colorResources.length) {
      lines.push(`【多选主题色】：${rec.colorResources.map((c) => `${c.id} ${c.resource.name}`).join(" + ")}`);
    }
    if (rec.toneResources.length) {
      lines.push(`【光影阶调】：${rec.toneResources.map((t) => `${t.id} ${t.resource.name_zh}`).join(" + ")}`);
    }
    if (rec.allMoods.length) {
      lines.push(`【情绪氛围】：${rec.allMoods.join("、")}`);
    }
    const wsObj = WHITESPACE_OPTIONS.find((w) => w.value === rec.whitespace);
    if (wsObj && wsObj.promptZh) lines.push(`【留白控制】：${wsObj.promptZh}`);
    if (effectiveAssetItems.length) {
      lines.push(`【参考图参资产】：${effectiveAssetItems.map((a) => `${a.id} ${a.name}`).join("、")}，严格保持跨图特征一致。`);
    }
    return lines.join("\n");
  }

  /* ======================== BATCH SPECS FOR SERIES & ARTICLE ======================== */

  function buildSeriesSlidesSpec(rawTopic, pageCount = 4, ratio = "3:4") {
    const total = Math.max(1, Math.min(200, Math.round(Number(pageCount) || 4)));
    const clean = String(rawTopic || "高效视觉笔记创作全流程指南").trim();
    const shortTitle = clean.split(/[：:。！!？?\n]/)[0].replace(/^#+\s*/, "").slice(0, 18) || "系列主题";
    const innerLayouts = ["USR-L01", "IG-003", "SC-006", "IG-001", "SB-002"];
    const sampleImgs = [
      "/images/layouts/social-cards/SC-023.webp",
      "/images/layouts/infographics/IG-005.webp",
      "/images/layouts/infographics/IG-003.webp",
      "/images/graphic-text-mode-demo.webp",
      "/images/layouts/social-cards/SC-006.webp",
      "/images/layouts/social-cards/SC-024.webp"
    ];

    const specs = [];
    for (let i = 0; i < total; i++) {
      if (i === 0) {
        specs.push({
          slotKey: `series_${i}`,
          role: "cover",
          title: total === 1 ? "第1张 · 主题主图" : "第1张 · 系列封面",
          layout: "LX-001",
          mode: "graphic-text",
          ratio,
          theme: `【第1张 主标题】${shortTitle}\n【画面焦点】围绕「${clean.slice(0, 44)}」提炼高反差手绘视觉主体居中，底部核心亮点`,
          sampleImg: sampleImgs[0]
        });
      } else if (i === total - 1 && total >= 3) {
        specs.push({
          slotKey: `series_${i}`,
          role: "slide",
          title: `第${i + 1}张 · 总结收尾页`,
          layout: "SC-024",
          mode: "graphic-text",
          ratio,
          theme: `【第${i + 1}张 行动总结】针对「${shortTitle}」列出关键要点清单与收尾金句`,
          sampleImg: sampleImgs[5]
        });
      } else if (i === 1) {
        specs.push({
          slotKey: `series_${i}`,
          role: "slide",
          title: "第2张 · 对照与核心拆解",
          layout: "USR-L01",
          mode: "graphic-text",
          ratio,
          theme: `【第2张 核心拆解】关键脉络对照解析，左右分栏清晰呈现「${shortTitle}」`,
          sampleImg: sampleImgs[1]
        });
      } else {
        specs.push({
          slotKey: `series_${i}`,
          role: "slide",
          title: `第${i + 1}张 · 分步图解`,
          layout: innerLayouts[(i - 1) % innerLayouts.length],
          mode: "graphic-text",
          ratio,
          theme: `【第${i + 1}张 分步图解】第 ${i} 节核心内容与手绘结构化演示「${clean.slice(0, 36)}」`,
          sampleImg: sampleImgs[i % sampleImgs.length]
        });
      }
    }
    return specs;
  }

  function buildArticleSlotsSpec(mdText, { coverRatio = "2.35:1", inlineRatio = "4:3", includeCover = true } = {}) {
    const lines = String(mdText || "").split(/\r?\n/);
    let h1 = "未命名专栏文章";
    let lead = "";
    const secs = [];
    let cur = null;

    for (const raw of lines) {
      const t = raw.trim();
      if (!t) continue;
      if (/^#\s+/.test(t)) h1 = t.replace(/^#\s+/, "").trim();
      else if (/^#{2,3}\s+/.test(t)) {
        if (cur) secs.push(cur);
        cur = { heading: t, body: [] };
      } else if (cur) cur.body.push(t);
      else if (!lead) lead = t;
    }
    if (cur) secs.push(cur);

    const sampleImgs = [
      "/images/individual/FA/FA-003.webp",
      "/images/individual/FA/FA-013.webp",
      "/images/individual/FB/FB-031.webp",
      "/images/poster-demo-autumn-equinox.webp",
      "/images/graphic-text-mode-demo.webp"
    ];

    const out = [];
    if (includeCover) {
      out.push({
        slotKey: "art_cover",
        role: "cover",
        title: `首图封面 · ${coverRatio}`,
        anchorHeading: `# ${h1}`,
        layout: "",
        mode: "article-cover",
        ratio: coverRatio,
        theme: `《${h1}》—— ${(lead || h1).slice(0, 64)}`,
        sampleImg: sampleImgs[0]
      });
    }

    const effectiveSecs =
      secs.length > 0
        ? secs
        : String(mdText || "")
            .split(/\n\s*\n/)
            .map((p) => p.trim())
            .filter(Boolean)
            .slice(0, 3)
            .map((p, idx) => ({ heading: `## 章节 ${idx + 1}`, body: [p] }));

    effectiveSecs.forEach((sec, idx) => {
      const cleanH = sec.heading.replace(/^#{2,3}\s+/, "").trim();
      const snippet = sec.body.join(" ").slice(0, 62);
      const useInfoLayout = /步骤|对比|架构|四步|清单/.test(cleanH) ? "IG-001" : "";
      out.push({
        slotKey: `art_sec_${idx}`,
        role: "inline",
        title: `章节插图 0${idx + 1} · ${cleanH.slice(0, 12)}`,
        anchorHeading: sec.heading.startsWith("#") ? sec.heading : `## ${sec.heading}`,
        layout: useInfoLayout,
        mode: "article-illust",
        ratio: inlineRatio,
        forceArticleLayout: Boolean(useInfoLayout),
        theme: `章节「${cleanH}」：${snippet || cleanH}`,
        sampleImg: sampleImgs[(idx + 1) % sampleImgs.length]
      });
    });

    return out;
  }

  /* ======================== READ-ONLY ARTICLE BLOCKS & NOTION-STYLE ARTICLE PLAN BUILDER ======================== */

  const DEFAULT_STARTER_ARTICLE_MD =
    "# 为什么越忙的人，越需要「留白工作法」？\n\n当我们把日历上的每一个半小时都塞满会议和待办事项时，看似运转到了极致，实际上大脑已经失去了真正产生创造性连接的呼吸缝隙。\n\n## 一、塞满的日程表，正在杀死你的深度思考\n\n现代职场最大的幻觉，就是把「响应速度」当成了「产出质量」。像一台没有缓冲内存的服务器，任何一点突发消息都会触发全盘卡顿。\n\n## 二、像画水彩一样管理精力：留出 30% 不设限白纸\n\n法国插画家桑贝的画里总有大片温润的空白纸面。正是那 70% 没有画满的天空与广场，让画面里那个骑单车的小人瞬间拥有了自由的诗意。\n\n## 三、建立你的每日微停顿仪式：散步、手写与慢煮茶\n\n真正的恢复不是刷短视频填满碎片时间，而是离开屏幕：下楼走过两条梧桐街区、在纸质笔记本上画三个凌乱的思维圈。";

  function parseArticleReadonlyBlocks(rawMd, options = {}) {
    const withLines = Boolean(options && options.withLines);
    const noStarter = Boolean(options && options.noStarter);

    const hasText = String(rawMd || "").trim().length > 0;
    if (!hasText && noStarter) {
      return [];
    }

    const src = hasText ? String(rawMd || "") : DEFAULT_STARTER_ARTICLE_MD;
    const lines = src.split(/\r?\n/);
    const blocks = [];
    let paraBuf = [];
    let paraStartLine = -1;
    let paraEndLine = -1;

    let listBuf = [];
    let listStartLine = -1;
    let listEndLine = -1;

    let quoteBuf = [];
    let quoteStartLine = -1;
    let quoteEndLine = -1;

    let inCode = false;
    let codeBuf = [];
    let codeStartLine = -1;
    let codeEndLine = -1;

    const flushAll = () => {
      if (paraBuf.length) {
        const txt = paraBuf.join(" ").trim();
        if (txt) {
          const blk = { idx: blocks.length, kind: "p", text: txt, rawMd: paraBuf.join("\n") };
          if (withLines) {
            blk.startLine = paraStartLine;
            blk.endLine = paraEndLine;
          }
          blocks.push(blk);
        }
        paraBuf = [];
        paraStartLine = -1;
        paraEndLine = -1;
      }
      if (listBuf.length) {
        const blk = {
          idx: blocks.length,
          kind: "ul",
          items: listBuf.map((l) => l.replace(/^([-*+]|\d+\.)\s+/, "").trim()),
          text: listBuf.map((l) => l.replace(/^([-*+]|\d+\.)\s+/, "").trim()).join("；"),
          rawMd: listBuf.join("\n")
        };
        if (withLines) {
          blk.startLine = listStartLine;
          blk.endLine = listEndLine;
        }
        blocks.push(blk);
        listBuf = [];
        listStartLine = -1;
        listEndLine = -1;
      }
      if (quoteBuf.length) {
        const qt = quoteBuf.map((l) => l.replace(/^>\s?/, "").trim()).join(" ");
        const blk = { idx: blocks.length, kind: "blockquote", text: qt, rawMd: quoteBuf.join("\n") };
        if (withLines) {
          blk.startLine = quoteStartLine;
          blk.endLine = quoteEndLine;
        }
        blocks.push(blk);
        quoteBuf = [];
        quoteStartLine = -1;
        quoteEndLine = -1;
      }
    };

    for (let lineIdx = 0; lineIdx < lines.length; lineIdx++) {
      const rawLine = lines[lineIdx];
      const trimmed = rawLine.trim();
      if (/^```/.test(trimmed)) {
        if (!inCode) {
          flushAll();
          inCode = true;
          codeBuf = [rawLine];
          codeStartLine = lineIdx;
          codeEndLine = lineIdx;
        } else {
          codeBuf.push(rawLine);
          codeEndLine = lineIdx;
          const blk = {
            idx: blocks.length,
            kind: "code",
            text: codeBuf.slice(1, -1).join("\n"),
            rawMd: codeBuf.join("\n")
          };
          if (withLines) {
            blk.startLine = codeStartLine;
            blk.endLine = codeEndLine;
          }
          blocks.push(blk);
          inCode = false;
          codeBuf = [];
          codeStartLine = -1;
          codeEndLine = -1;
        }
        continue;
      }
      if (inCode) {
        codeBuf.push(rawLine);
        codeEndLine = lineIdx;
        continue;
      }
      if (!trimmed) {
        flushAll();
        continue;
      }
      if (/^#\s+/.test(trimmed)) {
        flushAll();
        const blk = { idx: blocks.length, kind: "h1", text: trimmed.replace(/^#\s+/, "").trim(), rawMd: trimmed };
        if (withLines) { blk.startLine = lineIdx; blk.endLine = lineIdx; }
        blocks.push(blk);
      } else if (/^##\s+/.test(trimmed)) {
        flushAll();
        const blk = { idx: blocks.length, kind: "h2", text: trimmed.replace(/^##\s+/, "").trim(), rawMd: trimmed };
        if (withLines) { blk.startLine = lineIdx; blk.endLine = lineIdx; }
        blocks.push(blk);
      } else if (/^###+\s+/.test(trimmed)) {
        flushAll();
        const blk = { idx: blocks.length, kind: "h3", text: trimmed.replace(/^###+\s+/, "").trim(), rawMd: trimmed };
        if (withLines) { blk.startLine = lineIdx; blk.endLine = lineIdx; }
        blocks.push(blk);
      } else if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
        flushAll();
        const blk = { idx: blocks.length, kind: "hr", text: "", rawMd: trimmed };
        if (withLines) { blk.startLine = lineIdx; blk.endLine = lineIdx; }
        blocks.push(blk);
      } else if (/^>\s?/.test(trimmed)) {
        if (paraBuf.length || listBuf.length) flushAll();
        if (quoteBuf.length === 0) quoteStartLine = lineIdx;
        quoteEndLine = lineIdx;
        quoteBuf.push(trimmed);
      } else if (/^([-*+]|\d+\.)\s+/.test(trimmed)) {
        if (paraBuf.length || quoteBuf.length) flushAll();
        if (listBuf.length === 0) listStartLine = lineIdx;
        listEndLine = lineIdx;
        listBuf.push(trimmed);
      } else {
        if (listBuf.length || quoteBuf.length) flushAll();
        if (paraBuf.length === 0) paraStartLine = lineIdx;
        paraEndLine = lineIdx;
        paraBuf.push(trimmed);
      }
    }
    if (inCode && codeBuf.length) {
      const blk = { idx: blocks.length, kind: "code", text: codeBuf.slice(1).join("\n"), rawMd: codeBuf.join("\n") };
      if (withLines) {
        blk.startLine = codeStartLine;
        blk.endLine = lines.length - 1;
      }
      blocks.push(blk);
    }
    flushAll();

    if (!blocks.length && !noStarter) {
      const blk = { idx: 0, kind: "h1", text: "未命名文章", rawMd: "# 未命名文章" };
      if (withLines) {
        blk.startLine = 0;
        blk.endLine = 0;
      }
      blocks.push(blk);
    }
    return blocks;
  }

  function assembleArticleCardFullPrompt(graph, ctrlNode, catalog, slotInfo = {}) {
    const rec = ctrlNode ? resolveControlRecipe(graph, ctrlNode, catalog) : null;
    const role = slotInfo.role === "cover" ? "cover" : "inline";
    const ratio = slotInfo.ratio || (role === "cover" ? "2.35:1" : "4:3");
    const subjectLine = String(slotInfo.subject || "").trim() || "温暖手绘编辑风叙事插画";
    // Only a short steer belongs in a per-card prompt.  The recipe's note fields
    // hold whatever text the user supplied, which for article illustration is
    // usually the article itself; appending that made every card repeat the whole
    // body.  A steer is one short line, so anything longer or multi-line is not
    // a steer and is dropped.
    const noteText = rec ? String(rec.userNoteText || "").replace(/\s+/g, " ").trim() : "";
    const looksLikeBody = noteText.length > 100 || /\n/.test(String(rec?.userNoteText || ""));
    const extraNote = !noteText || looksLikeBody ? "" : noteText;

    const lines = [];
    if (role === "cover") {
      lines.push(
        `【文章封面视觉焦点】：${subjectLine}。提炼极具记忆点的手绘视觉隐喻作为封面中心主体，构图大气简洁，避免细碎说明杂字。`
      );
      lines.push(`【出图定位与比例】：文章首图封面 · 画幅比例 ${ratio}`);
    } else {
      lines.push(
        `【章节插图画面描述】：${subjectLine}。紧扣本段文章语义进行叙事手绘表达，角色神态生动，视觉重点突出。`
      );
      lines.push(`【出图定位与比例】：文章正文插图 · 画幅比例 ${ratio}`);
    }

    if (extraNote) {
      lines.push(`【补充创作要求】：${extraNote}`);
    }

    if (rec) {
      if (rec.fusionToggleOn && (rec.style1Res || rec.style2Res)) {
        const cs = rec.style1Res;
        const ss = rec.style2Res;
        lines.push(
          `【跨媒介双画风融合】：${cs ? `主体采用 #${cs.id} ${cs.name}` : ""}${cs && ss ? " × " : ""}${
            ss ? `场景采用 #${ss.id} ${ss.name}` : ""
          }`
        );
      } else if (rec.style1Res) {
        const s = rec.style1Res;
        lines.push(
          `【锁定手绘画风 #${s.id} ${s.name}】：${
            s.sourceType === "exclusive" ? `${s.name}（专属精调画风）` : s.definition || s.description || s.name
          }`
        );
      } else {
        lines.push("【手绘画风】：温暖编辑风手绘插画（纸张肌理自然、笔触富有人情味）");
      }

      if (rec.layoutRes) {
        lines.push(`【构图与图型参考 ${rec.layoutRes.id}】：${rec.layoutRes.name} —— ${rec.layoutRes.description || ""}`);
      }
      if (rec.colorResources.length) {
        lines.push(`【锁定主题色板】：${rec.colorResources.map((c) => `${c.id} ${c.resource.name}`).join(" + ")}，全篇配图保持色温连贯`);
      }
      if (rec.toneResources.length) {
        lines.push(`【光影阶调】：${rec.toneResources.map((t) => `${t.id} ${t.resource.name_zh}`).join(" + ")}`);
      }
      if (rec.allMoods.length) {
        lines.push(`【情绪氛围】：${rec.allMoods.join("、")}`);
      }
      if (rec.audience || rec.businessScene) {
        lines.push(
          `【受众与投放场景】：${rec.audience ? `目标受众「${rec.audience}」` : ""}${rec.audience && rec.businessScene ? " · " : ""}${
            rec.businessScene ? `场景「${rec.businessScene}」` : ""
          }`
        );
      }
      const wsObj = WHITESPACE_OPTIONS.find((w) => w.value === rec.whitespace);
      if (wsObj && wsObj.promptZh) {
        lines.push(`【留白控制】：${wsObj.promptZh}`);
      }
      if (rec.assetItems.length) {
        lines.push(`【参考图参资产】：${rec.assetItems.map((a) => `${a.id} ${a.name}`).join("、")}，严格保持角色与道具跨图一致`);
      }
    }

    return lines.join("\n");
  }

  function buildArticlePlanData(rawMd, ctrlNode, graph, catalog, { withSampleImages = false } = {}) {
    const rec = ctrlNode ? resolveControlRecipe(graph, ctrlNode, catalog) : null;
    const effectiveMd =
      String(rawMd || (rec && rec.articleSource) || "").trim() || DEFAULT_STARTER_ARTICLE_MD;
    const blocks = parseArticleReadonlyBlocks(effectiveMd);

    const h1Block = blocks.find((b) => b.kind === "h1");
    const firstTextBlock = blocks.find((b) => b.text);
    const articleTitle =
      (h1Block && h1Block.text) ||
      (rec && rec.attachedFileName ? rec.attachedFileName.replace(/\.[^.]+$/, "") : "") ||
      (firstTextBlock ? firstTextBlock.text.slice(0, 26) : "未命名文章");

    const leadBlock = blocks.find((b) => b !== h1Block && (b.kind === "p" || b.kind === "blockquote"));
    const leadSnippet = leadBlock ? leadBlock.text.slice(0, 88) : articleTitle;

    const cd = (ctrlNode && ctrlNode.data) || {};
    const coverRatio = cd.coverRatio || "2.35:1";
    const inlineRatio = cd.inlineRatio || "4:3";

    const sampleImgs = [
      "/images/individual/FA/FA-003.webp",
      "/images/individual/FA/FA-013.webp",
      "/images/individual/FB/FB-031.webp",
      "/images/poster-demo-autumn-equinox.webp",
      "/images/graphic-text-mode-demo.webp"
    ];

    const cards = [];

    if (cd.includeCover !== false) {
      const coverSubject = `围绕文章《${articleTitle}》（核心导语：${leadSnippet}）创作富有故事张力的手绘主题封面`;
      cards.push({
        id: uid("pcard"),
        role: "cover",
        title: "文章封面",
        ratio: coverRatio,
        afterBlockIdx: -1,
        prompt: assembleArticleCardFullPrompt(graph, ctrlNode, catalog, {
          role: "cover",
          ratio: coverRatio,
          subject: coverSubject
        }),
        promptCustomized: false,
        sampleImg: sampleImgs[0],
        imageUrl: withSampleImages ? sampleImgs[0] : "",
        status: withSampleImages ? "done" : "idle"
      });
    }

    let sectionAnchorBlocks = blocks.filter((b) => b.kind === "h2");
    if (!sectionAnchorBlocks.length) {
      sectionAnchorBlocks = blocks.filter((b) => b.kind === "h3");
    }
    if (!sectionAnchorBlocks.length) {
      sectionAnchorBlocks = blocks.filter((b) => b.kind === "p").slice(0, 3);
    }

    sectionAnchorBlocks.forEach((secBlock, idx) => {
      const bodyParts = [];
      for (let k = secBlock.idx + 1; k < blocks.length; k++) {
        const nb = blocks[k];
        if (nb.kind === "h1" || nb.kind === "h2" || nb.kind === "h3") break;
        if (nb.text) bodyParts.push(nb.text);
        if (bodyParts.length >= 2) break;
      }
      const secHeading = secBlock.kind === "p" ? `段落重点 ${idx + 1}` : secBlock.text;
      const secBodySnippet = (bodyParts.join(" ") || secBlock.text).slice(0, 110);
      const subject = `章节「${secHeading}」—— ${secBodySnippet}`;
      const sImg = sampleImgs[(idx + 1) % sampleImgs.length];

      cards.push({
        id: uid("pcard"),
        role: "inline",
        title: `插图 ${idx + 1} · ${secHeading.slice(0, 14)}`,
        ratio: inlineRatio,
        afterBlockIdx: secBlock.idx,
        prompt: assembleArticleCardFullPrompt(graph, ctrlNode, catalog, {
          role: "inline",
          ratio: inlineRatio,
          subject
        }),
        promptCustomized: false,
        sampleImg: sImg,
        imageUrl: withSampleImages ? sImg : "",
        status: withSampleImages ? "done" : "idle"
      });
    });

    // Final guard: whatever produced these prompts, a card must not carry the
    // whole article.  Every card is inspected here because several call sites
    // build plans and each one used to append the full body as 补充创作要求.
    const bodyFingerprint = String(effectiveMd || "")
      .replace(/\s+/g, "")
      .slice(0, 40);
    for (const card of cards) {
      if (!card || typeof card.prompt !== "string") continue;
      const marker = "【补充创作要求】：";
      const at = card.prompt.indexOf(marker);
      if (at < 0) continue;
      const head = card.prompt.slice(0, at + marker.length);
      const tail = card.prompt.slice(at + marker.length);
      // Cut the steer at the first newline group; a real steer is one short line.
      const firstBreak = tail.search(/\n\s*\n|【锁定手绘画风|【构图与图型参考/);
      let steer = (firstBreak >= 0 ? tail.slice(0, firstBreak) : tail).replace(/\s+/g, " ").trim();
      if (steer.length > 120) steer = steer.slice(0, 120) + "…";
      const rest = firstBreak >= 0 ? tail.slice(firstBreak) : "";
      card.prompt = head + steer + rest;
      if (bodyFingerprint && card.prompt.replace(/\s+/g, "").includes(bodyFingerprint)) {
        // Still holds the article body; drop the steer entirely.
        card.prompt = head + rest;
      }
    }

    return {
      articleTitle,
      markdown: effectiveMd,
      blocks,
      cards
    };
  }

  function buildArticlePlanFromAi(resp, { ctrlNode, graph, catalog, coverRatio, inlineRatio } = {}) {
    if (!resp || typeof resp !== "object") {
      const empty = [];
      empty.cards = empty;
      return empty;
    }
    const cd = (ctrlNode && ctrlNode.data) || {};
    const cRatio = coverRatio || cd.coverRatio || "2.35:1";
    const iRatio = inlineRatio || cd.inlineRatio || "4:3";
    const planSource = resp.source === "template" ? "template" : (resp.source || "model");
    const articleType = String(resp.articleType || "").trim();

    const sampleImgs = [
      "/images/individual/FA/FA-003.webp",
      "/images/individual/FA/FA-013.webp",
      "/images/individual/FB/FB-031.webp",
      "/images/poster-demo-autumn-equinox.webp",
      "/images/graphic-text-mode-demo.webp"
    ];

    const cards = [];

    // 1. Cover Card
    if (resp.cover && typeof resp.cover === "object") {
      const covSubject = String(resp.cover.subject || "").trim() || "文章主题封面";
      const covPurpose = String(resp.cover.purpose || "").trim();
      const covLayout = String(resp.cover.layout || resp.cover.layoutId || "").trim();
      const covImageType = String(resp.cover.imageType || "").trim();

      cards.push({
        id: uid("pcard"),
        role: "cover",
        title: "文章封面",
        ratio: cRatio,
        afterBlockIdx: -1,
        planSource,
        subject: covSubject,
        purpose: covPurpose,
        layoutId: covLayout,
        imageType: covImageType,
        articleType,
        prompt: assembleArticleCardFullPrompt(graph, ctrlNode, catalog, {
          role: "cover",
          ratio: cRatio,
          subject: covSubject
        }),
        promptCustomized: false,
        sampleImg: sampleImgs[0],
        imageUrl: "",
        status: "idle"
      });
    }

    // 2. Inline Illustration Cards
    const rawIllusts = Array.isArray(resp.illustrations) ? resp.illustrations : [];
    rawIllusts.forEach((item, idx) => {
      if (!item || typeof item !== "object") return;
      const blkIdx = Number.isInteger(item.afterBlockIdx)
        ? item.afterBlockIdx
        : (parseInt(item.afterBlockIdx, 10) || 0);
      const anchorText = String(item.anchorText || "").trim();
      const cleanSubj = String(item.subject || "").trim() || "章节手绘叙事插画";
      const cleanPurpose = String(item.purpose || "").trim();
      const layoutId = String(item.layout || item.layoutId || "").trim();
      const imageType = String(item.imageType || "").trim();
      const cleanAnchor = anchorText.replace(/^#+\s*/, "").slice(0, 14);

      cards.push({
        id: uid("pcard"),
        role: "inline",
        title: `插图 ${idx + 1} · ${cleanAnchor || "正文插图"}`,
        ratio: iRatio,
        afterBlockIdx: blkIdx,
        anchorText,
        planSource,
        subject: cleanSubj,
        purpose: cleanPurpose,
        layoutId,
        imageType,
        prompt: assembleArticleCardFullPrompt(graph, ctrlNode, catalog, {
          role: "inline",
          ratio: iRatio,
          subject: cleanSubj
        }),
        promptCustomized: false,
        sampleImg: sampleImgs[(idx + 1) % sampleImgs.length],
        imageUrl: "",
        status: "idle"
      });
    });

    cards.cards = cards;
    return cards;
  }

  function buildEditorSegments(markdown, cards) {
    const md = String(markdown || "");
    const blocks = parseArticleReadonlyBlocks(md, { withLines: true, noStarter: true });
    const lines = md.split(/\r?\n/);

    const cuts = [];
    const inlineCards = (cards || []).filter((c) => c && c.role !== "cover");
    inlineCards.forEach((c) => {
      const idx = Number(c.afterBlockIdx);
      if (Number.isInteger(idx) && idx >= 0 && idx < blocks.length - 1) {
        if (!cuts.includes(idx)) cuts.push(idx);
      }
    });
    cuts.sort((a, b) => a - b);

    if (cuts.length === 0) {
      return [
        {
          segIdx: 0,
          text: md,
          startLine: 0,
          endLine: lines.length - 1,
          afterBlockIdx: blocks.length > 0 ? blocks[blocks.length - 1].idx : -1
        }
      ];
    }

    const segments = [];
    let prevEndLine = -1;
    for (let i = 0; i < cuts.length; i++) {
      const cutIdx = cuts[i];
      const cutBlock = blocks.find((b) => b.idx === cutIdx);
      const startLine = prevEndLine + 1;
      const endLine = cutBlock && typeof cutBlock.endLine === "number" ? cutBlock.endLine : startLine;
      segments.push({
        segIdx: i,
        text: lines.slice(startLine, endLine + 1).join("\n"),
        startLine,
        endLine,
        afterBlockIdx: cutIdx
      });
      prevEndLine = endLine;
    }
    const lastStartLine = prevEndLine + 1;
    segments.push({
      segIdx: cuts.length,
      text: lines.slice(lastStartLine).join("\n"),
      startLine: lastStartLine,
      endLine: lines.length - 1,
      afterBlockIdx: blocks.length > 0 ? blocks[blocks.length - 1].idx : -1
    });

    return segments;
  }

  /* ======================== STARTER WORKFLOW BLUEPRINTS ======================== */

  function createBlueprintGraph(key, catalog, mockData, { withPresetAssets = false } = {}) {
    const nodes = [];
    const edges = [];
    const link = (a, b) => edges.push({ id: uid("edge"), from: a.id, to: b.id });

    if (key === "blank") {
      return { blueprint: "blank", nodes: [], edges: [], selectedIds: [] };
    }

    if (key === "article") {
      const aTpl = ((mockData && mockData.ARTICLE_BATCH_TEMPLATES) || [])[0];
      const mdText = (aTpl && aTpl.markdown) || DEFAULT_STARTER_ARTICLE_MD;

      const spNode = makeSkillParamsNode(64, 52, {
        style1: withPresetAssets ? "FA-003" : "",
        colors: withPresetAssets ? ["C-27", "C-15"] : [],
        tones: withPresetAssets ? ["T-13"] : [],
        moods: withPresetAssets ? ["诗意", "松弛"] : [],
        whitespace: withPresetAssets ? "high" : "",
        audience: "",
        businessScene: ""
      });

      const txtNode = makeTextInputNode(64, 548, {
        text: "",
        fileName: "留白工作法.md",
        fileContent: mdText,
        fileSize: mdText.length
      });

      const ctrlNode = makeOutputControlNode(488, 176, {
        mode: "article-illust",
        coverRatio: "2.35:1",
        inlineRatio: "4:3",
        includeCover: true
      });

      nodes.push(spNode, txtNode, ctrlNode);
      link(spNode, ctrlNode);
      link(txtNode, ctrlNode);

      if (withPresetAssets) {
        const tempGraph = { nodes, edges };
        const built = buildArticlePlanData(mdText, ctrlNode, tempGraph, catalog, {
          withSampleImages: true
        });

        const planNode = makeArticlePlanNode(920, 148, {
          status: "done",
          sourceControlId: ctrlNode.id,
          articleTitle: built.articleTitle,
          markdown: built.markdown,
          cards: built.cards,
          updatedAt: "预设样张",
          runCount: 1
        });

        nodes.push(planNode);
        link(ctrlNode, planNode);

        const readyCards = built.cards.filter((c) => c.imageUrl);
        readyCards.forEach((c, idx) => {
          const dNode = makeOutputDisplayNode(1408, 48 + idx * 336, {
            title: "图片显示",
            status: "done",
            mode: "article-illust",
            slotIndex: idx,
            planCardId: c.id,
            sourceNodeId: planNode.id,
            updatedAt: "预设样张",
            runCount: 1,
            items: [
              {
                id: c.id,
                slotKey: c.id,
                role: c.role,
                title: c.title,
                ratio: c.ratio,
                prompt: c.prompt,
                imageUrl: c.imageUrl
              }
            ]
          });
          nodes.push(dNode);
          link(planNode, dNode);
        });
      }

      return { blueprint: "article", nodes, edges, selectedIds: [] };
    }

    if (key === "ip_story" || key === "series" || key === "xhs") {
      const spNode = makeSkillParamsNode(64, 48, {
        style1: "FB-031",
        colors: ["C-15"],
        moods: ["治愈", "温暖", "叙事感"],
        whitespace: "moderate"
      });

      const astNode = makeAssetNode(64, 540, {
        items: [
          { id: "CH-001", name: "黑猫侍者", image: "/images/characters/CH-001.webp", cat: "characters", catLabel: "角色" },
          { id: "PR-001", name: "手冲黄铜细口壶", image: "/images/props/PR-001.webp", cat: "props", catLabel: "道具" }
        ]
      });

      const txtNode = makeTextInputNode(64, 780, {
        text: "深夜猫咪咖啡馆的四幕治愈故事：第1幕备豆磨粉迎客 → 第2幕铜壶闷蒸注水 → 第3幕端上热拿铁倾听心事 → 第4幕窗边听雨温暖收摊"
      });

      const ctrlNode = makeOutputControlNode(488, 260, {
        mode: "series",
        count: 4,
        ratio: "3:4",
        mixLayouts: true
      });

      nodes.push(spNode, astNode, txtNode, ctrlNode);
      link(spNode, ctrlNode);
      link(astNode, ctrlNode);
      link(txtNode, ctrlNode);

      return { blueprint: key === "series" || key === "xhs" ? "ip_story" : key, nodes, edges, selectedIds: [] };
    }

    if (key === "fusion") {
      const spNode = makeSkillParamsNode(64, 52, {
        fusion: true,
        style1: "FA-038",
        style2: "FI-028",
        layout: "SC-021",
        colors: ["C-30"],
        moods: ["叙事感", "诗意"]
      });

      const txtNode = makeTextInputNode(64, 636, {
        text: "雨后东京石板路街角，微缩手绘水墨小人撑着红伞站在真实胶片街景积水倒影旁，双世界跨媒介视觉张力"
      });

      const ctrlNode = makeOutputControlNode(488, 216, {
        mode: "poster",
        count: 1,
        ratio: "3:4"
      });

      nodes.push(spNode, txtNode, ctrlNode);
      link(spNode, ctrlNode);
      link(txtNode, ctrlNode);

      return { blueprint: "fusion", nodes, edges, selectedIds: [] };
    }

    if (key === "loop_100") {
      const spNode = makeSkillParamsNode(64, 48, {
        style1: "FA-013",
        layout: "SC-023",
        colors: ["C-15"],
        moods: ["治愈", "幽默", "松弛"]
      });

      const fisNode = makeFissionNode(64, 548, {
        seedTopic: "打工人反内卷治愈手绘日签",
        strategy: "daily_quote",
        targetCount: 100
      });

      const loopNode = makeLoopNode(488, 204, {
        loopMode: "prompts",
        promptListText: "",
        maxIterations: 200
      });

      const ctrlNode = makeOutputControlNode(912, 204, {
        mode: "graphic-text",
        count: 1,
        ratio: "3:4"
      });

      nodes.push(spNode, fisNode, loopNode, ctrlNode);
      link(spNode, loopNode);
      link(fisNode, loopNode);
      link(loopNode, ctrlNode);

      return { blueprint: "loop_100", nodes, edges, selectedIds: [] };
    }

    if (key === "style_ab") {
      const txtNode = makeTextInputNode(64, 188, {
        text: "独立书店深夜阅读企划：一盏暖黄台灯、翻开的旧诗集与窗外淅沥春雨，留白呼吸感社论插画排版"
      });

      const loopNode = makeLoopNode(488, 148, {
        loopMode: "styles",
        styleIds: ["FA-003", "FB-031", "FE-067", "FX-001"]
      });

      const ctrlNode = makeOutputControlNode(912, 156, {
        mode: "graphic-text",
        count: 1,
        ratio: "3:4"
      });

      nodes.push(txtNode, loopNode, ctrlNode);
      link(txtNode, loopNode);
      link(loopNode, ctrlNode);

      return { blueprint: "style_ab", nodes, edges, selectedIds: [] };
    }

    if (key === "omnimedia") {
      const spNode = makeSkillParamsNode(64, 48, {
        style1: "FA-003",
        colors: ["C-15"],
        moods: ["诗意", "温暖"],
        whitespace: "high",
        businessScene: "春季新茶全渠道上市宣发"
      });

      const astNode = makeAssetNode(64, 540, {
        items: [
          { id: "PR-002", name: "白瓷盖碗春茶器", image: "/images/poster-demo-autumn-equinox.webp", cat: "props", catLabel: "道具" }
        ]
      });

      const txtNode = makeTextInputNode(64, 780, {
        text: "明前狮峰龙井冷萃新茶上市：高山云雾慢采，0糖原叶兰花香，献给忙碌都市里的一杯春意留白"
      });

      const brgNode = makeBridgeNode(488, 360, {
        note: "一套品牌视觉规范，三端尺寸并发输出"
      });

      const ctrlBanner = makeOutputControlNode(824, 48, {
        title: "输出控制 · 公众号首图",
        mode: "graphic-text",
        count: 1,
        ratio: "2.35:1"
      });

      const ctrlSeries = makeOutputControlNode(824, 436, {
        title: "输出控制 · 社媒种草套图",
        mode: "series",
        count: 3,
        ratio: "3:4",
        mixLayouts: true
      });

      const ctrlPoster = makeOutputControlNode(824, 836, {
        title: "输出控制 · 朋友圈竖版海报",
        mode: "poster",
        count: 1,
        ratio: "9:16"
      });

      nodes.push(spNode, astNode, txtNode, brgNode, ctrlBanner, ctrlSeries, ctrlPoster);
      link(spNode, brgNode);
      link(astNode, brgNode);
      link(txtNode, brgNode);
      link(brgNode, ctrlBanner);
      link(brgNode, ctrlSeries);
      link(brgNode, ctrlPoster);

      return { blueprint: "omnimedia", nodes, edges, selectedIds: [] };
    }

    if (key === "loop") {
      const spNode = makeSkillParamsNode(64, 52, {
        style1: withPresetAssets ? "FA-003" : "FA-003",
        layout: "SC-023",
        colors: ["C-15"],
        moods: ["诗意", "温暖"]
      });

      const txtNode = makeTextInputNode(64, 588, {
        text: "二十四节气手绘东方茶席海报：{item}（第 {index} 期，统一暖米宣纸底色与留白呼吸感）"
      });

      const loopNode = makeLoopNode(488, 176, {
        loopMode: "prompts",
        promptItems: DEFAULT_LOOP_PROMPT_LINES
      });

      const ctrlNode = makeOutputControlNode(912, 188, {
        mode: "graphic-text",
        count: 1,
        ratio: "3:4"
      });

      nodes.push(spNode, txtNode, loopNode, ctrlNode);
      link(spNode, loopNode);
      link(txtNode, loopNode);
      link(loopNode, ctrlNode);

      return { blueprint: "loop", nodes, edges, selectedIds: [] };
    }

    // Default "single": Focused 3-Node Poster/Graphic Workflow (Skill Params + Text Input -> Output Control; NO empty unused nodes!)
    const spNode = makeSkillParamsNode(64, 52, {
      style1: "FA-003",
      layout: "SC-023",
      colors: ["C-15"],
      moods: ["诗意", "温暖"]
    });

    const txtNode = makeTextInputNode(64, 560, {
      text: "秋分节气 · 慢煮一壶桂花乌龙，茶人倚坐在白瓷盖碗旁看金桂飘落，温暖宣纸墨线与朱砂印章点睛"
    });

    const ctrlNode = makeOutputControlNode(488, 196, {
      mode: "poster",
      count: 1,
      ratio: "3:4"
    });

    nodes.push(spNode, txtNode, ctrlNode);
    link(spNode, ctrlNode);
    link(txtNode, ctrlNode);

    return { blueprint: "single", nodes, edges, selectedIds: [] };
  }

  /* ======================== LEFT-TO-RIGHT TOPOLOGICAL AUTO-ARRANGE ======================== */

  function autoArrangeGraph(graph) {
    const snapshot = (graph.nodes || []).map((n) => ({ id: n.id, x: n.x, y: n.y, w: n.w, h: n.h }));
    const topNodes = (graph.nodes || []).filter((n) => !n.groupId);
    const edges = graph.edges || [];

    // Column 0: Input Nodes (skill_params, asset, text_input, + standalone fission without upstream)
    // Column 1: Mid-stage Fission (when wired from upstream text_input)
    // Column 2: Loop / Bridge Nodes (loop, bridge) — skipped when empty
    // Column 3: Output Control Nodes (output_control)
    // Column 4: Article Plan Nodes + Direct Output Display Nodes (from output_control)
    // Column 5: Output Display Nodes connected downstream from Article Plan Nodes
    const columns = [[], [], [], [], [], []];
    for (const n of topNodes) {
      if (n.type === "article_plan") {
        columns[4].push(n);
      } else if (n.type === "output_display") {
        const upEdge = edges.find((e) => e.to === n.id);
        const upNode = upEdge ? topNodes.find((x) => x.id === upEdge.from) : null;
        if (upNode && upNode.type === "article_plan") {
          columns[5].push(n);
        } else {
          columns[4].push(n);
        }
      } else if (n.type === "output_control" || n.type === "generator") {
        columns[3].push(n);
      } else if (n.type === "bridge" || n.type === "loop") {
        columns[2].push(n);
      } else if (n.type === "fission") {
        const hasUpstream = edges.some((e) => e.to === n.id);
        columns[hasUpstream ? 1 : 0].push(n);
      } else {
        columns[0].push(n);
      }
    }

    const getParentYAndSlot = (n) => {
      const upEdge = edges.find((e) => e.to === n.id);
      const upNode = upEdge ? topNodes.find((x) => x.id === upEdge.from) : null;
      const py = upNode ? upNode.y : n.y;
      const slot = typeof n.data?.slotIndex === "number" ? n.data.slotIndex : 999;
      return { py, slot };
    };

    const typeOrder = { skill_params: 1, asset: 2, text_input: 3 };
    columns[0].sort((a, b) => (typeOrder[a.type] || 9) - (typeOrder[b.type] || 9) || a.y - b.y);
    columns[1].sort((a, b) => a.y - b.y);
    columns[2].sort((a, b) => a.y - b.y);
    columns[3].sort((a, b) => {
      const ma = getParentYAndSlot(a);
      const mb = getParentYAndSlot(b);
      return ma.py - mb.py || ma.slot - mb.slot || a.y - b.y;
    });
    columns[4].sort((a, b) => {
      const ma = getParentYAndSlot(a);
      const mb = getParentYAndSlot(b);
      return ma.py - mb.py || ma.slot - mb.slot || a.y - b.y;
    });

    let curX = 64;
    for (let cIdx = 0; cIdx < columns.length; cIdx++) {
      const col = columns[cIdx];
      if (!col.length) continue;

      let curY = 56;
      if (cIdx === 1 && columns[0].length >= 2) {
        curY = col.some((x) => x.type === "loop") ? 176 : 236;
      } else if (cIdx === 2 && !columns[1].length && col.length === 1 && columns[0].length >= 2) {
        curY = 176;
      }

      let maxW = cIdx === 1 ? 248 : 300;
      let lastParentId = null;
      for (const n of col) {
        n.x = curX;
        if (cIdx === 3 || cIdx === 4) {
          const upEdge = edges.find((e) => e.to === n.id);
          const upParent = upEdge ? topNodes.find((x) => x.id === upEdge.from) : null;
          if (upParent && upParent.id !== lastParentId) {
            if (col.length === 1) {
              curY = Math.max(curY, upParent.y);
            } else {
              curY = Math.max(curY, Math.max(48, upParent.y - 60));
            }
            lastParentId = upParent.id;
          }
        }
        n.y = curY;
        maxW = Math.max(maxW, n.w || 308);
        curY += (n.h || 280) + 32;
      }
      curX += maxW + 88;
    }

    return snapshot;
  }

  window.HANDRAW_CANVAS_ENGINE = {
    COLOR_FAMILIES,
    TONE_FAMILIES,
    SC021_PLAYSTYLES,
    WHITESPACE_OPTIONS,
    OUTPUT_MODES,
    LOOP_MODES,
    DEFAULT_LOOP_PROMPT_LINES,
    FISSION_STRATEGIES,
    PRESET_WORKFLOW_DEFS,
    generateFissionTopics,
    DEFAULT_MODE_RATIOS,
    RATIO_PRESETS,
    AUDIENCE_SUGGESTIONS,
    BUSINESS_SCENE_SUGGESTIONS,
    DEFAULT_MOOD_POOL,
    uid,
    colorMatchesFamily,
    DEFAULT_STARTER_ARTICLE_MD,
    makeSkillParamsNode,
    makeAssetNode,
    makeTextInputNode,
    makeBridgeNode,
    makeFissionNode,
    makeLoopNode,
    makeOutputControlNode,
    makeArticlePlanNode,
    makeOutputDisplayNode,
    expandUpstreamNodes,
    resolveControlRecipe,
    resolveLoopIterations,
    dedupeByIdOrImage,
    MAX_MERGED_REFS,
    assembleControlPrompt,
    // Alias for backward compatibility
    resolveGeneratorRecipe: resolveControlRecipe,
    assembleNodePrompt: assembleControlPrompt,
    buildSeriesSlidesSpec,
    buildXhsSlidesSpec: buildSeriesSlidesSpec,
    buildArticleSlotsSpec,
    parseArticleReadonlyBlocks,
    assembleArticleCardFullPrompt,
    buildArticlePlanData,
    buildArticlePlanFromAi,
    buildEditorSegments,
    createBlueprintGraph,
    autoArrangeGraph
  };
})();
