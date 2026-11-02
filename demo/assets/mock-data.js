/* Rich Mockup Data for Handraw Web 2.0 Interactive Prototype
 * All image paths map to real verified WebP assets in /images/* via serve_demo.py.
 */
(function () {
  const EXCLUSIVE_RESOURCES = [
    {
      id: "FX-001",
      kind: "style",
      sourceType: "exclusive",
      tier: "login_free",
      unlockCost: 0,
      name: "朱砂金箔东方节气社论风",
      group: "FX 在线独占画风 / Cloud Exclusive",
      description: "官网在线独占（登录免费可用）：温润宣纸纤维底纹、克制朱砂与哑光金箔点染、现代东方节气海报叙事与大留白微排版。",
      definition: "[CLOUD_BLACKBOX::FX-001] 仅限在线创作工坊云端生图时自动注入底层 18 项笔触与宣纸金箔质感锚点，不对外导出明文提示词。",
      image: "/images/poster-demo-autumn-equinox.webp",
      featuredWorksBonus: 18
    },
    {
      id: "FX-002",
      kind: "style",
      sourceType: "exclusive",
      tier: "login_free",
      unlockCost: 0,
      name: "丝网错版双色独立书店插画",
      group: "FX 在线独占画风 / Cloud Exclusive",
      description: "官网在线独占（登录免费可用）：高纯度孔版双色油墨叠印、0.8mm 自然错版边缘、粗颗粒特种纸肌理与独立刊物视觉张力。",
      definition: "[CLOUD_BLACKBOX::FX-002] 仅限在线创作工坊云端生图自动注入双色分版与网点颗粒曲线。",
      image: "/images/graphic-text-mode-demo.webp",
      featuredWorksBonus: 11
    },
    {
      id: "FX-003",
      kind: "style",
      sourceType: "exclusive",
      tier: "pro_credit",
      unlockCost: 15,
      name: "复古银盐暗房手作拼贴画报",
      group: "FX 在线独占画风 / Cloud Exclusive",
      description: "Pro 独占画风（15 积分永久解锁）：银盐相纸显影化学边缘、手工撕贴牛皮纸标签、冷暖反差戏剧光感与电影文学叙事。",
      definition: "[CLOUD_BLACKBOX::FX-003] Pro 级商业画报黑盒风格矩阵，云端生图时自动挂载暗房显影质感控制参数。",
      image: "/images/realistic.webp",
      featuredWorksBonus: 9
    },
    {
      id: "FX-004",
      kind: "style",
      sourceType: "exclusive",
      tier: "pro_credit",
      unlockCost: 15,
      name: "京都木版水印浮世绘现代商业版",
      group: "FX 在线独占画风 / Cloud Exclusive",
      description: "Pro 独占画风（15 积分永久解锁）：梨木刀刻硬朗墨线、植物矿物水性颜料马连擦印渐变、现代都市商业消费场景转译。",
      definition: "[CLOUD_BLACKBOX::FX-004] Pro 级木版水印色彩分离与版木纹理控制，仅支持在线云端合成。",
      image: "/images/E_124-139.webp",
      featuredWorksBonus: 7
    },
    {
      id: "LX-001",
      kind: "layout",
      sourceType: "exclusive",
      tier: "login_free",
      unlockCost: 0,
      name: "三段式杂志封面级痛点拆解卡",
      group: "social-card",
      description: "官网在线独占图型（登录免费可用）：刊头极简书眉 + 黄金分割巨幅视觉锚点 + 底部三栏胶囊结论，小红书高赞干货封面实测高点击结构。",
      definition: "[CLOUD_BLACKBOX::LX-001] 在线独占排版骨架，云端生图时自动锁定刊头字距、中景留白比与三栏对齐网格。",
      image: "/images/layouts/social-cards/SC-023.webp",
      featuredWorksBonus: 14
    },
    {
      id: "LX-002",
      kind: "layout",
      sourceType: "exclusive",
      tier: "pro_credit",
      unlockCost: 15,
      name: "全景折叠长卷式品牌故事分镜图",
      group: "comic-storyboard",
      description: "Pro 独占图型（15 积分永久解锁）：Z 字形跨格视线引导、无边框建筑剖面与微缩人物叙事流，适合品牌首发长图与主视觉提案。",
      definition: "[CLOUD_BLACKBOX::LX-002] Pro 级跨格连续叙事排版引擎，仅支持在线创作台云端渲染。",
      image: "/images/layouts/comic-storyboards/SB-004.webp",
      featuredWorksBonus: 6
    }
  ];

  const COMMUNITY_RESOURCES = [
    {
      id: "USR-S05",
      kind: "style",
      sourceType: "community",
      tier: "free",
      unlockCost: 0,
      author: "su_editorial",
      authorName: "苏苏的纸上茶馆",
      createdAt: "18 分钟前",
      isNewRelease: true,
      cheers: 19,
      name: "江南梅雨季宣纸淡墨小景",
      group: "USR 社区共创画风 / Community",
      description: "新发共创画风：湿润生宣渗墨微晕、青瓦屋檐雨丝细线、大面积呼吸感纸白与温润诗意小景。",
      definition: "#USR-S05 江南梅雨季宣纸淡墨小景。核心特征：生宣微渗淡墨轮廓、细柔青灰水彩晕染、克制赭石与嫩竹绿点染、60%留白呼吸感。",
      image: "/images/individual/FB/FB-002.webp"
    },
    {
      id: "USR-S04",
      kind: "style",
      sourceType: "community",
      tier: "free",
      unlockCost: 0,
      author: "yang0",
      authorName: "Yang · 创作者",
      createdAt: "1 小时前",
      isNewRelease: true,
      cheers: 27,
      name: "暖调木刻藏书票手绘版画",
      group: "USR 社区共创画风 / Community",
      description: "新发共创画风：手工梨木排刀肌理、暖棕松烟墨套印朱砂红边框，适合人文专栏封面与独立品牌书签。",
      definition: "#USR-S04 暖调木刻藏书票手绘版画。核心特征：手工木刻平行刀触排线、古籍棉纸暖米底色、松烟褐与朱砂红双色套印。",
      image: "/images/individual/FH/FH-002.webp"
    },
    {
      id: "USR-S03",
      kind: "style",
      sourceType: "community",
      tier: "free",
      unlockCost: 0,
      author: "lin_sketch",
      authorName: "林默 · 独立插画师",
      createdAt: "3 小时前",
      isNewRelease: true,
      cheers: 38,
      name: "敦煌矿物青绿岩彩绘本风",
      group: "USR 社区共创画风 / Community",
      description: "新发共创画风：天然石青石绿粗颗粒矿物色层、铁线描勾勒与温润土黄壁画肌理，叙事张力十足。",
      definition: "#USR-S03 敦煌矿物青绿岩彩绘本风。核心特征：天然矿物颜料颗粒层叠、石青石绿与朱膘暖土黄对比、中式铁线描造型。",
      image: "/images/individual/FE/FE-002.webp"
    },
    {
      id: "USR-S01",
      kind: "style",
      sourceType: "community",
      tier: "free",
      unlockCost: 0,
      author: "lin_sketch",
      authorName: "林默 · 独立插画师",
      createdAt: "2 天前",
      isNewRelease: false,
      cheers: 86,
      name: "老上海月份牌淡彩摩登速写",
      group: "USR 社区共创画风 / Community",
      description: "社区共创精选：炭精粉柔和擦笔晕染配钢笔细钩线，温润旧画报纸色与复古摩登生活物件表现。",
      definition: "#USR-S01 老上海月份牌淡彩摩登速写。核心特征：细腻炭精粉柔和过渡、复古石印海报暖黄纸感、钢笔淡彩勾勒人物服饰褶皱、克制胭脂红与湖蓝撞色。",
      image: "/images/individual/FD/FD-002.webp"
    },
    {
      id: "USR-S02",
      kind: "style",
      sourceType: "community",
      tier: "pro_credit",
      unlockCost: 8,
      author: "momo_design",
      authorName: "沫沫视觉实验室",
      createdAt: "3 天前",
      isNewRelease: false,
      cheers: 64,
      name: "高噪点酸性复古黑胶封面涂鸦",
      group: "USR 社区共创画风 / Community",
      description: "创作者定价 8 积分（解锁费 80% 归原作者）：70s 迷幻摇滚黑胶封套折痕、荧光橙绿高反差平涂与粗粝复印机碳粉颗粒。",
      definition: "#USR-S02 高噪点酸性复古黑胶封面涂鸦。核心特征：复印机高对比碳粉颗粒、黑胶唱片封套压痕磨损、怪诞橡皮管涂鸦角色、荧光橙与松石绿撞色。",
      image: "/images/individual/FC/FC-003.webp"
    },
    {
      id: "USR-L04",
      kind: "layout",
      sourceType: "community",
      tier: "free",
      unlockCost: 0,
      author: "brand_zhou",
      authorName: "周周品牌提案室",
      createdAt: "25 分钟前",
      isNewRelease: true,
      cheers: 17,
      name: "痛点三连问封面爆款钩子卡",
      group: "social-card",
      description: "新发共创图型：顶部 3 枚手绘对话气泡抛出读者痛点 + 中央视觉反转主图 + 底部解决方案红章锚点。",
      definition: "痛点三连问社媒封面卡：上部错落排布 3 枚手写提问气泡直击痛点，中部 55% 展示反差核心插画，底部通栏单句结论胶囊。",
      image: "/images/layouts/social-cards/SC-024.webp"
    },
    {
      id: "USR-L03",
      kind: "layout",
      sourceType: "community",
      tier: "free",
      unlockCost: 0,
      author: "momo_design",
      authorName: "沫沫视觉实验室",
      createdAt: "2 小时前",
      isNewRelease: true,
      cheers: 29,
      name: "播客金句黑胶歌词单页签",
      group: "social-card",
      description: "新发共创图型：上方圆形视窗或方形画框 + 下方打字机时间轴金句排版，极适合播客与读书笔记传播。",
      definition: "播客金句画报页签排版：上方居中方形手绘主视觉配细线外框，下方留白区排印时间戳进度条与双引号核心金句。",
      image: "/images/layouts/social-cards/SC-025.webp"
    },
    {
      id: "USR-L02",
      kind: "layout",
      sourceType: "community",
      tier: "free",
      unlockCost: 0,
      author: "pm_chen",
      authorName: "阿陈做产品",
      createdAt: "5 小时前",
      isNewRelease: true,
      cheers: 41,
      name: "方法论四象限手绘拆解矩阵",
      group: "infographic",
      description: "新发共创图型：十字手绘坐标轴划分四个决策象限，每格配微缩图标与两行结论，干货收藏率极高。",
      definition: "手绘四象限决策信息图：顶部通栏主标题，中部手绘十字箭头坐标轴分隔四大象限卡片，右上黄金象限以暖朱砂底高亮。",
      image: "/images/layouts/infographics/IG-004.webp"
    },
    {
      id: "USR-L01",
      kind: "layout",
      sourceType: "community",
      tier: "free",
      unlockCost: 0,
      author: "pm_chen",
      authorName: "阿陈做产品",
      createdAt: "2 天前",
      isNewRelease: false,
      cheers: 92,
      name: "红黑榜左右PK决策对比信息卡",
      group: "infographic",
      description: "社区共创图型：顶部一句话避坑结论 + 左灰冷色调踩雷区 vs 右暖朱砂红推荐区 + 底部 3 条选购铁律。",
      definition: "小红书红黑榜左右PK决策卡：顶部通栏大字号反差标题；中部严格 5:5 左右双栏对照，左侧低饱和灰蓝标注『别买/踩坑』3项，右侧暖米白配朱砂红勾号标注『闭眼入』3项；底部单行总结胶囊。",
      image: "/images/layouts/infographics/IG-005.webp"
    }
  ];

  // 20 Realistic Community Works covering all 4 elastic association combinations:
  // 1) Style + Layout (majority)  2) Style only  3) Layout only  4) Freeform (neither)
  const INITIAL_WORKS = [
    {
      id: "work_101",
      title: "秋分节气 · 桂花乌龙慢煮手账海报",
      author: "su_editorial",
      authorName: "苏苏的纸上茶馆",
      createdAt: "2 小时前",
      images: ["/images/poster-demo-autumn-equinox.webp", "/images/individual/FA/FA-038.webp"],
      styles: ["FX-001", "FA-038"],
      layout: "LX-001",
      color: "C-15",
      tone: "T-13",
      ratio: "3:4",
      mode: "poster",
      mood: "诗意",
      price: 0,
      likes: 186,
      favorites: 142,
      forks: 64,
      prompt: "海报模式（3:4 竖版）。融合 #FX-001 朱砂金箔东方节气社论风（主 70%）与 #FA-038 桑贝式诗意水墨小人（辅 30%），采用 LX-001 三段式杂志封面级排版。主标题『秋分 · 慢煮一壶桂花乌龙』置于顶部留白书眉，中央绘制微型茶人倚坐在巨型白瓷盖碗边缘看桂花飘落，朱砂红印章与金箔细点提亮，四周保留 55% 温润宣纸呼吸负空间。",
      notes: "用在线独占的 FX-001 叠了一点桑贝小人比例，留白拉到充裕后字体排版特别稳，直出零废片！",
      comments: [
        { id: "c1", user: "yang0", name: "Yang · 创作者", text: "巨型盖碗配微缩人物的比例反差太妙了，已收藏同款配方！", time: "1 小时前" },
        { id: "c2", user: "lin_sketch", name: "林默 · 独立插画师", text: "FX-001 的纸纹底色确实比普通水彩更有印刷高级感。", time: "35 分钟前" }
      ]
    },
    {
      id: "work_102",
      title: "早八精品咖啡店『周一续命杯套』商业联名企划",
      author: "brand_zhou",
      authorName: "周周品牌提案室",
      createdAt: "4 小时前",
      images: ["/images/individual/FA/FA-001.webp", "/images/layouts/ecommerce/EC-002.webp"],
      styles: ["FA-001"],
      layout: "SC-001",
      color: "C-26",
      tone: "T-01",
      ratio: "3:4",
      mode: "graphic-text",
      mood: "幽默",
      price: 0,
      likes: 245,
      favorites: 219,
      forks: 93,
      prompt: "图文社媒卡（3:4）。采用 #FA-001 Playful Deadpan Doodle（Gemma Correll 怪萌冷脸涂鸦），搭配 SC-001 经典上标题下主图小红书社媒卡结构。画面中央画一只顶着巨大黑眼圈、面无表情捧着特大号冰美式的社畜猫咪，两侧散落手写短标签：『灵魂尚未打卡』『咖啡因纯度 99%』『勿cue正在开机』；纯白纸底点缀柿子橙色块，线条松散生动。",
      notes: "给上海静安一家独立咖啡馆做的三联杯套商业提案已过稿！包含完整负向避坑词与手写体控制技巧。",
      comments: [
        { id: "c3", user: "coffee_cat", name: "橘猫店长", text: "花 5 积分太值了，直接套用改成了我们店里的柴犬店长！", time: "2 小时前" }
      ]
    },
    {
      id: "work_103",
      title: "雨后街角 · 真实摄影与手绘撕纸第二世界双拼实验",
      author: "luna_visual",
      authorName: "Luna 视觉转译",
      createdAt: "5 小时前",
      images: ["/images/layouts/social-cards/SC-021.webp", "/images/realistic.webp"],
      styles: ["FB-022"],
      layout: "SC-021",
      sc021Type: "撕纸裂变第二世界型",
      color: "C-30",
      tone: "T-14",
      ratio: "3:4",
      mode: "graphic-text",
      mood: "治愈",
      price: 0,
      likes: 312,
      favorites: 278,
      forks: 118,
      prompt: "小红书自适应双拼照片转译卡（SC-021 · 类型 02 撕纸裂变第二世界型，3:4 上下 1:1 堆叠）。上半部为雨后东京石板路街角撑透明伞女孩的胶片抓拍真实照片；接缝处采用不规则手工撕纸毛边，下半部进入 #FB-022 二十世纪中叶复古钢笔淡彩绘本世界，雨水跨过撕纸变成蓝色丝带被两只穿雨衣的小鸭子轻轻托起，四周 65% 象牙白水彩纸留白，右下角细字手写英文『After the rain, another story begins.』。",
      notes: "SC-021 选 02 撕纸第二世界时，一定要强调下半部剔除原片杂乱街景，四周留白拉满！",
      comments: []
    },
    {
      id: "work_104",
      title: "当代打工人开会精神状态四格实录",
      author: "meme_king",
      authorName: "阿泽画冷笑话",
      createdAt: "6 小时前",
      images: ["/images/individual/FA/FA-018.webp", "/images/layouts/comic-storyboards/SB-002.webp"],
      styles: ["FA-018"],
      layout: "SB-002",
      color: "C-08",
      tone: "T-01",
      ratio: "1:1",
      mode: "graphic-text",
      mood: "荒诞",
      price: 0,
      likes: 169,
      favorites: 134,
      forks: 57,
      prompt: "四格漫画分镜（SB-002 田字规整四宫格，1:1 方图）。采用 #FA-018 Minimal Deadpan Dialogue Cartoon（Poorly Drawn Lines 极简圆头冷面风）。第一格：圆头小人端坐电脑前说『这个需求很简单』；第二格：旁边一只绿色小鸟沉默盯着他；第三格：两人对视毫无表情；第四格：窗外天黑了，小鸟说『你刚刚立了最危险的 Flag』。低饱和灰蓝与米色小色块，干净白底。",
      notes: "FA-018 配 SB-002 做职场冷幽默公众号条漫点击率奇高，表情越平静越好笑。",
      comments: []
    },
    {
      id: "work_105",
      title: "远程办公效率工具栈 · 极简扁平信息图解",
      author: "pm_chen",
      authorName: "阿陈做产品",
      createdAt: "8 小时前",
      images: ["/images/graphic-text-mode-demo.webp", "/images/layouts/infographics/IG-001.webp"],
      styles: ["FC-029"],
      layout: "IG-001",
      color: "C-01",
      tone: "T-01",
      ratio: "3:4",
      mode: "graphic-text",
      mood: "松弛",
      price: 0,
      likes: 128,
      favorites: 115,
      forks: 49,
      prompt: "结构化知识信息图（IG-001 中心辐射模块信息图，3:4）。采用 #FC-029 清透扁平插画风格，主题色 C-01 克莱因蓝点缀暖米底。画面中心为一名戴降噪耳机的极简几何创作者，四周有序分布 4 个无框轻量信息簇：『异步文档』『自动化工作流』『番茄钟深潜』『灵感剪藏库』，两级硬边明暗，呼吸感充足。",
      notes: "做知识博主周更卡片最稳的一套黄金组合：FC-029 + IG-001。",
      comments: []
    },
    {
      id: "work_106",
      title: "1997 九龙霓虹夜雨 · 电影感人物情绪肖像（仅指定画风）",
      author: "film_poet",
      authorName: "暗房里的阿森",
      createdAt: "9 小时前",
      images: ["/images/realistic.webp"],
      styles: ["FI-028"],
      layout: null,
      color: "C-13",
      tone: "T-14",
      ratio: "2.35:1",
      mode: "photo",
      shootType: "复古港风",
      mood: "孤寂",
      price: 0,
      likes: 204,
      favorites: 176,
      forks: 42,
      prompt: "宽银幕电影剧照摄影（2.35:1）。仅采用 #FI-028 王家卫复古港风霓虹暗调美学，不锁定固定排版图型。透过布满雨珠的茶餐厅玻璃窗向内抓拍，暖绿与昏黄钨丝灯光晕染在人物侧脸，快门慢速拖影与粗颗粒柯达 500T 胶片色偏，克制深沉的叙事感。",
      notes: "测试『只选画风、不选图型』的纯摄影模式，2.35:1 公众号首图氛围感直接封神。",
      comments: []
    },
    {
      id: "work_107",
      title: "一个人与整片森林的安静午后（仅指定绘本画风）",
      author: "forest_mori",
      authorName: "森屿绘本屋",
      createdAt: "11 小时前",
      images: ["/images/individual/FB/FB-031.webp"],
      styles: ["FB-031"],
      layout: null,
      color: "C-10",
      tone: "T-10",
      ratio: "4:3",
      mode: "article-illust",
      mood: "治愈",
      price: 0,
      likes: 153,
      favorites: 129,
      forks: 38,
      prompt: "文章插图（4:3 横版）。采用 #FB-031 几米诗意水彩绘本插画风，自由构图不套版式。大面积鼠尾草绿与雾化晨光水彩晕染树冠，画面右下角小小的红围巾女孩坐在长椅上抬头听鸟鸣，上方保留 60% 空灵通透留白供后期压印散文金句。",
      notes: "散文配图不需要信息卡结构，直接清空图型槽位只用 FB-031 反而最灵动。",
      comments: []
    },
    {
      id: "work_108",
      title: "SaaS 订阅制三档价格权益横向对比表（仅指定图型）",
      author: "growth_li",
      authorName: "增长黑客老李",
      createdAt: "13 小时前",
      images: ["/images/layouts/infographics/IG-004.webp"],
      styles: [],
      layout: "IG-004",
      color: "C-35",
      tone: "T-02",
      ratio: "4:3",
      mode: "graphic-text",
      mood: "庄严",
      price: 0,
      likes: 94,
      favorites: 88,
      forks: 31,
      prompt: "纯粹结构驱动（仅挂载 IG-004 多维矩阵对比信息图型，不指定手绘画风）。干净现代瑞士网格信息设计，对比『个人免费版 / 专业创作者版 / 团队企业版』三列核心配额，中间推荐列用暖朱砂红顶栏高亮标注 Most Popular，极高可读性。",
      notes: "做汇报 PPT 图表时直接清空画风，只用图型库里的 IG 系列骨架，干净利落不花哨。",
      comments: []
    },
    {
      id: "work_109",
      title: "『林知夏』四款艺术手写签名定制提案稿（仅指定图型）",
      author: "calli_ink",
      authorName: "墨迹造字社",
      createdAt: "15 小时前",
      images: ["/images/layouts/social-cards/SC-022.webp"],
      styles: [],
      layout: "SC-022",
      color: "C-04",
      tone: "T-01",
      ratio: "9:16",
      mode: "poster",
      mood: "松弛",
      price: 0,
      likes: 141,
      favorites: 119,
      forks: 55,
      prompt: "【中文姓名】：林知夏 【姓名拼音】：LIN ZHIXIA 【顶部背景色】：深钴蓝 【画幅比例】：9:16。严格采用 SC-022 姓名四款签名设计展示卡结构：上方 40% 印刷体基准姓名，下方 60% 细虚线 2×2 四宫格分别呈现『飘逸、锋势、回环、极简』四种截然不同的签名骨架。",
      notes: "SC-022 本身就是完整的视觉系统，完全不需要额外叠加插画风，小红书接签名定制单神器！",
      comments: []
    },
    {
      id: "work_110",
      title: "玻璃温室里的微缩机械发条植物园（自由创作 · 无画风图型）",
      author: "dream_craft",
      authorName: "造梦零件铺",
      createdAt: "16 小时前",
      images: ["/images/F_155-170.webp"],
      styles: [],
      layout: null,
      color: "C-11",
      tone: "T-11",
      ratio: "1:1",
      mode: "pure",
      mood: "神秘",
      price: 0,
      likes: 117,
      favorites: 92,
      forks: 26,
      prompt: "自由纯图创作（不挂载预设画风与图型）：维多利亚黄铜齿轮与半透明吹制翡翠玻璃叶片交织生长的微缩温室植物盆景，一束斜射夕阳穿过玻璃穹顶形成丁达尔光束，桌面散落古董放大镜与手写植物学拉丁文标本签，超精细材质微距刻画。",
      notes: "偶尔跳出画风编号做纯自由提示词实验，一样可以发到广场和大家交流光影词！",
      comments: []
    },
    {
      id: "work_111",
      title: "手工粗陶咖啡滤杯与亚麻桌布静物晨光（自由创作）",
      author: "kinfolk_lee",
      authorName: "木白器物志",
      createdAt: "18 小时前",
      images: ["/images/I_332-347.webp"],
      styles: [],
      layout: null,
      color: "C-36",
      tone: "T-04",
      ratio: "3:4",
      mode: "pure",
      mood: "松弛",
      price: 0,
      likes: 89,
      favorites: 74,
      forks: 19,
      prompt: "自由创作静物摄影：未上釉的柴烧粗陶手冲咖啡滤杯置于本色褶皱亚麻桌布上，热气在清晨侧逆光中缓缓升腾，暖灰陶土颗粒与透明玻璃分享壶形成温润质感对比，极简侘寂美学。",
      notes: "自由创作无束缚，配合 T-04 软调影调控制非常舒服。",
      comments: []
    },
    {
      id: "work_112",
      title: "黑猫侍者『橘子汽水特调师』三视图与表情包设定集",
      author: "ip_maker",
      authorName: "潮玩造物局",
      createdAt: "1 天前",
      images: ["/images/characters/CH-001.webp", "/images/layouts/ip-characters/IP-002.webp"],
      styles: ["FB-023"],
      layout: "IP-002",
      color: "C-25",
      tone: "T-01",
      ratio: "4:3",
      mode: "graphic-text",
      mood: "童趣",
      price: 0,
      likes: 276,
      favorites: 251,
      forks: 84,
      prompt: "角色设定集（IP-002 正侧背三视图 + 4枚情绪头像设定卡，4:3）。挂载官方角色资产 CH-001 黑猫侍者保持面部特征与侍者马甲绝对一致，转译为 #FB-023 手绘水彩模切白边贴纸风，新增爱马仕橙领结与夏日橘子汽水摇酒壶道具，干净暖白设定集图鉴。",
      notes: "实测用 Studio 第 3 步挂载 CH-001 基准图锁脸稳如泰山，整套商业文创贴纸直接进打样。",
      comments: []
    },
    {
      id: "work_113",
      title: "法国小酒馆周末早午餐菜单手绘插画卡",
      author: "paris_croissant",
      authorName: "可颂不加糖",
      createdAt: "1 天前",
      images: ["/images/individual/FA/FA-003.webp", "/images/layouts/social-cards/SC-006.webp"],
      styles: ["FA-003"],
      layout: "SC-006",
      color: "C-27",
      tone: "T-13",
      ratio: "3:4",
      mode: "graphic-text",
      mood: "浪漫",
      price: 0,
      likes: 164,
      favorites: 140,
      forks: 47,
      prompt: "小红书美食探店手账卡（SC-006 散点图鉴清单排版）。采用 #FA-003 桑贝极细钢笔线法式淡彩风，描绘 5 款早午餐主角：酥皮牛角包、水波蛋牛油果吐司、热拿铁、无花果挞与黄油小碟，每件小物旁配纤细手写价格与法文小注记，大量纸白呼吸感。",
      notes: "FA-003 搭配 SC-006 画美食图鉴几乎零翻车，线条越轻盈越好看。",
      comments: []
    },
    {
      id: "work_114",
      title: "现代都市低头族地铁众生相 · 讽刺社论插画封面",
      author: "editorial_wu",
      authorName: "老吴看趋势",
      createdAt: "1 天前",
      images: ["/images/individual/FA/FA-013.webp"],
      styles: ["FA-013"],
      layout: "SC-019",
      color: "C-04",
      tone: "T-05",
      ratio: "2.35:1",
      mode: "article-cover",
      mood: "幽默",
      price: 0,
      likes: 198,
      favorites: 161,
      forks: 62,
      prompt: "公众号首图（2.35:1）。采用 #FA-013 Jean Jullien 粗黑轮廓扁平讽刺插画风 + SC-019 主体居中配两侧短标签结构。车厢里一排人手机屏幕发出的钴蓝色强光把每个人的脸照成小小的发光方块，唯独中间一只小狗抬头看窗外月亮。",
      notes: "深度科技评论公众号用 FA-013 做封面打开率提升了 40%。",
      comments: []
    },
    {
      id: "work_115",
      title: "日系手帐风『5分钟极简冥想入门步骤』跟练卡",
      author: "mindful_yuko",
      authorName: "知日生活手帖",
      createdAt: "2 天前",
      images: ["/images/D_099-114.webp", "/images/layouts/infographics/IG-003.webp"],
      styles: ["FD-016"],
      layout: "IG-003",
      color: "C-09",
      tone: "T-01",
      ratio: "3:4",
      mode: "graphic-text",
      mood: "松弛",
      price: 0,
      likes: 132,
      favorites: 118,
      forks: 44,
      prompt: "步骤流信息卡（IG-003 四步蜿蜒路径图解）。采用 #FD-016 tomatomayu 日系手帐小人物风，薄荷绿与奶油白配色，用可爱小人演示『01 找把椅子坐直 → 02 闭眼数呼吸 → 03 允许走神不评判 → 04 睁眼伸懒腰』，配手绘虚线箭头与小星星贴纸。",
      notes: "养生、心理、学习方法类账号闭眼冲这套组合。",
      comments: []
    },
    {
      id: "work_116",
      title: "独立书店『夜读鲁迅与孔版印刷展』双色海报",
      author: "zine_club",
      authorName: "小径分岔印务所",
      createdAt: "2 天前",
      images: ["/images/H_249-264.webp"],
      styles: ["FX-002", "FH-037"],
      layout: "SC-020",
      color: "C-16",
      tone: "T-06",
      ratio: "3:4",
      mode: "poster",
      mood: "激烈",
      price: 0,
      likes: 175,
      favorites: 149,
      forks: 39,
      prompt: "展览主视觉海报（3:4）。融合在线独占 #FX-002 丝网错版双色风与 #FH-037 红蓝 Riso 国潮套印，采用 SC-020 一大一组非对称结构：左侧大面积普鲁士蓝与朱红错版木刻感书本飞鸟图形，右侧紧凑排列展览日期、地点与三场沙龙议程。",
      notes: "登录免费解锁的 FX-002 套印错位质感太地道了！",
      comments: []
    },
    {
      id: "work_117",
      title: "夏日手工柠檬海盐气泡水 · 电商主图卖点拆解卡",
      author: "ecom_studio",
      authorName: "爆品视觉工场",
      createdAt: "2 天前",
      images: ["/images/layouts/ecommerce/EC-001.webp"],
      styles: ["FI-001", "FB-034"],
      layout: "EC-001",
      color: "C-27",
      tone: "T-13",
      ratio: "3:4",
      mode: "graphic-text",
      mood: "活力",
      price: 0,
      likes: 211,
      favorites: 193,
      forks: 71,
      prompt: "电商核心卖点首图（EC-001 实物居中 + 手绘趣味卖点环绕）。采用 #FI-001 商业级清透产品摄影刻画挂满冰水珠的玻璃瓶身，融合 #FB-034 简笔与半写实混合风，在瓶身周围用白色与柠檬黄2D涂鸦线条画出跳动气泡小人与『0糖0脂』『整颗安岳黄柠』『绵密3.2倍气量』三大卖点。",
      notes: "实拍级瓶身 + 2D涂鸦卖点混搭，淘宝天猫新品测图点击率比传统详情页高一截！",
      comments: []
    },
    {
      id: "work_118",
      title: "新手养猫必避的 6 个智商税用品红黑榜",
      author: "cat_doctor",
      authorName: "兽医小许画科普",
      createdAt: "3 天前",
      images: ["/images/layouts/infographics/IG-005.webp"],
      styles: ["FA-017"],
      layout: "USR-L01",
      color: "C-15",
      tone: "T-01",
      ratio: "3:4",
      mode: "graphic-text",
      mood: "幽默",
      price: 0,
      likes: 184,
      favorites: 167,
      forks: 58,
      prompt: "采用社区共创图型 USR-L01 红黑榜左右PK决策卡 + #FA-017 Sarah Andersen 黑白圆眼反应漫画风。左侧黑榜画猫咪一脸嫌弃踹开全自动烘干箱与染色猫砂，右侧红榜画猫咪幸福蹭着大号敞口塑料盆与瓦楞纸抓板。",
      notes: "阿陈贡献的 USR-L01 红黑榜图型太好用了，做宠物测评一篇涨粉两千。",
      comments: []
    },
    {
      id: "work_119",
      title: "复古橡皮管爵士乐队『周五不加班』摇摆贴纸海报",
      author: "retro_bean",
      authorName: "豆子复古画室",
      createdAt: "3 天前",
      images: ["/images/C_071-082.webp"],
      styles: ["FC-031"],
      layout: "SC-023",
      color: "C-28",
      tone: "T-05",
      ratio: "3:4",
      mode: "poster",
      mood: "活力",
      price: 0,
      likes: 147,
      favorites: 122,
      forks: 33,
      prompt: "竖版派对海报（SC-023 大标题突出 + 紧凑角色群像）。采用 #FC-031 现代美式复古橡皮管卡通风，顶部芥末黄手绘色块衬托粗体主标题『FRIDAY SWING!』，下方萨克斯猫、打鼓吐司面包与弹贝斯的咖啡杯四肢如柔软橡皮管般欢快扭动，无分镜框自然穿插。",
      notes: "FC-031 干净没有脏旧噪点，非常适合做文创帆布袋印花。",
      comments: []
    },
    {
      id: "work_120",
      title: "老上海霞飞路梧桐树影下的旗袍书店女孩",
      author: "lin_sketch",
      authorName: "林默 · 独立插画师",
      createdAt: "4 天前",
      images: ["/images/D_083-098.webp"],
      styles: ["USR-S01"],
      layout: "SC-024",
      color: "C-17",
      tone: "T-14",
      ratio: "3:4",
      mode: "graphic-text",
      mood: "浪漫",
      price: 0,
      likes: 162,
      favorites: 138,
      forks: 41,
      prompt: "采用我上传的社区共创画风 #USR-S01 老上海月份牌淡彩摩登速写 + SC-024 图下文上留白社媒卡。下方抱旧诗集的浅青旗袍少女走过斑驳梧桐树影，上方温暖旧纸白空间排印一句短诗『风翻开第三十七页的秋天』。",
      notes: "欢迎大家试用我整理的 USR-S01 画风，完全免费开放！",
      comments: []
    }
  ];

  // Rich Custom Forum Topics deeply integrated with Styles, Layouts, Works & Studio Recipes
  // Naturally mixes Multi-Image Gallery Posts (2~3 thumbs), Single-Image Cover Posts (1 right thumb), and Pure-Text Posts (0 thumbs)
  const INITIAL_TOPICS = [
    {
      id: "topic_201",
      category: "experience",
      categoryLabel: "📘 实战经验与变现",
      pinned: true,
      title: "【商单复盘】靠 #FA-001 + SC-001 拿下连锁精品咖啡三款杯套与周边企划，全流程交付 SOP 与避坑词公开",
      author: "brand_zhou",
      authorName: "周周品牌提案室",
      createdAt: "3 小时前",
      views: 1420,
      likes: 196,
      favorites: 168,
      price: 10,
      bounty: 0,
      solved: false,
      images: [
        { url: "/images/individual/FA/FA-001.webp", tag: "主画风 #FA-001" },
        { url: "/images/individual/FA/FA-018.webp", tag: "冷脸角色系列延展" },
        { url: "/images/layouts/social-cards/SC-001.webp", tag: "SC-001 排版骨架" }
      ],
      styles: ["FA-001", "FA-018"],
      layout: "SC-001",
      workId: "work_102",
      recipe: {
        mode: "graphic-text",
        theme: "早八打工人冰美式续命自嘲杯套插画",
        style1: "FA-001",
        style2: "",
        layout: "SC-001",
        color: "C-26",
        tone: "T-01",
        ratio: "3:4",
        mood: "幽默"
      },
      summary: "很多朋友觉得极简涂鸦风太简单不好收高价，其实新消费咖啡茶饮客户最买单的就是『情绪嘴替 + 低印刷成本矢量感』。本文拆解从提案比稿、3套备选画风对比，到杯套刀版出血位控制的全套实战经验……",
      lockedBody: "### 一、为什么新消费餐饮客户偏爱 #FA-001 胜过精细厚涂？\n1. **牛皮纸/白卡纸单双色印刷零色差**：`#FA-001` 以松散黑线配单一高辨识度点缀色（如 `C-26 柿子橙`），上机印杯套与纸袋成本直降 35%，且隔着 5 米一眼能认出表情梗。\n2. **系列化延展极快**：锁定动物角色圆脸与死鱼眼特征后，半小时即可衍生『周一冰美式 / 周三拿铁 / 周五特调』全套三联物料。\n\n### 二、防翻车核心控制句（直接复制进 Studio 补充说明）\n- 必加约束：`保持线条松散微抖的手工签字笔触，严禁出现3D渐变体积阴影，严禁把角色画成标准大眼微笑Q版吉祥物`\n- 字数铁律：画面内手写吐槽短标签严格控制在 3 组以内，每组不超过 6 个汉字，留足 55% 纯白底方便印厂排 Logo。\n\n### 三、报价参考与交付物清单\n单店联名快闪包（主视觉海报 ×1 + 杯套 ×2 + 贴纸 ×4）报价区间 `¥3,800 - ¥6,500`，交付矢量化 SVG 线稿 + 300DPI 分层 PSD。",
      replies: [
        {
          id: "r1",
          user: "su_editorial",
          name: "苏苏的纸上茶馆",
          time: "2 小时前",
          text: "10 积分花得太超值了！尤其是单双色杯套印刷省成本这个切入点，拿去说服茶饮老板一说一个准。",
          likes: 28
        },
        {
          id: "r2",
          user: "meme_king",
          name: "阿泽画冷笑话",
          time: "1 小时前",
          text: "刚点帖子里的参数卡一键带入 Studio 试了一版烘焙店纸袋，冷脸吐司小人效果绝了！",
          likes: 15
        }
      ]
    },
    {
      id: "topic_202",
      category: "tuning",
      categoryLabel: "🎯 作品求调优 / 悬赏",
      pinned: true,
      title: "【悬赏 15 积分】用 SC-021 做猫咪窗台双拼转译，下半部老是残留原照片的窗帘杂乱背景，怎么彻底洗干净留白？",
      author: "cat_newbie",
      authorName: "布偶猫铲屎官小唐",
      createdAt: "1 小时前",
      views: 486,
      likes: 42,
      favorites: 35,
      price: 0,
      bounty: 15,
      solved: false,
      images: [
        { url: "/images/realistic.webp", tag: "原片实拍输入" },
        { url: "/images/layouts/social-cards/SC-021.webp", tag: "目标双拼留白效果" }
      ],
      styles: ["FB-030"],
      layout: "SC-021",
      workId: "work_103",
      recipe: {
        mode: "graphic-text",
        theme: "午后窗台打哈欠的布偶猫上下双拼转译",
        style1: "FB-030",
        style2: "",
        layout: "SC-021",
        sc021Type: "撕纸裂变第二世界型",
        color: "C-30",
        tone: "T-01",
        ratio: "3:4",
        mood: "治愈"
      },
      summary: "我上传了家里布偶猫在飘窗上的照片，选了 #FB-030 水墨蜡笔猫绘本风 + SC-021，但生出来的下半部还是把背后的空调外机和花窗帘画进去了，求大佬帮改一版干净象牙白留白的配方！采纳立结 15 积分！",
      lockedBody: "",
      replies: [
        {
          id: "r3",
          user: "luna_visual",
          name: "Luna 视觉转译",
          time: "40 分钟前",
          text: "关键在于把 SC-021 子类型切到【04 微缩浮岛型】或明确写明『转译侧彻底剔除窗框窗帘等一切室内背景，仅提取猫咪打哈欠姿态置于 70% 象牙白纸中央，四周严禁贴边』！我把调好的配方挂在下面卡片里了，你可以一键带入 Studio 试试。",
          likes: 19,
          mountedStyle: "FB-030",
          mountedLayout: "SC-021"
        },
        {
          id: "r4",
          user: "lin_sketch",
          name: "林默 · 独立插画师",
          time: "22 分钟前",
          text: "补充一点：Studio 第三步把『画面留白密度』从适中切到『充裕大留白 (60%+)』，模型对负空间的执行力会直接翻倍。",
          likes: 11
        }
      ]
    },
    {
      id: "topic_208",
      category: "experience",
      categoryLabel: "📘 实战经验与变现",
      pinned: false,
      title: "【纯文讨论 · 商单报价】大家接小红书组图或公众号全篇定制插图，是按单张算还是按整篇打包报价？改稿边界怎么写进合同？",
      author: "editorial_wu",
      authorName: "老吴看趋势",
      createdAt: "2 小时前",
      views: 965,
      likes: 148,
      favorites: 132,
      price: 0,
      bounty: 0,
      solved: false,
      images: [],
      styles: ["FA-013", "FC-029"],
      layout: null,
      workId: null,
      recipe: null,
      summary: "最近连续有两家科技媒体和知识付费团队找我做公众号长文套图（1 张 2.35:1 首图 + 4 张章节插图）以及小红书 6P 干货组图。想和社区里的同行对一下行情：锁定统一画风编号后出图效率高了很多，大家一般首付收几成？超过 2 轮微调怎么加收费用？欢迎纯文字畅聊经验！",
      lockedBody: "",
      replies: [
        {
          id: "r8",
          user: "brand_zhou",
          name: "周周品牌提案室",
          time: "1 小时前",
          text: "我们工作室现在按『视觉企划包』报整包价：小红书 5~6P 组图 ¥1,200~¥2,000/组（含封面高点击排版设计 + 内页统一画风），定金 50%，先用画风库编号跟甲方锁死画风再批量跑，彻底杜绝中途推翻重画！",
          likes: 41
        },
        {
          id: "r9",
          user: "pm_chen",
          name: "阿陈做产品",
          time: "38 分钟前",
          text: "公众号包月专栏可以谈固定月费（比如每月 8 篇，每篇 1 封 + 3 插），用创作台的『文章批量配图台』半小时就能交初稿，利润率非常健康。",
          likes: 27
        }
      ]
    },
    {
      id: "topic_203",
      category: "assets",
      categoryLabel: "🎨 画风与图型专区",
      pinned: false,
      title: "实测官网独占画风 #FX-001 与 #FX-002：为什么在线云端黑盒注入比本地硬写几百字质感词更稳？",
      author: "su_editorial",
      authorName: "苏苏的纸上茶馆",
      createdAt: "5 小时前",
      views: 830,
      likes: 114,
      favorites: 97,
      price: 0,
      bounty: 0,
      solved: false,
      images: [
        { url: "/images/poster-demo-autumn-equinox.webp", tag: "FX-001 实测成片" }
      ],
      styles: ["FX-001", "FX-002"],
      layout: "LX-001",
      workId: "work_101",
      recipe: {
        mode: "poster",
        theme: "秋分节气桂花乌龙慢煮茶会海报",
        style1: "FX-001",
        style2: "FA-038",
        layout: "LX-001",
        color: "C-15",
        tone: "T-13",
        ratio: "3:4",
        mood: "诗意"
      },
      summary: "今天在创作台试了登录免费开放的 FX-001 朱砂金箔东方节气风，发现主题输入框只需要专心写清画面故事和标题文案（不到 50 字），底层笔触完全不会互相污染打架，附实测成片与心得。",
      lockedBody: "",
      replies: [
        {
          id: "r5",
          user: "yang0",
          name: "Yang · 创作者",
          time: "3 小时前",
          text: "没错！在线创作台把底层材质锚点和用户的业务主题做了分层隔离，避免长提示词稀释主体注意力。",
          likes: 34
        }
      ]
    },
    {
      id: "topic_204",
      category: "experience",
      categoryLabel: "📘 实战经验与变现",
      pinned: false,
      title: "小红书知识博主高赞公式：3 套最适合零基础起步的『画风 + 图型』黄金组合清单（附实测对比图）",
      author: "pm_chen",
      authorName: "阿陈做产品",
      createdAt: "10 小时前",
      views: 1190,
      likes: 173,
      favorites: 210,
      price: 0,
      bounty: 0,
      solved: false,
      images: [
        { url: "/images/graphic-text-mode-demo.webp", tag: "① FC-029 + IG-001" },
        { url: "/images/D_099-114.webp", tag: "② FD-016 + IG-003" },
        { url: "/images/individual/FA/FA-013.webp", tag: "③ FA-013 + SC-019" }
      ],
      styles: ["FC-029", "FD-016", "FA-013"],
      layout: "IG-001",
      workId: "work_105",
      recipe: {
        mode: "graphic-text",
        theme: "个人知识管理四步闭环飞轮图解",
        style1: "FC-029",
        style2: "",
        layout: "IG-001",
        color: "C-01",
        tone: "T-01",
        ratio: "3:4",
        mood: "松弛"
      },
      summary: "连续日更 30 天测试了 40 多组搭配，筛出收藏率最高的三组铁三角：① 职场工具干货用 FC-029 + IG-001；② 生活习惯跟练用 FD-016 + IG-003；③ 观点吐槽封面用 FA-013 + SC-019。现在还能直接在『小红书组图工坊』一次生成整套！",
      lockedBody: "",
      replies: []
    },
    {
      id: "topic_205",
      category: "tools",
      categoryLabel: "🛠️ 工具流与问答",
      pinned: false,
      title: "本地 Claude Code / Cursor 装了 handraw-style Skill 后，怎么和网站收藏夹联动最快？",
      author: "dev_kevin",
      authorName: "独立开发凯文",
      createdAt: "1 天前",
      views: 645,
      likes: 78,
      favorites: 64,
      price: 0,
      bounty: 0,
      solved: true,
      images: [],
      styles: ["FA-039"],
      layout: "IG-003",
      workId: null,
      recipe: null,
      summary: "分享我的双端丝滑工作流：平时在官网刷『作品广场』看到惊艳的实测图直接点 ♥ 收藏画风和图型，需要做小红书套图、文章批量插图或用独占画风时直接在 studio.handraw-style.com 云端批量出图；跑自动化脚本时复制 Skill 短指令回本地跑！",
      lockedBody: "",
      replies: [
        {
          id: "r6",
          user: "pm_chen",
          name: "阿陈做产品",
          time: "20 小时前",
          text: "而且现在本地画廊看到每个编号后面写了『N 作品』，点过来就能看大家真实生出来的成片，不用自己盲测编号了！",
          likes: 22
        }
      ]
    },
    {
      id: "topic_206",
      category: "assets",
      categoryLabel: "🎨 画风与图型专区",
      pinned: false,
      title: "【荒地开垦召集令】这几个冷门宝藏画风（FB-055 / FC-028 / FH-043）出图美哭了，首晒立拿 +15 积分！",
      author: "forest_mori",
      authorName: "森屿绘本屋",
      createdAt: "1 天前",
      views: 520,
      likes: 91,
      favorites: 83,
      price: 0,
      bounty: 0,
      solved: false,
      images: [
        { url: "/images/B_049-054.webp", tag: "FB-055 古地图绘本" },
        { url: "/images/H_265-280.webp", tag: "FH-043 丝网旅行风" }
      ],
      styles: ["FB-055", "FC-028", "FH-043"],
      layout: null,
      workId: null,
      recipe: {
        mode: "poster",
        theme: "中世纪星象航海图与鲸鱼岛屿幻想地图",
        style1: "FB-055",
        style2: "",
        layout: "",
        color: "C-03",
        tone: "T-14",
        ratio: "3:4",
        mood: "神秘"
      },
      summary: "大家别光盯着 FA 前二十号薅啦！FB-055 点描古地图幻想绘本风和 FH-043 复古普鲁士蓝珊瑚红丝网旅行插画美到窒息，而且现在这些编号下作品数不到 3 个，去晒首图系统直接奖 +15 积分！",
      lockedBody: "",
      replies: []
    },
    {
      id: "topic_207",
      category: "tuning",
      categoryLabel: "🎯 作品求调优 / 悬赏",
      pinned: false,
      title: "【已解决 · 10 积分已结】CH-001 黑猫侍者换装成宇航员时怎么保留马甲领结元素不走形？",
      author: "ip_maker",
      authorName: "潮玩造物局",
      createdAt: "2 天前",
      views: 710,
      likes: 65,
      favorites: 52,
      price: 0,
      bounty: 10,
      solved: true,
      images: [
        { url: "/images/characters/CH-001.webp", tag: "CH-001 锁脸设定成片" }
      ],
      styles: ["FB-017"],
      layout: "IP-002",
      workId: "work_112",
      recipe: {
        mode: "graphic-text",
        theme: "黑猫侍者身穿复古宇航服在月球表面端着银托盘咖啡",
        style1: "FB-017",
        style2: "",
        layout: "IP-002",
        color: "C-04",
        tone: "T-13",
        ratio: "4:3",
        mood: "童趣"
      },
      summary: "感谢大家支招！在 Studio 第 3 步勾选 CH-001 参考资产后，在补充说明里写『宇航服胸口外置保留标志性侍者领结，头盔全透明露出黑猫翡翠眼与胡须』完美解决。",
      lockedBody: "",
      replies: []
    }
  ];

  // Studio Batch Mode 1: Xiaohongshu Carousel Deck Templates (Global Style Lock + Per-Slide Differentiated Layouts)
  const XHS_DECK_TEMPLATES = [
    {
      id: "xhs_tpl_knowledge",
      label: "📘 知识干货 4P（AI 时代个人知识管理闭环）",
      topic: "告别收藏夹吃灰！普通人用好这 4 步建立真正能变现的个人知识飞轮：极简捕获、一句话蒸馏、跨领域卡片连接、每周微输出。",
      style1: "FC-029",
      color: "C-01",
      tone: "T-01",
      ratio: "3:4",
      useCh001: false,
      slides: [
        {
          id: "s1",
          role: "P1 吸睛封面",
          layout: "LX-001",
          headline: "告别收藏夹吃灰！4步搭建个人知识飞轮",
          visualPrompt: "极简几何创作者站在发光的知识齿轮中央，顶部醒目主标题『收藏≠学会！4步把碎片信息变成你的作品』，底部三枚核心收益胶囊标签",
          sampleImg: "/images/layouts/social-cards/SC-023.webp"
        },
        {
          id: "s2",
          role: "P2 痛点反差",
          layout: "USR-L01",
          headline: "为什么你存了1000篇干货还是用不上？",
          visualPrompt: "左右红黑榜对比：左侧灰暗杂乱堆积如山的未读文件夹标注『松鼠症囤积：只存不看、分类过细』；右侧清爽卡片盒标注『高手做法：只记能触动行动的1句话』",
          sampleImg: "/images/layouts/infographics/IG-005.webp"
        },
        {
          id: "s3",
          role: "P3 核心四步法",
          layout: "IG-003",
          headline: "每天15分钟：采集→蒸馏→连接→微输出",
          visualPrompt: "四步蜿蜒路径流程卡：01 随手收进唯一收件箱 → 02 用自己的话重写3行卡片 → 03 挂钩已有项目问题 → 04 周末发1篇复盘图文",
          sampleImg: "/images/layouts/infographics/IG-003.webp"
        },
        {
          id: "s4",
          role: "P4 行动清单尾页",
          layout: "IG-001",
          headline: "今晚就能立刻开始的最小行动清单",
          visualPrompt: "中心辐射行动卡：中央画一本摊开的轻盈手账本，四周分布4个打勾项『删掉半年没看的文件夹』『建1个今日灵感卡』『挑1个旧笔记改写成动态』『点个收藏周末对照做』",
          sampleImg: "/images/graphic-text-mode-demo.webp"
        }
      ]
    },
    {
      id: "xhs_tpl_coffee",
      label: "☕ 趣味探店/职场 4P（早八打工人续命咖啡图鉴）",
      topic: "当代早八人靠咖啡续命的精神状态图鉴：从周一特浓冰美式硬撑开机，到周五果咖提前进入周末模式。",
      style1: "FA-001",
      color: "C-26",
      tone: "T-01",
      ratio: "3:4",
      useCh001: false,
      slides: [
        {
          id: "c1",
          role: "P1 爆梗封面",
          layout: "SC-001",
          headline: "当代早八打工人『血管里的咖啡因』图鉴",
          visualPrompt: "一只顶着浓重黑眼圈、面无表情双手捧巨型冰美式桶的冷脸小猫，头顶大字标题『早八续命指南：今天你喝到第几级？』，柿子橙色块点缀纯白纸底",
          sampleImg: "/images/individual/FA/FA-001.webp"
        },
        {
          id: "c2",
          role: "P2 散点风味单",
          layout: "SC-006",
          headline: "周一到周五：不同工位情绪对应哪一杯？",
          visualPrompt: "手绘散点小物图鉴清单：双份冰美式（周一消肿回魂）、燕麦拿铁（周三温和护胃）、dirty（周四赶DDL一口闷）、橘子气泡美式（周五下午心已下班）",
          sampleImg: "/images/layouts/social-cards/SC-006.webp"
        },
        {
          id: "c3",
          role: "P3 四格工位实录",
          layout: "SB-002",
          headline: "喝咖啡前 vs 喝咖啡后的真实 10 分钟",
          visualPrompt: "田字四格冷幽默漫画：第1格趴桌灵魂出窍 → 第2格吸管猛吸第一口冰美式 → 第3格瞳孔微震敲键盘如飞 → 第4格十分钟后『困意学会了耐药性』",
          sampleImg: "/images/layouts/comic-storyboards/SB-002.webp"
        },
        {
          id: "c4",
          role: "P4 互动投票尾页",
          layout: "SC-025",
          headline: "评论区对暗号：你工位桌上现在摆的哪一杯？",
          visualPrompt: "冷脸猫咪举着空白点单牌，周围围绕三个手写对话气泡：『A. 纯黑冰美式党』『B. 无奶不欢拿铁党』『C. 保温杯枸杞叛徒』",
          sampleImg: "/images/layouts/ecommerce/EC-002.webp"
        }
      ]
    },
    {
      id: "xhs_tpl_cat",
      label: "🐱 萌宠测评 3P（新手养猫省钱避坑红黑榜）",
      topic: "养猫三年花掉两万块才悟出的真话：哪些高价网红宠物用品纯属智商税，哪些十几块钱平替猫咪爱到疯？",
      style1: "FA-017",
      color: "C-15",
      tone: "T-01",
      ratio: "3:4",
      useCh001: true,
      slides: [
        {
          id: "m1",
          role: "P1 反差封面",
          layout: "SC-023",
          headline: "养猫3年含泪总结：6个智商税 vs 6个真香平替",
          visualPrompt: "黑猫侍者 CH-001 一脚踩在拆开的快递纸箱里满脸傲娇，旁边昂贵豪华猫窝落灰，顶部朱砂红醒目大字『别乱花冤枉钱！新手养猫红黑榜』",
          sampleImg: "/images/characters/CH-001.webp"
        },
        {
          id: "m2",
          role: "P2 红黑榜对比",
          layout: "USR-L01",
          headline: "猫砂盆与饮水机：越花哨越容易闲置",
          visualPrompt: "左右红黑榜对照卡：左侧黑榜画幽闭全封闭猫砂盆、难洗死角饮水机；右侧红榜画大号敞口周转箱猫砂盆、陶瓷大碗流动水泵",
          sampleImg: "/images/layouts/infographics/IG-005.webp"
        },
        {
          id: "m3",
          role: "P3 选购三铁律",
          layout: "SC-024",
          headline: "买前默念三句话，立省 3000 块冤枉钱",
          visualPrompt: "图下文上留白社媒卡：下方黑猫幸福团在干净瓦楞纸抓板上打呼噜，上方温暖纸白排印三条核心原则：『好拆洗 > 高颜值』『无香精 > 浓香味』『大空间 > 花造型』",
          sampleImg: "/images/individual/FA/FA-018.webp"
        }
      ]
    }
  ];

  // Studio Batch Mode 2: Long-form Article Batch Illustration Templates (Cover + Chapter Inline Illustrations + Markdown Export)
  const ARTICLE_BATCH_TEMPLATES = [
    {
      id: "art_tpl_whitespace",
      label: "📰 深度散文/效率专栏：《为什么越忙的人，越需要「留白工作法」？》",
      style1: "FA-003",
      color: "C-27",
      tone: "T-13",
      coverRatio: "2.35:1",
      inlineRatio: "4:3",
      markdown: `# 为什么越忙的人，越需要「留白工作法」？

当我们把日历上的每一个半小时都塞满会议和待办事项时，看似运转到了极致，实际上大脑已经失去了真正产生创造性连接的呼吸缝隙。

## 一、塞满的日程表，正在杀死你的深度思考

现代职场最大的幻觉，就是把「响应速度」当成了「产出质量」。像一台没有缓冲内存的服务器，任何一点突发消息都会触发全盘卡顿。

## 二、像画水彩一样管理精力：留出 30% 不设限白纸

法国插画家桑贝的画里总有大片温润的空白纸面。正是那 70% 没有画满的天空与广场，让画面里那个骑单车的小人瞬间拥有了自由的诗意。把每天上午最清醒的 90 分钟彻底留白，关掉红点通知。

## 三、建立你的每日微停顿仪式：散步、手写与慢煮茶

真正的恢复不是刷短视频填满碎片时间，而是离开发光的屏幕：下楼走过两条梧桐街区、在纸质笔记本上画三个凌乱的思维圈，让潜意识自己浮出答案。`,
      slots: [
        {
          id: "art_s0",
          checked: true,
          role: "首图封面",
          anchorHeading: "# 为什么越忙的人，越需要「留白工作法」？",
          ratio: "2.35:1",
          layout: "SC-019",
          scenePrompt: "公众号宽幅首图（2.35:1）：偌大温润象牙白纸面上，一个极小的钢笔淡彩上班族推开密密麻麻的日程表高墙，走进一片洒满阳光的开阔草地，四周 65% 通透纸白呼吸感",
          sampleImg: "/images/individual/FA/FA-003.webp"
        },
        {
          id: "art_s1",
          checked: true,
          role: "章节插图 01",
          anchorHeading: "## 一、塞满的日程表，正在杀死你的深度思考",
          ratio: "4:3",
          layout: "",
          scenePrompt: "法式钢笔淡彩社论插图：一个打领带的小人被层层叠叠如俄罗斯方块般落下的会议弹窗与闹钟包围，头顶冒出一团缠绕的毛线球，幽默克制不压抑",
          sampleImg: "/images/individual/FA/FA-013.webp"
        },
        {
          id: "art_s2",
          checked: true,
          role: "章节插图 02",
          anchorHeading: "## 二、像画水彩一样管理精力：留出 30% 不设限白纸",
          ratio: "4:3",
          layout: "",
          scenePrompt: "诗意大留白水彩插图：大面积干净水彩纸留白中央，小小的人骑着黄色单车迎风穿过开阔广场，远处仅几笔轻盈树影与飞鸟，自由松弛",
          sampleImg: "/images/individual/FB/FB-031.webp"
        },
        {
          id: "art_s3",
          checked: true,
          role: "章节插图 03",
          anchorHeading: "## 三、建立你的每日微停顿仪式：散步、手写与慢煮茶",
          ratio: "4:3",
          layout: "IG-001",
          scenePrompt: "轻量图解插画：阳光木桌上一杯热茶与钢笔手账本居中，周围轻盈环绕三枚微停顿小景：梧桐树下散步、纸笔涂鸦、闭目听雨",
          sampleImg: "/images/poster-demo-autumn-equinox.webp"
        }
      ]
    },
    {
      id: "art_tpl_indiedev",
      label: "💻 科技产品长文：《独立开发者如何用视觉卡片把硬核技术讲出人味？》",
      style1: "FC-029",
      color: "C-01",
      tone: "T-01",
      coverRatio: "2.35:1",
      inlineRatio: "4:3",
      markdown: `# 独立开发者如何用视觉卡片把硬核技术讲出人味？

酒香也怕巷子深。很多工程师花三个月打磨出极致的底层性能，发布日却只贴了一张黑底白字的终端截图，读者三秒钟就划走了。

## 一、别只晒黑底终端截图：先画清用户痛点的「前后反差」

用户不关心你用了什么异步队列算法，只关心以前要折腾两小时的繁琐配置，现在点一下按钮就能喝着咖啡等结果。

## 二、把复杂架构翻译成一张一眼秒懂的模块图解

用克莱因蓝点缀的现代扁平几何插画替代枯燥的灰框流程图，把数据流向变成有温度的视觉动线，技术博客转发率往往能翻三倍。`,
      slots: [
        {
          id: "dev_s0",
          checked: true,
          role: "首图封面",
          anchorHeading: "# 独立开发者如何用视觉卡片把硬核技术讲出人味？",
          ratio: "2.35:1",
          layout: "SC-019",
          scenePrompt: "科技专栏首图（2.35:1）：清透现代扁平插画，创作者把冰冷的黑色代码窗口像折纸一样折成一朵发光的克莱因蓝纸飞机飞向读者，暖米纸底",
          sampleImg: "/images/graphic-text-mode-demo.webp"
        },
        {
          id: "dev_s1",
          checked: true,
          role: "章节插图 01",
          anchorHeading: "## 一、别只晒黑底终端截图：先画清用户痛点的「前后反差」",
          ratio: "4:3",
          layout: "USR-L01",
          scenePrompt: "左右痛点对比插画：左侧满头大汗对着报错命令行抓狂；右侧轻松靠在椅背喝手冲咖啡，屏幕上显示绿色一键完成勾号",
          sampleImg: "/images/layouts/infographics/IG-005.webp"
        },
        {
          id: "dev_s2",
          checked: true,
          role: "章节插图 02",
          anchorHeading: "## 二、把复杂架构翻译成一张一眼秒懂的模块图解",
          ratio: "4:3",
          layout: "IG-004",
          scenePrompt: "现代扁平几何信息图解：清晰展示输入文稿、画风矩阵注入、多端分发三个清透模块卡片，克莱因蓝与暖米白高可读性配色",
          sampleImg: "/images/layouts/infographics/IG-004.webp"
        }
      ]
    }
  ];

  const AI_COMBO_PRESETS = [
    {
      keywords: ["咖啡", "茶", "早餐", "美食", "探店", "甜品", "杯套", "菜单"],
      combos: [
        { tag: "商业爆款提案", style1: "FA-001", layout: "SC-001", color: "C-26", reason: "怪萌冷脸涂鸦 + 经典社媒大标题卡，情绪传播与印刷落地兼顾" },
        { tag: "法式手账图鉴", style1: "FA-003", layout: "SC-006", color: "C-27", reason: "桑贝细钢笔淡彩 + 散点小物清单，探店菜单高级感拉满" },
        { tag: "在线独占国风", style1: "FX-001", layout: "LX-001", color: "C-15", reason: "朱砂金箔宣纸独占画风 + 三段式杂志封面，节气茶饮直出大片" }
      ]
    },
    {
      keywords: ["科普", "干货", "对比", "工具", "步骤", "清单", "职场", "复盘", "AI", "产品"],
      combos: [
        { tag: "高收藏知识卡", style1: "FC-029", layout: "IG-001", color: "C-01", reason: "清透现代扁平色块 + 中心辐射信息图，逻辑一眼秒懂" },
        { tag: "红黑榜避坑PK", style1: "FA-017", layout: "USR-L01", color: "C-15", reason: "圆眼反应漫画 + 左右红黑榜对照，测评决策点击率极高" },
        { tag: "手帐步骤跟练", style1: "FD-016", layout: "IG-003", color: "C-09", reason: "日系手帐小人 + 四步路径引导，亲和力强零说教感" }
      ]
    },
    {
      keywords: [],
      combos: [
        { tag: "社媒吸睛双拼", style1: "FB-022", layout: "SC-021", color: "C-30", reason: "真实摄影 × 复古钢笔水彩撕纸第二世界，跨媒介反差极强" },
        { tag: "官网独占主推", style1: "FX-001", layout: "LX-001", color: "C-15", reason: "登录免费解锁东方节气金箔画风 + 杂志封面排版，大留白不翻车" },
        { tag: "冷幽默四格条漫", style1: "FA-018", layout: "SB-002", color: "C-08", reason: "极简圆头冷面对话 + 田字四格分镜，公众号与小红书连载利器" }
      ]
    }
  ];

  function createInitialState() {
    return {
      version: 3,
      loggedIn: true,
      user: {
        username: "yang0",
        name: "Yang · 创作者",
        level: "Lv.4 资深主理人",
        inviteCode: "yang0"
      },
      credits: 128,
      freeQuotaRemaining: 3,
      freeQuotaMax: 3,
      dailyCheckedIn: false,
      collections: {
        styles: ["FA-001", "FX-001", "FB-031", "FC-029"],
        layouts: ["SC-021", "LX-001", "IG-001"],
        works: ["work_101", "work_103", "work_106"],
        topics: ["topic_201", "topic_204"]
      },
      unlockedIds: ["work_112"],
      likedIds: ["work_101"],
      works: JSON.parse(JSON.stringify(INITIAL_WORKS)),
      topics: JSON.parse(JSON.stringify(INITIAL_TOPICS)),
      communityResources: JSON.parse(JSON.stringify(COMMUNITY_RESOURCES)),
      ledger: [
        { id: "l1", time: "今天 09:40", reason: "作品《秋分节气手账》被收藏满 10 次里程碑奖励", delta: +5 },
        { id: "l2", time: "昨天 21:15", reason: "解锁角色设定作品《黑猫侍者特调师》完整参数", delta: -10 },
        { id: "l3", time: "昨天 18:02", reason: "通过专属分享海报成功邀请好友 @momo 注册", delta: +15 },
        { id: "l4", time: "昨天 10:00", reason: "新老用户迁移激活礼包（Discourse 账号无缝承接）", delta: +118 }
      ]
    };
  }

  window.HANDRAW_MOCK = {
    EXCLUSIVE_RESOURCES,
    COMMUNITY_RESOURCES,
    INITIAL_WORKS,
    INITIAL_TOPICS,
    XHS_DECK_TEMPLATES,
    ARTICLE_BATCH_TEMPLATES,
    AI_COMBO_PRESETS,
    createInitialState
  };
})();
