#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Handraw Web - Local Development Server
Zero-ops local development and debugging server for Handraw Studio.
Simulates Discourse + Handraw Plugin environment natively on Windows/Linux/macOS.
Strictly isolates Local Development from Online Production configurations.
"""

import sys
import os
import json
import time
import io
import mimetypes
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 on Windows console
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Workspace Paths
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PLUGIN_ROOT = REPO_ROOT / "plugin"
PUBLIC_DIR = PLUGIN_ROOT / "public"
CONTENT_DIR = PLUGIN_ROOT / "content"

# External handraw-style resource paths (if available locally)
HANDRAW_STYLE_ROOT = Path("E:/handraw-style")
GALLERY_DIR = HANDRAW_STYLE_ROOT / "skills" / "handdraw-style-prompter" / "gallery"
IMAGES_DIR = HANDRAW_STYLE_ROOT / "images"
REFERENCES_DIR = HANDRAW_STYLE_ROOT / "skills" / "handdraw-style-prompter" / "references"

DEV_DATA_FILE = SCRIPT_DIR / "dev_data.json"

# Import Config and Forum Emulators
sys.path.insert(0, str(SCRIPT_DIR))
from config import get_config
from local_forum import render_forum_latest, render_forum_topic

# Global active configuration
ACTIVE_CONFIG = get_config("local")

# Load Static Content Definitions
with open(CONTENT_DIR / "catalog.json", "r", encoding="utf-8") as f:
    CATALOG_DATA = json.load(f)

with open(CONTENT_DIR / "studio-options.json", "r", encoding="utf-8") as f:
    STUDIO_OPTIONS = json.load(f)

with open(CONTENT_DIR / "editorial.json", "r", encoding="utf-8") as f:
    EDITORIAL_DATA = json.load(f)

with open(CONTENT_DIR / "fusion-prompt.txt", "r", encoding="utf-8") as f:
    FUSION_TEMPLATE = f.read()

# Default Seed Test Data
DEFAULT_STATE = {
    "user": {
        "id": 1,
        "username": "yang0",
        "name": "旺旺老师",
        "avatar_template": "/images/avatar.png"
    },
    "wallet": {
        "balance": 88,
        "frozen": False,
        "welcome_claimed": True,
        "pending": 15,
        "entries": [
            {"amount": 10, "reason": "新人创作者欢迎礼", "created_at": "2026-10-20T10:00:00Z"},
            {"amount": 20, "reason": "作品《雨天与红雨靴》入选官方精选展位", "created_at": "2026-10-22T14:30:00Z"},
            {"amount": 58, "reason": "经验分享《自适应双拼照片转译社媒卡实战》获得社区解锁收益", "created_at": "2026-10-25T18:15:00Z"}
        ]
    },
    "official_collected": ["official:FA-001", "official:FB-006", "official:SC-021"],
    "collected_entry_ids": ["e-001", "e-003", "e-004"],
    "unlocked_entry_ids": ["e-001", "e-002"],
    "entries": [
        {
            "id": "e-001",
            "kind": "work",
            "title": "雨天与红雨靴",
            "summary": "在灰蒙蒙的雨天里，穿上一双鲜红的雨靴去踩水坑。极端透视与手绘墨线，带来温暖的童年叙事感。",
            "cover_url": "/images/individual/FB/FB-006.webp",
            "author": {"id": 1, "username": "yang0", "name": "旺旺老师"},
            "topic_url": "/t/101",
            "version": "1.0.0",
            "license": "CC-BY-NC-4.0",
            "featured": True,
            "verified": True,
            "paid": False,
            "price": 0,
            "pricing_mode": "free",
            "market": True,
            "forum_curated": False,
            "tradable": True,
            "review_pending": False,
            "content_available": True,
            "price_revision": 1,
            "bundle_available": False,
            "assets": [
                {"ref": "official:FB-006", "kind": "style", "role": "style", "version": "1.0.0", "name": "Bendy Absurd Storybook", "available": True}
            ],
            "examples": [],
            "collection_count": 42,
            "created_at": "2026-10-21T08:30:00Z",
            "source_label": None,
            "prompt": "请直接生成一张图片，忠实表达主题：在灰蒙蒙的雨天里穿上一双鲜红的雨靴去踩水坑\n\n创作类型：pure\n\n#FB-006 Bendy Absurd Storybook。核心风格特征：极端比例、弯曲结构、怪生物、流动线条、疯狂想象。\n\n【画幅比例】：3:4。【情绪】：温暖治愈。\n不要把参数标签和资源编号画进画面。",
            "parameters": {
                "theme": "在灰蒙蒙的雨天里穿上一双鲜红的雨靴去踩水坑",
                "mode": "pure",
                "style": "FB-006",
                "ratio": "3:4",
                "mood": "温暖治愈"
            }
        },
        {
            "id": "e-002",
            "kind": "experience",
            "title": "自适应双拼照片转译社媒卡实战与提示词解析",
            "summary": "左右双拼，左侧摄影实景、右侧手绘提炼。手绘侧清除照片环境杂质，保留大量纯净负空间。分享我的小红书爆款模版！",
            "cover_url": "/images/layouts/SC-021.webp",
            "author": {"id": 1, "username": "yang0", "name": "旺旺老师"},
            "topic_url": "/t/102",
            "version": "1.1.0",
            "license": "CC-BY-NC-SA-4.0",
            "featured": True,
            "verified": True,
            "paid": True,
            "price": 5,
            "pricing_mode": "fixed",
            "market": True,
            "forum_curated": False,
            "tradable": True,
            "review_pending": False,
            "content_available": True,
            "price_revision": 1,
            "bundle_available": False,
            "assets": [
                {"ref": "official:SC-021", "kind": "layout", "role": "layout", "version": "1.0.0", "name": "自适应双拼照片转译社媒卡", "available": True}
            ],
            "examples": [],
            "collection_count": 128,
            "created_at": "2026-10-22T11:20:00Z",
            "source_label": None,
            "prompt": "自适应双拼照片转译社媒卡。左右双拼，左侧摄影、右侧手绘。仅采用线稿涂鸦转译，不混用其他转译类型；手绘侧清除照片环境杂质，保留大量纯净负空间。",
            "content": "【双拼转译核心设计心法】\n1. 左右分割比例保持 1:1，手绘侧严格继承摄影侧的主体动作与视觉焦点。\n2. 手绘侧建议选用松散墨线或水彩绘本风（如 FA-001 或 FB-006），消除背景杂质。\n3. 保留大量纯白或米色负空间用于排版核心观点文字。\n4. 提示词技巧：在提示词中明确'左侧摄影现场、右侧手绘提炼，同一主体在不同时空的呼应'。",
            "parameters": {
                "theme": "双拼转译社媒卡制作经验",
                "layout": "SC-021",
                "layout_variant": 1
            }
        },
        {
            "id": "e-003",
            "kind": "work",
            "title": "今天也是不想上班的一天",
            "summary": "松散黑线、日常吐槽与冷脸小人。只要咖啡够大杯，今天就能撑过去。",
            "cover_url": "/images/individual/FA/FA-001.webp",
            "author": {"id": 2, "username": "coffee_cat", "name": "猫猫不打卡"},
            "topic_url": "/t/103",
            "version": "1.0.0",
            "license": "CC-BY-NC-4.0",
            "featured": False,
            "verified": True,
            "paid": False,
            "price": 0,
            "pricing_mode": "free",
            "market": True,
            "forum_curated": False,
            "tradable": True,
            "review_pending": False,
            "content_available": True,
            "price_revision": 1,
            "bundle_available": False,
            "assets": [
                {"ref": "official:FA-001", "kind": "style", "role": "style", "version": "1.0.0", "name": "Playful Deadpan Doodle", "available": True}
            ],
            "examples": [],
            "collection_count": 31,
            "created_at": "2026-10-23T14:10:00Z",
            "source_label": None,
            "prompt": "日常吐槽漫画，冷脸猫咪端着一杯巨大的美式咖啡，文字参与构图：'今天不想营业'。",
            "parameters": {
                "theme": "冷脸猫咪端着巨大咖啡",
                "mode": "graphic-text",
                "style": "FA-001"
            }
        },
        {
            "id": "e-004",
            "kind": "work",
            "title": "极简金属质感机械表·商业静物摄影",
            "summary": "精准的苹果风商业静物摄影，极具现代工业质感的高光与暗部层次。",
            "cover_url": "/images/individual/FI/FI-001.webp",
            "author": {"id": 3, "username": "lens_pro", "name": "光影大师"},
            "topic_url": "/t/104",
            "version": "1.0.0",
            "license": "CC-BY-NC-4.0",
            "featured": True,
            "verified": True,
            "paid": False,
            "price": 0,
            "pricing_mode": "free",
            "market": True,
            "forum_curated": False,
            "tradable": True,
            "review_pending": False,
            "content_available": True,
            "price_revision": 1,
            "bundle_available": False,
            "assets": [
                {"ref": "official:FI-001", "kind": "style", "role": "style", "version": "1.0.0", "name": "Apple Tech Photography", "available": True}
            ],
            "examples": [],
            "collection_count": 55,
            "created_at": "2026-10-24T09:40:00Z",
            "source_label": None,
            "prompt": "苹果风格高端工业设计产品静物摄影，极简金属机械腕表在深空灰哑光表面上的侧逆光特写。",
            "parameters": {
                "theme": "极简机械腕表商业摄影",
                "mode": "photo",
                "style": "FI-001"
            }
        },
        {
            "id": "e-005",
            "kind": "work",
            "title": "清晨的第一杯手冲咖啡",
            "summary": "现代极简平涂扁平插画，干净柔和的高级灰与暖橙对比，享受慢节奏的周末清晨。",
            "cover_url": "/images/individual/FC/FC-029.webp",
            "author": {"id": 4, "username": "vector_flow", "name": "矢量生活"},
            "topic_url": "/t/105",
            "version": "1.0.0",
            "license": "CC-BY-NC-4.0",
            "featured": False,
            "verified": False,
            "paid": False,
            "price": 0,
            "pricing_mode": "free",
            "market": True,
            "forum_curated": False,
            "tradable": True,
            "review_pending": False,
            "content_available": True,
            "price_revision": 1,
            "bundle_available": False,
            "assets": [
                {"ref": "official:FC-029", "kind": "style", "role": "style", "version": "1.0.0", "name": "Clean Airy Flat Vector", "available": True}
            ],
            "examples": [],
            "collection_count": 18,
            "created_at": "2026-10-24T16:20:00Z",
            "source_label": None,
            "prompt": "清晨木质餐桌上手冲滤杯滴落咖啡的温暖瞬间，清透扁平矢量插画风格。",
            "parameters": {
                "theme": "清晨手冲咖啡",
                "mode": "pure",
                "style": "FC-029"
            }
        },
        {
            "id": "e-006",
            "kind": "work",
            "title": "一盅两件·早茶时光",
            "summary": "暖橙青绿的广式早茶国潮，虾饺、烧卖、流沙包热气腾腾的人间烟火气。",
            "cover_url": "/images/individual/FE/FE-053.webp",
            "author": {"id": 5, "username": "canton_eats", "name": "老广饮茶"},
            "topic_url": "/t/106",
            "version": "1.0.0",
            "license": "CC-BY-NC-4.0",
            "featured": True,
            "verified": True,
            "paid": False,
            "price": 0,
            "pricing_mode": "free",
            "market": True,
            "forum_curated": False,
            "tradable": True,
            "review_pending": False,
            "content_available": True,
            "price_revision": 1,
            "bundle_available": False,
            "assets": [
                {"ref": "official:FE-053", "kind": "style", "role": "style", "version": "1.0.0", "name": "Cantonese Dim-Sum Guochao", "available": True}
            ],
            "examples": [],
            "collection_count": 67,
            "created_at": "2026-10-25T10:00:00Z",
            "source_label": None,
            "prompt": "岭南茶楼一角，竹蒸笼里晶莹剔透的虾饺与热气腾腾的普洱茶，现代生活国潮插画。",
            "parameters": {
                "theme": "广式早茶生活国潮",
                "mode": "pure",
                "style": "FE-053"
            }
        },
        {
            "id": "e-007",
            "kind": "work",
            "title": "周末治愈烘焙坊",
            "summary": "黏土3D质感与暖调微缩场景，胖乎乎的可颂与刚出炉的法棍面包。",
            "cover_url": "/images/individual/FF/FF-001.webp",
            "author": {"id": 6, "username": "clay_art", "name": "黏土梦境"},
            "topic_url": "/t/107",
            "version": "1.0.0",
            "license": "CC-BY-NC-4.0",
            "featured": False,
            "verified": False,
            "paid": False,
            "price": 0,
            "pricing_mode": "free",
            "market": True,
            "forum_curated": False,
            "tradable": True,
            "review_pending": False,
            "content_available": True,
            "price_revision": 1,
            "bundle_available": False,
            "assets": [
                {"ref": "official:FF-001", "kind": "style", "role": "style", "version": "1.0.0", "name": "Stylized 3D Cartoon", "available": True}
            ],
            "examples": [],
            "collection_count": 24,
            "created_at": "2026-10-25T13:30:00Z",
            "source_label": None,
            "prompt": "手工揉制面团的微缩厨房场景，3D黏土触感材质，暖光与面包香味。",
            "parameters": {
                "theme": "微缩黏土烘焙坊",
                "mode": "pure",
                "style": "FF-001"
            }
        },
        {
            "id": "e-008",
            "kind": "work",
            "title": "街角的光影与自行车",
            "summary": "iPhone 17 自然直出随手拍，斜阳穿过法桐树叶在青砖墙上投下的斑驳光影。",
            "cover_url": "/images/individual/FI/FI-032.webp",
            "author": {"id": 7, "username": "street_lens", "name": "街角观察家"},
            "topic_url": "/t/108",
            "version": "1.0.0",
            "license": "CC-BY-NC-4.0",
            "featured": True,
            "verified": True,
            "paid": False,
            "price": 0,
            "pricing_mode": "free",
            "market": True,
            "forum_curated": False,
            "tradable": True,
            "review_pending": False,
            "content_available": True,
            "price_revision": 1,
            "bundle_available": False,
            "assets": [
                {"ref": "official:FI-032", "kind": "style", "role": "style", "version": "1.0.0", "name": "iPhone 17 Candid Snapshot", "available": True}
            ],
            "examples": [],
            "collection_count": 89,
            "created_at": "2026-10-25T17:00:00Z",
            "source_label": None,
            "prompt": "深秋傍晚街角斜靠在青砖墙边的复古自行车，落叶与斑驳金黄斜阳，手机真实抓拍直出质感。",
            "parameters": {
                "theme": "街角光影与自行车随手拍",
                "mode": "photo",
                "style": "FI-032"
            }
        }
    ],
    "forum_topics": [
        {
            "id": 101,
            "title": "手绘风 3.0 正式发布，画风库扩容至 366 种！",
            "category": "官方公告",
            "author": "旺旺老师",
            "posts_count": 3,
            "created_at": "2026-10-21T10:00:00Z"
        },
        {
            "id": 102,
            "title": "探讨：社论涂鸦风格在商业封面设计中的应用经验",
            "category": "画风探索",
            "author": "猫猫不打卡",
            "posts_count": 2,
            "created_at": "2026-10-22T14:20:00Z"
        },
        {
            "id": 103,
            "title": "新手求助：如何让 AI 生成的手绘墨线更有纸面质感？",
            "category": "新手求助",
            "author": "插画小白",
            "posts_count": 2,
            "created_at": "2026-10-23T09:15:00Z"
        },
        {
            "id": 104,
            "title": "灵感集：适合国风生活小红书封面的图型搭配推荐",
            "category": "图型讨论",
            "author": "老广饮茶",
            "posts_count": 2,
            "created_at": "2026-10-24T16:30:00Z"
        }
    ],
    "forum_posts": {
        "101": [
            {
                "id": 1,
                "author": "旺旺老师",
                "content": "大家好！手绘风 3.0 今日正式上线。\n\n本次主要更新：\n1. 官方画风库扩容至 366 种，新增生活随拍写真（FI 系列）与 3D 黏土（FF 系列）。\n2. 创作台支持自适应双拼转译（SC-021）等 168 种构图图型。\n3. 支持在本地与线上无缝调试，欢迎大家在此交流！",
                "created_at": "2026-10-21 10:00"
            },
            {
                "id": 2,
                "author": "猫猫不打卡",
                "content": "太赞了！刚好在画一组社论吐槽漫画，FA-001 和 FB-006 的融合模式效果非常惊艳！",
                "created_at": "2026-10-21 11:30"
            },
            {
                "id": 3,
                "author": "光影大师",
                "content": "FI-001 科技大片摄影的材质高光表现非常细腻，支持旺旺老师！",
                "created_at": "2026-10-21 15:45"
            }
        ],
        "102": [
            {
                "id": 1,
                "author": "猫猫不打卡",
                "content": "在做商业微信公众号封面时，发现社论涂鸦风格（FA-001）加大量留白（whitespace: high）可以在标题区域留出极大视觉呼吸感，大家有什么排版心得吗？",
                "created_at": "2026-10-22 14:20"
            },
            {
                "id": 2,
                "author": "旺旺老师",
                "content": "非常推荐配合【自适应双拼社媒卡 SC-021】使用！左侧放纯色或写实，右侧放涂鸦手绘，手绘侧清除照片环境杂质，视觉冲击力极强。",
                "created_at": "2026-10-22 16:00"
            }
        ],
        "103": [
            {
                "id": 1,
                "author": "插画小白",
                "content": "新手刚开始使用手绘风，为什么有时生成的墨线会太光滑像矢量？如何增加粗糙水彩纸面质感？",
                "created_at": "2026-10-23 09:15"
            },
            {
                "id": 2,
                "author": "旺旺老师",
                "content": "可以在创作台的影调选项中勾选【微糙棉麻纸纹】或在补充要求中加入【手绘笔压、断续墨线、天然棉纸纤维】，也可以选择 FB 系列绘本画风。",
                "created_at": "2026-10-23 10:20"
            }
        ],
        "104": [
            {
                "id": 1,
                "author": "老广饮茶",
                "content": "最近在做广式早茶生活国潮（FE-053）系列，推荐大家搭配暖橙青绿配色，画面烟火气十足！",
                "created_at": "2026-10-24 16:30"
            },
            {
                "id": 2,
                "author": "矢量生活",
                "content": "流沙包和晶莹虾饺的暖调非常治愈，已经收藏了你的作品！",
                "created_at": "2026-10-24 18:10"
            }
        ]
    },
    "generation_tasks": [
        {
            "id": 101,
            "batch_id": "b-101",
            "client_id": "c-101",
            "title": "雨天与红雨靴",
            "status": "success",
            "message": None,
            "images": ["/images/individual/FB/FB-006.webp"],
            "batch_total": 1,
            "batch_position": 1,
            "prompt": "在灰蒙蒙的雨天里穿上一双鲜红的雨靴去踩水坑",
            "creation": {
                "parameters": {"theme": "在灰蒙蒙的雨天里穿上一双鲜红的雨靴去踩水坑", "style": "FB-006", "ratio": "3:4"},
                "assets": [{"ref": "official:FB-006", "kind": "style", "name": "Bendy Absurd Storybook"}]
            }
        },
        {
            "id": 102,
            "batch_id": "b-102",
            "client_id": "c-102",
            "title": "咖啡馆里的冷脸猫",
            "status": "success",
            "message": None,
            "images": ["/images/individual/FA/FA-001.webp"],
            "batch_total": 1,
            "batch_position": 1,
            "prompt": "日常吐槽漫画，冷脸猫咪端着巨大咖啡",
            "creation": {
                "parameters": {"theme": "日常吐槽漫画，冷脸猫咪端着巨大咖啡", "style": "FA-001", "mode": "graphic-text"},
                "assets": [{"ref": "official:FA-001", "kind": "style", "name": "Playful Deadpan Doodle"}]
            }
        }
    ],
    "private_images": {}
}


class DevStateManager:
    """Manages the in-memory state with JSON file persistence."""
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.state = self.load()

    def load(self):
        if self.filepath.exists():
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Merge missing fields if any
                    for key in ["forum_topics", "forum_posts"]:
                        if key not in data:
                            data[key] = DEFAULT_STATE[key]
                    print(f"[*] Loaded dev state from {self.filepath}")
                    return data
            except Exception as e:
                print(f"[!] Error loading {self.filepath}: {e}, using default state")
        return json.loads(json.dumps(DEFAULT_STATE))

    def save(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[!] Error saving dev state: {e}")


state_manager = DevStateManager(DEV_DATA_FILE)
STATE = state_manager.state


def localize_data(data):
    """Rewrites remote CDN URLs to local disk routes for offline debugging."""
    if not ACTIVE_CONFIG.get("offline_images"):
        return data
    if isinstance(data, str):
        data = data.replace("https://img.handraw-style.com/images/", "/images/")
        data = data.replace("https://static.handraw-style.com/gallery/", "/gallery/")
        data = data.replace("https://static.handraw-style.com/data/", "/data/")
        return data
    elif isinstance(data, dict):
        return {k: localize_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [localize_data(item) for item in data]
    return data


def resolve_creation_prompt(input_data):
    """
    Python implementation of Handraw::Creation.resolve from plugin/lib/handraw/creation.rb.
    """
    modes = ['pure', 'graphic-text', 'poster', 'article-cover', 'article-illust', 'photo']
    mode = input_data.get('mode') or 'pure'
    if mode not in modes:
        mode = 'pure'

    theme = (input_data.get('theme') or '').strip()
    if len(theme) < 5:
        theme = f"主题描述：{theme}（测试示例主题）"

    fusion = bool(input_data.get('fusion'))
    refs = [input_data.get('character_style'), input_data.get('scene_style')] if fusion else [input_data.get('style')]
    refs = [r for r in refs if r]

    linked = []
    references = input_data.get('references') or []
    styles = []

    for index, ref in enumerate(refs):
        if ref == 'realistic':
            styles.append('写实摄影，真实材质、自然光照与透视关系。')
            continue
        clean_ref = ref.replace('official:', '').replace('community:', '')
        asset = next((item for item in CATALOG_DATA['resources'] if item['id'] == clean_ref), None)
        if not asset:
            # check community entries
            entry = next((e for e in STATE['entries'] if e['id'] == clean_ref), None)
            if entry:
                asset = {'id': entry['id'], 'kind': entry['kind'], 'name': entry['title'], 'definition': entry.get('prompt')}
            else:
                asset = {'id': clean_ref, 'kind': 'style', 'name': clean_ref, 'definition': '精选手绘风格'}

        role = ['character', 'scene'][index] if fusion else 'style'
        linked.append({
            'ref': f"official:{asset['id']}",
            'kind': asset.get('kind', 'style'),
            'name': asset.get('name', asset.get('title')),
            'version': '1.0.0',
            'role': role
        })
        policy = STUDIO_OPTIONS.get('styles', {}).get(asset['id'], {})
        if policy.get('reference'):
            references.append({'source': 'official', 'path': policy['reference'], 'role': 'style', 'name': asset['name']})
        styles.append(policy.get('definition') or asset.get('definition') or asset.get('description', ''))

    ratio = input_data.get('ratio') or ('3:4' if fusion else '1:1')

    if fusion:
        parts = FUSION_TEMPLATE.replace('{character}', styles[0] if len(styles) > 0 else '') \
                               .replace('{scene}', styles[1] if len(styles) > 1 else '') \
                               .replace('{theme}', theme)
    else:
        parts = f"请直接生成一张图片，忠实表达主题：{theme}\n\n创作类型：{mode}\n\n{styles[0] if styles else ''}"

    mode_prompt = {
        'graphic-text': '【如果主题直白包含画面元素那就按主题出图，文案由你来升华，但是不要直接描述画面。 如果主题比较概念化，那么文案和主题尽量保持一致，如果文案较长由你提炼，由你先设计画面隐喻（人类和非人类都行）再出图   。    文字参与构图，图文一体】',
        'poster': '设计海报：先设计隐喻再出图，主标题明显，小字少或者没有小字。其他你帮我设计。',
        'article-cover': '设计文章封面：从文章中提炼核心观点，先设计隐喻再出图，主标题明显，小字少或者没有小字。',
        'article-illust': '为文章绘制一张正文插图，提炼核心观点与具象隐喻，不把全文排成文字海报。',
        'photo': '摄影写真，按照拍摄类型与主题安排人物、场景、光线和镜头。'
    }.get(mode)
    if mode_prompt:
        parts += f"\n\n{mode_prompt}"

    layout_ref = input_data.get('layout')
    if layout_ref and mode not in ['article-cover', 'article-illust']:
        clean_layout = layout_ref.replace('official:', '').replace('community:', '')
        layout = next((item for item in CATALOG_DATA['resources'] if item['id'] == clean_layout), None)
        if layout:
            linked.append({
                'ref': f"official:{layout['id']}",
                'kind': 'layout',
                'name': layout['name'],
                'version': '1.0.0',
                'role': 'layout'
            })
            definition = (layout.get('definition') or layout.get('description') or '').split('<!-- en -->')[0].replace('<!-- zh -->', '').strip()
            if layout['id'] == 'SC-021':
                variant = int(input_data.get('layout_variant') or 1)
                sc021_types = STUDIO_OPTIONS.get('sc021_types', [])
                type_desc = sc021_types[variant - 1] if 0 < variant <= len(sc021_types) else sc021_types[0]
                direction = '左右双拼，左侧摄影、右侧手绘'
                definition = f"自适应双拼照片转译社媒卡。{direction}。仅采用{type_desc}，不混用其他转译类型；手绘侧清除照片环境杂质，保留大量纯净负空间。"
            parts += f"\n\n【图型】：{definition}"
            if mode != 'graphic-text' and not layout['id'].startswith('EC-'):
                parts += "\n【如果主题直白包含画面元素那就按主题出图，文案由你来升华，但是不要直接描述画面。 如果主题比较概念化，那么文案和主题尽量保持一致，如果文案较长由你提炼，由你先设计画面隐喻（人类和非人类都行）再出图   。    文字参与构图，图文一体】"

    color_ref = input_data.get('color')
    if color_ref:
        clean_color = color_ref.replace('official:', '').replace('community:', '')
        color = next((item for item in CATALOG_DATA['resources'] if item['id'] == clean_color), None)
        if color:
            parts += f"\n\n{color.get('definition') or color.get('description')}"

    mood = input_data.get('mood') or ('治愈' if fusion else '')
    parts += f"\n\n【画幅比例】：{ratio}。"
    if mood:
        parts += f"【情绪】：{mood}。"
    parts += "\n不要把参数标签和资源编号画进画面。"

    whitespace = input_data.get('whitespace') or 'normal'
    if whitespace == 'moderate':
        parts += "\n【大量留白】"
    elif whitespace == 'high':
        parts += "\n【大量留白，场景只显示必要部分，不要显示全】"

    tones = input_data.get('tones') or []
    for t_id in tones:
        tone = next((t for t in STUDIO_OPTIONS.get('tones', []) if t['id'] == t_id), None)
        if tone:
            parts += f"\n影调：{tone['name_zh']}，{tone['desc_zh']}。"

    for key, label in [('audience', '受众'), ('channel', '投放渠道'), ('shoot_type', '拍摄类型'), ('extra', '用户补充要求')]:
        val = input_data.get(key)
        if val:
            parts += f"\n{label}：{val}"

    params = {k: v for k, v in input_data.items() if k in [
        'theme', 'mode', 'fusion', 'style', 'character_style', 'scene_style',
        'layout', 'color', 'ratio', 'whitespace', 'tones', 'audience',
        'channel', 'shoot_type', 'extra', 'layout_variant', 'references',
        'asset_refs', 'batch', 'count', 'themes', 'layouts', 'mix_layouts'
    ]}
    params['mood'] = mood
    params['quality'] = input_data.get('quality') or 'auto'

    return {
        'prompt': parts,
        'title': theme[:120],
        'ratio': ratio,
        'assets': linked,
        'references': references,
        'parameters': params
    }


def render_mock_image(title="手绘风创作", subtitle="HANDRAW STUDIO PREVIEW"):
    """Creates a stylized placeholder PNG matching the warm-paper Handraw aesthetic."""
    if HAS_PIL:
        im = Image.new("RGB", (768, 768), color=(250, 248, 244))
        draw = ImageDraw.Draw(im)
        draw.rectangle([20, 20, 748, 748], outline=(220, 214, 204), width=2)
        draw.rectangle([28, 28, 740, 740], outline=(169, 64, 40), width=1)
        draw.text((50, 60), "HANDRAW · LOCAL PREVIEW", fill=(169, 64, 40))
        draw.text((50, 110), f"{subtitle}", fill=(80, 80, 80))
        draw.text((50, 160), f"{title}", fill=(30, 30, 30))
        # Draw a small decorative ink stamp
        draw.rectangle([620, 60, 700, 140], outline=(169, 64, 40), width=2)
        draw.text((645, 90), "绘", fill=(169, 64, 40))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue(), "image/png"
    else:
        # Fallback SVG if PIL not present
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" viewBox="0 0 600 600">
          <rect width="100%" height="100%" fill="#faf8f4"/>
          <rect x="20" y="20" width="560" height="560" fill="none" stroke="#a94028" stroke-width="2"/>
          <text x="40" y="70" fill="#a94028" font-size="20" font-family="sans-serif">HANDRAW LOCAL PREVIEW</text>
          <text x="40" y="120" fill="#252722" font-size="24" font-weight="bold" font-family="sans-serif">{title}</text>
          <text x="40" y="160" fill="#666" font-size="16" font-family="sans-serif">{subtitle}</text>
        </svg>"""
        return svg.encode("utf-8"), "image/svg+xml"


class HandrawDevHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler emulating Handraw Discourse Plugin APIs."""

    def log_message(self, format, *args):
        # Clean terminal logging
        sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] {self.command} {self.path} - {format % args}\n")

    def send_json(self, data, status=200):
        localized = localize_data(data)
        body = json.dumps(localized, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-CSRF-Token, X-Requested-With")
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html_str, status=200):
        body = html_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_file_response(self, file_path: Path, content_type=None):
        if not file_path.exists():
            self.send_error(404, f"File not found: {file_path.name}")
            return
        if not content_type:
            content_type, _ = mimetypes.guess_type(str(file_path))
            content_type = content_type or "application/octet-stream"
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading file: {e}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-CSRF-Token, X-Requested-With")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. Main Portal Page: / or /studio
        if path in ["/", "/studio", "/studio/"]:
            return self.serve_portal_html(query)

        # Favicon (silent 204)
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        # 2. Session / CSRF
        if path == "/session/csrf.json":
            return self.send_json({"csrf": "handraw-dev-csrf-token-xyz"})

        # 3. Studio Assets: /studio/assets/<filename>
        if path.startswith("/studio/assets/"):
            filename = path.replace("/studio/assets/", "")
            if filename in ["catalog.json", "studio-options.json"]:
                return self.send_file_response(CONTENT_DIR / filename, "application/json")
            return self.send_file_response(PUBLIC_DIR / filename)

        # 4. Images: /images/<path> (Local SSD mapping from E:\handraw-style\images\)
        if path.startswith("/images/"):
            img_rel = path.replace("/images/", "")
            local_img = IMAGES_DIR / img_rel
            if local_img.exists() and local_img.is_file():
                return self.send_file_response(local_img)
            # Placeholder if image missing locally
            data, mime = render_mock_image(title=Path(img_rel).stem, subtitle=f"Image: {img_rel}")
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        # 5. Gallery Pages: /gallery/<filename>
        if path.startswith("/gallery/"):
            rel = path.replace("/gallery/", "")
            return self.send_file_response(GALLERY_DIR / rel)

        # 6. References: /data/<filename>
        if path.startswith("/data/"):
            rel = path.replace("/data/", "")
            return self.send_file_response(REFERENCES_DIR / rel)

        # 7. Core Portal APIs: /studio/api/*
        if path.startswith("/studio/api/"):
            return self.handle_studio_api_get(path.replace("/studio/api/", ""), query)

        # 8. Discourse Forum Handling (Local vs Remote mode)
        discourse_mode = ACTIVE_CONFIG.get("discourse_mode", "local")
        discourse_url = ACTIVE_CONFIG.get("discourse_url", "http://localhost:3000")

        if discourse_mode == "local":
            # Local Forum UI - 100% offline, zero leakage to internet
            nav_html = self.get_navigation_html(surface="forum", active="community")
            
            # Forum Latest / Home
            if path in ["/latest", "/top", "/categories"]:
                topics = STATE.get("forum_topics", [])
                categories = ["社区交流", "画风探索", "图型讨论", "新手求助", "官方公告"]
                return self.send_html(render_forum_latest(topics, categories, nav_html))

            # Forum Category View: /c/:category_id
            if path.startswith("/c/"):
                cat_id = path.replace("/c/", "").split("/")[0]
                cat_names = {"1": "画风探索", "2": "图型讨论", "3": "新手求助", "4": "官方公告"}
                cat_name = cat_names.get(cat_id, "社区交流")
                topics = [t for t in STATE.get("forum_topics", []) if t.get("category") == cat_name]
                return self.send_html(render_forum_latest(topics, [], nav_html, current_category=cat_id))

            # Forum Topic View: /t/:topic_id
            if path.startswith("/t/"):
                try:
                    topic_id = int(path.replace("/t/", "").split("/")[0].split(".")[0])
                except Exception:
                    topic_id = 101

                topic = next((t for t in STATE.get("forum_topics", []) if t["id"] == topic_id), None)
                if not topic:
                    # check community entries
                    entry = next((e for e in STATE.get("entries", []) if e.get("topic_url") == f"/t/{topic_id}"), None)
                    if entry:
                        topic = {"id": topic_id, "title": entry["title"], "category": "社区作品", "created_at": entry["created_at"]}
                    else:
                        topic = {"id": topic_id, "title": f"讨论话题 #{topic_id}", "category": "社区交流", "created_at": "刚刚"}

                posts = STATE.get("forum_posts", {}).get(str(topic_id), [
                    {
                        "id": 1,
                        "author": topic.get("author", "旺旺老师"),
                        "content": f"关于话题《{topic['title']}》的讨论与经验分享。\n\n欢迎大家在本地交流讨论！",
                        "created_at": "刚刚"
                    }
                ])
                return self.send_html(render_forum_topic(topic, posts, nav_html))

            # User Profile: /u/:username
            if path.startswith("/u/"):
                username = path.replace("/u/", "").split("/")[0]
                return self.send_html(f"""{nav_html}
                <div style="max-width:800px;margin:40px auto;padding:24px;background:#fffdf9;border:1px solid #ded8cf;border-radius:8px;">
                  <h2>用户个人主页: @{username}</h2>
                  <p>当前处于 <strong>Local Dev</strong> 调试模式，用户信息保存在本地。</p>
                  <a href="/studio" style="color:#a94028;">← 返回手绘风创作台</a>
                </div>""")

            # Guidelines: /guidelines
            if path == "/guidelines":
                return self.send_html(f"""{nav_html}
                <div style="max-width:800px;margin:40px auto;padding:24px;background:#fffdf9;border:1px solid #ded8cf;border-radius:8px;line-height:1.8;">
                  <h2>手绘风社区准则 (Local Dev)</h2>
                  <p>1. 尊重原创创作者，分享优质提示词与视觉灵感。</p>
                  <p>2. 友好交流，共建高质量手绘风视觉资产社区。</p>
                  <div style="margin-top:24px;"><a href="/studio" style="color:#a94028;">← 返回创作台</a></div>
                </div>""")

            # Login: /login
            if path == "/login":
                return self.send_html(f"""{nav_html}
                <div style="max-width:500px;margin:60px auto;padding:32px;background:#fffdf9;border:1px solid #ded8cf;border-radius:8px;text-align:center;">
                  <h2>本地免密登录调试</h2>
                  <p>当前登录用户: <strong>{STATE['user']['name']} (@{STATE['user']['username']})</strong></p>
                  <p style="color:#666;font-size:14px;">在 local 模式下已默认授予创作者与审核员权限。</p>
                  <a href="/studio" class="hw-button" style="display:inline-block;margin-top:16px;">进入手绘风创作台 →</a>
                </div>""")

        else:
            # Remote Mode: Redirect to online Discourse
            discourse_prefixes = (
                "/latest", "/top", "/categories", "/c/", "/t/", "/u/",
                "/login", "/signup", "/guidelines", "/badges", "/faq",
                "/tos", "/privacy", "/search", "/notifications"
            )
            for prefix in discourse_prefixes:
                matched = path.startswith(prefix) if prefix.endswith("/") else (
                    path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?")
                )
                if matched:
                    query_str = f"?{parsed.query}" if parsed.query else ""
                    target_url = f"{discourse_url.rstrip('/')}{path}{query_str}"
                    self.send_response(302)
                    self.send_header("Location", target_url)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    return

        self.send_error(404, f"Path not found: {path}")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""
        payload = {}
        if body:
            content_type = self.headers.get("Content-Type", "")
            if "application/json" in content_type:
                try:
                    payload = json.loads(body.decode("utf-8"))
                except Exception:
                    payload = {}
            elif "application/x-www-form-urlencoded" in content_type:
                try:
                    form_dict = urllib.parse.parse_qs(body.decode("utf-8"))
                    payload = {k: v[0] for k, v in form_dict.items()}
                except Exception:
                    payload = {}

        # 1. Local Forum Topic Reply: /t/:id/reply
        if path.startswith("/t/") and path.endswith("/reply"):
            topic_id = path.split("/t/")[1].split("/reply")[0]
            reply_text = payload.get("reply", "").strip()
            if reply_text:
                if str(topic_id) not in STATE.setdefault("forum_posts", {}):
                    STATE["forum_posts"][str(topic_id)] = []
                STATE["forum_posts"][str(topic_id)].append({
                    "id": len(STATE["forum_posts"][str(topic_id)]) + 1,
                    "author": STATE["user"]["name"],
                    "content": reply_text,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                })
                # increment post count
                for t in STATE.get("forum_topics", []):
                    if str(t.get("id")) == str(topic_id):
                        t["posts_count"] = t.get("posts_count", 1) + 1
                state_manager.save()

            self.send_response(302)
            self.send_header("Location", f"/t/{topic_id}")
            self.end_headers()
            return

        # 2. Local Forum Topic Create: /studio/api/forum/topics
        if path == "/studio/api/forum/topics":
            title = payload.get("title", "").strip()
            category = payload.get("category", "社区交流")
            content = payload.get("content", "").strip()
            if title:
                new_id = len(STATE.get("forum_topics", [])) + 101
                new_topic = {
                    "id": new_id,
                    "title": title,
                    "category": category,
                    "author": STATE["user"]["name"],
                    "posts_count": 1,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                }
                STATE.setdefault("forum_topics", []).insert(0, new_topic)
                STATE.setdefault("forum_posts", {})[str(new_id)] = [
                    {
                        "id": 1,
                        "author": STATE["user"]["name"],
                        "content": content or title,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                    }
                ]
                state_manager.save()
            self.send_response(302)
            self.send_header("Location", "/latest")
            self.end_headers()
            return

        # 3. Studio APIs
        if path.startswith("/studio/api/"):
            return self.handle_studio_api_post(path.replace("/studio/api/", ""), query, payload, body)

        self.send_error(404, f"POST path not found: {path}")

    def do_PATCH(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""
        payload = json.loads(body.decode("utf-8")) if body else {}

        if path.startswith("/studio/api/entries/"):
            entry_id = path.replace("/studio/api/entries/", "").split("/")[0]
            for e in STATE["entries"]:
                if e["id"] == entry_id:
                    if "entry" in payload:
                        e.update({k: v for k, v in payload["entry"].items() if v is not None})
                    state_manager.save()
                    return self.send_json(self.format_entry(e))
            return self.send_error(404, "Entry not found")

        self.send_error(404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/studio/api/assets/") and path.endswith("/collection"):
            ref = urllib.parse.unquote(path.split("/studio/api/assets/")[1].split("/collection")[0])
            if ref in STATE["official_collected"]:
                STATE["official_collected"].remove(ref)
                state_manager.save()
            return self.send_json({"collected": False})

        if path.startswith("/studio/api/entries/") and path.endswith("/collection"):
            entry_id = path.split("/studio/api/entries/")[1].split("/collection")[0]
            if entry_id in STATE["collected_entry_ids"]:
                STATE["collected_entry_ids"].remove(entry_id)
                state_manager.save()
            self.send_response(204)
            self.end_headers()
            return

        self.send_error(404)

    # --- HTML Shell Rendering ---
    def get_navigation_html(self, surface="portal", active=None):
        nav_path = PUBLIC_DIR / "navigation.html"
        nav_html = ""
        if nav_path.exists():
            with open(nav_path, "r", encoding="utf-8") as f:
                nav_html = f.read()

        nav_html = nav_html.replace('data-surface="portal"', f'data-surface="{surface}"')
        if active:
            nav_html = nav_html.replace(f'data-site-section="{active}"', f'data-site-section="{active}" aria-current="page"')
        
        # Localize navigation URLs in local mode
        if ACTIVE_CONFIG.get("is_local"):
            nav_html = nav_html.replace("https://handraw-style.com/studio", "/studio")
            nav_html = nav_html.replace("https://handraw-style.com/login", "/login")
            nav_html = nav_html.replace("https://handraw-style.com/latest", "/latest")

        return nav_html

    def serve_portal_html(self, query):
        index_path = PUBLIC_DIR / "index.html"
        if not index_path.exists():
            return self.send_error(500, "plugin/public/index.html missing")

        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()

        view = query.get("view", ["home"])[0]
        creator = query.get("creator", [None])[0]
        if creator:
            view = "creator"

        active = {
            "resources": "explore",
            "explore": "explore",
            "works": "community",
            "experience": "community",
            "community": "community",
            "creator": "community",
            "create": "create",
            "learn": "learn"
        }.get(view, "explore" if view == "explore" else None)

        nav_html = self.get_navigation_html(surface="portal", active=active)
        html = html.replace("<!-- handraw-navigation -->", nav_html)

        # Hide Hero on subviews
        if view != "home":
            html = html.replace('id="hero"', 'id="hero" hidden')

        # Local development banner / label in footer
        html = html.replace(
            '<span id="release"></span>',
            f'<span id="release" style="margin-left:12px;padding:2px 8px;border-radius:4px;background:#e5ded3;color:#8f301a;font-size:12px;">LOCAL DEV · 旺旺调试环境 (模式: {ACTIVE_CONFIG.get("discourse_mode", "local")})</span>'
        )

        # Localize image and static URLs in local mode
        if ACTIVE_CONFIG.get("offline_images"):
            html = html.replace("https://img.handraw-style.com/images/", "/images/")

        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- API Handlers ---
    def handle_studio_api_get(self, subpath, query):
        # /boot
        if subpath == "boot":
            editorial_payload = dict(EDITORIAL_DATA)
            for g in editorial_payload.get("guides", []):
                g["url"] = f"/t/{g.get('topic_id', 101)}"
                g["title"] = g.get("title") or f"指南：{g.get('summary', '')[:20]}"

            is_local = ACTIVE_CONFIG.get("is_local")
            boot_data = {
                "user": STATE["user"],
                "participant": True,
                "reviewer": True,
                "pilot": False,
                "official": {
                    "styles": "/gallery/index.html" if is_local else "https://static.handraw-style.com/gallery/index.html",
                    "layouts": "/gallery/layouts.html" if is_local else "https://static.handraw-style.com/gallery/layouts.html"
                },
                "rules": {
                    "welcome": 10,
                    "settlement_days": 7,
                    "author_percent": 80,
                    "initial_price": 5,
                    "min_price": 1,
                    "max_price": 50,
                    "price_days": 30
                },
                "categories": [
                    [1, "社区交流"],
                    [2, "画风探索"],
                    [3, "新手求助"],
                    [4, "优质作品"],
                    [5, "公告板"]
                ],
                "editorial": editorial_payload,
                "generation": {
                    "enabled": True,
                    "available": True,
                    "daily_limit": 50
                },
                "fixed_price_max": 50,
                "min_title_length": 5,
                "release": "local-dev-v3.0"
            }
            return self.send_json(boot_data)

        # /feed
        if subpath == "feed":
            kind = query.get("kind", [None])[0]
            search = query.get("q", [""])[0].lower()
            sort = query.get("sort", ["recommended"])[0]

            entries = list(STATE["entries"])
            if kind == "resource":
                entries = [e for e in entries if e["kind"] in ["style", "layout"]]
            elif kind and kind != "":
                entries = [e for e in entries if e["kind"] == kind]

            if search:
                entries = [e for e in entries if search in e["title"].lower() or search in e["summary"].lower()]

            if sort == "latest":
                entries.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            else:
                entries.sort(key=lambda x: (x.get("featured", False), x.get("collection_count", 0)), reverse=True)

            formatted_entries = [self.format_entry(e) for e in entries]

            # Discussions list
            discussions = []
            if kind != "work":
                topics = STATE.get("forum_topics", [])
                for t in topics[:6]:
                    discussions.append({
                        "title": t.get("title"),
                        "url": f"/t/{t.get('id')}",
                        "posts_count": t.get("posts_count", 1)
                    })

            return self.send_json({
                "entries": formatted_entries,
                "discussions": discussions
            })

        # /assets or /assets/:ref
        if subpath.startswith("assets"):
            parts = subpath.split("/")
            if len(parts) == 1:
                kind = query.get("kind", ["style"])[0]
                q = query.get("q", [""])[0].lower().lstrip("#")
                source = query.get("source", [""])[0]

                items = []
                if source != "community":
                    for r in CATALOG_DATA["resources"]:
                        if r["kind"] == kind:
                            item = dict(r)
                            item.pop("definition", None)
                            item["ref"] = f"official:{r['id']}"
                            item["source"] = "official"
                            item["price"] = 0
                            item["version"] = "1.0.0"
                            item["unlocked"] = True
                            item["tradable"] = True
                            item["collected"] = f"official:{r['id']}" in STATE["official_collected"]
                            item["author"] = {"name": "手绘风官方"}
                            item["license"] = "沿用官方 Skill 的使用说明"
                            items.append(item)

                if q:
                    filtered = []
                    for it in items:
                        text = f"{it.get('id', '')} {it.get('name', '')} {it.get('legacy', '')} {it.get('description', '')}".lower()
                        if q in text:
                            filtered.append(it)
                    items = filtered

                return self.send_json({"assets": items})

            ref = urllib.parse.unquote(parts[1])
            if len(parts) >= 3 and parts[2] == "content":
                return self.handle_asset_content(ref)
            if len(parts) >= 3 and parts[2] == "related":
                return self.handle_asset_related(ref)

            return self.handle_asset_show(ref)

        # /generations
        if subpath == "generations":
            tasks = list(STATE["generation_tasks"])
            return self.send_json({
                "remaining": 48,
                "tasks": tasks
            })

        if subpath.startswith("generations/") and subpath.endswith("/image"):
            task_id = subpath.split("/")[1]
            data, mime = render_mock_image(title=f"生成任务 #{task_id}", subtitle="Handraw Studio Task Image")
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if subpath.startswith("generations/") and subpath.endswith("/content"):
            task_id = int(subpath.split("/")[1])
            task = next((t for t in STATE["generation_tasks"] if t["id"] == task_id), None)
            if task:
                return self.send_json({
                    "prompt": task.get("prompt", ""),
                    "creation": task.get("creation", {})
                })
            return self.send_error(404, "Generation task not found")

        # /library
        if subpath == "library":
            owned = [self.format_entry(e) for e in STATE["entries"] if e["author"]["id"] == STATE["user"]["id"]]
            collected = [self.format_entry(e) for e in STATE["entries"] if e["id"] in STATE["collected_entry_ids"]]
            official = []
            for ref in STATE["official_collected"]:
                clean = ref.replace("official:", "")
                asset = next((r for r in CATALOG_DATA["resources"] if r["id"] == clean), None)
                if asset:
                    it = dict(asset)
                    it.pop("definition", None)
                    it["ref"] = ref
                    it["source"] = "official"
                    it["collected"] = True
                    it["author"] = {"name": "手绘风官方"}
                    official.append(it)

            return self.send_json({
                "owned": owned,
                "collected": collected,
                "official": official
            })

        # /wallet
        if subpath == "wallet":
            return self.send_json(STATE["wallet"])

        # /creators/:username
        if subpath.startswith("creators/"):
            username = urllib.parse.unquote(subpath.replace("creators/", ""))
            user_entries = [self.format_entry(e) for e in STATE["entries"] if e["author"]["username"].lower() == username.lower()]
            return self.send_json({
                "author": {"username": username, "name": f"{username} (创作者)", "profile_url": f"/u/{username}"},
                "featured_count": sum(1 for e in user_entries if e.get("featured")),
                "verified_count": sum(1 for e in user_entries if e.get("verified")),
                "contributions": {
                    "work": {"published": len(user_entries), "featured": 1, "verified": 1, "useful_users": 15, "reuse_users": 8, "honor": "精选创作者"},
                    "experience": {"published": 1, "featured": 1, "verified": 1, "useful_users": 12, "reuse_users": 5, "honor": "经验导师"},
                    "style": {"published": 0, "featured": 0, "verified": 0, "useful_users": 0, "reuse_users": 0, "honor": None},
                    "layout": {"published": 0, "featured": 0, "verified": 0, "useful_users": 0, "reuse_users": 0, "honor": None}
                },
                "entries": user_entries
            })

        # /entries/:id
        if subpath.startswith("entries/"):
            parts = subpath.split("/")
            entry_id = parts[1]
            entry = next((e for e in STATE["entries"] if e["id"] == entry_id), None)
            if not entry:
                return self.send_error(404, f"Entry {entry_id} not found")

            if len(parts) >= 3 and parts[2] == "content":
                return self.send_json({
                    "prompt": entry.get("prompt", ""),
                    "content": entry.get("content", entry.get("summary", "")),
                    "parameters": entry.get("parameters", {}),
                    "assets": entry.get("assets", [])
                })

            return self.send_json(self.format_entry(entry))

        # /review
        if subpath == "review":
            return self.send_json({"queue": []})

        self.send_error(404, f"API endpoint not found: {subpath}")

    def handle_studio_api_post(self, subpath, query, payload, raw_body):
        # /creation/resolve
        if subpath == "creation/resolve":
            creation = payload.get("creation", {})
            try:
                resolved = resolve_creation_prompt(creation)
                return self.send_json(dict(resolved, plans=[resolved]))
            except Exception as e:
                return self.send_json({"errors": [str(e)]}, status=422)

        # /generations
        if subpath == "generations":
            creation = payload.get("creation", {})
            client_id = payload.get("client_id", f"c-{int(time.time())}")
            resolved = resolve_creation_prompt(creation)
            new_id = len(STATE["generation_tasks"]) + 101

            task = {
                "id": new_id,
                "batch_id": f"b-{new_id}",
                "client_id": client_id,
                "title": resolved["title"],
                "status": "success",
                "message": None,
                "images": [f"/studio/api/generations/{new_id}/image"],
                "batch_total": 1,
                "batch_position": 1,
                "prompt": resolved["prompt"],
                "creation": {
                    "parameters": resolved["parameters"],
                    "assets": resolved["assets"]
                }
            }
            STATE["generation_tasks"].insert(0, task)
            state_manager.save()
            return self.send_json(dict(task, tasks=STATE["generation_tasks"]))

        # /generations/:id/retry
        if subpath.startswith("generations/") and subpath.endswith("/retry"):
            task_id = int(subpath.split("/")[1])
            task = next((t for t in STATE["generation_tasks"] if t["id"] == task_id), None)
            if task:
                task["status"] = "success"
                state_manager.save()
            return self.send_json({"status": "queued"})

        # /generation-batches/:batch_id/cancel
        if subpath.startswith("generation-batches/") and subpath.endswith("/cancel"):
            return self.send_json({"status": "cancelled"})

        # /welcome
        if subpath == "welcome":
            if not STATE["wallet"]["welcome_claimed"]:
                STATE["wallet"]["welcome_claimed"] = True
                STATE["wallet"]["balance"] += 10
                STATE["wallet"]["entries"].insert(0, {
                    "amount": 10,
                    "reason": "新人创作者欢迎礼",
                    "created_at": datetime.now(timezone.utc).isoformat()
                })
                state_manager.save()
            return self.send_json(STATE["wallet"])

        # /entries
        if subpath == "entries":
            entry_input = payload.get("entry", {})
            new_id = f"e-{len(STATE['entries']) + 1:03d}"
            new_entry = {
                "id": new_id,
                "kind": entry_input.get("kind", "work"),
                "title": entry_input.get("title", "未命名作品"),
                "summary": entry_input.get("summary", ""),
                "cover_url": entry_input.get("cover_url", "/images/individual/FB/FB-006.webp"),
                "author": STATE["user"],
                "topic_url": f"/t/{new_id}",
                "version": "1.0.0",
                "license": entry_input.get("license", "CC-BY-NC-4.0"),
                "featured": False,
                "verified": True,
                "paid": bool(entry_input.get("paid")),
                "price": int(entry_input.get("price", 0)),
                "pricing_mode": entry_input.get("pricing_mode", "free"),
                "market": True,
                "forum_curated": False,
                "tradable": True,
                "review_pending": False,
                "content_available": True,
                "price_revision": 1,
                "bundle_available": False,
                "assets": entry_input.get("assets", []),
                "examples": [],
                "collection_count": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "prompt": entry_input.get("prompt", ""),
                "content": entry_input.get("content", ""),
                "parameters": entry_input.get("parameters", {})
            }
            STATE["entries"].insert(0, new_entry)
            state_manager.save()
            return self.send_json(self.format_entry(new_entry), status=201)

        # /assets/:ref/collection
        if subpath.startswith("assets/") and subpath.endswith("/collection"):
            ref = urllib.parse.unquote(subpath.split("/assets/")[1].split("/collection")[0])
            if ref not in STATE["official_collected"]:
                STATE["official_collected"].append(ref)
                state_manager.save()
            return self.send_json({"collected": True})

        # /entries/:id/collection
        if subpath.startswith("entries/") and subpath.endswith("/collection"):
            entry_id = subpath.split("/entries/")[1].split("/collection")[0]
            if entry_id not in STATE["collected_entry_ids"]:
                STATE["collected_entry_ids"].append(entry_id)
                state_manager.save()
            return self.send_json({"collected": True})

        # /entries/:id/unlock
        if subpath.startswith("entries/") and subpath.endswith("/unlock"):
            entry_id = subpath.split("/entries/")[1].split("/unlock")[0]
            entry = next((e for e in STATE["entries"] if e["id"] == entry_id), None)
            if entry and entry["id"] not in STATE["unlocked_entry_ids"]:
                price = entry.get("price", 0)
                if STATE["wallet"]["balance"] >= price:
                    STATE["wallet"]["balance"] -= price
                    STATE["wallet"]["entries"].insert(0, {
                        "amount": -price,
                        "reason": f"解锁作品《{entry['title']}》",
                        "created_at": datetime.now(timezone.utc).isoformat()
                    })
                    STATE["unlocked_entry_ids"].append(entry["id"])
                    state_manager.save()
            return self.send_json(self.format_entry(entry))

        # /entries/:id/events
        if subpath.startswith("entries/") and subpath.endswith("/events"):
            self.send_response(204)
            self.end_headers()
            return

        # /impressions
        if subpath == "impressions":
            self.send_response(204)
            self.end_headers()
            return

        # /private-images
        if subpath == "private-images":
            img_id = f"img-{int(time.time())}"
            return self.send_json({
                "id": img_id,
                "url": f"/studio/api/private-images/{img_id}"
            })

        self.send_error(404, f"POST API not found: {subpath}")

    # --- Helper Data Formatters ---
    def format_entry(self, entry):
        formatted = dict(entry)
        formatted["collected"] = entry["id"] in STATE["collected_entry_ids"]
        formatted["unlocked"] = entry["id"] in STATE["unlocked_entry_ids"] or entry["author"]["id"] == STATE["user"]["id"]
        return formatted

    def handle_asset_show(self, ref):
        clean_ref = ref.replace("official:", "").replace("community:", "")
        item = next((r for r in CATALOG_DATA["resources"] if r["id"] == clean_ref), None)
        if item:
            payload = dict(item)
            payload.pop("definition", None)
            payload["ref"] = f"official:{item['id']}"
            payload["source"] = "official"
            payload["price"] = 0
            payload["version"] = "1.0.0"
            payload["unlocked"] = True
            payload["tradable"] = True
            payload["collected"] = f"official:{item['id']}" in STATE["official_collected"]
            payload["author"] = {"name": "手绘风官方"}
            payload["license"] = "沿用官方 Skill 的使用说明"
            return self.send_json(payload)

        # Check community entries
        entry = next((e for e in STATE["entries"] if e["id"] == clean_ref), None)
        if entry:
            return self.send_json(self.format_entry(entry))

        return self.send_error(404, f"Asset not found: {ref}")

    def handle_asset_content(self, ref):
        clean_ref = ref.replace("official:", "").replace("community:", "")
        item = next((r for r in CATALOG_DATA["resources"] if r["id"] == clean_ref), None)
        if item:
            definition = item.get("definition") or item.get("description", "")
            resource = {
                "id": f"official:{item['id']}",
                "kind": item["kind"],
                "name": item["name"],
                "prompt_zh": definition,
                "prompt_en": definition,
                "license": "沿用官方 Skill 的使用说明",
                "version": "1.0.0",
                "author": {"name": "手绘风官方"},
                "source": f"/studio?view=explore&asset=official:{item['id']}"
            }
            return self.send_json({
                "resource": resource,
                "sha256": "dev-asset-sha256"
            })
        return self.send_error(404, f"Asset content not found: {ref}")

    def handle_asset_related(self, ref):
        clean_ref = ref.replace("official:", "").replace("community:", "")
        works = []
        experiences = []
        for e in STATE["entries"]:
            for a in e.get("assets", []):
                if a.get("ref", "").endswith(clean_ref):
                    if e["kind"] == "work":
                        works.append(self.format_entry(e))
                    elif e["kind"] == "experience":
                        experiences.append(self.format_entry(e))
        return self.send_json({
            "works": works,
            "experiences": experiences
        })


def run(env="local", port=None, host=None, discourse_mode=None, discourse_url=None):
    global ACTIVE_CONFIG
    cli_overrides = {}
    if port: cli_overrides["port"] = port
    if host: cli_overrides["host"] = host
    if discourse_mode: cli_overrides["discourse_mode"] = discourse_mode
    if discourse_url: cli_overrides["discourse_url"] = discourse_url

    ACTIVE_CONFIG = get_config(env, cli_overrides)
    bind_host = ACTIVE_CONFIG.get("host", "127.0.0.1")
    bind_port = ACTIVE_CONFIG.get("port", 3000)

    server_address = (bind_host, bind_port)
    try:
        httpd = ThreadingHTTPServer(server_address, HandrawDevHandler)
    except OSError as e:
        if "address already in use" in str(e).lower() or getattr(e, "errno", None) == 10048:
            print(f"[!] Port {bind_port} is occupied, trying port {bind_port + 1}...")
            bind_port += 1
            server_address = (bind_host, bind_port)
            ACTIVE_CONFIG["port"] = bind_port
            httpd = ThreadingHTTPServer(server_address, HandrawDevHandler)
        else:
            raise

    print("=" * 70)
    print("  [+] Handraw Web Server Ready")
    print(f"  [+] Environment: {ACTIVE_CONFIG.get('name')} [{ACTIVE_CONFIG.get('env')}]")
    print(f"  [+] Local Studio URL: http://localhost:{bind_port}/studio")
    print(f"  [+] Discourse Mode: {ACTIVE_CONFIG.get('discourse_mode')} -> {ACTIVE_CONFIG.get('discourse_url')}")
    print(f"  [+] Image Delivery: {ACTIVE_CONFIG.get('image_mode')} (Offline: {ACTIVE_CONFIG.get('offline_images')})")
    print(f"  [+] User Identity: {STATE['user']['name']} (@{STATE['user']['username']})")
    print(f"  [+] Data Storage: {ACTIVE_CONFIG.get('storage_driver')} ({ACTIVE_CONFIG.get('storage_file')})")
    print("=" * 70)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Stopping development server...")
        httpd.server_close()
        print("[*] Stopped.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Handraw Web Server")
    parser.add_argument("--env", default="local", choices=["local", "production"], help="Environment profile (default: local)")
    parser.add_argument("--host", default=None, help="Host to bind (default from config)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind (default from config)")
    parser.add_argument("--discourse-mode", choices=["local", "remote"], default=None, help="Discourse forum mode: local (serve local forum) or remote (redirect to online)")
    parser.add_argument("--discourse", default=None, help="Discourse upstream URL")
    args = parser.parse_args()

    run(env=args.env, port=args.port, host=args.host, discourse_mode=args.discourse_mode, discourse_url=args.discourse)
