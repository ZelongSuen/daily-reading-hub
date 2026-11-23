import os
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse
import feedparser
import requests
from bs4 import BeautifulSoup

# ================= 1. 信源配置区 =================
RSS_FEEDS = {
    "经济学与政策": [
        "https://marginalrevolution.com/feed",
        "https://worksinprogress.co/feed/",
        "https://fredblog.stlouisfed.org/feed/",
        "https://www.nber.org/rss/new.xml",
    ],
    "地缘政治与中东": [
        "https://warontherocks.com/feed/",
        "https://www.mei.edu/rss.xml",
        "https://www.brookings.edu/feed/",
        "https://thediplomat.com/feed/",
    ],
    "系统工程与技术": [
        "https://hnrss.org/best",
        "https://blog.cloudflare.com/rss/",
        "https://martin.kleppmann.com/feed.xml",
    ]
}

NON_RSS_PAGES = [
    {
        "category": "地缘政治与智库",
        "source": "RAND International Affairs",
        "url": "https://www.rand.org/topics/international-affairs.html",
        "must_contain": "/pubs/"
    },
    {
        "category": "系统工程与思维",
        "source": "Paul Graham Essays",
        "url": "https://paulgraham.com/articles.html",
        "must_contain": ".html"
    }
]

# ================= 2. 过滤与置顶规则 =================
EXCLUDE_KEYWORDS = [
    "open thread", "podcast", "assorted links", "weekly roundup",
    "subscribe", "webinar", "event:", "livestream", "about us", "privacy policy"
]

PRIORITY_KEYWORDS = [
    "iran", "tehran", "middle east", "persian", "geopolitics", "sanctions",
    "macro", "inflation", "housing", "supply chain", "welfare", "urban",
    "distributed", "linux", "architecture", "compiler", "database", "latency"
]

DB_PATH = "reading_links_history.db"
OUTPUT_HTML = "index.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# 使用美西太平洋时间 (UTC-8) 记录日期
PST_TZ = timezone(timedelta(hours=-8))
today_str = datetime.now(PST_TZ).strftime("%Y-%m-%d")
now_iso = datetime.now(PST_TZ).isoformat()

# ================= 3. 初始化数据库 =================
conn = sqlite3.connect(DB_PATH)
conn.execute("""
    CREATE TABLE IF NOT EXISTS articles (
        url TEXT PRIMARY KEY,
        title TEXT,
        category TEXT,
        source TEXT,
        priority INTEGER,
        added_date TEXT,
        added_at TEXT
    )
""")
conn.commit()

def is_valid_and_new(url: str, title: str) -> bool:
    if not url or not title or len(title.split()) < 3:
        return False
    if conn.execute("SELECT 1 FROM articles WHERE url = ?", (url,)).fetchone():
        return False
    title_lower = title.lower()
    if any(bad in title_lower for bad in EXCLUDE_KEYWORDS):
        conn.execute(
            "INSERT INTO articles VALUES (?, ?, ?, ?, ?, ?, ?)",
            (url, title, "EXCLUDED", "", 0, today_str, now_iso)
        )
        return False
    return True

def check_priority(title: str, summary: str = "") -> int:
    combined = (title + " " + summary).lower()
    return 1 if any(kw in combined for kw in PRIORITY_KEYWORDS) else 0

# ================= 4. 执行双引擎抓取 =================
new_count = 0

for category, urls in RSS_FEEDS.items():
    for feed_url in urls:
        try:
            feed = feedparser.parse(feed_url)
            source_name = feed.feed.get("title", urlparse(feed_url).netloc)
            for entry in feed.entries[:8]:
                link = entry.get("link", "").strip()
                title = entry.get("title", "").strip()
                summary = entry.get("summary", "")
                if is_valid_and_new(link, title):
                    prio = check_priority(title, summary)
                    conn.execute(
                        "INSERT INTO articles VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (link, title, category, source_name, prio, today_str, now_iso)
                    )
                    new_count += 1
        except Exception as e:
            print(f"[RSS Error] {feed_url}: {e}")

for site in NON_RSS_PAGES:
    try:
        resp = requests.get(site["url"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        count = 0
        for a_tag in soup.find_all("a", href=True):
            if count >= 8:
                break
            raw_href = a_tag["href"].strip()
            full_url = urljoin(site["url"], raw_href).split("#")[0]
            title = " ".join(a_tag.get_text().split())
            if site["must_contain"] not in full_url or full_url == site["url"]:
                continue
            if len(title) < 15:
                continue
            if is_valid_and_new(full_url, title):
                prio = check_priority(title)
                conn.execute(
                    "INSERT INTO articles VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (full_url, title, site["category"], site["source"], prio, today_str, now_iso)
                )
                new_count += 1
                count += 1
    except Exception as e:
        print(f"[Web Scrape Error] {site['url']}: {e}")

conn.commit()

# ================= 5. 读取最近 7 天数据生成 index.html =================
seven_days_ago = (datetime.now(PST_TZ) - timedelta(days=7)).strftime("%Y-%m-%d")
rows = conn.execute("""
    SELECT url, title, category, source, priority, added_date
    FROM articles
    WHERE category != 'EXCLUDED' AND added_date >= ?
    ORDER BY added_date DESC, priority DESC, category ASC
""", (seven_days_ago,)).fetchall()
conn.close()

grouped_html = ""
current_date = None

for url, title, category, source, priority, added_date in rows:
    if added_date != current_date:
        current_date = added_date
        label = f"{added_date} (今日更新)" if added_date == today_str else added_date
        grouped_html += f'<h3 style="margin-top: 32px; padding-bottom: 6px; border-bottom: 2px solid #0969da; color: #0969da;">{label}</h3>'

    badge = '<span style="background:#ffe8e6; color:#cf1322; padding:2px 6px; border-radius:4px; font-size:12px; font-weight:bold; margin-right:6px;">★ 重点</span>' if priority else ""
    grouped_html += f"""
    <div style="padding: 12px 0; border-bottom: 1px solid #eaeaea;">
        <div style="margin-bottom: 4px;">
            {badge}<a href="{url}" target="_blank" rel="noopener noreferrer" style="font-size: 16px; color: #1f2328; text-decoration: none; font-weight: 600;">{title}</a>
        </div>
        <div style="font-size: 13px; color: #57606a;">
            <strong>[{category}]</strong> {source} &nbsp;|&nbsp; 
            <a href="{url}" target="_blank" rel="noopener noreferrer" style="color: #1a7f37; text-decoration: none; word-break: break-all;">{url}</a>
        </div>
    </div>
    """

if not grouped_html:
    grouped_html = "<p style='color:#666;'>最近 7 天暂无文章记录。</p>"

html_page = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日精选文章直达清单</title>
<style>
  a:hover {{ text-decoration: underline !important; }}
</style>
</head>
<body style="max-width: 880px; margin: 30px auto; padding: 0 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #ffffff; color: #1f2328; line-height: 1.55;">
    <h2 style="margin-bottom: 6px;">多领域深度文章直达清单</h2>
    <p style="color: #57606a; font-size: 14px; margin-top: 0;">
        最后更新时间：{datetime.now(PST_TZ).strftime('%Y-%m-%d %H:%M')} (PST) &nbsp;|&nbsp; 本次新增：<strong>{new_count}</strong> 篇 &nbsp;|&nbsp; 展示近 7 日存档
    </p>
    {grouped_html}
</body>
</html>
"""

with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
    f.write(html_page)

print(f"Done. Added {new_count} new articles.")
