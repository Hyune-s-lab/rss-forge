#!/usr/bin/env python3
"""rss-forge — RSS를 제공하지 않는 사이트의 목록 페이지를 긁어 RSS 2.0 피드를 만든다.

sites.yml에 사이트별 CSS 셀렉터를 적어두면 사이트 수만큼 public/<id>.xml 이 생성된다.
state.json 에 글별 최초 발견 시각과 og:description 을 캐시해 두기 때문에
- 날짜를 못 읽는 사이트라도 pubDate 가 실행할 때마다 흔들리지 않고
- 이미 본 글의 본문 페이지를 매번 다시 받지 않는다.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from email.utils import format_datetime
from xml.sax.saxutils import escape

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
STATE_PATH = ROOT / "state.json"
FAILURE_MARKER = ROOT / ".failures"

UA = "rss-forge/1.0 (+https://github.com/USER/rss-forge)"
TIMEOUT = 20


# --------------------------------------------------------------------------- io

def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("::warning::state.json 파손 — 새로 시작합니다")
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def fetch(session: requests.Session, url: str) -> str:
    resp = session.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    # 한국 사이트는 meta charset 을 믿는 편이 안전하다
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text


# ------------------------------------------------------------------- parsing

def parse_date(raw: str | None, formats: list[str], tz: ZoneInfo) -> datetime | None:
    """목록에 찍힌 날짜 문자열을 tz-aware datetime 으로."""
    if not raw:
        return None
    raw = " ".join(raw.split())
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=tz)
        except ValueError:
            continue
    # ISO 8601 (<time datetime="..."> 가 있는 사이트)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=tz)
    except ValueError:
        return None


def extract_link(item, cfg: dict, base: str) -> str | None:
    sel = cfg.get("link_sel")
    node = item.select_one(sel) if sel else (item if item.name == "a" else item.select_one("a[href]"))
    if node is None:
        return None
    href = node.get(cfg.get("link_attr", "href"))
    return urljoin(base, href) if href else None


def extract_text(item, sel: str | None, attr: str | None = None) -> str | None:
    if not sel:
        return None
    node = item.select_one(sel)
    if node is None:
        return None
    if attr:
        value = node.get(attr)
        if value:
            return value.strip()
    return node.get_text(" ", strip=True) or None


def og_description(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    for key, attr in (("og:description", "property"), ("description", "name")):
        tag = soup.find("meta", attrs={attr: key})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


# --------------------------------------------------------------------- build

def build_site(cfg: dict, session: requests.Session, state: dict) -> int:
    site_id = cfg["id"]
    tz = ZoneInfo(cfg.get("tz", "Asia/Seoul"))
    limit = int(cfg.get("limit", 20))
    formats = cfg.get("date_formats") or ["%Y. %m. %d", "%Y-%m-%d", "%Y.%m.%d", "%Y년 %m월 %d일"]
    seen: dict = state.setdefault(site_id, {})
    now = datetime.now(timezone.utc)

    html = fetch(session, cfg["list_url"])
    soup = BeautifulSoup(html, "lxml")
    items = soup.select(cfg["item_sel"])
    if not items:
        raise RuntimeError(f"item_sel '{cfg['item_sel']}' 이 아무것도 못 잡았습니다 (마크업 변경?)")

    entries: list[dict] = []
    for item in items[: limit * 2]:  # 중복 제거 여유분
        link = extract_link(item, cfg, cfg["list_url"])
        title = extract_text(item, cfg.get("title_sel")) or (item.get_text(" ", strip=True)[:120] or None)
        if not link or not title:
            continue
        if any(e["link"] == link for e in entries):
            continue

        record = seen.setdefault(link, {})
        if "first_seen" not in record:
            record["first_seen"] = now.isoformat()

        published = parse_date(
            extract_text(item, cfg.get("date_sel"), cfg.get("date_attr")), formats, tz
        ) or datetime.fromisoformat(record["first_seen"])

        description = record.get("description")
        if cfg.get("enrich") and description is None:
            try:
                description = og_description(fetch(session, link)) or ""
            except requests.RequestException as exc:
                print(f"::warning::{site_id}: 본문 조회 실패 {link} ({exc})")
                description = ""
            record["description"] = description

        record["title"] = title
        entries.append(
            {
                "link": link,
                "title": title,
                "description": description or title,
                "published": published,
            }
        )
        if len(entries) >= limit:
            break

    entries.sort(key=lambda e: e["published"], reverse=True)

    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / f"{site_id}.xml").write_text(render_rss(cfg, entries, now), encoding="utf-8")
    print(f"  ✓ {site_id}: {len(entries)}개 → public/{site_id}.xml")
    return len(entries)


def render_rss(cfg: dict, entries: list[dict], now: datetime) -> str:
    """의존성 없이 RSS 2.0 을 직접 렌더링한다."""
    home = cfg.get("home", cfg["list_url"])
    self_link = (
        f'\n    <atom:link href="{escape(cfg["feed_url"])}" rel="self" type="application/rss+xml"/>'
        if cfg.get("feed_url")
        else ""
    )
    items = "\n".join(
        f"""    <item>
      <title>{escape(e["title"])}</title>
      <link>{escape(e["link"])}</link>
      <guid isPermaLink="true">{escape(e["link"])}</guid>
      <pubDate>{format_datetime(e["published"])}</pubDate>
      <description>{escape(e["description"])}</description>
    </item>"""
        for e in entries
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(cfg["title"])}</title>
    <link>{escape(home)}</link>
    <description>{escape(cfg.get("description", cfg["title"]))}</description>
    <language>{escape(cfg.get("language", "ko"))}</language>
    <generator>rss-forge</generator>
    <lastBuildDate>{format_datetime(now)}</lastBuildDate>{self_link}
{items}
  </channel>
</rss>
"""


def write_index(sites: list[dict], base_url: str) -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        f'    <li><a href="{s["id"]}.xml">{s["title"]}</a> '
        f'<small>— <a href="{s.get("home", s["list_url"])}">원본</a></small></li>'
        for s in sites
    )
    PUBLIC.joinpath("index.html").write_text(
        f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>rss-forge</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{ font: 16px/1.7 system-ui, -apple-system, "Apple SD Gothic Neo", sans-serif;
           max-width: 42rem; margin: 3rem auto; padding: 0 1rem; }}
    li {{ margin: .4rem 0; }}
    small {{ opacity: .6; }}
  </style>
</head>
<body>
  <h1>rss-forge</h1>
  <p>RSS를 제공하지 않는 블로그들의 피드입니다. 주소를 리더기에 붙여넣어 주세요.</p>
  <ul>
{rows}
  </ul>
  <p><small>base: {base_url}</small></p>
</body>
</html>
""",
        encoding="utf-8",
    )


def main() -> int:
    sites = yaml.safe_load((ROOT / "sites.yml").read_text(encoding="utf-8"))
    base_url = os.environ.get("FEED_BASE_URL", "")
    state = load_state()
    session = requests.Session()
    session.headers["User-Agent"] = UA

    failures: list[str] = []
    for cfg in sites:
        if base_url and "feed_url" not in cfg:
            cfg["feed_url"] = f"{base_url.rstrip('/')}/{cfg['id']}.xml"
        print(f"- {cfg['id']} ({cfg['list_url']})")
        try:
            if build_site(cfg, session, state) == 0:
                raise RuntimeError("항목 0개")
        except Exception as exc:  # 한 사이트가 깨져도 나머지는 계속
            print(f"::error::{cfg['id']} 실패: {exc}")
            failures.append(f"{cfg['id']}: {exc}")

    save_state(state)
    write_index(sites, base_url)

    if failures:
        FAILURE_MARKER.write_text("\n".join(failures) + "\n", encoding="utf-8")
    elif FAILURE_MARKER.exists():
        FAILURE_MARKER.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
