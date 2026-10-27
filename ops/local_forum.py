#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Handraw Web - Local Discourse Forum Emulator
Provides a complete, isolated local Discourse forum experience for local web debugging.
Renders /latest, /t/:id, /c/:id, /u/:username, and /guidelines without external internet.
"""

def render_forum_header(nav_html, active_tab="latest"):
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>手绘风社区论坛 (Local Dev)</title>
  <link rel="stylesheet" href="/studio/assets/navigation.css" />
  <link rel="stylesheet" href="/studio/assets/portal.css" />
  <link rel="stylesheet" href="/studio/assets/market.css" />
  <style>
    :root {{
      --hw-paper: #faf8f4;
      --hw-ink: #252722;
      --hw-vermilion: #a94028;
      --hw-border: #ded8cf;
      --hw-card-bg: #fffdf9;
    }}
    body {{
      margin: 0;
      background: var(--hw-paper);
      color: var(--hw-ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      line-height: 1.6;
    }}
    .hw-forum-banner {{
      background: #fbf0ea;
      border-bottom: 1px solid #ebd2c6;
      color: #8c321d;
      padding: 10px 24px;
      font-size: 13px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .hw-forum-banner code {{
      background: #f4ded4;
      padding: 2px 6px;
      border-radius: 4px;
      font-family: monospace;
    }}
    .hw-forum-container {{
      max-width: 1100px;
      margin: 24px auto 60px;
      padding: 0 20px;
    }}
    .hw-forum-nav-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .hw-forum-tabs {{
      display: flex;
      gap: 8px;
    }}
    .hw-forum-tab {{
      padding: 6px 14px;
      border-radius: 6px;
      text-decoration: none;
      color: #666;
      font-size: 14px;
      font-weight: 500;
      transition: all 0.2s;
    }}
    .hw-forum-tab:hover {{
      background: #eee8de;
      color: var(--hw-ink);
    }}
    .hw-forum-tab.active {{
      background: var(--hw-vermilion);
      color: #fff;
    }}
    .hw-forum-btn {{
      background: var(--hw-vermilion);
      color: #fff;
      border: none;
      padding: 8px 16px;
      border-radius: 6px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .hw-forum-btn:hover {{
      background: #8e321c;
    }}
    .hw-forum-btn-quiet {{
      background: transparent;
      color: var(--hw-vermilion);
      border: 1px solid var(--hw-vermilion);
    }}
    .hw-forum-btn-quiet:hover {{
      background: #faede9;
    }}
    .hw-topic-table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--hw-card-bg);
      border: 1px solid var(--hw-border);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 2px 8px rgba(0,0,0,0.03);
    }}
    .hw-topic-table th {{
      background: #f4eee3;
      padding: 12px 16px;
      text-align: left;
      font-size: 13px;
      color: #777;
      border-bottom: 1px solid var(--hw-border);
    }}
    .hw-topic-table td {{
      padding: 14px 16px;
      border-bottom: 1px solid #eee8dd;
      font-size: 14px;
    }}
    .hw-topic-table tr:hover td {{
      background: #fbf9f4;
    }}
    .hw-topic-title {{
      font-weight: 600;
      color: var(--hw-ink);
      text-decoration: none;
      font-size: 15px;
      display: block;
      margin-bottom: 4px;
    }}
    .hw-topic-title:hover {{
      color: var(--hw-vermilion);
    }}
    .hw-badge-cat {{
      display: inline-block;
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 4px;
      background: #eee8dd;
      color: #665;
      text-decoration: none;
      font-weight: 500;
    }}
    .hw-post-author {{
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: #666;
    }}
    .hw-post-avatar {{
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background: #e2dbce;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 12px;
      color: #666;
    }}
    .hw-post-card {{
      background: var(--hw-card-bg);
      border: 1px solid var(--hw-border);
      border-radius: 8px;
      padding: 24px;
      margin-bottom: 20px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.03);
    }}
    .hw-post-meta {{
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 16px;
      border-bottom: 1px solid #f0eae0;
      padding-bottom: 12px;
    }}
    .hw-post-avatar-lg {{
      width: 44px;
      height: 44px;
      border-radius: 50%;
      background: var(--hw-vermilion);
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: bold;
      font-size: 18px;
    }}
    .hw-reply-form {{
      background: var(--hw-card-bg);
      border: 1px solid var(--hw-border);
      border-radius: 8px;
      padding: 20px;
      margin-top: 24px;
    }}
    .hw-reply-form textarea {{
      width: 100%;
      box-sizing: border-box;
      border: 1px solid var(--hw-border);
      border-radius: 6px;
      padding: 12px;
      font: inherit;
      resize: vertical;
      min-height: 100px;
      background: #fff;
      color: var(--hw-ink);
    }}
    .hw-reply-form textarea:focus {{
      outline: 2px solid var(--hw-vermilion);
    }}
  </style>
</head>
<body>
  {nav_html}
  <div class="hw-forum-banner">
    <div>
      🌱 <strong>本地开发论坛 (Local Forum)</strong> · 当前处于 <code>local</code> 调试环境，讨论与发帖保存在本地 <code>dev_data.json</code>，完全与线上隔离。
    </div>
    <div>
      <a href="/studio" class="hw-forum-btn hw-forum-btn-quiet" style="padding:4px 10px;font-size:12px;">← 返回手绘风创作台</a>
    </div>
  </div>
"""

def render_forum_latest(topics, categories, nav_html, current_category=None):
    header = render_forum_header(nav_html, active_tab="latest")
    
    rows = []
    for t in topics:
        cat_badge = f'<span class="hw-badge-cat">{t.get("category", "社区交流")}</span>'
        posts = t.get("posts_count", 1)
        author = t.get("author", "旺旺老师")
        avatar_letter = author[0] if author else "U"
        rows.append(f"""
        <tr>
          <td>
            <a class="hw-topic-title" href="/t/{t.get('id')}">{t.get('title')}</a>
            {cat_badge}
          </td>
          <td>
            <div class="hw-post-author">
              <span class="hw-post-avatar">{avatar_letter}</span>
              <span>{author}</span>
            </div>
          </td>
          <td style="color:#666;font-size:13px;text-align:center;">{posts}</td>
          <td style="color:#888;font-size:12px;text-align:right;">{t.get('created_at', '刚刚')[:10]}</td>
        </tr>
        """)

    body = f"""
    <div class="hw-forum-container">
      <div class="hw-forum-nav-bar">
        <div class="hw-forum-tabs">
          <a href="/latest" class="hw-forum-tab {'active' if not current_category else ''}">全部话题</a>
          <a href="/c/1" class="hw-forum-tab {'active' if current_category=='1' else ''}">画风探索</a>
          <a href="/c/2" class="hw-forum-tab {'active' if current_category=='2' else ''}">图型讨论</a>
          <a href="/c/3" class="hw-forum-tab {'active' if current_category=='3' else ''}">新手求助</a>
          <a href="/c/4" class="hw-forum-tab {'active' if current_category=='4' else ''}">官方公告</a>
        </div>
        <div>
          <button class="hw-forum-btn" onclick="document.getElementById('new-topic-dialog').showModal()">+ 发布新话题</button>
        </div>
      </div>

      <table class="hw-topic-table">
        <thead>
          <tr>
            <th>话题</th>
            <th style="width:160px;">发帖人</th>
            <th style="width:80px;text-align:center;">回复</th>
            <th style="width:120px;text-align:right;">活动时间</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows)}
        </tbody>
      </table>
    </div>

    <dialog id="new-topic-dialog" style="padding:24px;border:1px solid #ded8cf;border-radius:8px;max-width:540px;width:90%;background:#fffdf9;">
      <h3 style="margin-top:0;">发布本地测试话题</h3>
      <form method="POST" action="/studio/api/forum/topics">
        <div style="margin-bottom:12px;">
          <label style="display:block;font-size:13px;font-weight:bold;margin-bottom:4px;">标题</label>
          <input name="title" style="width:100%;box-sizing:border-box;padding:8px;border:1px solid #ded8cf;border-radius:4px;" required minlength="5" placeholder="至少五个字符的话题标题" />
        </div>
        <div style="margin-bottom:12px;">
          <label style="display:block;font-size:13px;font-weight:bold;margin-bottom:4px;">分类</label>
          <select name="category" style="width:100%;box-sizing:border-box;padding:8px;border:1px solid #ded8cf;border-radius:4px;">
            <option value="社区交流">社区交流</option>
            <option value="画风探索">画风探索</option>
            <option value="图型讨论">图型讨论</option>
            <option value="新手求助">新手求助</option>
          </select>
        </div>
        <div style="margin-bottom:16px;">
          <label style="display:block;font-size:13px;font-weight:bold;margin-bottom:4px;">内容</label>
          <textarea name="content" style="width:100%;box-sizing:border-box;padding:8px;border:1px solid #ded8cf;border-radius:4px;min-height:90px;" placeholder="话题正文内容"></textarea>
        </div>
        <div style="display:flex;justify-content:flex-end;gap:8px;">
          <button type="button" class="hw-forum-btn hw-forum-btn-quiet" onclick="document.getElementById('new-topic-dialog').close()">取消</button>
          <button type="submit" class="hw-forum-btn">立即发布</button>
        </div>
      </form>
    </dialog>
</body>
</html>
"""
    return header + body

def render_forum_topic(topic, posts, nav_html):
    header = render_forum_header(nav_html, active_tab="topic")
    posts_html = []
    for i, p in enumerate(posts):
        avatar = p.get("author", "U")[0]
        posts_html.append(f"""
        <article class="hw-post-card">
          <div class="hw-post-meta">
            <div class="hw-post-avatar-lg">{avatar}</div>
            <div>
              <strong style="font-size:15px;">{p.get('author', '匿名')}</strong>
              <div style="font-size:12px;color:#888;">楼层 #{i+1} · {p.get('created_at', '刚刚')}</div>
            </div>
          </div>
          <div style="white-space: pre-wrap;font-size:15px;line-height:1.7;">{p.get('content', '')}</div>
        </article>
        """)

    body = f"""
    <div class="hw-forum-container">
      <div style="margin-bottom:16px;display:flex;justify-content:space-between;align-items:center;">
        <div>
          <a href="/latest" style="color:#a94028;text-decoration:none;font-size:14px;font-weight:500;">← 全部话题列表</a>
          <span style="color:#ccc;margin:0 8px;">/</span>
          <span class="hw-badge-cat">{topic.get('category', '社区交流')}</span>
        </div>
        <a href="/studio" class="hw-forum-btn hw-forum-btn-quiet" style="font-size:13px;padding:4px 12px;">打开创作台 ↗</a>
      </div>

      <h1 style="margin: 0 0 20px 0;font-size:26px;color:var(--hw-ink);">{topic.get('title')}</h1>

      {"".join(posts_html)}

      <div class="hw-reply-form">
        <h3 style="margin-top:0;">发表回复</h3>
        <form method="POST" action="/t/{topic.get('id')}/reply">
          <textarea name="reply" placeholder="写下你的回复与交流想法..." required></textarea>
          <div style="margin-top:12px;text-align:right;">
            <button type="submit" class="hw-forum-btn">发表回复</button>
          </div>
        </form>
      </div>
    </div>
</body>
</html>
"""
    return header + body
