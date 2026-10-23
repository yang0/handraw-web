"use strict";
// Generated from the public Skill. Refresh with ops/refresh_studio.py.
const I18N = {
  zh: {
    pageTitle: "手绘 Skill 提示词拼装器",
    stylesNav: "风格画廊",
    layoutsNav: "图型画廊",
    colorsNav: "色彩画廊",
    assetsNav: "自建图库",
    tutorialsNav: "提示词",
    wechatBtn: "💬 创作变现交流群",
    assemblerTitle: "🛠️ 提示词拼装器",
    assemblerSub: "交互式点选图型、风格与色彩，实时拼装出图指令。",
    fusionCheckboxLabel: "风格融合",
    toneCheckboxLabel: "影调",
    batchCheckboxLabel: "批量出图",
    mixLayoutsCheckboxLabel: "混合多种图型",
    step1Title: "出图模式与留白",
    step2Title: "画面主题与内容",
    step3Title: "画幅比例与情绪",
    step4Title: "视觉资产与风格搭配",
    step5Title: "拼装生成的出图指令",
    assetsTrayTitle: "自建图库",
    assetsTrayDesc:
      "可选 · 支持多选跨媒介参考图（垫图），出图时保持主体视觉绝对一致",
    assetsEmptyText:
      "点击按图添加自建资产（支持同时多选角色 IP、道具 PR、场景 SCN 基准图）",
    addAssetsBtn: "添加自建资产",
    clearAssetsBtn: "清空已选资产",
    modalAssetClearBtn: "清空全部",
    modalAssetConfirmBtn: "完成选择",
    modeLabel: "出图模式：",
    modePure: "纯图",
    modeGraphicText: "图文",
    modePoster: "海报",
    modeArticleIllust: "文章插图",
    modeArticleCover: "文章封面",
    modePhoto: "摄影",
    whitespaceLabel: "留白：",
    whitespaceNormal: "正常",
    whitespaceModerate: "适中",
    whitespaceHigh: "多",
    whitespaceModeratePrompt: "【大量留白】",
    whitespaceHighPrompt: "【大量留白，场景只显示必要部分，不要显示全】",
    themeLabel: "主题：",
    articlePathLabel: "文件或文件夹地址：",
    articleCoverPathLabel: "文件/文件夹地址或内容：",
    shootTypeLabel: "拍摄类型：",
    audienceLabel: "受众：",
    channelLabel: "海报投放渠道：",
    themePlaceholder:
      "输入画面主题，亦可输入本地文件或文件夹路径（例如：秋天的第一杯奶茶 / 窗台晒太阳的猫咪，或 D:\\path\\to\\...）...",
    themePhotoPlaceholder:
      "选填：输入特定主题或场景，亦可输入本地文件或文件夹路径（如：海边夕阳 / 90年代港风），不填由AI推荐...",
    articlePathPlaceholder:
      "请输入本地文件或文件夹绝对路径（支持单篇或批量配图，例如：D:\\path\\to\\article.md 或文件夹）...",
    articleCoverPathPlaceholder:
      "请输入本地文件或文件夹绝对路径（例如：D:\\path\\to\\article.md），或直接粘贴文章内容...",
    articleCoverFixedPrompt:
      "先设计隐喻再出图，主标题明显，小字少或者没有小字。 其他你帮我设计。",
    shootTypePlaceholder: "点选上方标签，或手动输入/修改拍摄类型...",
    shootTypeCouple: "情侣",
    shootTypeWedding: "婚纱",
    shootTypeSolo: "个人写真",
    shootTypeFamily: "亲子全家福",
    shootTypeHanfu: "古风汉服",
    shootTypeNewChinese: "新中式",
    shootTypeVintageHK: "复古港风",
    shootTypeCosplay: "Cosplay",
    shootTypeTravel: "旅行抓拍",
    shootTypeCareer: "职场肖像",
    audiencePlaceholder: "例如：年轻都市白领 / 露营爱好者 / 亲子家庭...",
    channelPlaceholder: "例如：小红书 / 微信公众号封面 / 线下门店立牌...",
    ratioLabel: "画幅比例：",
    ratioPlaceholder: "输入或点击上方预设，例如：3:4、5:2、1:1（可手填）",
    presetXiaohongshu: "小红书/公众号贴图 (3:4)",
    presetWechatCover: "公众号封面 (2.35:1)",
    presetXCover: "X文章封面 (5:2)",
    presetArticleIllust: "文章插图 (4:3)",
    presetSquare: "方块 (1:1)",
    presetVerticalStory: "手机全屏 (9:16)",
    moodLabel: "情绪：",
    moodPlaceholder: "输入或点选上方情绪（可多选，例如：治愈、松弛）",
    moodHealing: "治愈",
    moodRelaxed: "松弛",
    moodHumorous: "幽默",
    moodPoetic: "诗意",
    moodRomantic: "浪漫",
    moodVibrant: "活力",
    moodMelancholy: "微丧",
    moodChildlike: "童趣",
    moodSolitary: "孤寂",
    moodTense: "紧张",
    moodSolemn: "庄严",
    moodAbsurd: "荒诞",
    moodEerie: "恐怖",
    moodMysterious: "神秘",
    moodIntense: "激烈",
    slotAsset: "自建资产",
    slotLayout: "图型",
    slotStyle: "风格",
    slotCharStyle: "角色风格",
    slotSceneStyle: "场景风格",
    slotColor: "主题色",
    slotTone: "影调",
    optional: "可选",
    optionalAsset: "可选 (1)",
    optionalLayout: "可选 (168)",
    optionalStyle: "可选 (366 / 写实)",
    optionalCharStyle: "可选 (风格/写实)",
    optionalSceneStyle: "可选 (风格/写实)",
    optionalColor: "可选 (36)",
    optionalTone: "可选 (16) · 多选",
    layoutNotApplicable: "不适用",
    pickAssetText: "按图选择自建资产",
    pickLayoutText: "按图选择图型 (168)",
    pickStyleText: "按图选择风格 / 写实 (366)",
    pickCharStyleText: "按图选择角色风格",
    pickSceneStyleText: "按图选择场景风格",
    pickColorText: "按图选择主题色 (36)",
    pickToneText: "按图选择影调 (16)",
    changeBtn: "更换",
    gachaBtn: "智能随机抽卡",
    resetBtn: "一键清空",
    outputTitle: "📋 拼装生成的出图指令：",
    copyPromptBtn: "复制出图指令",
    copied: "已复制！",
    guidesTitle: "📖 实战思维与技巧说明",
    formulaLabel: "示例提示词：",
    searchPlaceholder: "输入编号或名称过滤...",
    pickerTitleAsset: "选择视觉资产（角色 / 道具 / 场景）",
    pickerTitleLayout: "选择图型 (168)",
    pickerTitleStyle: "选择手绘与写实风格 (366)",
    pickerTitleCharStyle: "选择角色风格",
    pickerTitleSceneStyle: "选择场景风格",
    styleConflictAlert: "角色风格与场景风格必须不同，请选择不同的风格！",
    pickerTitleColor: "选择主题色 (36)",
    pickerTitleTone: "选择影调 (16 · 可多选)",
    modalToneCount: "已选择 {count} 项影调",
    filterToneKey: "明暗阶调",
    filterToneContrast: "反差过渡",
    filterToneAtmosphere: "氛围风格",
    filterAll: "全部",
    filterCharacters: "角色库",
    filterProps: "道具库",
    filterScenes: "场景库",
    filterSocialCard: "社媒卡 (SC)",
    filterInfographic: "信息图 (IG)",
    filterComicStoryboard: "漫画分镜 (SB)",
    filterIpCharacter: "IP设计 (IP)",
    filterEcommerce: "电商 (EC)",
    filterBlue: "经典蓝系",
    filterGreen: "清新绿系",
    filterRed: "古典红绿",
    filterPurple: "浪漫粉紫",
    filterWarm: "暖阳大地",
    filterNeutral: "中性色系",
    fallbackPrompt: "其他你帮我选择",
    themeEmptyText: "【输入主题】",
    articlePathEmptyText: "【输入文件或文件夹地址】",
    audienceEmptyText: "【输入受众】",
    channelEmptyText: "【输入海报投放渠道】",
    wechatTitle: "💬 创作变现交流群",
    wechatSub: "请优先加群，满了的话也可以尝试加我个人微信",
    wechatNote: "请备注：手绘",
    wechatGroupLabel: "① 优先加入群聊",
    wechatPersonalLabel: "② 个人微信备用",
    langBtn: "🌐 English",
  },
  en: {
    pageTitle: "Prompt Assembler | Handraw Style Prompter",
    stylesNav: "Styles",
    layoutsNav: "Layouts",
    colorsNav: "Colors",
    assetsNav: "Custom Library",
    tutorialsNav: "Prompts",
    wechatBtn: "💬 Creator Community",
    assemblerTitle: "🛠️ Prompt Assembler",
    assemblerSub:
      "Visually select layout, style, and color to assemble prompt commands in real time.",
    fusionCheckboxLabel: "Style Fusion",
    toneCheckboxLabel: "Tone",
    batchCheckboxLabel: "Batch Generation",
    mixLayoutsCheckboxLabel: "Mix Multiple Layouts",
    step1Title: "Mode & Negative Space",
    step2Title: "Theme & Content",
    step3Title: "Aspect Ratio & Mood",
    step4Title: "Visual Assets & Style Composition",
    step5Title: "Generated Prompt Command",
    assetsTrayTitle: "Custom Library",
    assetsTrayDesc:
      "Optional · Multi-select reference images to maintain consistent character, prop, and scene appearance",
    assetsEmptyText:
      "Click to select visual benchmark assets (Multi-select characters, props, scenes)",
    addAssetsBtn: "Add Assets",
    clearAssetsBtn: "Clear Assets",
    modalAssetClearBtn: "Clear All",
    modalAssetConfirmBtn: "Done",
    modeLabel: "Mode:",
    modePure: "Image Only",
    modeGraphicText: "Graphic-Text",
    modePoster: "Poster",
    modeArticleIllust: "Article Illustration",
    modeArticleCover: "Article Cover",
    modePhoto: "Photography",
    whitespaceLabel: "Negative Space:",
    whitespaceNormal: "Normal",
    whitespaceModerate: "Moderate",
    whitespaceHigh: "Generous",
    whitespaceModeratePrompt: "[Generous negative space]",
    whitespaceHighPrompt:
      "[Generous negative space, scene shows only essential parts, do not show in full]",
    themeLabel: "Theme:",
    articlePathLabel: "File or Folder Path:",
    articleCoverPathLabel: "File / Folder Path or Text:",
    shootTypeLabel: "Shoot Type:",
    audienceLabel: "Audience:",
    channelLabel: "Distribution Channel:",
    themePlaceholder:
      "Enter theme, or local file/folder path (e.g. Autumn milk tea / Cat on windowsill, or D:\\path\\to\\dir)...",
    themePhotoPlaceholder:
      "Optional: Enter specific theme or setting, or local file/folder path (e.g. Sunset beach / Vintage cafe), or leave empty for AI recommendation...",
    articlePathPlaceholder:
      "Enter absolute local file or folder path (supports single or batch illustration, e.g. D:\\path\\to\\article.md or folder)...",
    articleCoverPathPlaceholder:
      "Enter absolute local file or folder path (e.g. D:\\path\\to\\article.md), or paste article text...",
    articleCoverFixedPrompt:
      "Design a visual metaphor first, then generate the image. Ensure the main title is bold and prominent, with few or no small text. Pick the rest of the design for me.",
    shootTypePlaceholder: "Click tags above, or type/edit shoot type...",
    shootTypeCouple: "Couple",
    shootTypeWedding: "Wedding",
    shootTypeSolo: "Solo Portrait",
    shootTypeFamily: "Family",
    shootTypeHanfu: "Ancient Hanfu",
    shootTypeNewChinese: "New Chinese",
    shootTypeVintageHK: "Vintage HK",
    shootTypeCosplay: "Cosplay",
    shootTypeTravel: "Travel Snapshot",
    shootTypeCareer: "Professional Portrait",
    audiencePlaceholder:
      "e.g. Young urban professionals / Campers / Families...",
    channelPlaceholder: "e.g. Instagram / RED / Store poster stand...",
    ratioLabel: "Aspect Ratio:",
    ratioPlaceholder:
      "Enter or click preset, e.g. 3:4, 5:2, 1:1 (customizable)",
    presetXiaohongshu: "RED / WeChat Sticker (3:4)",
    presetWechatCover: "WeChat Official Cover (2.35:1)",
    presetXCover: "X Article Cover (5:2)",
    presetArticleIllust: "Article Illustration (4:3)",
    presetSquare: "Square (1:1)",
    presetVerticalStory: "Full Screen (9:16)",
    moodLabel: "Mood:",
    moodPlaceholder: "Type or pick moods (e.g. Healing, Relaxed)",
    moodHealing: "Healing",
    moodRelaxed: "Relaxed",
    moodHumorous: "Humorous",
    moodPoetic: "Poetic",
    moodRomantic: "Romantic",
    moodVibrant: "Vibrant",
    moodMelancholy: "Melancholy",
    moodChildlike: "Childlike",
    moodSolitary: "Solitary",
    moodTense: "Tense",
    moodSolemn: "Solemn",
    moodAbsurd: "Absurd",
    moodEerie: "Eerie",
    moodMysterious: "Mysterious",
    moodIntense: "Intense",
    slotAsset: "Asset",
    slotLayout: "Layout",
    slotStyle: "Style",
    slotCharStyle: "Character Style",
    slotSceneStyle: "Scene Style",
    slotColor: "Theme Color",
    slotTone: "Tone",
    optional: "Optional",
    optionalAsset: "Optional (1)",
    optionalLayout: "Optional (168)",
    optionalStyle: "Optional (366 / Realistic)",
    optionalCharStyle: "Optional (Style/Realistic)",
    optionalSceneStyle: "Optional (Style/Realistic)",
    optionalColor: "Optional (36)",
    optionalTone: "Optional (16) · Multi",
    layoutNotApplicable: "N/A",
    pickAssetText: "Pick Custom Asset",
    pickLayoutText: "Pick Layout (168)",
    pickStyleText: "Pick Style / Realistic (366)",
    pickCharStyleText: "Pick Character Style",
    pickSceneStyleText: "Pick Scene Style",
    pickColorText: "Pick Theme Color (36)",
    pickToneText: "Pick Visual Tone (16)",
    changeBtn: "Change",
    gachaBtn: "Random Gacha",
    resetBtn: "Reset All",
    outputTitle: "📋 Assembled Generation Command:",
    copyPromptBtn: "Copy Command",
    copied: "Copied!",
    guidesTitle: "📖 Practical Guides & Principles",
    formulaLabel: "Example Prompt:",
    searchPlaceholder: "Search ID or name...",
    pickerTitleAsset: "Select Visual Asset (Character / Prop / Scene)",
    pickerTitleLayout: "Select Layout (168)",
    pickerTitleStyle: "Select Style / Realistic (366)",
    pickerTitleCharStyle: "Select Character Style",
    pickerTitleSceneStyle: "Select Scene Style",
    styleConflictAlert: "Character style and scene style must be different!",
    pickerTitleColor: "Select Theme Color (36)",
    pickerTitleTone: "Select Tone (16 · Multi-select)",
    modalToneCount: "{count} Tone(s) Selected",
    filterToneKey: "Key & Exposure",
    filterToneContrast: "Contrast & Transition",
    filterToneAtmosphere: "Atmosphere & Style",
    filterAll: "All",
    filterCharacters: "Characters",
    filterProps: "Props",
    filterScenes: "Scenes",
    filterSocialCard: "Social Cards (SC)",
    filterInfographic: "Infographics (IG)",
    filterComicStoryboard: "Comic Storyboards (SB)",
    filterIpCharacter: "IP Design (IP)",
    filterEcommerce: "E-commerce (EC)",
    filterBlue: "Classic Blue",
    filterGreen: "Fresh Green",
    filterRed: "Classic Red & Vintage",
    filterPurple: "Romantic Pink & Purple",
    filterWarm: "Warm Sun & Earth",
    filterNeutral: "Classic Neutral Tones",
    fallbackPrompt: "pick the rest for me",
    themeEmptyText: "[Enter Theme]",
    articlePathEmptyText: "[Enter File or Folder Path]",
    audienceEmptyText: "[Enter Audience]",
    channelEmptyText: "[Enter Channel]",
    wechatTitle: "💬 Creator Monetization Community",
    wechatSub:
      "Please prioritize joining the group; if full, try adding personal WeChat",
    wechatNote: "Note: handdraw",
    wechatGroupLabel: "① Join Group (Priority)",
    wechatPersonalLabel: "② Personal WeChat (Fallback)",
    langBtn: "🌐 中文",
  },
};

window.HandrawComposerCommand = (
  draft,
  resources,
  options,
  language = "zh",
) => {
  const currentLang = language === "en" ? "en" : "zh";
  const currentMode = draft.mode || "pure",
    currentWhitespace = draft.whitespace || "normal";
  const find = (id) =>
    id === "realistic"
      ? { id, isRealistic: true }
      : resources.find((item) => item.id === id) || null;
  const selectedStyle = find(draft.style),
    selectedCharStyle = find(draft.character_style),
    selectedSceneStyle = find(draft.scene_style);
  const selectedLayout = find(draft.layout),
    selectedColor = find(draft.color);
  const selectedAssets = [
    ...(draft.asset_refs || []).map((id) => ({ id })),
    ...(draft.references || []).map((item) => ({
      id: item.name,
      cat: item.role,
    })),
  ];
  const selectedTones = (draft.tones || [])
    .map((id) => options.tones.find((item) => item.id === id))
    .filter(Boolean)
    .map((item) => ({ ...item, name: item.name_zh }));
  const isFusionActive = !!draft.fusion,
    isToneActive = selectedTones.length > 0,
    isBatchActive = !!draft.batch,
    isMixLayoutsActive = !!draft.mix_layouts;
  const inputTheme = { value: draft.theme || "" },
    inputAudience = { value: draft.audience || "" },
    inputChannel = { value: draft.channel || "" };
  const inputRatio = { value: draft.ratio || "" },
    inputMood = { value: draft.mood || "" },
    inputShootType = { value: draft.shoot_type || "" };
  const assembledText = { textContent: "" };
  function updatePrompt() {
    const isZh = currentLang === "zh";
    const t = I18N[currentLang];

    const parts = [];

    // Prefix based on mode / fusion
    if (isFusionActive) {
      parts.push(isZh ? "【风格融合设计】" : "[Style Fusion Design]");
      if (currentMode === "poster") {
        parts.push(isZh ? "海报模式" : "Poster mode");
      } else if (currentMode === "graphic-text") {
        parts.push(isZh ? "图文模式" : "Graphic-text mode");
      } else if (currentMode === "article-illust") {
        parts.push(isZh ? "文章插图模式" : "Article illustration mode");
      } else if (currentMode === "article-cover") {
        parts.push(isZh ? "文章封面模式" : "Article cover mode");
      } else if (currentMode === "photo") {
        parts.push(
          isZh
            ? "摄影写真模式，请先出3个方案供我挑选"
            : "Photo portrait mode, please first propose 3 candidate directions for me to choose from",
        );
      }
    } else {
      if (currentMode === "poster") {
        parts.push(
          isZh
            ? "请帮我出海报提示词"
            : "Please generate a poster prompt for me",
        );
      } else if (currentMode === "graphic-text") {
        parts.push(isZh ? "图文模式" : "Graphic-text mode");
      } else if (currentMode === "article-illust") {
        parts.push(isZh ? "文章插图模式" : "Article illustration mode");
      } else if (currentMode === "article-cover") {
        parts.push(isZh ? "请设计文章封面" : "Please design an article cover");
      } else if (currentMode === "photo") {
        parts.push(
          isZh
            ? "摄影写真模式，请先出3个方案供我挑选"
            : "Photo portrait mode, please first propose 3 candidate directions for me to choose from",
        );
      }
    }

    // Assets (Characters / Props / Scenes)
    if (selectedAssets && selectedAssets.length > 0) {
      const charIds = [];
      const propIds = [];
      const sceneIds = [];
      selectedAssets.forEach((a) => {
        if (a.id.startsWith("PR-") || a.cat === "props") {
          propIds.push(a.id);
        } else if (a.id.startsWith("SCN-") || a.cat === "scenes") {
          sceneIds.push(a.id);
        } else {
          charIds.push(a.id);
        }
      });
      const joinSep = isZh ? "、" : ", ";
      if (charIds.length > 0) {
        parts.push(
          isZh
            ? `角色：${charIds.join(joinSep)}`
            : `Character: ${charIds.join(joinSep)}`,
        );
      }
      if (propIds.length > 0) {
        parts.push(
          isZh
            ? `道具：${propIds.join(joinSep)}`
            : `Prop: ${propIds.join(joinSep)}`,
        );
      }
      if (sceneIds.length > 0) {
        parts.push(
          isZh
            ? `场景：${sceneIds.join(joinSep)}`
            : `Scene: ${sceneIds.join(joinSep)}`,
        );
      }
    }

    // Layout
    if (
      selectedLayout &&
      currentMode !== "article-illust" &&
      currentMode !== "article-cover"
    ) {
      parts.push(
        isZh ? `图型：${selectedLayout.id}` : `Layout: ${selectedLayout.id}`,
      );
    }

    // Style(s)
    if (isFusionActive) {
      if (selectedCharStyle) {
        const charName = selectedCharStyle.isRealistic
          ? isZh
            ? "写实"
            : "Realistic"
          : selectedCharStyle.id;
        parts.push(
          isZh ? `角色风格：${charName}` : `Character style: ${charName}`,
        );
      }
      if (selectedSceneStyle) {
        const sceneName = selectedSceneStyle.isRealistic
          ? isZh
            ? "写实"
            : "Realistic"
          : selectedSceneStyle.id;
        parts.push(
          isZh ? `场景风格：${sceneName}` : `Scene style: ${sceneName}`,
        );
      }
    } else {
      if (selectedStyle) {
        const styleName = selectedStyle.isRealistic
          ? isZh
            ? "写实"
            : "Realistic"
          : selectedStyle.id;
        parts.push(isZh ? `风格：${styleName}` : `Style: ${styleName}`);
      }
    }

    // Theme color
    if (selectedColor) {
      parts.push(
        isZh
          ? `主题色：${selectedColor.id}`
          : `Theme color: ${selectedColor.id}`,
      );
    }

    // Tone(s)
    if (isToneActive && selectedTones && selectedTones.length > 0) {
      const toneParts = selectedTones.map((t) =>
        isZh ? `${t.name} (${t.id})` : `${t.name_en || t.name} (${t.id})`,
      );
      const sep = isZh ? "、" : ", ";
      parts.push(
        isZh ? `影调：${toneParts.join(sep)}` : `Tone: ${toneParts.join(sep)}`,
      );
    }

    // Aspect ratio (optional, default empty)
    const ratioVal = inputRatio ? inputRatio.value.trim() : "";
    if (ratioVal) {
      parts.push(isZh ? `画幅比例：${ratioVal}` : `Aspect ratio: ${ratioVal}`);
    }

    // Mood (optional, default empty)
    const moodVal = inputMood ? inputMood.value.trim() : "";
    if (moodVal) {
      parts.push(isZh ? `情绪：${moodVal}` : `Mood: ${moodVal}`);
    }

    // Whitespace (negative space)
    if (currentWhitespace === "moderate") {
      parts.push(t.whitespaceModeratePrompt);
    } else if (currentWhitespace === "high") {
      parts.push(t.whitespaceHighPrompt);
    }

    // Fallback: if style OR color is missing, inject "其他你帮我选择"
    const missingStyleOrColor = isFusionActive
      ? !selectedCharStyle || !selectedSceneStyle || !selectedColor
      : !selectedStyle || !selectedColor;
    if (missingStyleOrColor) {
      parts.push(t.fallbackPrompt);
    }

    // Theme or Article File Path
    const themeVal = inputTheme.value.trim();
    if (currentMode === "article-illust") {
      const articleDisplay = themeVal || t.articlePathEmptyText;
      parts.push(
        isZh
          ? `文件或文章地址：${articleDisplay}`
          : `File or article path: ${articleDisplay}`,
      );
    } else if (currentMode === "article-cover") {
      const articleDisplay =
        themeVal ||
        (isZh
          ? "【输入文件/文件夹地址或文章内容】"
          : "[Enter file/folder path or article text]");
      parts.push(
        isZh ? `文章：${articleDisplay}` : `Article: ${articleDisplay}`,
      );
      let scenario = isZh ? "公众号文章封面" : "WeChat Official Account Cover";
      if (ratioVal === "5:2" || ratioVal === "16:9")
        scenario = isZh ? "X文章封面" : "X Article Cover";
      else if (ratioVal === "3:4")
        scenario = isZh ? "小红书封面" : "Xiaohongshu Cover";
      else if (ratioVal === "2.35:1" || ratioVal === "21:9")
        scenario = isZh ? "公众号文章封面" : "WeChat Official Account Cover";
      parts.push(isZh ? `业务场景：${scenario}` : `Scenario: ${scenario}`);
    } else if (currentMode === "photo") {
      const shootTypeVal = inputShootType ? inputShootType.value.trim() : "";
      if (shootTypeVal) {
        parts.push(
          isZh ? `拍摄类型：${shootTypeVal}` : `Shoot type: ${shootTypeVal}`,
        );
      }
      if (themeVal) {
        parts.push(isZh ? `主题：${themeVal}` : `Theme: ${themeVal}`);
      }
    } else {
      const themeDisplay = themeVal || t.themeEmptyText;
      parts.push(isZh ? `主题：${themeDisplay}` : `Theme: ${themeDisplay}`);
    }

    // Extra fields for poster mode
    if (currentMode === "poster") {
      const audienceVal = inputAudience.value.trim();
      const audienceDisplay = audienceVal || t.audienceEmptyText;
      parts.push(
        isZh ? `受众：${audienceDisplay}` : `Audience: ${audienceDisplay}`,
      );

      const channelVal = inputChannel.value.trim();
      const channelDisplay = channelVal || t.channelEmptyText;
      parts.push(
        isZh ? `海报投放渠道：${channelDisplay}` : `Channel: ${channelDisplay}`,
      );
    }

    const delimiter = isZh ? "，" : ", ";
    let promptText = parts.join(delimiter);
    if (isBatchActive) {
      promptText += isZh ? " | 批量出图" : " | Batch Generation";
      if (isMixLayoutsActive) {
        promptText += isZh ? " | 混合多种图型" : " | Mix Multiple Layouts";
      }
    }
    assembledText.textContent = promptText;
  }

  updatePrompt();
  return assembledText.textContent;
};
