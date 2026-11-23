"""AI 글쓰기: 작가 지침(md) + 블로그 기억(md) + 키워드 데이터로 네이버 블로그 초안을 쓰고, 보관하고, docx로 만든다.

키워드 플래너(app.py)가 불러 쓰는 모듈. 표준 라이브러리만으로 동작하며,
Claude를 쓸 때만 공식 SDK(anthropic)가 필요하다(실행 파일이 처음 한 번 설치).
"""
import io
import json
import re
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xesc

KST = timezone(timedelta(hours=9))
CLAUDE_MODEL = "claude-opus-5-5"
APP_DIR = Path(__file__).parent
# 예전 버전의 기본 작가 지침(sha256). 사용자가 손대지 않았으면 새 지침으로 올려 줌
OLD_DEFAULT_GUIDES = {"201e6c46be11f3c6f03a4a7ebeca2b8087171be4fb4d68999fb15b37cce266bc", "d7968cfbd083a6600eb3401689c1f9fd44ad9108112322f54770fc22f4d00d35", "3519e01e9dac935f01e4b18077546724be432c950e4f249936862faa348b8447", "f3cf4b8202540efe74128bd754e2e3ab40dc351799341b3f18a98d92c40f69f2", "289967fe17a69d557c55a39cdb15a4b784965003f49ae5682e961125aa806a4e", "5897740aa8f6dca0c354460c6362be80863616e86e4dd7f7cc1b6588df4d4560", "b894956ecb9089c3354c665cdf684da4e198659d502ce0f79c1f83437b579539", "4ae5dbab9cc26888f6b56281624ace2319763bd1248671eb0cd7cc1c78ead867", "2228d665832e96c6568394f82940539a100aae17576214723e59f3dfb5323c71", "0c961d7c537c2be1a0e7613886ae38f6dbe302a68f6cfb3d1784cdacade57787", "a6f083674fa6e12b47a94a308965a6162027a2bd6c5ab0eec813bb798a992e60", "0cd20f813afa36be043b94d94405eef301eddfbfe9765425ffc35de3592f490b", "f6bb50a3a4463a3fabab14ccb79c75b5bb4e123b0e34f863719e64c001a9dc42",
                      "50ddd38bb2615fdda855534a003fe9f226bfb05e6d06d7f5b8072cdb3b332a68",
                      "737470eff321f4bf999e3a33d06e476814f40e558765752e63f81d31bd119726",
                      "88607b921186d719388360cffe4419d31c3bb103b8bee917379ceb3327609ba2",
                      "06be32f92cc49185be6986defbb3c89068ccb5d52784bb760f04da28378d186e",
                      "443b239c1ec7f02ac813c6942b978b3a54f0654bef854fe277fce3b057a33317",
                      "3620ce3f06472fa115d2494c3d9ee284c176116396b03402e827c5ebe8c93bef",
                      "513517507612fc0309677eccd64036dbc7dbb17f14e64b2663d86f668aa070e5",
                      "6cbed19bef719ab124271087459f4e15bf287411589078fde34b825ba25f3289",
                      "ea85552c4a2f488578bf64aabbc0b90c5d5e082c1a48f43985d58108641ef8f5",
                      "65db9579d5c8d039ce913a352268f31cdcc91e55d3c4245cb831d709fc0d8290"}  # v58까지 보낸 지침


UPDATE_REPO = "mielle3/keyword-planner"
VOICE = {"text": ""}  # make_draft 때 store.voice()로 채움 (system_prompt에서 사용)


def fetch_repo_file(name):
    """프로그램 폴더에 빠진 파일을 GitHub 공개 저장소에서 받아 저장 (성공하면 True)."""
    for url, hdr in ((f"https://api.github.com/repos/{UPDATE_REPO}/contents/{urllib.parse.quote(name)}?ref=main",
                      {"Accept": "application/vnd.github.raw+json", "User-Agent": "KeywordPlanner"}),
                     (f"https://raw.githubusercontent.com/{UPDATE_REPO}/main/{urllib.parse.quote(name)}", {"User-Agent": "KeywordPlanner"})):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=15).read()
            if data:
                (APP_DIR / name).write_bytes(data)
                return True
        except Exception:
            continue
    return False


OLD_ESSAY_GUIDES = {"96b65eff47e4ec4ba812c4ca4b74ba4052397f84094b128f0f92968302c76a4e", "ea28eea311b851a60e5774ae1b66ec0d446c7f31fd603973f78aea6ada0e6f63", "ed1b71a6215fbd82305e1cea5165e40d0f7bef63321648b4c02495f976cd4816", "45cd7fcfeb57cb08bd66ff87fb7b328a78035e580592aeb545ee4a8003d49987", "8902f714050f13c941454680dea97257484de367d3a10fa6f64d403cd0df4ff5", "d4ab69ab3c7c45557d336d05a2171330b004b3c54aa6ced436f4be26879c312f", "18eac005a699b2a7cfa1ddd23e90f5ff9f9f2f70f07388daa608dda49c558a7f", "4daefb41ecf10b68cab44a5e092bf4756970d4e730128849c7af6229216fdd33"}  # 읽을거리형 기본 지침의 예전 판 (고치지 않았으면 자동 교체)

GUIDE_FILES = {"info": "writer_guide.md", "essay": "writer_guide_essay.md", "deal": "writer_guide_deal.md"}
OLD_DEAL_GUIDES = {"6b55a9c9027df6edb6edb0e4e7a6a373a7dbc331ed5f7b4c7a18bda8a5093c76", "8d3a5790537d218a41286a849dfae061c8be637b331be44f416915ab33f13fa0", "2e89ca129de16b8d17b3cc2b6e9ff1f0ee1eced8cab0fb7933c7ba50eb90f607", "de03160a2180a98424ce1b83490cac780822805ef5ef4d7b8524b5d9dd1b92bc", "630d625ce119fda6136d2b61fc362fd1ca864200af7c5506f24481ea0e3f1b42", "1236c80d084fa0ec1dbd9d1cc93e651f14c63ea8634875fe0f93b88004a83a1e", "b6f576099c0177811aaba58d82a0c054bbdcd661d8d73d92b7da92088360abf3", "ef714a4751cb6e8f163634329da698bc9733fb280c538a7c8056a624c0bb41c9", "e90e6b081db348c81e8a6db390e6dfc77f4fe2b2441d653cd72a29ca15b056f5", "eb6cf6538685a58580f804568b1244da811c1755c0ae7a3bcdb2182965a8a39d", "6bb7940776d446bcd5f7ecd7d6c4c0f76d8a391f7c009bb270b07f9ae8796a6a"}
DEAL_RE = re.compile(r"할인|블프|블랙프라이데이|사이버먼데이|직구|핫딜|특가|쿠폰|프로모션|캐시백|최저가|세일|타임딜|사전예약|사전 예약|"
                     r"얼리버드|예매 오픈|티켓 오픈|티켓팅|예매|요금제|통신사 혜택|카드 혜택|광군제|아마존|알리|테무|쿠팡 로켓|정가")
ESSAY_RE = re.compile(r"영화|드라마|넷플릭스|티빙|디즈니\+|웨이브|쿠팡플레이|OTT|애니|웹툰|책|소설|에세이|도서|시집|음악|앨범|플레이리스트|노래|"
                      r"공연 후기|전시 후기|관람 후기|후기|리뷰|여행기|여행 코스|가볼만한|데이트|맛집|카페|브런치|일상|감성|추천작|작품|시리즈|명작")
INFO_RE = re.compile(r"신청|지원금|환급|세금|보험|대출|계산|기준|조건|방법|절차|서류|일정|마감|등급컷|과태료|요금|금리|연말정산|청약|발표|접수")


def pick_style(item):
    """글 종류 자동 선택: 사용자가 고른 게 있으면 그대로, 아니면 키워드·분야로 판단 (정보형이 기본)."""
    s = (item or {}).get("style")
    if s in ("info", "essay", "deal"):
        return s
    text = f"{item.get('keyword', '')} {item.get('topic', '')}"
    if item.get("rewrite_source"):
        text += " " + item["rewrite_source"][:400]
    if DEAL_RE.search(item.get("keyword", "")):
        return "deal"
    if INFO_RE.search(item.get("keyword", "")):
        return "info"
    return "essay" if ESSAY_RE.search(text) else "info"


class WriterError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 오류."""


class DraftCancelled(WriterError):
    """사용자가 취소 버튼을 누름."""


import threading as _threading
CANCEL = _threading.Event()  # 초안 작성은 작업자 스레드 하나가 차례로 처리하므로 전역 하나로 충분


def run_proc(cmd, input_bytes=None, cwd=None, env=None, timeout=900):
    """subprocess.run 대신: 취소 버튼을 누르면 AI 프로그램(자식 프로세스까지)을 즉시 종료."""
    import os, subprocess, time as _t
    flags = 0x08000000 if os.name == "nt" else 0
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env, creationflags=flags,
                         start_new_session=(os.name != "nt"))
    res = {}

    def comm():
        o, e = p.communicate(input_bytes)
        res.update(out=o, err=e)
    th = _threading.Thread(target=comm, daemon=True)
    th.start()
    start = _t.time()

    def kill():
        try:
            if os.name == "nt":  # .cmd → node 등 자식까지 함께 종료
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, creationflags=flags)
            else:
                import signal
                os.killpg(p.pid, signal.SIGKILL)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    while th.is_alive():
        th.join(0.3)
        if CANCEL.is_set():
            kill()
            th.join(5)
            raise DraftCancelled("취소했어요.")
        if _t.time() - start > timeout:
            kill()
            th.join(5)
            raise subprocess.TimeoutExpired(cmd, timeout)
    return subprocess.CompletedProcess(cmd, p.returncode, res.get("out", b""), res.get("err", b""))


# ------------------------------------------------------------------ 저장 위치

class Store:
    def __init__(self, data_dir):
        self.data = Path(data_dir)
        self.mem_dir = self.data / "memory"
        self.drafts_dir = self.data / "drafts"
        self.guide_path = self.mem_dir / "작가_지침.md"
        self.memory_path = self.mem_dir / "블로그_기억.md"
        self.index_path = self.drafts_dir / "index.json"

    # 작가 지침: info(정보형) · essay(읽을거리형: 영화·책·리뷰·여행기 등)
    def guide_file(self, style="info"):
        return {"essay": self.mem_dir / "작가_지침_읽을거리.md", "deal": self.mem_dir / "작가_지침_할인구매.md"}.get(style, self.guide_path)

    def default_guide(self, style="info"):
        name = GUIDE_FILES.get(style, "writer_guide.md")
        path = APP_DIR / name
        if not path.exists():
            fetch_repo_file(name)  # 예전 업데이트 코드가 새 파일을 빠뜨린 경우: 저장소에서 받아 복구
        if path.exists():
            return path.read_text(encoding="utf-8")
        return (APP_DIR / "writer_guide.md").read_text(encoding="utf-8")  # 받을 수 없으면 정보형 지침으로 대신

    def guide(self, style="info"):
        path = self.guide_file(style)
        if not path.exists():
            self.mem_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(self.default_guide(style), encoding="utf-8")
        text = path.read_text(encoding="utf-8")
        # 사용자가 고치지 않은 예전 기본 지침이면 새 기본 지침으로 자동 교체 (고친 지침은 그대로 둠)
        import hashlib
        if hashlib.sha256(text.strip().encode("utf-8")).hexdigest() in {"essay": OLD_ESSAY_GUIDES, "deal": OLD_DEAL_GUIDES}.get(style, OLD_DEFAULT_GUIDES):
            text = self.default_guide(style)
            path.write_text(text, encoding="utf-8")
        return text

    # 내 문체 프로필 (사용자 본인 글에서 학습)
    @property
    def voice_path(self):
        return self.mem_dir / "내_문체_프로필.md"

    def voice(self):
        try:
            return self.voice_path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def save_voice(self, text):
        self.mem_dir.mkdir(parents=True, exist_ok=True)
        if text.strip():
            self.voice_path.write_text(text.strip() + "\n", encoding="utf-8")
        elif self.voice_path.exists():
            self.voice_path.unlink()

    def save_guide(self, text, style="info"):
        self.mem_dir.mkdir(parents=True, exist_ok=True)
        self.guide_file(style).write_text(text.strip() + "\n", encoding="utf-8")

    # 초안 보관함
    def index(self):
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _write_index(self, idx):
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")

    def get(self, did):
        rec = next((r for r in self.index() if r["id"] == did), None)
        if not rec:
            return None
        p = self.drafts_dir / f"{did}.md"
        return {**rec, "text": p.read_text(encoding="utf-8") if p.exists() else ""}

    def add(self, rec, text):
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        (self.drafts_dir / f"{rec['id']}.md").write_text(text, encoding="utf-8")
        idx = [r for r in self.index() if r["id"] != rec["id"]]
        idx.insert(0, rec)
        self._write_index(idx)
        return rec

    def set_meta(self, did, **kw):
        idx = self.index()
        for r in idx:
            if r["id"] == did:
                r.update(kw)
        self._write_index(idx)

    def update(self, did, text=None, status=None):
        idx = self.index()
        rec = next((r for r in idx if r["id"] == did), None)
        if not rec:
            return None
        if text is not None:
            (self.drafts_dir / f"{did}.md").write_text(text, encoding="utf-8")
            rec["title"] = parse_title(text) or rec.get("title")
            rec["chars"] = body_chars(text)
            rec["check"] = check_draft(text, rec.get("style", "info"))
            rec["edited_at"] = now_iso()
        if status:
            rec["status"] = status
            if status == "발행 완료":
                rec["published_at"] = now_iso()
        self._write_index(idx)
        return rec

    def delete(self, did):
        self._write_index([r for r in self.index() if r["id"] != did])
        for p in [self.drafts_dir / f"{did}.md"] + list(self.drafts_dir.glob(f"{did}.v*.md")):
            try:
                p.unlink()
            except Exception:
                pass

    # 덮어쓰기 · 되돌리기 (덮어쓰기 전 내용은 버전 파일로 보관)
    def overwrite(self, did, text, **meta):
        idx = self.index()
        rec = next((r for r in idx if r["id"] == did), None)
        if not rec:
            return None
        cur = self.drafts_dir / f"{did}.md"
        n = int(rec.get("versions") or 0) + 1
        if cur.exists():
            (self.drafts_dir / f"{did}.v{n}.md").write_text(cur.read_text(encoding="utf-8"), encoding="utf-8")
            rec["versions"] = n
        cur.write_text(text, encoding="utf-8")
        rec.update({k: v for k, v in meta.items() if v is not None})
        rec["title"] = parse_title(text) or rec.get("title")
        rec["chars"] = body_chars(text)
        rec["check"] = check_draft(text, rec.get("style", "info"))
        rec["edited_at"] = now_iso()
        self._write_index(idx)
        return rec

    def undo(self, did):
        idx = self.index()
        rec = next((r for r in idx if r["id"] == did), None)
        n = int((rec or {}).get("versions") or 0)
        if not rec or n < 1:
            return None
        vp = self.drafts_dir / f"{did}.v{n}.md"
        if not vp.exists():
            rec["versions"] = n - 1
            self._write_index(idx)
            return rec
        text = vp.read_text(encoding="utf-8")
        (self.drafts_dir / f"{did}.md").write_text(text, encoding="utf-8")
        vp.unlink()
        rec["versions"] = n - 1
        rec["title"] = parse_title(text) or rec.get("title")
        rec["chars"] = body_chars(text)
        rec["check"] = check_draft(text, rec.get("style", "info"))
        rec["edited_at"] = now_iso()
        self._write_index(idx)
        return rec


def now_iso():
    return datetime.now(KST).isoformat(timespec="seconds")


# ------------------------------------------------------------------ 블로그 기억(md): 매번 새로 써서 AI에게 함께 전달

def closing_line(text):
    """'## 마치며' 첫 문장 (다음 초안이 같은 마무리를 반복하지 않게)."""
    m = re.search(r"##\s*(?:마치며|한눈에 요약)\s*\n+(.+)", text or "")
    if not m:
        return ""
    return re.split(r"(?<=[.!?요다])\s", m.group(1).strip().lstrip("▪ ").strip())[0][:80]


def build_memory(store, cfg, saved):
    idx = store.index()
    site = cfg.get("site") or {}
    lines = ["# 블로그 기억", "", f"> 키워드 플래너가 자동으로 쓰는 파일입니다. 마지막 갱신: {now_iso()}", "",
             "## 블로그 정보",
             f"- 운영 주제: {', '.join(cfg.get('topics', [])) or '미설정'}"]
    if site.get("name"):
        lines.append(f"- 연결할 내 사이트: {site['name']} ({site.get('url', '')}) · 제공: {', '.join(site.get('offers', []))}")
    if cfg.get("my_keywords"):
        lines.append(f"- 내 블로그 유입 검색어: {', '.join(cfg['my_keywords'][:15])}")
    lines += ["", "## 최근 작성한 초안 (같은 주제·제목 반복 금지)"]
    if idx:
        for r in idx[:20]:
            lines.append(f"- {r['created_at'][:10]} · [{r.get('status', '초안')}] {r['keyword']} — {r.get('title') or ''}")
    else:
        lines.append("- 아직 없음")
    closings = []
    for r in idx[:6]:
        rec = store.get(r["id"])
        c = closing_line(rec["text"] if rec else "")
        if c:
            closings.append(c)
    lines += ["", "## 최근 마무리 문장 (그대로 반복하지 말 것)"] + ([f"- {c}" for c in closings] or ["- 아직 없음"])
    myposts = cfg.get("_my_posts") or []
    if myposts:
        lines += ["", "## 내 네이버 블로그에 이미 올린 글 (같은 주제면 새 각도로, 제목은 겹치지 않게)"]
        lines += [f"- {p.get('date', '')} {p['title']}" for p in myposts[:30]]
    pub = [r["keyword"] for r in idx if r.get("status") == "발행 완료"][:15]
    want = [s["item"]["keyword"] for s in saved if s.get("status") in ("쓸 예정", "작성 중")][:15]
    lines += ["", "## 사용자의 선택",
              f"- 발행 완료한 글감: {', '.join(pub) or '없음'}",
              f"- 쓰려고 저장해 둔 글감: {', '.join(want) or '없음'}"]
    text = "\n".join(lines) + "\n"
    store.mem_dir.mkdir(parents=True, exist_ok=True)
    store.memory_path.write_text(text, encoding="utf-8")
    return text


# ------------------------------------------------------------------ AI에게 보낼 요청

def draft_request(item, cfg, today):
    """키워드 플래너가 모은 데이터를 AI가 쓰기 좋게 정리한 요청문."""
    if item.get("revise_instruction") and item.get("revise_source"):  # AI로 고치기: 요청한 부분만 수정
        return "\n".join([f"오늘 날짜: {today.isoformat()} (한국 시간).", "",
                           "아래 초안을 사용자의 수정 요청대로 고쳐 주세요.", "",
                           "## 고치는 원칙",
                           "- 요청한 부분만 고치고, 요청과 관계없는 문장·형식·숫자는 그대로 둡니다.",
                           "- 고친 결과는 기획부터 태그까지 **초안 전체**를 출력합니다(바뀐 부분만 출력하지 않음).",
                           "- 새로 넣는 사실·숫자는 확인한 것만 쓰고, 출처는 참고 자료 칸에 더합니다.",
                           "- 설명이나 변경 목록을 덧붙이지 않습니다.", "",
                           "## 수정 요청 (최우선)", item["revise_instruction"][:2000], "",
                           "## 지금 초안", item["revise_source"][:30000]])
    if item.get("rewrite_source"):  # 내 글 다듬기: 이미 올린 글을 지침 형식으로 고쳐 쓰기
        out = [f"오늘 날짜: {today.isoformat()} (한국 시간).", "",
               "아래는 사용자가 이미 네이버 블로그에 올린 글입니다. 작가 지침의 출력 양식과 편집 형식에 맞춰 **수정본**을 써 주세요.", "",
               "## 고쳐 쓰는 원칙",
               "- 원문의 숫자·날짜·출처·고유명사는 그대로 쓰고 바꾸지 않습니다. 원문에 없는 수치는 공식 자료로 확인한 것만 더하고, 더한 것은 참고 자료 칸에 출처를 적습니다.",
               "- 사용자 자신의 사이트·서비스 소개는 맨 뒤 번호 섹션 하나(이용 방법)와 면책 문구로 줄이고, 처음 언급할 때 운영자임을 한 번 밝힙니다. 첫 문장을 사이트 소개로 시작하지 않습니다.",
               "- 사이트 화면 캡처 설명이 여러 개면 꼭 필요한 1~2개만 이미지 삽입 위치로 남기고, 나머지는 지침의 이미지 규칙에 맞는 프롬프트로 바꿉니다.",
               "- 정보 글이면 독자가 사이트 없이도 쓸 수 있는 정보(기준·절차·확인할 것·문의처)를 앞쪽에 둡니다. 영화·문화·여행 같은 읽을거리 글이면 문단의 흐름을 살리고 박스·체크리스트를 줄입니다.",
               "- 제목은 숫자가 앞에 오는 건조한 서술형으로 바꿉니다. 감탄·낚시형(\"꼭 확인하세요!\")을 쓰지 않습니다.",
               "- 방어적인 마무리(\"양해 바랍니다\")는 정정 요청 창구 한 줄로 바꿉니다.",
               "- 블로그 화면에서 같이 복사된 메뉴 글자(프로파일, URL 복사, 통계, 공감, 댓글 등)는 무시합니다."]
        note = (item.get("user_note") or "").strip()
        if note:
            out += ["", "## 사용자가 원하는 고칠 방향 (최우선)", note[:1500]]
        out += ["", "## 원문", item["rewrite_source"][:20000]]
        return "\n".join(out)
    b, m, src = item.get("brief", {}), item.get("metrics", {}), item.get("src", {})
    out = [f"오늘 날짜: {today.isoformat()} (한국 시간). 기준일이 필요한 정보는 이 날짜 기준으로 적고, 확인하지 못한 내용은 단정하지 마세요.",
           "", "아래 데이터로 작가 지침의 출력 양식에 맞춘 네이버 블로그 포스팅 초안을 써 주세요.", "",
           "## 글감 데이터", f"- 메인 키워드: {item.get('keyword')}", f"- 분야: {item.get('topic', '')}"]
    rel = [r for r in item.get("related", []) if r != item.get("keyword")][:8]
    if rel:
        out.append(f"- 롱테일 후보(네이버 자동완성에서 함께 찾는 말): {', '.join(rel)}")
    nums = []
    if m.get("volume") is not None:
        nums.append(f"월간 검색수 약 {m['volume']:,}회(네이버 검색광고)")
    if m.get("blog_total") is not None:
        nums.append(f"관련 블로그 글 {m['blog_total']:,}건")
    if m.get("growth") is not None:
        nums.append(f"최근 7일 검색 추이 {m['growth']:+.0f}%(네이버 데이터랩)")
    if nums:
        out.append("- 검색 데이터(글 소재일 뿐, 본문에 그대로 쓰지 않아도 됨): " + " · ".join(nums))
    for k, label in (("why", "지금 쓰는 이유"), ("reader", "주요 독자"), ("content", "담을 내용"), ("angle", "차별화 포인트")):
        v = b.get(k) or ""
        if k == "angle":  # 화면용 안내(키 설정·경험담 권유)는 AI에게 보내지 않음: 지어낸 경험 금지 규칙과 충돌
            v = re.sub(r"[^.]*(키를 넣으면|경험담|직접 찍은)[^.]*\.\s*", "", v).strip()
        if v:
            out.append(f"- {label}: {v}")
    if b.get("titles"):
        out.append(f"- 참고 제목(더 좋게 고쳐도 됨): {' / '.join(b['titles'][:3])}")
    note = (item.get("user_note") or "").strip()
    if note:  # 기획안의 '내 생각 반영' 칸
        out += ["", "## 사용자 메모 = 이 글의 기획 의도 (최우선 반영)",
                "작가 지침 '0. 사용자 의도와 콘셉트' 규칙에 따라, 이 메모가 지침의 기본 틀(구성·각도·문체·이미지)을 변형합니다. 메모에 없는 부분은 지침대로 쓰고, 사실 확인·출처·지어낸 경험 금지·출력 순서는 지킵니다.",
                note[:2000]]
    tool = item.get("tool")
    if isinstance(tool, dict) and tool.get("name"):
        site = (cfg.get("site") or {}).get("name") or "내 사이트"
        out += ["", "## 내 사이트 도구 연결 (반드시 반영)",
                f"- 도구: {site} {tool['name']}" + (f" – {tool['url']}" if tool.get("url") else ""),
                f"- 도구 설명(사용자 제공, 이 범위 안에서만 소개): {tool.get('desc') or '설명 없음 · 이름에서 알 수 있는 기능만 소개'}",
                f"- 번호 소제목 중 하나를 '{site} {tool['name']} 이용 방법'으로 두고(보통 계산·확인 방법 설명 바로 뒤), ① 입력할 것 → ② 결과 보는 법 → ③ 결과 활용을 번호 단계로 씁니다.",
                "- 링크는 그 섹션에 1번, 면책 문구 바로 앞에 1번만 넣습니다. 링크 앞뒤로 직접 정리한 정보를 충분히 쓰고, 광고 문구처럼 쓰지 않습니다.",
                "- 도구 화면·버튼·결과 숫자를 지어내지 않습니다. 예시 계산이 필요하면 공식 기준으로 직접 계산한 '가상 예시'로 밝힙니다.",
                "- 카드뉴스 중 한 장은 이 도구 이용 3단계 카드로 만듭니다(실제 화면처럼 그리지 않고 단계 도식으로)."]
    cp = item.get("concept_plan")
    if isinstance(cp, dict):  # 검색 화면의 콘셉트·AI 아이디어에서 고른 글
        out += ["", "## 이번 글의 콘셉트 (사용자가 고른 기획 · 이 방향으로 씀)"]
        for k, label in (("title", "제목 방향"), ("concept", "콘셉트"), ("reader", "대상 독자"), ("evidence", "근거")):
            if cp.get(k):
                out.append(f"- {label}: {cp[k]}")
        if cp.get("must_include"):
            out.append("- 꼭 다룰 내용: " + " / ".join(cp["must_include"]))
        if cp.get("keywords"):
            out.append("- 함께 다룰 연관 검색어: " + ", ".join(cp["keywords"]))
        if cp.get("link_to"):
            out.append(f"- '함께 읽으면 좋은 글'에 넣을 내 기존 글: {cp['link_to']}")
    if item.get("event_line"):
        out.append(f"- 행사 날짜 확인 결과: {item['event_line']}")
    if src.get("note"):
        out.append(f"- 생활 제도 일정: {src.get('civic', '')} — {src['note']} (마감 {src.get('end', '')})")
    news = [n.get("title") for n in (src.get("news_list") or []) if n.get("title")] or ([src["news"]] if src.get("news") else [])
    if news:
        out.append("- 관련 최신 기사 제목(사실 확인의 출발점, 문장 그대로 쓰지 말 것): " + " / ".join(news[:5]))
    sp = b.get("site")
    if sp:
        site = cfg.get("site") or {}
        out += ["", "## 내 사이트 연결",
                f"- {site.get('name', '내 사이트')}({site.get('url', '')})와 연결되는 글입니다. 넣을 위치: {sp.get('placement', '')}",
                f"- 연결 문구 예시: {' / '.join(sp.get('ctas', [])[:2])}",
                "- 광고처럼 보이지 않게 독자에게 실제로 도움이 되는 맥락에서 한두 번만 자연스럽게 안내하세요."]
    return "\n".join(out)


def system_prompt(guide, memory, web, style="info"):
    tail = ["", "---", "", "# 실행 환경 안내 (키워드 플래너)",
            "- 결과물은 위 지침의 출력 양식 그대로, 마크다운 텍스트로만 답합니다. 앞뒤 인사나 설명을 붙이지 않습니다.",
            ("- 이미지는 사용자가 Gemini로 직접 만듭니다. 당신은 이미지를 만들지 않고, 참고 자료 아래·태그 바로 위의 '■ Gemini 이미지 프롬프트'에 #1 대표 이미지(글 전체 요약이 보이는 표지)와 #2·#3 섹션 핵심 이미지(본문의 고유 대상이 주인공, 내용과 무관한 분위기 이미지 금지, 필요 없으면 생략) 프롬프트를 ~~~ 블록 하나씩 씁니다. 실제 포스터·배우 얼굴·책 표지는 재현하지 않습니다." if style == "essay" else
             "- 이미지는 사용자가 Gemini로 직접 만듭니다. 당신은 이미지를 만들지 않고, 참고 자료 아래·태그 바로 위의 '■ Gemini 이미지 프롬프트'에 4장(#1 표지 포스터, #2 할인 구조·마감 타임라인, #3 실가격 비교, #4 구매 체크리스트) 프롬프트를 ~~~ 블록 하나씩 씁니다. 실제 제품 사진·브랜드 로고·판매처 화면은 재현하지 않습니다." if style == "deal" else
             "- 이미지는 사용자가 Gemini로 직접 만듭니다. 당신은 이미지를 만들지 않고, 참고 자료 아래·태그 바로 위의 '■ Gemini 이미지 프롬프트'에 이미지 6장 프롬프트를 각각 ~~~ 블록 하나씩 단독 실행되는 완성형으로 씁니다. #1은 글 주제를 함축한 강렬한 표지 포스터(정보 카드 틀을 쓰지 않음), #2~#6은 섹션마다 그 내용과 직접 관련된 실사 사진(진짜 사진 촬영 지시) 위에 핵심 숫자·라벨을 반투명 패널로 얹은 '실사 사진 + 가공' 이미지입니다(그래프만 있는 카드 단독 금지). 파스텔·둥근 카드·부드러운 그림자의 평범한 인포그래픽은 쓰지 않습니다. 이미지마다 실제 장면이 도움이 되면 지침의 '실사 사진형'(진짜 사진 촬영 지시로 시작하고 끝에 not an illustration/not a 3D render/not CGI를 붙인 사진, 주인공 클로즈업 + 손만 보이는 생활 장면, 글자 없음), 숫자·비교가 핵심이면 카드형을 스스로 골라 씁니다."),
            "- '함께 읽으면 좋은 글'에는 아래 블로그 기억의 '내 네이버 블로그에 이미 올린 글' 목록에 있는 제목만 씁니다. 목록이 없거나 관련 글이 없으면 그 섹션을 뺍니다."]
    if web is None:
        tail.append("- 웹 검색을 쓸 수 있으면 정부·기관·기업 공식 사이트를 우선 확인하고 확인한 자료만 ■ 참고한 공식 자료 칸에 적습니다. 쓸 수 없으면 바뀔 수 있는 수치·날짜·조건을 단정하지 말고, 참고 자료 칸에 '웹 검색 없이 작성됨 · 게시 전 공식 자료 확인 필요'라고 적습니다.")
    elif web:
        tail.append("- 웹 검색 도구로 정부·기관·기업 공식 사이트를 우선 확인하고, 확인한 자료만 ■ 참고한 공식 자료 칸에 적습니다.")
    else:
        tail.append("- 이번에는 웹 검색을 쓸 수 없습니다. 바뀔 수 있는 수치·날짜·조건은 단정하지 말고 '공식 공지 확인'을 안내하며, 참고 자료 칸에는 '이번 초안은 웹 검색 없이 작성됨 · 게시 전 공식 자료 확인 필요'라고 적습니다.")
    voice = (VOICE.get("text") or "").strip()
    if voice:
        tail += ["", "---", "", "# 내 문체 프로필 (사용자 본인의 글에서 학습한 문체)",
                 "글의 구성·출력 양식·편집 형식은 위 작가 지침을 따르고, **문장·말투·어미·도입과 마무리 방식·자주 쓰는 표현**은 이 프로필을 따릅니다. "
                 "프로필과 지침의 문체 규칙이 다르면 프로필을 따릅니다(사용자 메모가 있으면 메모가 가장 우선). 프로필의 예시 문장을 그대로 복사하지 말고, 같은 결로 새로 씁니다.",
                 "", voice]
    return guide.strip() + "\n\n---\n\n" + memory.strip() + "\n" + "\n".join(tail)


# ------------------------------------------------------------------ AI 호출

def call_claude(api_key, system, user, web=True):
    try:
        import anthropic
    except ImportError:
        raise WriterError("Claude 연결 부품(anthropic)이 설치되지 않았어요. 프로그램을 START_windows.bat으로 다시 실행하면 자동으로 설치됩니다.")
    client = anthropic.Anthropic(api_key=api_key)
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}] if web else []
    messages = [{"role": "user", "content": user}]
    base = dict(model=CLAUDE_MODEL, max_tokens=32000,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                output_config={"effort": "high"})
    if tools:
        base["tools"] = tools
    msg = None
    try:
        for _ in range(5):  # 웹 검색이 길어져 pause_turn이 오면 이어서 요청
            try:
                with client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                                                 messages=messages, **base) as stream:
                    msg = stream.get_final_message()
            except TypeError:  # 오래된 SDK: 대체 모델 기능 없이
                with client.messages.stream(messages=messages, **base) as stream:
                    msg = stream.get_final_message()
            if msg.stop_reason != "pause_turn":
                break
            messages = [{"role": "user", "content": user}, {"role": "assistant", "content": msg.content}]
    except anthropic.AuthenticationError:
        raise WriterError("Claude API 키가 맞지 않아요. 설정 → AI 글쓰기에서 키를 다시 넣어 주세요.")
    except anthropic.PermissionDeniedError:
        raise WriterError("이 Claude API 키로는 사용할 수 없어요(권한·결제 확인 필요).")
    except anthropic.RateLimitError:
        raise WriterError("Claude 사용 한도에 걸렸어요. 잠시 뒤 다시 시도해 주세요.")
    except anthropic.BadRequestError as e:
        if "credit" in str(e).lower() or "billing" in str(e).lower():
            raise WriterError("Claude 크레딧이 부족해요. console.anthropic.com에서 결제(충전) 상태를 확인해 주세요.")
        raise WriterError(f"Claude 요청 오류: {getattr(e, 'message', e)}")
    except anthropic.APIStatusError as e:
        raise WriterError(f"Claude 서버 오류({e.status_code}). 잠시 뒤 다시 시도해 주세요.")
    except anthropic.APIConnectionError:
        raise WriterError("Claude에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.")
    if msg.stop_reason == "refusal":
        raise WriterError("AI가 이 주제의 글 작성을 거절했어요. 다른 키워드로 시도해 주세요.")
    text = "\n".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    sources = []
    for blk in msg.content:
        if getattr(blk, "type", "") == "web_search_tool_result" and isinstance(getattr(blk, "content", None), list):
            for r in blk.content:
                url = getattr(r, "url", None)
                if url and url not in [s["url"] for s in sources]:
                    sources.append({"title": getattr(r, "title", "") or url, "url": url})
    if msg.stop_reason == "max_tokens":
        text += "\n\n(※ 글이 길어 끝부분이 잘렸어요. '다시 쓰기'를 눌러 주세요.)"
    return text, sources, CLAUDE_MODEL


def find_claude_code(custom=""):
    """PC에 설치된 Claude Code 실행 파일 찾기."""
    import os, shutil
    cands = [custom] if custom else []
    w = shutil.which("claude")
    if w:
        cands.append(w)
    home = os.path.expanduser("~")
    cands += [os.path.join(home, ".local", "bin", "claude.exe"), os.path.join(home, ".local", "bin", "claude"),
              os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd"),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "claude", "claude.exe"),
              "/usr/local/bin/claude", os.path.join(home, ".claude", "local", "claude")]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def _subscription_env():
    """구독(Max)으로만 쓰이게: API 키 환경 변수는 빼고 실행 (있으면 -p 모드는 그 키로 과금됨)."""
    import os
    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
        env.pop(k, None)
    return env


def call_claude_code(system, user, web=True, exe="", work_dir=None, model="opus"):
    """PC의 Claude Code(Max 구독 로그인)로 초안 작성. 공식 CLI의 -p(자동 실행) 모드 사용."""
    import os, subprocess, tempfile
    exe = find_claude_code(exe)
    if not exe:
        raise WriterError("이 PC에서 Claude Code를 찾지 못했어요. 명령 창에서 claude 를 실행해 로그인했는지 확인하거나, "
                          "설정 → AI 글쓰기 → Claude Code 위치에 claude.exe 경로를 넣어 주세요.")
    work = Path(work_dir or tempfile.gettempdir()) / "keywordplanner_claude"
    work.mkdir(parents=True, exist_ok=True)  # 빈 폴더에서 실행: 다른 프로젝트의 CLAUDE.md 등이 섞이지 않게
    sys_file = work / "system_prompt.md"
    sys_file.write_text(system, encoding="utf-8")
    cmd = [exe, "-p", "Write the Naver blog draft exactly as instructed by the system prompt, using the request given on stdin. Output only the finished draft in Korean.",
           "--output-format", "json", "--system-prompt-file", str(sys_file), "--permission-mode", "dontAsk", "--max-turns", "30"]
    if model:
        cmd += ["--model", model]
    if web:
        cmd += ["--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch"]
    else:
        cmd += ["--tools", ""]
    flags = 0x08000000 if os.name == "nt" else 0  # 창 띄우지 않기
    try:
        p = run_proc(cmd, user.encode("utf-8"), str(work), _subscription_env(), 900)
    except subprocess.TimeoutExpired:
        raise WriterError("Claude Code가 15분 안에 끝내지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    except OSError as e:
        raise WriterError(f"Claude Code를 실행하지 못했어요: {e}")
    out = p.stdout.decode("utf-8", "replace").strip()
    err = p.stderr.decode("utf-8", "replace").strip()
    try:
        data = json.loads(out[out.find("{"):]) if "{" in out else {}
    except Exception:
        data = {}
    text = (data.get("result") or "").strip() if isinstance(data, dict) else ""
    low = (text + " " + err).lower()
    if p.returncode != 0 or data.get("is_error") or str(data.get("subtype", "")).startswith("error"):
        if "login" in low or "log in" in low or "authenticat" in low or "/login" in low:
            raise WriterError("Claude Code에 로그인되어 있지 않아요. 명령 창에서 claude 를 실행해 Max 계정으로 로그인한 뒤 다시 시도해 주세요.")
        if "limit" in low or "usage" in low:
            raise WriterError("Max 구독 사용 한도에 걸렸어요. 한도가 풀린 뒤 다시 시도해 주세요. " + (text or err)[:120])
        raise WriterError("Claude Code 실행 중 문제가 생겼어요: " + ((text or err or out)[:200] or f"종료 코드 {p.returncode}"))
    if len(text) < 200:
        raise WriterError("Claude Code가 초안을 돌려주지 않았어요: " + (text or err)[:200])
    return text, sources_from_text(text), f"Claude Code ({model or '기본'})"


def sources_from_text(text):
    """초안의 '■ 참고한 공식 자료' 칸에서 링크를 뽑음."""
    m = re.search(r"■\s*참고한 공식 자료(.*?)(?:\n-{3,}|\n■|$)", text or "", re.S)
    out = []
    for line in (m.group(1) if m else "").splitlines():
        u = re.search(r"https?://\S+", line)
        if u:
            url = u.group(0).rstrip(").,")
            title = re.sub(r"^[-•*\s]+", "", line[:u.start()]).strip(" –-:") or url
            out.append({"title": title, "url": url})
    return out


class GeminiHTTPError(WriterError):
    def __init__(self, code, message, detail=""):
        super().__init__(message)
        self.code, self.detail = code, detail


def _gemini_explain(code, raw):
    """Google이 보낸 오류를 알기 쉽게. (무료 한도 0인 모델, 검색 도구 한도 등)"""
    try:
        err = json.loads(raw).get("error", {})
    except Exception:
        err = {}
    msg = err.get("message") or raw[:200]
    metrics = []
    for d in err.get("details", []) or []:
        for v in d.get("violations", []) or []:
            metrics.append((v.get("quotaMetric") or v.get("quotaId") or "") + (f" (한도 {v.get('quotaValue')})" if v.get("quotaValue") else ""))
    return msg, "; ".join(m for m in metrics if m)


def find_agy(custom=""):
    """Antigravity CLI(agy) 위치. 개인 구글 계정(Google AI Pro·Ultra 구독)은 2026년부터 Gemini CLI 대신 이것으로 씀."""
    import os, shutil
    la = os.environ.get("LOCALAPPDATA", "")
    custom = (custom or "").strip().strip('"')
    if custom and os.path.isdir(custom):
        custom = os.path.join(custom, "agy.exe")
    cands = [custom] if custom else []
    w = shutil.which("agy")
    if w:
        cands.append(w)
    cands += [os.path.join(la, "agy", "bin", "agy.exe"), os.path.join(la, "Antigravity", "agy.exe"),
              os.path.join(la, "agy", "agy.exe"), os.path.join(os.path.expanduser("~"), ".local", "bin", "agy"), "/usr/local/bin/agy"]
    home = os.path.expanduser("~")
    up = os.environ.get("USERPROFILE", "") or home
    # LOCALAPPDATA가 비어 있는 실행 환경에서도 찾도록 사용자 폴더 기준 경로도 확인
    cands += [os.path.join(up, "AppData", "Local", "agy", "bin", "agy.exe"), os.path.join(up, "AppData", "Local", "agy", "bin", "agy.cmd")]
    cands += [os.path.join(la, "Programs", "agy", "agy.exe"), os.path.join(la, "Programs", "Antigravity", "bin", "agy.exe"),
              os.path.join(home, ".antigravity", "bin", "agy.exe"), os.path.join(home, ".agy", "bin", "agy.exe"),
              os.path.join(home, ".local", "bin", "agy.exe")]
    # 프로그램을 켠 뒤에 설치했으면 이 프로그램의 PATH에는 아직 없음 → 윈도우에 저장된 최신 PATH(사용자·시스템)에서 다시 찾음
    if os.name == "nt":
        try:
            import winreg
            paths = []
            for root, key in ((winreg.HKEY_CURRENT_USER, r"Environment"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
                try:
                    with winreg.OpenKey(root, key) as k:
                        paths += os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]).split(";")
                except OSError:
                    pass
            for d in paths:
                for n in ("agy.exe", "agy.cmd", "agy.bat"):
                    cands.append(os.path.join(d.strip(), n))
        except Exception:
            pass
    for c in cands:
        if c and os.path.isfile(c) and "agy-node" not in os.path.basename(c).lower():
            return c
    return None


def call_agy(system, user, web=True, exe="", work_dir=None, model="", note=None):
    """PC의 Antigravity CLI(구글 계정 로그인 = 구독 한도)로 초안 작성. 헤드리스(-p) + JSON 출력.
    PC 테스트 결과: 파이프로 넣은 입력은 읽지 않으므로 요청 전체를 -p 인자로 넘김(너무 길면 파일로)."""
    import os, subprocess, tempfile
    exe = find_agy(exe)
    if not exe:
        raise WriterError("이 PC에서 Antigravity CLI(agy)를 찾지 못했어요. 설정 → AI 글쓰기의 설치 안내를 따라 주세요.")
    work = Path(work_dir or tempfile.gettempdir()) / "keywordplanner_agy"
    work.mkdir(parents=True, exist_ok=True)  # 빈 폴더에서 실행: 다른 프로젝트 파일이 섞이지 않게
    full = (system + "\n\n---\n\n# 이번 요청\n\n" + user +
            ("\n\n(웹 검색은 수치·날짜·제도처럼 틀리면 안 되는 핵심 사실 확인에만 2~3번 이내로 쓰고, 바로 작성하세요.)" if web else "") +
            "\n\n" + (note or "파일을 만들거나 고치지 말고, 완성한 초안 전체를 답변으로만 출력하세요."))
    if len(full) < 24000:  # 윈도우 명령줄 한도(약 32,000자) 안
        prompt = full
    else:
        (work / "request.md").write_text(full, encoding="utf-8")
        prompt = ("이 폴더의 request.md 파일을 읽고, 그 안의 지침과 요청대로 네이버 블로그 초안을 작성하세요. "
                  "파일을 만들거나 고치지 말고, 완성한 초안 전체를 답변으로만 출력하세요.")
    env = dict(os.environ)
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_APPLICATION_CREDENTIALS"):
        env.pop(k, None)  # 구독(구글 계정 로그인)으로만
    base = [exe, "-p", prompt, "--output-format", "json"] + (["--model", model] if model else [])

    def run(extra):
        return run_proc(base + extra, None, str(work), env, 1200)
    try:
        p = run(["--print-timeout", "15m"])  # 기본 5분이면 긴 초안이 잘릴 수 있음
        if p.returncode != 0 and b"print-timeout" in (p.stderr + p.stdout).lower():
            p = run([])  # 이 버전이 옵션 형식을 받지 않으면 기본값으로
    except subprocess.TimeoutExpired:
        raise WriterError("Antigravity가 20분 안에 끝내지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    except OSError as e:
        raise WriterError(f"Antigravity CLI를 실행하지 못했어요: {e}")
    out = p.stdout.decode("utf-8", "replace").strip()
    err = p.stderr.decode("utf-8", "replace").strip()
    data = {}
    for line in reversed(out.splitlines()):  # 마지막 JSON 줄
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                break
            except Exception:
                pass
    if not data and "{" in out:
        try:
            data = json.loads(out[out.find("{"):])
        except Exception:
            data = {}
    text = (data.get("response") or "").strip()
    status = str(data.get("status", "")).upper()
    low = (out + " " + err).lower()
    if status != "SUCCESS" or len(text) < (200 if not note else 20):
        if "auth" in low or "login" in low or "sign in" in low or "credential" in low:
            raise WriterError("Antigravity CLI에 로그인되어 있지 않아요. 명령 창에서 agy 를 한 번 실행해 구독 계정으로 로그인해 주세요.")
        if "quota" in low or "limit" in low or "429" in low or "exhausted" in low:
            raise WriterError("구독 사용 한도에 걸렸어요. 한도가 풀린 뒤 다시 시도해 주세요. " + (err or out)[:160])
        if "timeout" in low or "timed out" in low:
            raise WriterError("Antigravity 응답 시간이 초과됐어요. 다시 시도해 주세요.")
        raise WriterError("Antigravity 실행 중 문제가 생겼어요: " + (status + " " + (err or out))[:240])
    used = model or data.get("model") or "기본 모델"
    return text, sources_from_text(text), f"Antigravity ({used})"


def find_gemini_cli(custom=""):
    import os, shutil
    cands = [custom] if custom else []
    w = shutil.which("gemini")
    if w:
        cands.append(w)
    cands += [os.path.join(os.environ.get("APPDATA", ""), "npm", "gemini.cmd"), "/usr/local/bin/gemini",
              os.path.join(os.path.expanduser("~"), ".npm-global", "bin", "gemini")]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def call_gemini_cli(system, user, web=True, exe="", work_dir=None, model=""):
    """PC의 Gemini CLI(구글 계정 로그인 = Gemini 구독 한도)로 초안 작성. 공식 CLI의 -p(자동 실행) 모드."""
    import os, subprocess, tempfile
    exe = find_gemini_cli(exe)
    if not exe:
        raise WriterError("이 PC에서 Gemini CLI를 찾지 못했어요. 설정 → AI 글쓰기의 설치 안내대로 설치하고 한 번 로그인해 주세요.")
    work = Path(work_dir or tempfile.gettempdir()) / "keywordplanner_gemini"
    work.mkdir(parents=True, exist_ok=True)  # 빈 폴더에서 실행: 다른 프로젝트의 GEMINI.md 등이 섞이지 않게
    stdin = system + "\n\n---\n\n# 이번 요청\n\n" + user + ("\n\n(웹 검색은 수치·날짜·제도처럼 틀리면 안 되는 핵심 사실 확인에만 2~3번 이내로 쓰고, 바로 작성하세요.)" if web else "")
    cmd = [exe, "-p", "Write the Naver blog draft exactly as instructed in the input. Output only the finished draft in Korean.",
           "--output-format", "json"]
    if model:
        cmd += ["-m", model]
    env = dict(os.environ)
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI"):
        env.pop(k, None)  # 구독(구글 계정 로그인)으로만: API 키가 있으면 API 한도로 처리될 수 있음
    try:
        p = run_proc(cmd, stdin.encode("utf-8"), str(work), env, 900)
    except subprocess.TimeoutExpired:
        raise WriterError("Gemini CLI가 15분 안에 끝내지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    except OSError as e:
        raise WriterError(f"Gemini CLI를 실행하지 못했어요: {e}")
    out = p.stdout.decode("utf-8", "replace").strip()
    err = p.stderr.decode("utf-8", "replace").strip()
    try:
        data = json.loads(out[out.find("{"):]) if "{" in out else {}
    except Exception:
        data = {}
    text = (data.get("response") or "").strip() if isinstance(data, dict) else ""
    e = data.get("error") if isinstance(data, dict) else None
    low = (json.dumps(e, ensure_ascii=False) if e else "") + " " + err.lower()
    if p.returncode != 0 or e or len(text) < 200:
        if "auth" in low or "login" in low or "credential" in low:
            raise WriterError("Gemini CLI에 로그인되어 있지 않아요. 명령 창에서 gemini 를 실행해 'Login with Google'로 구독 계정에 로그인해 주세요.")
        if "429" in low or "quota" in low or "exhausted" in low:
            raise WriterError("Gemini 구독 한도에 걸렸어요. 한도가 풀린 뒤 다시 시도해 주세요. " + (str(e) or err)[:160])
        raise WriterError("Gemini CLI 실행 중 문제가 생겼어요: " + ((str(e) if e else "") or err or out)[:220])
    stats = data.get("stats") or {}
    used = model or next(iter((stats.get("models") or {}).keys()), "") or "기본 모델"
    return text, sources_from_text(text), f"Gemini CLI ({used})"


def _gemini_get(url, key, body=None, timeout=240):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8") if body is not None else None,
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        msg, metrics = _gemini_explain(e.code, raw)
        if e.code in (400, 401, 403) and re.search(r"API key|API_KEY|PERMISSION_DENIED|unregistered callers", raw):
            raise GeminiHTTPError(e.code, "Gemini API 키가 맞지 않거나 이 키로 Gemini API를 쓸 수 없어요. "
                                  "aistudio.google.com/apikey 에서 만든 키인지 확인해 주세요. (Google: " + msg[:120] + ")", raw)
        raise GeminiHTTPError(e.code, f"Gemini 오류 {e.code}: {msg[:200]}" + (f" [{metrics[:160]}]" if metrics else ""), raw)
    except urllib.error.URLError:
        raise WriterError("Gemini에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.")


GEMINI_MIN_VERSION = 4.0  # 사용자 요청: 최소 4세대, Flash 미사용


def gemini_available(key):
    data = _gemini_get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", key, timeout=20)
    return [m["name"].split("/")[-1] for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", []) and m["name"].split("/")[-1].startswith("gemini-")]


def _gver(n):
    v = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
    return float(v.group(1)) if v else 0.0


def gemini_models(key, wanted=""):
    """항상 최고 버전: 이 키로 쓸 수 있는 모델 중 버전이 가장 높은 것부터 (같은 버전이면 Ultra > Pro > 기타). Flash·Lite는 쓰지 않음.
    새 버전이 나오면 코드 수정 없이 자동으로 그 모델을 고름. 설정에 모델 이름을 적으면 그 모델로 고정."""
    if wanted:
        return [wanted]
    names = [n for n in gemini_available(key) if not re.search(r"embed|image|tts|audio|live|vision|flash|lite|nano|gemma", n, re.I)]
    tier = lambda n: 3 if "ultra" in n else 2 if "pro" in n else 1
    out = sorted(names, key=lambda n: (_gver(n), tier(n), "exp" not in n), reverse=True)
    if not out:
        allm = gemini_available(key)
        raise WriterError("이 키로 쓸 수 있는 Gemini 상위 모델(Pro·Ultra)을 찾지 못했어요. 설정 → AI 글쓰기 → 모델 칸에 이름을 직접 적어 주세요. "
                          "쓸 수 있는 모델: " + ", ".join(sorted(allm, key=_gver, reverse=True)[:12]))
    return out


def pick_gemini_model(key, wanted=""):
    return gemini_models(key, wanted)[0]


def call_gemini(api_key, system, user, web=True, model=""):
    """Flash부터 차례로 시도. 한도 0(무료 등급에 없는 모델)·검색 도구 한도로 거절되면 다음 방법으로 자동 전환."""
    tried, last = [], None
    for m in gemini_models(api_key, model)[:3]:
        for use_search in ([True, False] if web else [False]):
            body = {"systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {"maxOutputTokens": 32000}}
            if use_search:
                body["tools"] = [{"google_search": {}}]
            try:
                data = _gemini_get(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent", api_key, body)
            except GeminiHTTPError as e:
                tried.append(f"{m}{'+검색' if use_search else ''}: {e.code}")
                last = e
                if e.code in (400, 401, 403) and "키가 맞지" in str(e):
                    raise
                if e.code == 429 or e.code == 404 or (e.code == 400 and use_search):
                    continue  # 검색 도구 없이 → 다음 모델
                raise
            cands = data.get("candidates") or []
            if not cands:
                raise WriterError("Gemini가 답을 주지 않았어요(안전 필터 등). 다른 키워드로 시도해 주세요.")
            c = cands[0]
            text = "".join(p.get("text", "") for p in c.get("content", {}).get("parts", [])).strip()
            sources = []
            for ch in (c.get("groundingMetadata") or {}).get("groundingChunks", []) or []:
                w = ch.get("web") or {}
                if w.get("uri") and w["uri"] not in [s_["url"] for s_ in sources]:
                    sources.append({"title": w.get("title") or w["uri"], "url": w["uri"]})
            if c.get("finishReason") == "MAX_TOKENS":
                text += "\n\n(※ 글이 길어 끝부분이 잘렸어요. '다시 쓰기'를 눌러 주세요.)"
            if not text:
                raise WriterError("Gemini가 빈 답을 보냈어요. 다시 시도해 주세요.")
            label = m + ("" if use_search or not web else " · 검색 없이")
            return text, sources, label
    reason = str(last) if last else "알 수 없음"
    if last is not None and last.code == 429:
        raise WriterError("Gemini가 '한도 초과(429)'로 거절했어요. 아직 안 썼는데 이렇게 나오면 대부분 "
                          "이 키가 결제를 설정하지 않은 프로젝트(무료 등급)의 키라서예요. Pro 계열은 API 무료 등급 한도가 0입니다. "
                          "Gemini 앱 유료 구독은 API에 적용되지 않아요. 해결: aistudio.google.com → 결제(Billing)를 설정한 프로젝트에서 키를 새로 만들기. "
                          "(Google: " + reason[:200] + ") · 시도: " + ", ".join(tried[:4]))
    raise WriterError("Gemini가 요청을 거절했어요. Google이 보낸 이유: " + reason[:260] + " · 시도: " + ", ".join(tried[:4]))


# ------------------------------------------------------------------ 초안 만들기

def parse_title(text):
    m = re.search(r"추천 제목[^\n]*\n+\s*1\.\s*(.+)", text or "")
    return m.group(1).strip().strip("()") if m else ""


def body_part(text):
    """[본문 시작]부터 마치며 끝까지: 네이버에 붙여 넣을 부분 (아래의 참고 자료·이미지 프롬프트·태그 앞)."""
    t = text or ""
    s = t.find("[본문 시작]")
    t = t[s + len("[본문 시작]"):] if s >= 0 else t
    e = re.search(r"\n(?:-{3,}\s*\n+\s*)?■\s*(?:네이버 블로그|참고한|Gemini 이미지)", t)
    return t[:e.start()].strip() if e else t.strip()


def body_chars(text):
    b = re.sub(r"\[📸[^\]]*\]", "", body_part(text))
    b = re.sub(r"[*#|>]", "", b)
    return len(b.strip())


def manual_prompt(store, cfg, item, saved, today):
    """붙여넣기 방식: Claude(Max)·Gemini 채팅에 붙여 넣을 요청문.
    - full: 작가 지침 + 블로그 기억 + 글감 (아무 채팅에나)
    - short: 블로그 기억 + 글감 (작가 지침을 Claude 프로젝트·Gemini Gems에 미리 넣어 둔 경우)"""
    style = pick_style(item)
    guide = store.guide(style)
    memory = build_memory(store, cfg, saved)
    VOICE["text"] = store.voice()
    user = draft_request(item, cfg, today)
    full = system_prompt(guide, memory, None, style) + "\n\n---\n\n# 이번 요청\n\n" + user
    short = ("(작가 지침은 이 프로젝트/Gem에 들어 있는 지침을 따르세요. 이미지는 만들지 말고 맨 아래에 Gemini 이미지 프롬프트 3개만 쓰세요.)\n\n"
             + memory.strip() + "\n\n---\n\n# 이번 요청\n\n" + user)
    return {"full": full, "short": short, "guide": guide, "style": style}


def save_draft(store, cfg, item, saved, text, provider, model, web, sources=None, seconds=0, style=None):
    text = (text or "").strip()
    if len(text) < 200:
        raise WriterError("붙여 넣은 내용이 너무 짧아요. AI가 쓴 초안 전체를 붙여 넣어 주세요.")
    tid = item.get("target_id")
    if tid and store.get(tid):  # 다시 쓰기·형식 바꾸기·AI로 고치기: 같은 초안을 덮어씀
        st = style or pick_style(item)
        rec = store.overwrite(tid, text, provider=provider, model=model, web=web, seconds=seconds, style=st,
                              sources=(sources or sources_from_text(text))[:12])
        build_memory(store, cfg, saved)
        return {**rec, "text": text}
    rec = {"id": datetime.now(KST).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4],
           "keyword": item.get("keyword", ""), "topic": item.get("topic", ""), "title": parse_title(text),
           "status": "초안", "created_at": now_iso(), "provider": provider, "model": model,
           "web": web, "sources": (sources or sources_from_text(text))[:12], "chars": body_chars(text),
           "seconds": seconds, "item_id": item.get("id"), "style": style or pick_style(item),
           "check": check_draft(text, style or pick_style(item))}
    store.add(rec, text)
    build_memory(store, cfg, saved)  # 방금 쓴 초안까지 기억에 반영
    return {**rec, "text": text}


def check_draft(text, style="info"):
    """작가 지침(출력 양식)대로 썼는지 프로그램이 직접 검사. 크게 빠진 항목은 AI에게 고쳐 쓰게 함."""
    if style == "essay":
        return check_essay(text)
    if style == "deal":
        return check_deal(text)
    t = text or ""
    body = body_part(t)

    def section(name):  # "■ name"부터 다음 ■ 전까지
        i = t.rfind("■ " + name)
        if i < 0:
            return ""
        j = t.find("■", i + 1)
        return t[i:j if j > 0 else len(t)]
    tags_sec = section("네이버 블로그")
    n_tags = len(re.findall(r"#[^\s#]+", tags_sec))
    tags_last = bool(tags_sec) and t.rfind("■") == t.rfind("■ 네이버 블로그") and "~~~" not in tags_sec
    ref = section("참고한")
    heads = re.findall(r"(?m)^##\s*(\d+)\.\s*(.+)$", body)
    nums = [int(n) for n, _ in heads]
    n_sec = len(nums)
    tables = len(re.findall(r"(?m)^\|\s*:?-{2,}", body))
    tips = len(re.findall(r"(?m)^>\s*💡", body))
    checks = len(re.findall(r"(?m)^\s*✔", body))
    faqs = len(re.findall(r"(?m)^\s*\**Q[.:]", body))
    prompts = len(re.findall(r"(?m)^(?:~~~|```)[^\n]*\n\s*Aspect ratio", t))
    imgs = sum(1 for i in range(1, 7) if re.search(rf"이미지\s*#{i}\b", body))
    head30 = "\n".join(body.strip().splitlines()[:8])
    chars = body_chars(t)
    items = [
        ("기획: 메인 키워드·롱테일·추천 제목 3개", bool(re.search(r"메인 키워드", t) and re.search(r"추천 제목[^\n]*\n+\s*1\..+\n+\s*2\..+\n+\s*3\.", t)), ""),
        ("맨 위 라벨·확인 일자 줄 없음", not re.search(r"(?m)^확인 (일자|시각)\s*[:：]", head30), ""),
        ("핵심만 먼저 보기 (✔ 4~5줄)", "핵심만 먼저" in body and 4 <= checks <= 6, f"{checks}줄"),
        ("목차", bool(re.search(r"(?m)^##\s*목차", body)), ""),
        ("소제목 5~6개 (번호 순서대로)", 5 <= n_sec <= 7 and nums == list(range(1, n_sec + 1)), f"{n_sec}개"),
        ("섹션마다 핵심 한 줄 박스 (> 💡)", n_sec > 0 and tips >= n_sec - 1, f"{tips}개"),
        ("표 3개 이상", tables >= 3, f"{tables}개"),
        ("이미지 삽입 위치 6곳", imgs == 6, f"{imgs}곳"),
        ("한눈에 요약", bool(re.search(r"(?m)^##\s*한눈에 요약", body)), ""),
        ("자주 묻는 질문 4개 이상", faqs >= 4, f"{faqs}개"),
        ("분량 3,000자 이상 (권장 3,500~4,500)", chars >= 3000, f"{chars:,}자"),
        ("본문에 URL 없음 (출처는 참고 자료에만)", not re.search(r"https?://", body), ""),
        ("기준일 면책 문구 (※)", bool(re.search(r"(?m)^※", body)), ""),
        ("참고한 공식 자료 (URL)", bool(re.search(r"https?://", ref)), ""),
        ("Gemini 카드뉴스 프롬프트 6개", prompts >= 6, f"{prompts}개"),
        ("네이버 태그 10~15개", 10 <= n_tags <= 15, f"{n_tags}개"),
        ("태그는 글 맨 마지막", tags_last, ""),
    ]
    out = [{"name": n, "ok": bool(ok), "note": note} for n, ok, note in items]
    return {"ok": all(x["ok"] for x in out), "passed": sum(x["ok"] for x in out), "total": len(out), "items": out, "chars": chars}


def check_deal(text):
    """할인·구매형 지침 검사: 사용자 지정 순서(한눈에 보기 → 1) 할인 구조와 마감 → 2) 실가격 표 → 3) 적용 방식 → 4) 제외·주의 → 5) 체크리스트)."""
    t = text or ""
    body = body_part(t)
    i = t.rfind("■ 네이버 블로그")
    tags_sec = t[i:] if i >= 0 else ""
    n_tags = len(re.findall(r"#[^\s#]+", tags_sec))
    j = t.find("■ 참고한")
    ref = t[j:t.find("■", j + 1)] if j >= 0 else ""
    nums = [int(n) for n in re.findall(r"(?m)^##\s*(\d+)\.", body)]
    prompts = len(re.findall(r"(?m)^(?:~~~|```)[^\n]*\n\s*Aspect ratio", t))
    imgs = sum(1 for k in range(1, 5) if re.search(rf"이미지\s*#{k}\b", body))
    checks = len(re.findall(r"(?m)^\s*✔", body))
    sec2 = re.split(r"(?m)^##\s*3\.", re.split(r"(?m)^##\s*2\.", body, 1)[-1], 1)[0] if re.search(r"(?m)^##\s*2\.", body) else ""
    price_table = bool(re.search(r"(?m)^\|.*(원|\$|₩).*\|", sec2))
    foreign = "$" in body or "달러" in body or "USD" in body
    chars = body_chars(t)
    items = [
        ("기획: 메인 키워드·추천 제목 3개", bool(re.search(r"메인 키워드", t) and re.search(r"추천 제목[^\n]*\n+\s*1\..+\n+\s*2\..+\n+\s*3\.", t)), ""),
        ("맨 위 라벨·확인 시각 줄 없음", not re.search(r"(?m)^확인 (일자|시각)\s*[:：]", "\n".join(body.strip().splitlines()[:8])), ""),
        ("한눈에 보기 (✔ 3~5줄)", "한눈에 보기" in body and 3 <= checks <= 6, f"{checks}줄"),
        ("소제목 1~5 (할인 구조·실가격·적용 방식·제외·체크리스트)", len(nums) >= 4 and nums == list(range(1, len(nums) + 1)), f"{len(nums)}개"),
        ("대표 제품 실가격 표", price_table, ""),
        ("환율 기준 (해외 가격일 때)", (not foreign) or bool(re.search(r"환율", body)), ""),
        ("할인 적용 단계 (①②③)", bool(re.search(r"(?m)^\s*①", body)), ""),
        ("제외 품목·주의 박스 (⚠️)", bool(re.search(r"(?m)^>\s*⚠", body)), ""),
        ("구매 체크리스트 (✅ 3줄 이상)", len(re.findall(r"(?m)^\s*✅", body)) >= 3, ""),
        ("이미지 삽입 위치 4곳", imgs == 4, f"{imgs}곳"),
        ("분량 2,000자 이상 (권장 2,500~3,500)", chars >= 2000, f"{chars:,}자"),
        ("본문에 URL 없음 (판매처 링크는 참고 자료에)", not re.search(r"https?://", body), ""),
        ("면책 문구 (※ 확인 시각 기준)", bool(re.search(r"(?m)^※", body)), ""),
        ("참고한 공식 자료 (URL)", bool(re.search(r"https?://", ref)), ""),
        ("Gemini 이미지 프롬프트 4개", prompts >= 4, f"{prompts}개"),
        ("네이버 태그 10~15개", 10 <= n_tags <= 15, f"{n_tags}개"),
        ("태그는 글 맨 마지막", bool(tags_sec) and t.rfind("■") == i and "~~~" not in tags_sec, ""),
    ]
    out = [{"name": n, "ok": bool(ok), "note": note} for n, ok, note in items]
    return {"ok": all(x["ok"] for x in out), "passed": sum(x["ok"] for x in out), "total": len(out), "items": out, "chars": chars}


def check_essay(text):
    """읽을거리형 지침 검사: 문단 중심 글이라 항목이 가벼움."""
    t = text or ""
    body = body_part(t)
    i = t.rfind("■ 네이버 블로그")
    tags_sec = t[i:] if i >= 0 else ""
    n_tags = len(re.findall(r"#[^\s#]+", tags_sec))
    j = t.find("■ 참고한")
    ref = t[j:t.find("■", j + 1)] if j >= 0 else ""
    nums = [int(n) for n in re.findall(r"(?m)^##\s*(\d+)\.", body)]
    prompts = len(re.findall(r"(?m)^(?:~~~|```)[^\n]*\n\s*Aspect ratio", t))
    imgs = sum(1 for k in range(1, 4) if re.search(rf"이미지\s*#{k}\b", body))
    q = len(re.findall(r"[가-힣](?:나요|까요|을까|ㄹ까|니까요)\?", body))
    chars = body_chars(t)
    items = [
        ("기획: 메인 키워드·추천 제목 3개", bool(re.search(r"메인 키워드", t) and re.search(r"추천 제목[^\n]*\n+\s*1\..+\n+\s*2\..+\n+\s*3\.", t)), ""),
        ("소제목 3~5개 (번호 순서대로)", 3 <= len(nums) <= 5 and nums == list(range(1, len(nums) + 1)), f"{len(nums)}개"),
        ("마무리", bool(re.search(r"(?m)^##\s*마무리", body)), ""),
        ("이미지 삽입 위치 3곳", imgs == 3, f"{imgs}곳"),
        ("분량 2,000자 이상 (권장 2,500~3,500)", chars >= 2000, f"{chars:,}자"),
        ("의문형 문장 없음", q == 0, f"{q}개" if q else ""),
        ("본문에 URL 없음", not re.search(r"https?://", body), ""),
        ("참고한 공식 자료", bool(ref.strip()), ""),
        ("Gemini 이미지 프롬프트 3개", prompts >= 3, f"{prompts}개"),
        ("네이버 태그 10~15개", 10 <= n_tags <= 15, f"{n_tags}개"),
        ("태그는 글 맨 마지막", bool(tags_sec) and t.rfind("■") == i and "~~~" not in tags_sec, ""),
    ]
    out = [{"name": n, "ok": bool(ok), "note": note} for n, ok, note in items]
    return {"ok": all(x["ok"] for x in out), "passed": sum(x["ok"] for x in out), "total": len(out), "items": out, "chars": chars}


def strip_top_labels(body):
    """본문 맨 앞의 '주제 · 세부주제' 라벨 줄과 '확인 일자/시각: …' 줄을 지움."""
    lines = body.split("\n")
    seen = 0
    for i, l in enumerate(lines):
        s = l.strip()
        if not s or s == "[본문 시작]":
            continue
        seen += 1
        if seen > 4:
            break
        if re.match(r"^확인 (일자|시각)\s*[:：]", s) or (len(s) <= 30 and re.fullmatch(r"[^.!?:：#\[\]|>]+ · [^.!?:：#\[\]|>]+", s)):
            lines[i] = None
    out = "\n".join(l for l in lines if l is not None)
    return re.sub(r"\n{3,}", "\n\n", out)


def local_fix(text):
    """AI를 다시 부르지 않고 프로그램이 바로 고치는 것: 태그를 맨 끝으로, 태그 15개 이내, 본문 속 URL 제거, 질문·답 묶음 사이 빈 줄."""
    t = (text or "").rstrip()
    m = re.search(r"\n(?:-{3,}\s*\n+\s*)?(■\s*네이버 블로그[^\n]*\n+[^\n■]*)", t)
    if m:
        block = m.group(1).strip()
        head, _, tags = block.partition("\n")
        tl = re.findall(r"#[^\s#]+", tags)
        if len(tl) > 15:
            tags = " ".join(tl[:15])
        rest = (t[:m.start()] + "\n" + t[m.end():]).rstrip()
        rest = re.sub(r"\n-{3,}\s*$", "", rest).rstrip()
        t = rest + "\n\n---\n\n" + head.strip() + "\n" + tags.strip()
    s = t.find("[본문 시작]")
    if s >= 0:
        e = re.search(r"\n(?:-{3,}\s*\n+\s*)?■\s*(?:네이버 블로그|참고한|Gemini 이미지)", t[s:])
        e = s + e.start() if e else len(t)
        body = re.sub(r"\s*\(?https?://[^\s)]+\)?", "", t[s:e])
        # 맨 위 카테고리 라벨·확인 일자 줄은 쓰지 않음 (사용자 요청)
        body = strip_top_labels(body)
        # 자주 묻는 질문: 질문·답 묶음 사이에 빈 줄 1개 (질문 줄 앞이 붙어 있으면 띄움)
        body = re.sub(r"(?m)^([^\n]*\S[^\n]*)\n(\*\*Q[.．])", r"\1\n\n\2", body)
        # 번호 단계(①~⑩): 단계 사이 빈 줄 1개
        body = re.sub(r"(?m)^([①-⑩][^\n]*)\n(?=[①-⑩])", r"\1\n\n", body)
        # ✔·▪ 줄도 줄 사이 빈 줄 1개
        for _ in range(2):  # 목록 줄(✔·▪·①·✅·❌·-·1.) 사이 빈 줄 1개
            body = re.sub(r"(?m)^((?:[✔▪✅❌•①-⑩]|[-*] |\d{1,2}\. )[^\n]*)\n(?=(?:[✔▪✅❌•①-⑩]|[-*] |\d{1,2}\. ))", r"\1\n\n", body)
        t = t[:s] + body + t[e:]
    return t.strip() + "\n"


# AI에게 다시 쓰게 할 만큼 큰 문제 (나머지는 프로그램이 고치거나 화면에 표시만)
MAJOR = ("기획", "핵심만 먼저", "한눈에 보기", "소제목 5~6개", "소제목 3~5개", "소제목 1~5", "표 3개", "대표 제품 실가격", "이미지 삽입", "Gemini 카드뉴스", "Gemini 이미지 프롬프트", "자주 묻는", "섹션마다 핵심")


def _needs_rewrite(chk):
    for x in chk["items"]:
        if not x["ok"] and (x["name"].startswith(MAJOR) or (x["name"].startswith("분량") and chk["chars"] < (1700 if "2,000" in x["name"] else 2700))):
            return True
    return False


def _fix_request(user, text, chk):
    miss = [f"- {x['name']}" + (f" (지금 {x['note']})" if x["note"] else "") for x in chk["items"] if not x["ok"]]
    return (user + "\n\n---\n\n# 고쳐 쓰기\n\n아래는 방금 쓴 초안입니다. 작가 지침의 '9. 출력 양식'과 비교해 다음 항목이 빠졌거나 틀렸습니다:\n"
            + "\n".join(miss) + "\n\n내용은 살리고 위 항목을 고쳐서, 기획부터 이미지 프롬프트까지 **초안 전체를 처음부터 다시** 출력하세요. "
            "분량이 모자라면 각 소제목에 배경·기준·적용 예시·헷갈리는 점을 보태세요(반복·수식어로 채우지 말 것). 설명 없이 초안만 출력합니다.\n\n"
            "[방금 쓴 초안]\n\n" + text)


def _caller(provider, cfg, store, system, web):
    """provider에 맞는 '요청 → (글, 출처, 모델)' 함수."""
    if provider == "antigravity":
        model = cfg.get("agy_model", "")
        return lambda u: call_agy(system, u, web, cfg.get("agy_path", ""), store.data, model)
    if provider == "gemini_cli":
        model = cfg.get("gemini_model", "")
        if cfg.get("gemini_api_key") and not model:  # 키가 있으면 모델 목록에서 항상 최고 버전을 골라 CLI에 지정
            try:
                model = pick_gemini_model(cfg["gemini_api_key"], "")
            except Exception:
                model = ""
        def run(u):
            try:
                return call_gemini_cli(system, u, web, cfg.get("gemini_cli_path", ""), store.data, model)
            except WriterError as e:
                if model and not cfg.get("gemini_model") and re.search(r"model|not found|404|permission|unsupported", str(e), re.I):
                    return call_gemini_cli(system, u, web, cfg.get("gemini_cli_path", ""), store.data, "")
                raise
        return run
    if provider == "claude_code":
        return lambda u: call_claude_code(system, u, web, cfg.get("claude_code_path", ""), store.data, cfg.get("claude_code_model", "opus"))
    # 유료 API(Gemini API·Claude API)로 글을 쓰는 경로는 막혀 있음: 추가 결제가 생기지 않게
    raise WriterError("유료 API로는 글을 쓰지 않도록 막혀 있어요. 설정 → AI 글쓰기에서 'Gemini 구독'을 골라 주세요.")


def make_draft(store, cfg, item, saved, today, progress=None):
    """선택한 글감으로 작가 지침(Gems)대로 초안을 완성: 쓰기 → 양식 검사 → 빠진 것 고쳐 쓰기 → 저장."""
    say = progress or (lambda msg: None)
    provider = cfg.get("ai_provider", "antigravity")
    web = cfg.get("ai_web_check", True)
    if provider == "manual":
        raise WriterError("붙여넣기 방식에서는 요청문을 복사해 Gemini·Claude에 붙여 넣어 주세요.")
    style = pick_style(item)
    guide = store.guide(style)
    memory = build_memory(store, cfg, saved)
    VOICE["text"] = store.voice()
    system, user = system_prompt(guide, memory, web, style), draft_request(item, cfg, today)
    t0 = time.time()
    call = _caller(provider, cfg, store, system, web)
    say({"essay": "읽을거리형 지침으로 쓰는 중", "deal": "할인·구매형 지침으로 쓰는 중"}.get(style, "작가 지침(정보형)으로 쓰는 중"))
    # 유료 API로 몰래 넘어가지 않음: 구독(CLI)이 실패하면 멈추고 이유를 보여 줌
    text, sources, model = call(user)
    t_first = round(time.time() - t0)
    text = local_fix(text)
    chk = check_draft(text, style)
    fixed = 0
    intent = bool((item.get("user_note") or "").strip() or item.get("revise_instruction"))  # 사용자 의도로 형식을 바꾼 글은 기본 틀로 되돌려 고쳐 쓰지 않음
    if not chk["ok"] and _needs_rewrite(chk) and not intent:
        say(f"양식 검사 {chk['passed']}/{chk['total']} · 빠진 항목을 고쳐 쓰는 중")
        try:
            t2, s2, _m = call(_fix_request(user, text, chk))
            t2 = local_fix(t2)
            c2 = check_draft(t2, style)
            if c2["passed"] >= chk["passed"] and len(t2) > len(text) * 0.6:
                text, chk, fixed = t2, c2, 1
                seen = {x.get("url") for x in (sources or [])}
                sources = (sources or []) + [x for x in (s2 or []) if x.get("url") not in seen]
        except DraftCancelled:
            raise
        except WriterError:
            pass  # 고쳐 쓰기가 실패하면 첫 초안을 그대로 저장 (검사 결과는 화면에 표시)
    say("저장하는 중")
    rec = save_draft(store, cfg, item, saved, text, provider, model, bool(web), sources, round(time.time() - t0), style=style)
    store.set_meta(rec["id"], fixed=fixed, auto=bool(cfg.get("_auto")), first_seconds=t_first, intent=intent)
    return {**rec, "check": chk, "fixed": fixed, "auto": bool(cfg.get("_auto")), "first_seconds": t_first}


VOICE_SYSTEM = """# 역할
당신은 글쓰기 문체 분석가입니다. 사용자가 직접 쓴 네이버 블로그 글 여러 편을 읽고, 다른 AI가 이 사람처럼 쓸 수 있도록 **문체 프로필**을 만듭니다.

# 원칙
- 글의 주제·정보가 아니라 **쓰는 방식**을 분석합니다.
- 실제 글에서 확인되는 특징만 씁니다. 추측하거나 일반론을 늘어놓지 않습니다.
- 각 항목은 구체적으로: "문장이 짧다" 대신 "한 문장 평균 30~45자, 2~3문장마다 줄바꿈".
- 잘 된 점(살릴 것)과 반복되는 약점(고칠 것)을 구분합니다.

# 출력 (마크다운만, 앞뒤 설명 없이)
## 한 줄 요약
## 문장과 어미
(평균 문장 길이, 주로 쓰는 어미 비율(~입니다/~해요 등), 문장 시작 습관)
## 도입 방식
(첫 2~3문장을 어떻게 여는지, 독자에게 말을 거는지)
## 소제목과 구성
(소제목 짓는 법·길이·번호, 섹션 순서 습관)
## 문단과 줄바꿈
(문단 길이, 빈 줄 사용, 모바일 가독성 습관)
## 강조·표·박스
(굵게 쓰는 대상, 표·체크리스트·인용 박스 쓰는 습관)
## 자주 쓰는 표현 (살릴 것)
(이 사람다운 표현 5~10개를 짧게 인용)
## 반복되는 약점 (고칠 것)
(반복 표현·장황한 부분·말버릇)
## 마무리 방식
## 예시 문장
(이 사람 문체를 잘 보여 주는 원문 문장 5개를 그대로 인용)
"""


def learn_voice(store, cfg, samples):
    """사용자 글 여러 편 → 내 문체 프로필(md) 생성·저장."""
    provider = cfg.get("ai_provider", "antigravity")
    stat = [s for s in samples if s.startswith("[편집 통계")]
    posts = [s for s in samples if not s.startswith("[편집 통계")]
    joined = "\n\n".join(f"## 글 {i + 1}\n\n{s.strip()[:9000]}" for i, s in enumerate(posts[:6]) if s.strip()) + ("\n\n" + stat[0] if stat else "")
    if len(joined) < 800:
        raise WriterError("분석할 글이 너무 짧아요. 내 글을 2편 이상(각 1,000자 이상) 붙여 넣어 주세요.")
    user = "아래는 사용자가 직접 쓴 네이버 블로그 글입니다. 블로그 화면에서 같이 복사된 메뉴 글자(프로파일, URL 복사, 공감, 댓글 등)는 무시하세요.\n\n" + joined
    note = "파일을 만들거나 고치지 말고, 문체 프로필 마크다운만 답변으로 출력하세요."
    if provider == "antigravity":
        text, _s, _m = call_agy(VOICE_SYSTEM, user, False, cfg.get("agy_path", ""), store.data, cfg.get("agy_model", ""), note=note)
    elif provider == "claude_code":
        text, _s, _m = call_claude_code(VOICE_SYSTEM, user + "\n\n" + note, False, cfg.get("claude_code_path", ""), store.data,
                                        cfg.get("claude_code_model", "opus"))
    else:
        raise WriterError("문체 학습은 Antigravity 또는 Claude Max 연결이 필요해요.")
    text = text.strip()
    if "##" not in text or len(text) < 300:
        raise WriterError("AI 답변에서 문체 프로필을 읽지 못했어요. 다시 시도해 주세요.")
    profile = f"# 내 문체 프로필\n\n> 내 글 {len(posts)}편에서 학습 · {now_iso()[:10]} · 직접 고쳐도 됩니다\n\n" + text
    store.save_voice(profile)
    return profile


# ---------- 오늘의 글 계획 (요일 코너 + 유효성 검증) ----------
WEEKDAYS = "월화수목금토일"


def plan_guide(store):
    """오늘의 글 계획 지침: 사용자가 고친 memory/오늘의_글_계획_지침.md 가 있으면 그것, 없으면 기본."""
    p = store.mem_dir / "오늘의_글_계획_지침.md"
    try:
        t = p.read_text(encoding="utf-8").strip()
        if t:
            return t
    except Exception:
        pass
    try:
        return (Path(__file__).resolve().parent / "daily_plan_guide.md").read_text(encoding="utf-8").strip()
    except Exception:
        return fetch_repo_file("daily_plan_guide.md") or ""


def save_plan_guide(store, text):
    p = store.mem_dir / "오늘의_글_계획_지침.md"
    store.mem_dir.mkdir(parents=True, exist_ok=True)
    if text.strip():
        p.write_text(text.strip() + "\n", encoding="utf-8")
    elif p.exists():
        p.unlink()


def make_daily_plan(store, cfg, ctx, now):
    """오늘 쓸 글 1건(+예비 1건) 계획을 마크다운으로."""
    provider = cfg.get("ai_provider", "antigravity")
    system = plan_guide(store).replace("{블로그 이름}", cfg.get("blog_name") or cfg.get("blog_id") or "내 블로그")
    lines = [f"# 실행 기준 시각 (프로그램이 확인)", f"{now.strftime('%Y-%m-%d')} ({WEEKDAYS[now.weekday()]}) {now.strftime('%H:%M')} KST", ""]
    if ctx.get("my_posts"):
        lines += ["# 최근 블로그 발행 글 (겹치지 않게)"] + [f"- {t}" for t in ctx["my_posts"][:30]] + [""]
    if ctx.get("drafts"):
        lines += ["# 최근 2주 초안 (겹치지 않게)"] + [f"- {t}" for t in ctx["drafts"][:20]] + [""]
    if ctx.get("my_keywords"):
        lines += ["# 블로그 유입 검색어 (사용자가 넣은 것 · 이 검색어 중심으로 고르기)", ", ".join(ctx["my_keywords"][:20]), ""]
    if ctx.get("today"):
        lines += ["# 프로그램이 오늘 모은 추천 글감 (검색 수치 기반 · 참고용)"] + [f"- {t}" for t in ctx["today"][:15]] + [""]
    if ctx.get("news"):
        lines += ["# 최근 뉴스 제목 (참고용)"] + [f"- {t}" for t in ctx["news"][:15]] + [""]
    user = "\n".join(lines) + "\n위 지침의 '5. 출력 형식' 그대로, 오늘의 블로그 글 예정을 작성하세요."
    note = "파일을 만들거나 고치지 말고, 출력 형식의 마크다운만 답변으로 출력하세요. 수치는 웹 검색으로 공식 출처를 확인하고, 확인하지 못한 것은 (미확인)으로 표시하세요."
    if provider == "antigravity":
        text, _s, _m = call_agy(system, user, True, cfg.get("agy_path", ""), store.data, cfg.get("agy_model", ""), note=note)
    elif provider == "claude_code":
        text, _s, _m = call_claude_code(system, user + "\n\n" + note, True, cfg.get("claude_code_path", ""), store.data,
                                        cfg.get("claude_code_model", "opus"))
    else:
        raise WriterError("오늘의 글 계획은 Antigravity(Gemini 자동 작성) 또는 Claude Max 연결이 필요해요. 붙여넣기 방식이면 [요청문 복사]를 쓰세요.")
    text = (text or "").strip()
    if "선정 주제" not in text:
        raise WriterError("AI 답변에서 글 계획을 읽지 못했어요. 다시 시도해 주세요.")
    return text, system, user


IDEAS_SYSTEM = """# 역할
당신은 네이버 블로그 콘텐츠 기획자입니다. 키워드 플래너가 모은 기록(검색 수치, 연관 검색어 묶음, 사용자의 기존 글·초안·인기 검색어, 최근 뉴스)을 검토해,
이 블로그가 이어서 쓰기 좋은 **글 아이디어 8~10개**를 제안합니다.

# 원칙
- 데이터에 근거합니다. 아이디어마다 근거(어떤 연관 검색어·수치·기존 글·뉴스 때문인지)를 한 줄로 적습니다. 없는 수치를 지어내지 않습니다.
- 서로 겹치지 않게: 독자 상황(기준 확인·처리 순서·비용·보험/법률·치료·서류·비교·사례·일정)이 다른 아이디어로 고르게 나눕니다.
- 사용자가 이미 쓴 글과 같은 주제는 피하고, 그 글과 이어지는 다음 글(심화·후속·반대 상황)을 제안합니다. 이어지는 기존 글이 있으면 link_to에 그 제목을 그대로 적습니다(목록에 없는 제목은 쓰지 않음).
- 제목은 건조한 서술형·명사형. 의문형("~나요?", "몇 점?")을 쓰지 않고, 메인 검색어를 앞쪽에 둡니다.
- 시리즈 순서(series)는 독자가 읽을 순서: 기준·개념 → 절차 → 비용 → 보험·법률 → 사례·심화.
- 사고·질병·법률 같은 주제는 단정 대신 기준과 확인 방법 중심으로 기획합니다.

# 출력
JSON 배열만 출력합니다. 앞뒤 설명, 마크다운 코드 표시 없이.
[{"title": "추천 제목", "keyword": "이 글의 메인 검색어(연관 검색어 중 하나)", "concept": "글의 콘셉트 한 문장", "reader": "대상 독자와 상황",
  "must_include": ["꼭 다룰 내용 3~5개"], "evidence": "근거 한 줄", "series": 1, "link_to": "이어지는 내 기존 글 제목 또는 빈 문자열"}]
"""


def make_ideas(store, cfg, data, today):
    """검색한 키워드에 대해 기록을 검토한 글 아이디어 8~10개 (JSON)."""
    provider = cfg.get("ai_provider", "antigravity")
    lines = [f"오늘 날짜: {today.isoformat()} (한국 시간)", "", f"## 검색한 키워드: {data['keyword']}", "", "## 연관 검색어와 수치 (점수 높은 순)"]
    for c in data.get("items", [])[:30]:
        m = c.get("metrics") or {}
        bits = [f"점수 {round(c.get('score', 0))}"]
        if m.get("volume") is not None:
            bits.append(f"월 검색 {m['volume']:,}")
        if m.get("blog_total") is not None:
            bits.append(f"블로그 글 {m['blog_total']:,}")
        lines.append(f"- {c.get('keyword')} ({' · '.join(bits)})")
    if data.get("concepts"):
        lines += ["", "## 독자 상황별 묶음 (프로그램이 연관 검색어를 묶은 것)"]
        lines += [f"- {g['name']}: {', '.join(k['keyword'] for k in g['keywords'])} (월 검색 합 {g['volume']:,})" for g in data["concepts"]]
    r = data.get("records") or {}
    lines += ["", "## 사용자 기록"]
    lines.append("- 이 키워드와 관련해 이미 올린 글: " + (" / ".join(p["title"] for p in r.get("posts", [])) or "없음"))
    lines.append("- 이미 쓴 초안: " + (" / ".join(d["title"] for d in r.get("drafts", [])) or "없음"))
    lines.append("- 블로그 유입·인기 검색어(사용자가 입력): " + (", ".join(cfg.get("my_keywords", [])[:15]) or "없음"))
    if data.get("my_posts"):
        lines.append("- 최근 올린 글 전체 제목: " + " / ".join(data["my_posts"][:30]))
    if data.get("news"):
        lines += ["", "## 최근 관련 뉴스 제목"] + [f"- {n}" for n in data["news"][:8]]
    user = "\n".join(lines)
    note = "파일을 만들거나 고치지 말고, JSON 배열만 답변으로 출력하세요."
    if provider == "antigravity":
        text, _s, _m = call_agy(IDEAS_SYSTEM, user, False, cfg.get("agy_path", ""), store.data, cfg.get("agy_model", ""), note=note)
    elif provider == "claude_code":
        text, _s, _m = call_claude_code(IDEAS_SYSTEM, user + "\n\n" + note, False, cfg.get("claude_code_path", ""), store.data,
                                        cfg.get("claude_code_model", "opus"))
    elif provider == "gemini_cli":
        text, _s, _m = call_gemini_cli(IDEAS_SYSTEM, user + "\n\n" + note, False, cfg.get("gemini_cli_path", ""), store.data, cfg.get("gemini_model", ""))
    else:
        raise WriterError("AI 아이디어는 Antigravity 또는 Claude Max 연결이 필요해요.")
    s, e = text.find("["), text.rfind("]")
    try:
        arr = json.loads(text[s:e + 1]) if s >= 0 and e > s else []
    except Exception:
        arr = []
    ideas = []
    for x in arr if isinstance(arr, list) else []:
        if isinstance(x, dict) and x.get("title"):
            ideas.append({"title": str(x.get("title"))[:120], "keyword": str(x.get("keyword") or data["keyword"])[:60],
                          "concept": str(x.get("concept", ""))[:300], "reader": str(x.get("reader", ""))[:200],
                          "must_include": [str(i)[:120] for i in (x.get("must_include") or [])][:6],
                          "evidence": str(x.get("evidence", ""))[:240], "series": x.get("series") if isinstance(x.get("series"), int) else None,
                          "link_to": str(x.get("link_to", ""))[:120]})
    if not ideas:
        raise WriterError("AI 답변에서 아이디어를 읽지 못했어요. 다시 시도해 주세요.")
    ideas.sort(key=lambda i: i["series"] or 99)
    return ideas


# ------------------------------------------------------------------ docx (표준 라이브러리로 직접 만듦)

FONT = "맑은 고딕"


def _runs(text, base_bold=False, size=None, color=None, italic=False):
    """**굵게** 표시를 실제 굵은 글씨로 바꾼 run XML."""
    out = []
    for i, part in enumerate(re.split(r"\*\*", text)):
        if not part:
            continue
        bold = base_bold or (i % 2 == 1)
        rpr = f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:eastAsia="{FONT}"/>'
        if bold:
            rpr += "<w:b/>"
        if italic:
            rpr += "<w:i/>"
        if color:
            rpr += f'<w:color w:val="{color}"/>'
        if size:
            rpr += f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
        out.append(f'<w:r><w:rPr>{rpr}</w:rPr><w:t xml:space="preserve">{xesc(part)}</w:t></w:r>')
    return "".join(out)


def _p(inner, style=None, spacing_after=120, shade=None):
    ppr = f'<w:pStyle w:val="{style}"/>' if style else ""
    if shade:
        ppr += f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>'
    ppr += f'<w:spacing w:after="{spacing_after}" w:line="320" w:lineRule="auto"/>'
    return f"<w:p><w:pPr>{ppr}</w:pPr>{inner}</w:p>"


def _table(rows):
    cols = max(len(r) for r in rows)
    grid = "".join('<w:gridCol w:w="%d"/>' % (9000 // cols) for _ in range(cols))
    trs = []
    for ri, r in enumerate(rows):
        tcs = []
        for ci in range(cols):
            cell = r[ci] if ci < len(r) else ""
            shd = '<w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/>' if ri == 0 else ""
            tcs.append(f'<w:tc><w:tcPr><w:tcW w:w="{9000 // cols}" w:type="dxa"/>{shd}</w:tcPr>'
                       f'{_p(_runs(cell, base_bold=(ri == 0), size=20), spacing_after=40)}</w:tc>')
        trs.append("<w:tr>" + "".join(tcs) + "</w:tr>")
    border = "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
                     for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
    return (f'<w:tbl><w:tblPr><w:tblW w:w="9000" w:type="dxa"/><w:tblBorders>{border}</w:tblBorders></w:tblPr>'
            f'<w:tblGrid>{grid}</w:tblGrid>{"".join(trs)}</w:tbl>' + _p("", spacing_after=60))


def build_docx(text, title=""):
    body, lines, i = [], (text or "").replace("\r\n", "\n").split("\n"), 0
    if title:
        body.append(_p(_runs(title, base_bold=True, size=36), spacing_after=240))
    while i < len(lines):
        ln = lines[i].rstrip()
        s = ln.strip()
        if s.startswith("|") and s.endswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                body.append(_table(rows))
            continue
        if not s:
            body.append(_p("", spacing_after=60))
        elif s.startswith("```") or s.startswith("~~~"):
            pass  # 프롬프트 블록 표시 줄은 docx에 넣지 않음
        elif re.fullmatch(r"[-=]{3,}", s):
            body.append(_p("", spacing_after=120))
        elif s.startswith("## "):
            body.append(_p(_runs(s[3:], base_bold=True, size=38, color="2B6CB0"), spacing_after=160))  # 소제목 19pt
        elif s.startswith("# "):
            body.append(_p(_runs(s[2:], base_bold=True, size=34), spacing_after=200))
        elif s.startswith("[📸") or s.startswith("[본문 시작]") or s.startswith("[블로그 포스팅"):
            body.append(_p(_runs(s, italic=True, color="7F7F7F", size=20), shade="F7F7F7"))
        elif s.startswith(">"):  # 핵심 한 줄·주의 박스 → 스마트에디터 인용구로 옮길 부분
            q = s.lstrip(">").strip()
            warn = "⚠" in q or q.startswith("▪")
            body.append(_p(_runs(q, base_bold=q.startswith(("💡", "⚠")), size=22), shade="FFF4E0" if warn else "EAF1FF", spacing_after=40))
        elif s.startswith("■"):
            body.append(_p(_runs(s, base_bold=True, size=24), spacing_after=100))
            refs = "참고한" in s  # 참고한 공식 자료 칸: 본문보다 작게(블로그 13 크기에 맞춤)
            while refs and i + 1 < len(lines) and re.match(r"^\s*[-•]\s+", lines[i + 1]):
                i += 1
                body.append(_p(_runs("•  " + re.sub(r"^\s*[-•]\s+", "", lines[i].strip()), size=19), spacing_after=40))
        elif re.match(r"^[-*•]\s+", s):
            body.append(_p(_runs("•  " + re.sub(r"^[-*•]\s+", "", s), size=22), spacing_after=60))
        else:
            body.append(_p(_runs(s, size=22)))
        i += 1
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           + "".join(body) +
           '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
           'w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              f'<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:eastAsia="{FONT}" w:cs="{FONT}"/>'
              '<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="ko-KR" w:eastAsia="ko-KR"/></w:rPr></w:rPrDefault>'
              '<w:pPrDefault><w:pPr><w:spacing w:after="120"/></w:pPr></w:pPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style></w:styles>')
    ctypes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="xml" ContentType="application/xml"/>'
              '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
              '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
              '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                '</Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
    return buf.getvalue()


def docx_filename(rec):
    safe = re.sub(r'[\\/:*?"<>|]+', " ", rec.get("keyword") or "초안").strip()[:40]
    return f"{rec.get('created_at', '')[:10]}_{safe}.docx"


def check_ai(cfg):
    """키가 맞는지 확인 (요금이 나가지 않는 방법으로)."""
    import subprocess, os
    out = {}
    ax = find_agy(cfg.get("agy_path", ""))
    if not ax:
        out["antigravity"] = {"ok": False, "message": "이 PC에서 Antigravity CLI(agy)를 찾지 못했어요 (설치 후 새 창에서 agy --version)"}
    else:
        try:
            v = subprocess.run([ax, "--version"], capture_output=True, timeout=30,
                               creationflags=0x08000000 if os.name == "nt" else 0).stdout.decode("utf-8", "replace").strip()
            out["antigravity"] = {"ok": True, "message": f"찾음 {v} ({ax}) · 로그인 상태는 첫 초안 때 확인돼요"}
        except Exception as e:
            out["antigravity"] = {"ok": False, "message": f"실행 실패: {e}"}
    gx = find_gemini_cli(cfg.get("gemini_cli_path", ""))
    if not gx:
        out["gemini_cli"] = {"ok": False, "message": "이 PC에서 Gemini CLI를 찾지 못했어요 (설치 후 gemini 를 한 번 실행해 로그인)"}
    else:
        try:
            v = subprocess.run([gx, "--version"], capture_output=True, timeout=30,
                               creationflags=0x08000000 if os.name == "nt" else 0).stdout.decode("utf-8", "replace").strip()
            out["gemini_cli"] = {"ok": True, "message": f"찾음 {v} ({gx}) · 로그인 상태는 첫 초안 때 확인돼요"}
        except Exception as e:
            out["gemini_cli"] = {"ok": False, "message": f"실행 실패: {e}"}
    exe = find_claude_code(cfg.get("claude_code_path", ""))
    if not exe:
        out["claude_code"] = {"ok": False, "message": "이 PC에서 Claude Code를 찾지 못했어요 (설치·경로 확인)"}
    else:
        try:
            v = subprocess.run([exe, "--version"], capture_output=True, timeout=30, env=_subscription_env(),
                               creationflags=0x08000000 if os.name == "nt" else 0).stdout.decode("utf-8", "replace").strip()
            note = " · PC에 ANTHROPIC_API_KEY가 있지만 이 프로그램은 빼고 실행해요" if os.environ.get("ANTHROPIC_API_KEY") else ""
            out["claude_code"] = {"ok": True, "message": f"찾음 {v or ''} ({exe}) · 로그인 상태는 첫 초안 때 확인돼요{note}"}
        except Exception as e:
            out["claude_code"] = {"ok": False, "message": f"실행 실패: {e}"}
    if cfg.get("anthropic_api_key"):
        try:
            import anthropic
            anthropic.Anthropic(api_key=cfg["anthropic_api_key"]).models.retrieve(CLAUDE_MODEL)
            out["claude"] = {"ok": True, "message": f"연결됨 · {CLAUDE_MODEL}"}
        except ImportError:
            out["claude"] = {"ok": False, "message": "연결 부품(anthropic) 미설치 · START_windows.bat으로 다시 실행하면 설치돼요"}
        except Exception as e:
            name = type(e).__name__
            msg = {"AuthenticationError": "키가 맞지 않아요", "PermissionDeniedError": "권한·결제 확인 필요",
                   "NotFoundError": "이 키로는 해당 모델을 쓸 수 없어요", "APIConnectionError": "연결 실패(인터넷 확인)"}.get(name, f"오류: {name}")
            out["claude"] = {"ok": False, "message": msg}
    else:
        out["claude"] = {"ok": False, "message": "키 없음"}
    if cfg.get("gemini_api_key"):
        try:
            allm = sorted(gemini_available(cfg["gemini_api_key"]), key=_gver, reverse=True)
            try:
                chosen = pick_gemini_model(cfg['gemini_api_key'], cfg.get('gemini_model', ''))
                out["gemini"] = {"ok": True, "message": f"연결됨 · 쓸 모델: {chosen} · 이 키로 쓸 수 있는 모델: {', '.join(allm[:8])}"}
            except WriterError as e:
                out["gemini"] = {"ok": False, "message": str(e)}
        except WriterError as e:
            out["gemini"] = {"ok": False, "message": str(e)}
    else:
        out["gemini"] = {"ok": False, "message": "키 없음"}
    return out
