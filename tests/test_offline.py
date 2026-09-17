#!/usr/bin/env python3
"""네트워크 없이 파서/렌더러를 검증하는 스모크 테스트.

    python3 tests/test_offline.py

실제 tech.kakaopay.com 의 카드 마크업(Astro)을 그대로 축약한 픽스처를 쓴다.
CI에서 셀렉터 리팩터링이 깨지는지 빠르게 잡는 용도.
"""
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build  # noqa: E402

LIST_HTML = """
<html><body><section>
  <a href="/post/querydsl-paging-strategy/" data-astro-cid-aldj6tzs="">
    <div class="post-image"><img alt="thumb"></div>
    <strong data-astro-cid-aldj6tzs="">Querydsl 대량 데이터 처리 &amp; 페이지네이션</strong>
    <div class="_postExtraInfo_1luvd_1"><time>2026. 9. 16</time><span>카카오페이</span></div>
  </a>
  <a href="/post/mongodb-nplus1-issue/" data-astro-cid-aldj6tzs="">
    <div class="post-image"><img alt="thumb"></div>
    <strong>Spring Data MongoDB 가이드: 연관관계 설계와 업데이트 전략</strong>
    <div><time>2026. 9. 9</time></div>
  </a>
  <a href="/tag/llm/">태그 링크 — 잡히면 안 됨</a>
</section></body></html>
"""

POST_HTML = """
<html><head>
  <meta property="og:description" content="요약 <설명> & 특수문자">
</head><body></body></html>
"""

CFG = {
    "id": "fixture",
    "title": "픽스처 블로그",
    "description": "테스트용",
    "home": "https://tech.kakaopay.com/",
    "list_url": "https://tech.kakaopay.com/",
    "feed_url": "https://example.github.io/rss-forge/fixture.xml",
    "item_sel": 'a[href^="/post/"]',
    "title_sel": "strong",
    "date_sel": "time",
    "date_formats": ["%Y. %m. %d"],
    "enrich": True,
    "limit": 20,
}


def fake_fetch(_session, url):
    return LIST_HTML if url.rstrip("/") == "https://tech.kakaopay.com" else POST_HTML


def main() -> int:
    build.fetch = fake_fetch
    build.PUBLIC = Path(__file__).resolve().parent / "_out"
    state = {}

    count = build.build_site(CFG, None, state)
    assert count == 2, f"글 2개를 기대했는데 {count}개 (태그 링크가 섞였을 수 있음)"

    xml = (build.PUBLIC / "fixture.xml").read_text(encoding="utf-8")
    root = ElementTree.fromstring(xml)  # 잘못 이스케이프되면 여기서 터진다
    items = root.findall("./channel/item")
    assert len(items) == 2, len(items)

    first = items[0]
    assert first.findtext("title") == "Querydsl 대량 데이터 처리 & 페이지네이션"
    assert first.findtext("link") == "https://tech.kakaopay.com/post/querydsl-paging-strategy/"
    assert first.findtext("description") == "요약 <설명> & 특수문자", first.findtext("description")

    published = parsedate_to_datetime(first.findtext("pubDate"))
    assert (published.year, published.month, published.day) == (2026, 9, 16), published
    assert published.utcoffset().total_seconds() == 9 * 3600, "KST 오프셋이 아님"

    # 최신 글이 위에 오는지
    second = parsedate_to_datetime(items[1].findtext("pubDate"))
    assert published > second, "정렬이 최신순이 아님"

    # 상태 캐시: 같은 링크는 first_seen 과 description 이 유지되어야 한다
    saved = state["fixture"]["https://tech.kakaopay.com/post/mongodb-nplus1-issue/"]
    assert saved["description"] == "요약 <설명> & 특수문자"
    assert "first_seen" in saved

    # 날짜가 없는 사이트: first_seen 으로 pubDate 가 고정되는지
    no_date = dict(CFG, id="nodate", date_sel=None, enrich=False)
    pinned = datetime(2020, 1, 2, 3, 4, tzinfo=timezone.utc).isoformat()
    for link in list(state["fixture"]):
        state.setdefault("nodate", {})[link] = {"first_seen": pinned}
    build.build_site(no_date, None, state)
    nd = ElementTree.fromstring((build.PUBLIC / "nodate.xml").read_text(encoding="utf-8"))
    for item in nd.findall("./channel/item"):
        assert parsedate_to_datetime(item.findtext("pubDate")).year == 2020, "first_seen 고정 실패"

    print("OK — 모든 검증 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
