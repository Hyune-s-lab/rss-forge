# rss-forge

RSS를 제공하지 않는(또는 제공하는 척만 하는) 블로그의 목록 페이지를 긁어 RSS 2.0 피드를 만들고, GitHub Pages로 퍼블리시합니다.

첫 대상은 [카카오페이 기술 블로그](https://tech.kakaopay.com/)입니다. 공식 `rss.xml`이 채널 메타데이터만 있고 `<item>`이 0개라 리더기에서 영원히 비어 보입니다.

## 설치

1. 이 디렉터리를 새 GitHub 저장소로 push 합니다.
2. **Settings → Pages → Build and deployment → Source** 를 **GitHub Actions** 로 바꿉니다.
3. **Actions** 탭에서 `build feeds` 를 한 번 수동 실행(Run workflow)합니다.
4. 끝나면 `https://<계정>.github.io/<저장소>/kakaopay.xml` 을 리더기에 넣습니다.
   `https://<계정>.github.io/<저장소>/` 로 들어가면 피드 목록 페이지가 나옵니다.

`build.py` 상단의 `UA` 상수에 있는 `USER` 를 본인 계정으로 바꿔 두면, 상대 서버 로그에서 이 봇이 누군지 알아볼 수 있습니다.

## 사이트 추가하기

`sites.yml` 에 블록을 하나 더 넣으면 됩니다. 브라우저 개발자 도구에서 셀렉터만 확인하면 보통 5분입니다.

```yaml
- id: some-blog            # → public/some-blog.xml
  title: 어떤 블로그
  home: https://example.com/
  list_url: https://example.com/blog/
  item_sel: 'article.post' # 글 하나를 감싸는 요소
  title_sel: 'h2 a'
  link_sel: 'h2 a'         # 생략하면 item 자신이 <a> 거나 그 안의 첫 a[href]
  date_sel: 'time'
  date_attr: datetime      # 텍스트 대신 속성에서 날짜를 읽을 때
  enrich: true             # 각 글 페이지의 og:description 을 요약으로 사용
  limit: 20
```

셀렉터가 맞는지는 대상 페이지 콘솔에서 먼저 확인하는 게 빠릅니다.

```js
document.querySelectorAll('article.post').length
```

## 동작 방식에서 알아둘 것

**`state.json` 이 핵심입니다.** 링크별 최초 발견 시각과 `og:description` 을 저장해 두고 매 실행마다 커밋합니다. 덕분에

- 날짜를 못 읽는 사이트라도 `pubDate` 가 실행할 때마다 흔들리지 않습니다. 이게 없으면 리더기가 매번 전체 글을 새 글로 표시합니다.
- 이미 수집한 글의 본문 페이지를 다시 받지 않습니다. 매 실행 요청 수가 목록 페이지 1회 + 새 글 수만큼입니다.

**깨지면 빨간 X 가 뜹니다.** 스크래퍼는 상대가 마크업을 바꾸면 조용히 0건을 뱉는 게 가장 위험합니다. 한 사이트라도 0건이면 나머지 피드는 정상 배포하되 워크플로는 실패로 끝나고, 요약에 원인이 찍힙니다. 저장소 알림만 켜두면 메일이 옵니다.

**주기는 6시간입니다.** `.github/workflows/build.yml` 의 cron 을 바꾸면 됩니다. 기술 블로그는 이 정도로 충분하고, 상대 서버에도 그쪽이 예의입니다. GitHub의 schedule 은 러너가 붐비면 수십 분 밀릴 수 있으니 정시 도착을 기대하진 마세요.

## 로컬 실행

```bash
pip install -r requirements.txt
python3 tests/test_offline.py            # 네트워크 없이 파서 검증
FEED_BASE_URL=http://localhost python3 build.py
open public/kakaopay.xml
```

## 주의

공개 페이지의 제목·링크·요약(og:description)만 가져오고 본문은 복제하지 않습니다. `robots.txt` 를 존중하고, 대상이 공식 피드를 제대로 제공하기 시작하면 해당 블록을 지우고 원본을 구독하는 편이 낫습니다. 카카오페이 쪽에는 `rss.xml` 이 비어 있다고 제보해 두면 이 저장소가 필요 없어질 수도 있고요.
