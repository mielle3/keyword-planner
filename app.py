# -*- coding: utf-8 -*-
"""
블로그 키워드 플래너 (네이버 블로그용)

실행:  python app.py   ->  브라우저에서 http://127.0.0.1:8765 이 열립니다.

분석 순서
  1. 내가 고른 네이버 블로그 주제(공식 32개 중) + 이달의 시즌 이슈 + 오늘의 이슈 + 내 블로그 유입 검색어로 씨앗 구성
  2. 네이버 자동완성을 2단계로 파고들어 실제 검색 문구를 대량 수집                 (무료, 키 불필요)
  3. 키워드별 수치 측정
       - 네이버 검색광고 키워드도구: 월간 검색수(PC/모바일), 경쟁 정도              (무료, 검색광고 키)
       - NAVER API HUB 블로그 검색: 전체 글 수, 최근 7일 새 글 수, 상위 글          (무료, API HUB 키)
       - NAVER API HUB 지식iN 검색: 질문 수                                        (무료, API HUB 키)
       - NAVER API HUB 검색어 트렌드: 최근 7일 vs 직전 21일 변화율                 (무료, API HUB 키)
       - 카카오 블로그 검색: 다음 블로그 글 수                                      (무료, 카카오 키, 선택)
       - 키가 없으면 자동완성 노출 순위로 수요를 추정
  4. 기회 점수(0~100) = 수요 35% + 상승세 25% + (100-경쟁) 25% + 글감 적합도 15%, 없는 항목은 빼고 비율 재조정
  5. 키워드마다 네이버 블로그 글 기획안(문장)을 작성
"""
import base64
import subprocess
import os
import shutil
import hashlib
import hmac
import json
import math
import random
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
def user_data_dir():
    """키·기록 저장 위치: 프로그램 폴더 밖의 사용자 설정 폴더 (새 버전을 어디에 풀어도 유지됨)."""
    if os.environ.get("KEYWORD_PLANNER_DATA"):
        return Path(os.environ["KEYWORD_PLANNER_DATA"])
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "KeywordPlanner"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "KeywordPlanner"
    return Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "KeywordPlanner"


DATA = user_data_dir()
HISTORY = DATA / "history"
CONFIG_PATH = DATA / "config.json"
SAVED_PATH = DATA / "saved.json"
USAGE_PATH = DATA / "usage.json"
PREEMPT_PATH = DATA / "preempt.json"
EVERGREEN_CHECK_PATH = DATA / "evergreen_check.json"
import writer as _writer  # AI 글쓰기 (작가 지침·블로그 기억·초안 보관·docx)
WRITER = _writer.Store(DATA)
KST = timezone(timedelta(hours=9))
APP_VERSION = "2026.11.21-49"  # 화면 파일을 바꿀 때마다 올림 (예전 창·브라우저 캐시와 구분)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

DEFAULT_CONFIG = {
    "naver_client_id": "", "naver_client_secret": "",
    "searchad_api_key": "", "searchad_secret": "", "searchad_customer_id": "", "kakao_rest_key": "",
    "topics": [], "include_issues": True, "my_keywords": [],
    "site": {"name": "", "url": "", "offers": []}, "site_boost": True,
    "watchlist": ["악동뮤지션", "아이유", "임영웅", "성시경", "데이식스"],
    "scale": "보통", "use_signal_bz": True, "port": 8765,
    "anthropic_api_key": "", "gemini_api_key": "", "ai_provider": "antigravity", "agy_path": "", "agy_model": "", "ai_web_check": True, "gemini_model": "", "claude_code_path": "", "gemini_cli_path": "",
    "blog_id": "", "dislikes": [], "auto_refresh_hours": 4, "auto_draft_per_day": 2,
}
# 수집 규모: 씨앗당 2단계 확장 수, 분석할 키워드 총량
SCALES = {"빠름": {"depth2": 1, "budget": 120}, "보통": {"depth2": 3, "budget": 240}, "정밀": {"depth2": 5, "budget": 420}}
DAILY_LIMITS = {"search": 25000, "trend": None, "searchad": None}

# ------------------------------------------------------------------ 네이버 블로그 공식 주제 (4그룹 32개)
# 씨앗 키워드: {m}=이번 달, {s}=계절, {y}=올해
TOPIC_GROUPS = {
    "엔터테인먼트·예술": {
        "문학·책": ["책 추천", "베스트셀러", "{s} 책 추천"],
        "영화": ["{m}월 개봉 영화", "넷플릭스 영화 추천", "영화 추천"],
        "미술·디자인": ["전시회 추천", "그림 그리기", "디자인 툴"],
        "공연·전시": ["{m}월 전시회", "뮤지컬", "{m}월 축제"],
        "음악": ["{s} 노래 추천", "플레이리스트", "콘서트 일정"],
        "드라마": ["드라마 추천", "드라마 촬영지", "{m}월 드라마"],
        "스타·연예인": ["아이돌 컴백", "연예인 패션", "{m}월 컴백"],
        "만화·애니": ["애니 추천", "웹툰 추천", "애니 극장판"],
        "방송": ["예능 추천", "방송 맛집", "예능 촬영지"],
    },
    "생활·노하우·쇼핑": {
        "일상·생각": ["{m}월 할일", "생활꿀팁", "다이소 추천템"],
        "육아·결혼": ["아이랑 가볼만한곳", "이유식", "결혼 준비"],
        "반려동물": ["강아지 간식", "고양이 용품", "강아지 산책"],
        "좋은글·이미지": ["좋은 글귀", "{m}월 인사말", "{s} 감성 문구"],
        "패션·미용": ["{s} 코디", "{s} 스킨케어", "{s} 네일"],
        "인테리어·DIY": ["{s} 인테리어", "원룸 인테리어", "정리수납"],
        "요리·레시피": ["{s} 제철 음식", "집밥 레시피", "에어프라이어 요리"],
        "상품리뷰": ["{s} 가전 추천", "다이소 신상", "올리브영 추천"],
        "원예·재배": ["식물 키우기", "베란다 텃밭", "{s} 꽃"],
    },
    "취미·여가·여행": {
        "게임": ["모바일 게임 추천", "스팀 게임 추천", "닌텐도 스위치 게임"],
        "스포츠": ["러닝", "골프", "{s} 운동"],
        "사진": ["아이폰 사진", "카메라 추천", "{s} 출사"],
        "자동차": ["신차 출시", "자동차 보험", "중고차"],
        "취미": ["취미 추천", "뜨개질", "원데이클래스"],
        "국내여행": ["{m}월 국내여행", "당일치기 여행", "{s} 여행지"],
        "세계여행": ["{m}월 해외여행", "일본 여행", "동남아 여행"],
        "맛집": ["{s} 맛집", "데이트 맛집", "서울 맛집"],
    },
    "지식·동향": {
        "IT·컴퓨터": ["노트북 추천", "아이폰 꿀팁", "AI 활용"],
        "사회·정치": ["{y} 달라지는 제도", "생활 법률", "{m}월 지원금"],
        "건강·의학": ["{s} 건강관리", "영양제 추천", "다이어트 식단"],
        "비즈니스·경제": ["적금 추천", "{y} 연말정산", "재테크", "금리 전망", "창업 아이템", "{m}월 신제품"],
        "국제·글로벌": ["환율", "해외 직구", "해외여행 물가", "{y} 글로벌 트렌드"],
        "어학·외국어": ["영어 공부", "일본어 공부", "토익"],
        "교육·학문": ["초등 공부법", "자격증 추천", "공부법"],
    },
}
TOPICS = {t: seeds for g in TOPIC_GROUPS.values() for t, seeds in g.items()}
# 한 번에 고르는 추천 묶음
TOPIC_PRESETS = [
    {"name": "공연·여행 (떠나셈 맞춤)", "topics": ["공연·전시", "음악", "국내여행", "세계여행"]},
    {"name": "여행·맛집", "topics": ["국내여행", "세계여행", "맛집", "요리·레시피"]},
    {"name": "육아·교육", "topics": ["육아·결혼", "교육·학문", "요리·레시피", "건강·의학"]},
    {"name": "문화·엔터", "topics": ["영화", "드라마", "공연·전시", "음악", "스타·연예인"]},
    {"name": "리뷰·쇼핑", "topics": ["상품리뷰", "IT·컴퓨터", "패션·미용", "인테리어·DIY"]},
    {"name": "사회·문화", "topics": ["교육·학문", "문학·책", "미술·디자인", "공연·전시"]},
    {"name": "경제·국제", "topics": ["비즈니스·경제", "국제·글로벌", "IT·컴퓨터", "상품리뷰"]},
    {"name": "생활·재테크", "topics": ["일상·생각", "비즈니스·경제", "건강·의학", "인테리어·DIY"]},
]
TOPIC_GROUP_OF = {t: g for g, ts in TOPIC_GROUPS.items() for t in ts}
ISSUE_TOPIC = "오늘의 이슈"
CIVIC_TOPIC = "생활 제도 일정"
NEWS_TOPIC = "분야별 뉴스 이슈"  # 예전 기록 호환용


def news_topic(label):
    return f"{label} 뉴스"


NEWS_HINTS = {"사회": ["신청", "지원금", "대상", "자격", "방법", "정리", "뜻", "기간"],
              "생활·제도": ["신청", "기간", "대상", "마감", "조회", "방법", "계산"],
              "문화": ["전시", "예매", "일정", "기간", "가격", "후기", "위치", "관람"],
              "경제": ["전망", "금리", "가격", "계산", "신청", "조회", "정리"],
              "국제": ["환율", "여행", "전망", "정리", "뜻", "영향"],
              "IT·과학": ["출시", "가격", "사용법", "비교", "후기", "설정"],
              "연예": ["출연", "방송", "일정", "공개", "회차", "시청"],
              "건강": ["증상", "효과", "방법", "예방", "음식", "시기"],
              "스포츠": ["일정", "중계", "순위", "예매", "결과", "명단"]}
# (구글 뉴스 섹션 코드 또는 "q:검색어", 분야 이름). 같은 분야 이름은 합쳐서 보여 줌
NEWS_SECTIONS = [("BUSINESS", "경제"), ("WORLD", "국제"),
                 ("q:교육 OR 복지 OR 환경 OR 저출생 OR 기후 OR 고령화 OR 청년 OR 육아 OR 지원금 when:2d", "사회"),
                 ("NATION", "사회"),
                 ("q:전시 OR 공연 OR 박물관 OR 미술관 OR 문화재 OR 출간 OR 신간 OR 국립극장 OR 축제 when:2d", "문화"),
                 ("q:신청 마감 OR 신청 기간 OR 고지서 OR 세액공제 OR 바우처 OR 환급 OR 지원금 신청 when:3d", "생활·제도"),
                 ("TECHNOLOGY", "IT·과학"), ("ENTERTAINMENT", "연예"), ("HEALTH", "건강"), ("SPORTS", "스포츠")]
MINE_TOPIC = "내 블로그 유입어"

# 시즌 씨앗을 주제에 연결하기 위한 별칭
LIFE, TREND, FOOD, TRAVEL, KIDS, HEALTH = "일상·생각", "일상·생각", "요리·레시피", "국내여행", "육아·결혼", "건강·의학"
BEAUTY, MONEY, HOME, CULTURE, IT = "패션·미용", "비즈니스·경제", "인테리어·DIY", "공연·전시", "IT·컴퓨터"
SEASON_EXTRA = {KIDS: ["교육·학문"], IT: ["상품리뷰"], HOME: ["일상·생각"], CULTURE: ["영화"]}

SEASON_SEEDS = {
    1: [("신년 계획", [LIFE], None), ("신년운세", [TREND], None), ("연말정산", [MONEY], None),
        ("겨울방학", [KIDS], None), ("스키장", [TRAVEL], None), ("방어", [FOOD], None), ("딸기 디저트", [FOOD], None),
        ("설날 선물", [LIFE, MONEY], None), ("겨울 가습기", [HOME, IT], None), ("독감", [HEALTH], None)],
    2: [("졸업식", [KIDS, LIFE], None), ("발렌타인데이", [TREND, FOOD], (2, 14)), ("입학 준비물", [KIDS], None),
        ("봄 신상", [BEAUTY], None), ("정월대보름", [FOOD, TREND], None), ("설날", [LIFE, TRAVEL], None),
        ("연말정산 환급", [MONEY], None), ("봄맞이 대청소", [HOME], None)],
    3: [("입학", [KIDS], None), ("화이트데이", [TREND, FOOD], (3, 14)), ("봄 대청소", [HOME], None),
        ("미세먼지", [HEALTH, IT], None), ("벚꽃 개화", [TRAVEL, CULTURE], None), ("봄 코디", [BEAUTY], None),
        ("봄동", [FOOD], None), ("공기청정기", [IT, HOME], None)],
    4: [("벚꽃 명소", [TRAVEL], None), ("피크닉", [LIFE, FOOD], None), ("캠핑", [TRAVEL, CULTURE], None),
        ("환절기 비염", [HEALTH], None), ("중간고사", [KIDS], None), ("봄 나물", [FOOD], None), ("자외선 차단제", [BEAUTY], None)],
    5: [("어린이날", [KIDS, TRAVEL], (5, 5)), ("어버이날", [LIFE], (5, 8)), ("스승의날", [KIDS], (5, 15)),
        ("종합소득세", [MONEY], None), ("가정의달 선물", [LIFE, MONEY], None), ("부처님오신날", [CULTURE, TRAVEL], None),
        ("장미축제", [CULTURE], None), ("여름 다이어트", [HEALTH], None)],
    6: [("현충일", [LIFE], (6, 6)), ("장마", [HOME, LIFE], None), ("여름휴가", [TRAVEL], None),
        ("에어컨 청소", [HOME, IT], None), ("제습기", [IT, HOME], None), ("여름 다이어트", [HEALTH], None),
        ("여름 코디", [BEAUTY], None), ("콩국수", [FOOD], None)],
    7: [("워터파크", [TRAVEL, KIDS], None), ("복날", [FOOD, HEALTH], None), ("여름방학", [KIDS], None),
        ("폭염", [HEALTH, LIFE], None), ("전기요금", [MONEY, HOME], None), ("휴가 준비물", [TRAVEL, LIFE], None),
        ("빙수", [FOOD], None), ("선풍기", [IT], None)],
    8: [("광복절", [LIFE, CULTURE], (8, 15)), ("말복", [FOOD], None), ("개학 준비물", [KIDS], None),
        ("여름 세일", [BEAUTY, IT], None), ("늦여름 휴가", [TRAVEL], None), ("추석 선물", [LIFE, MONEY], None)],
    9: [("추석", [LIFE, TRAVEL, FOOD], None), ("추석 선물세트", [LIFE, MONEY], None), ("가을 나들이", [TRAVEL, KIDS], None),
        ("환절기 비염", [HEALTH], None), ("가을 코디", [BEAUTY], None), ("전어", [FOOD], None), ("가을 캠핑", [TRAVEL, CULTURE], None)],
    10: [("단풍", [TRAVEL], None), ("할로윈", [TREND, KIDS], (10, 31)), ("가을 축제", [CULTURE], None),
         ("한글날", [KIDS, CULTURE], (10, 9)), ("독감 예방접종", [HEALTH, KIDS], None), ("트렌치코트", [BEAUTY], None),
         ("대하", [FOOD], None), ("가을 이불", [HOME], None)],
    11: [("수능", [KIDS, TREND], None), ("수능 선물", [LIFE], None), ("빼빼로데이", [TREND, FOOD], (11, 11)),
         ("김장", [HOME, FOOD], None), ("블랙프라이데이", [IT, BEAUTY], None), ("패딩", [BEAUTY], None),
         ("연말정산", [MONEY], None), ("독감 예방접종", [HEALTH, KIDS], None), ("가습기", [HOME, IT], None),
         ("늦가을 단풍", [TRAVEL], None), ("크리스마스 선물", [LIFE, KIDS], None), ("귤", [FOOD], None),
         ("송년회", [FOOD, LIFE], None), ("크리스마스 트리", [HOME, CULTURE], None)],
    12: [("크리스마스", [CULTURE, TRAVEL, FOOD], (12, 25)), ("크리스마스 선물", [LIFE, KIDS], (12, 25)),
         ("송년회", [FOOD, LIFE], None), ("연말정산", [MONEY], None), ("겨울방학", [KIDS], None),
         ("동지 팥죽", [FOOD], (12, 22)), ("해돋이 명소", [TRAVEL], (12, 31)), ("신년 다이어리", [LIFE], None),
         ("겨울 스킨케어", [BEAUTY], None), ("난방비", [MONEY, HOME], None), ("연말 결산", [TREND], None)],
}

INTENTS = [
    (("티켓팅", "예매", "선예매", "일반예매", "티켓 오픈", "티켓오픈", "예매처", "예매 방법", "예매일정", "좌석", "좌석배치도", "취켓팅"),
     ["{q} 일정·가격·좌석 총정리 (+성공 팁)", "{q} 성공하려면 미리 준비할 것"],
     ["예매 일정 한눈에", "좌석·가격 정리", "티켓팅 성공 팁", "예매 바로가기"], True),
    (("콘서트", "내한", "팬미팅", "페스티벌", "라인업", "투어", "앵콜", "공연 일정", "셋리스트"),
     ["{q} 일정·장소·예매 정보 한 번에 정리", "{q}, 가기 전에 알아둘 모든 것"],
     ["공연 일정과 장소", "예매 일정·가격", "관람 팁·셋리스트"], True),
    (("출시일", "출시", "사전예약", "사전 예약", "개봉", "개봉일", "개봉 예정", "공개일", "공개 예정", "오픈일", "얼리버드"),
     ["{q} 언제? 일정·가격 미리 정리", "{q} 미리 보기, 놓치지 않으려면"],
     ["언제 나오나", "가격·혜택 정리", "미리 준비할 것"], True),
    (("시기", "언제", "날짜", "일정", "기간", "디데이", "시간표", "마감"),
     ["{q}, {y}년 기준으로 정리했어요", "{q} 헷갈린다면 이 글 하나로 끝"],
     ["{y}년 일정 한눈에", "놓치기 쉬운 포인트", "미리 준비하면 좋은 것"], True),
    (("레시피", "만들기", "만드는법", "황금레시피", "양념", "끓이는법"),
     ["{q} 실패 없이 따라 하는 법", "{q} 직접 해보니 이 비율이 정답"],
     ["재료 준비", "순서대로 따라 하기", "맛있게 만드는 팁"], False),
    (("가볼만한곳", "갈만한곳", "명소", "여행지", "여행지 추천", "핫플", "맛집", "장소", "장소 추천", "숙소", "카페"),
     ["{q} BEST 5 직접 골라봤어요", "{q}, 실패 없는 곳만 모았어요"],
     ["고른 기준", "추천 리스트", "가기 전 알아둘 점"], False),
    (("추천", "베스트", "순위", "인기"),
     ["{q} BEST 5, 직접 비교해서 골랐어요", "{q} 고민이라면 이것부터 보세요"],
     ["고르는 기준", "추천 리스트", "사기 전 체크할 점"], False),
    (("블랙프라이데이", "세일", "할인", "특가", "쿠폰"),
     ["{q} 할인 품목·일정 총정리", "{q} 놓치면 아쉬운 꿀템 정리"],
     ["언제·어디서 하나", "할인 폭 큰 품목", "싸게 사는 요령"], True),
    (("가격", "비용", "최저가", "얼마", "가격표", "예상가격", "대여", "렌탈"),
     ["{q} 얼마일까? {y} 최신 정리", "{q} 아끼는 방법까지 총정리"],
     ["가격 정리", "할인 받는 법", "구매 전 체크"], True),
    (("후기", "리뷰", "솔직", "장단점"),
     ["{q} 솔직하게 써봤어요 (장단점)", "{q}, 사기 전에 꼭 보세요"],
     ["써보게 된 이유", "좋았던 점·아쉬운 점", "이런 분께 추천"], False),
    (("오류", "안됨", "안 됨", "안옴", "안 옴", "먹통", "오류코드", "인식 안", "연결 안", "해결"),
     ["{q} 원인과 해결 방법, 이것부터 확인하세요", "{q}일 때 바로 해볼 수 있는 방법 정리"],
     ["증상별로 먼저 확인할 것", "해결 방법 단계별 정리", "그래도 안 될 때(고객센터·문의)"], False),
    (("취소", "환불", "해지", "탈퇴", "취소 수수료", "환불 수수료", "환불규정", "주문취소", "취소표"),
     ["{q}, 조건과 기간 한 번에 정리", "{q} 방법과 수수료·처리 기간 총정리"],
     ["가능한 경우와 안 되는 경우", "단계별 방법", "수수료·처리 기간"], False),
    (("고객센터", "전화번호", "상담원", "상담원 연결"),
     ["{q} 운영시간과 상담원 연결 순서", "{q} 연결 전에 준비할 것 정리"],
     ["운영시간·연결 순서", "전화 말고 빠른 방법(채팅·앱)", "자주 묻는 문의"], False),
    (("재발급", "복구", "분실", "분실신고", "찾기"),
     ["{q} 방법과 준비물 정리", "{q} 처음부터 끝까지 따라 하기"],
     ["먼저 확인할 것", "단계별 방법", "준비물·주의사항"], False),
    (("투표", "문자투표", "재방송", "방청", "방청 신청", "다시보기", "최종순위", "우승자"),
     ["{q} 방법과 일정 한 번에 정리", "{q}, 놓치지 않게 정리했어요"],
     ["일정·기간", "참여(시청) 방법", "결과·다음 회차"], True),
    (("신청", "조회", "신청방법", "자격", "대상", "계산", "환급", "모의계산"),
     ["{q} 이렇게 하면 쉬워요", "{q} 단계별로 정리했어요"],
     ["대상·자격 확인", "단계별 방법", "놓치기 쉬운 점"], True),
    (("방법", "하는법", "꿀팁", "보관법", "보관", "세탁", "관리", "청소", "정리", "루틴"),
     ["{q} 이렇게 하면 쉬워요", "{q}, 해보니 이게 제일 편했어요"],
     ["먼저 알아둘 것", "단계별 방법", "자주 하는 실수"], False),
    (("선물", "세트", "키트", "포장"),
     ["{q} 받는 사람이 좋아한 리스트", "{q} 고민 끝! 가격대별 추천"],
     ["가격대별 추천", "센스 있는 고르는 법", "포장·전달 팁"], False),
    (("준비물", "체크리스트", "리스트", "필수템"),
     ["{q} 빠짐없이 체크리스트", "{q}, 이것만 챙기면 돼요"],
     ["꼭 필요한 것", "있으면 좋은 것", "미리 사두면 좋은 시기"], False),
    (("비교", "차이", "vs"),
     ["{q} 한눈에 비교해봤어요", "{q}, 나한테 맞는 건?"],
     ["비교 기준", "항목별 차이", "상황별 선택"], False),
    (("옷차림", "코디", "룩", "아우터", "패딩"),
     ["{q}, 요즘 날씨에 딱 맞게", "{q} 실패 없는 조합 모음"],
     ["날씨·기온 체크", "추천 조합", "포인트 아이템"], False),
]
DEFAULT_INTENT = (["{q} 알아두면 좋은 정보 총정리", "요즘 많이 찾는 {q}, 핵심만 정리"],
                  ["요즘 왜 많이 찾을까", "핵심 정리", "알아두면 좋은 팁"], False)
PRODUCT_INTENT = (["{q} 사기 전에 꼭 볼 장단점 정리", "{q} 직접 써보고 느낀 점"],
                  ["왜 필요할까", "고를 때 볼 것", "장단점 정리"], False)
PRODUCT_CATS = {"IT·컴퓨터", "상품리뷰", "인테리어·DIY", "패션·미용", "반려동물", "자동차", "사진"}

# 검색 의도별 기획 문장 재료: (독자, 담을 내용, 도입부에서 약속할 것)
INTENT_INFO = {
    "티켓팅": ("예매를 준비하는 사람", "예매 일정과 좌석·가격, 티켓팅 성공 팁", "예매 일정부터 성공 팁"),
    "콘서트": ("공연을 보러 가려는 사람", "공연 일정과 장소, 예매 방법, 관람 팁", "일정·장소·예매 정보"),
    "출시일": ("나오기 전에 미리 알아보는 사람", "공개·출시 일정과 가격·혜택, 미리 준비할 것", "일정과 가격"),
    "시기": ("정확한 날짜와 시기를 확인하려는 사람", "올해 정확한 일정과 언제부터 준비하면 좋은지", "일정과 준비 시점"),
    "레시피": ("직접 만들어 보려는 사람", "재료와 분량, 순서, 실패하지 않는 팁", "재료부터 꿀팁"),
    "가볼만한곳": ("갈 곳을 고르는 사람", "장소별 특징과 위치·운영 정보, 방문 팁", "추천 장소와 방문 팁"),
    "추천": ("무엇을 고를지 비교 중인 사람", "고르는 기준과 추천 목록, 각각의 장단점", "고르는 기준과 추천 목록"),
    "블랙프라이데이": ("할인 기간에 싸게 사려는 사람", "행사 일정과 할인 폭이 큰 품목, 싸게 사는 요령", "일정과 할인 품목"),
    "가격": ("가격과 비용을 미리 알아보는 사람", "가격대와 비용 구성, 아끼는 방법", "가격과 아끼는 방법"),
    "후기": ("사기 전에 실제 사용 경험을 확인하려는 사람", "직접 써본 경험과 좋았던 점·아쉬운 점", "솔직한 장단점"),
    "오류": ("지금 오류로 불편을 겪고 있는 사람", "증상별 원인과 바로 해볼 수 있는 해결 방법", "원인과 해결 방법"),
    "취소": ("취소·환불을 하려는 사람", "가능 조건과 방법, 수수료와 처리 기간", "가능 조건과 처리 기간"),
    "고객센터": ("문의할 곳을 찾는 사람", "운영시간과 연결 순서, 전화보다 빠른 방법", "운영시간과 연결 방법"),
    "재발급": ("다시 발급·복구해야 하는 사람", "준비물과 단계별 방법, 주의할 점", "준비물과 방법"),
    "투표": ("방송에 참여하거나 결과를 확인하려는 사람", "참여 방법과 일정, 결과", "방법과 일정"),
    "신청": ("신청이나 조회를 해야 하는 사람", "대상과 자격, 신청 순서, 놓치기 쉬운 점", "대상 확인부터 신청 방법"),
    "방법": ("방법을 따라 해 보려는 사람", "단계별 방법과 자주 하는 실수", "방법과 주의할 점"),
    "선물": ("선물을 고르는 사람", "가격대별 추천과 센스 있게 고르는 요령", "가격대별 추천"),
    "준비물": ("빠뜨리지 않고 준비하려는 사람", "꼭 필요한 것과 있으면 좋은 것을 나눈 체크리스트", "체크리스트"),
    "비교": ("무엇을 고를지 고민하는 사람", "항목별 차이와 상황별 추천", "차이점과 선택 기준"),
    "옷차림": ("날씨에 맞는 옷을 고르는 사람", "기온별 추천 조합과 포인트 아이템", "코디 조합"),
}
DEFAULT_INFO = ("'{kw}'에 대해 알아보는 사람", "꼭 알아야 할 핵심 정보와 알아두면 좋은 팁", "핵심 정보와 팁")
PRODUCT_INFO = ("구매를 고민하는 사람", "고르는 기준과 장단점, 사기 전 확인할 점", "고르는 기준과 장단점")
TREND_INFO = ("화제가 된 이유가 궁금한 사람", "무슨 일인지, 왜 화제인지, 알아두면 좋은 점", "핵심 내용")

# 뉴스에서 출발한 글: (독자, 담을 내용, 약속, 제목 틀, 소제목)
NEWS_BRIEF = {
    "문화": ("이번 주말 볼거리·갈 곳을 찾는 사람", "어떤 행사·작품인지, 볼거리와 의미, 일정·장소·예매 방법", "일정·장소·예매 방법",
           ["{q} 일정·장소·예매 총정리", "{q} 가기 전 꼭 알아둘 볼거리", "{y} {q} 관람 팁, 직접 정리했어요"],
           ["어떤 행사·작품인가", "볼거리와 의미", "일정·장소·예매", "함께 가 볼 곳"]),
    "경제": ("내 돈과 일에 어떤 영향이 있는지 궁금한 사람", "무슨 일인지, 왜 중요한지, 내 지갑에 미치는 영향", "핵심 내용과 내 지갑에 미치는 영향",
           ["{q} 무슨 일? 핵심만 쉽게 정리", "{q}, 내 지갑에는 어떤 영향이 있을까", "{y} {q} 알아둘 점 총정리"],
           ["무슨 일이 있었나", "왜 중요한가", "내 지갑에 미치는 영향", "지금 해 둘 일"]),
    "국제": ("해외 소식이 내 생활에 어떤 영향을 주는지 궁금한 사람", "무슨 일인지, 배경, 우리나라와 내 생활에 미치는 영향", "배경과 우리에게 미치는 영향",
           ["{q} 무슨 일? 배경부터 쉽게 정리", "{q}, 우리 생활에는 어떤 영향이 있을까", "{y} {q} 한눈에 정리"],
           ["무슨 일이 있었나", "배경 한 번에 이해하기", "우리나라·내 생활에 미치는 영향", "더 알아볼 곳"]),
    "_": ("뉴스를 보고 내 생활에 어떤 영향이 있는지 궁금한 사람", "무슨 일인지, 왜 중요한지, 내 생활에 미치는 영향", "핵심 내용과 내 생활에 미치는 영향",
          ["{q} 무슨 일? 핵심만 쉽게 정리", "{q}, 우리 생활에 어떤 영향이 있을까", "{y} {q} 알아둘 점 총정리"],
          ["무슨 일이 있었나", "왜 중요한가", "내 생활에 미치는 영향", "더 알아볼 곳"]),
}


def news_brief_of(section):
    return NEWS_BRIEF.get(section) or NEWS_BRIEF["_"]

# 주제별로 잘 맞는 연관어 (후보 중 이 단어가 들어간 것을 우선)
GENERIC_HINTS = ["추천", "방법", "후기", "정리", "비교"]
CAT_HINTS = {
    "문학·책": ["추천", "베스트셀러", "줄거리", "후기", "리스트"], "영화": ["추천", "개봉", "후기", "결말", "쿠키"],
    "미술·디자인": ["전시", "그리기", "추천", "툴", "강좌"], "공연·전시": ["일정", "예매", "전시", "추천", "축제"],
    "음악": ["추천", "플레이리스트", "콘서트", "가사", "일정"], "드라마": ["추천", "촬영지", "결말", "출연진", "ost"],
    "스타·연예인": ["컴백", "패션", "프로필", "일정", "콘서트"], "만화·애니": ["추천", "극장판", "순위", "결말"],
    "방송": ["촬영지", "맛집", "추천", "출연진", "재방송"],
    "일상·생각": ["꿀팁", "추천", "방법", "선물", "준비"], "육아·결혼": ["아이", "아기", "개월", "준비", "추천", "유아"],
    "반려동물": ["강아지", "고양이", "추천", "간식", "방법"], "좋은글·이미지": ["글귀", "문구", "인사말", "명언", "모음"],
    "패션·미용": ["코디", "네일", "컬러", "추천", "브랜드", "스킨케어"], "인테리어·DIY": ["인테리어", "정리", "수납", "조명", "셀프"],
    "요리·레시피": ["레시피", "만들기", "황금레시피", "보관", "메뉴"], "상품리뷰": ["추천", "후기", "비교", "가격", "최저가"],
    "원예·재배": ["키우기", "물주기", "분갈이", "추천", "텃밭"],
    "게임": ["추천", "공략", "순위", "출시", "쿠폰"], "스포츠": ["일정", "방법", "추천", "규칙", "중계"],
    "사진": ["설정", "보정", "추천", "출사", "촬영"], "자동차": ["가격", "출시", "비교", "보험", "연비"],
    "취미": ["추천", "배우기", "클래스", "방법", "준비물"], "국내여행": ["가볼만한곳", "코스", "숙소", "여행지", "명소"],
    "세계여행": ["여행", "코스", "준비물", "날씨", "환전"], "맛집": ["맛집", "추천", "메뉴", "웨이팅", "가성비"],
    "IT·컴퓨터": ["추천", "설정", "비교", "사용법", "꿀팁"], "사회·정치": ["신청", "제도", "지원금", "자격", "조회"],
    "건강·의학": ["증상", "효과", "방법", "시기", "식단"], "비즈니스·경제": ["신청", "조회", "계산", "환급", "비용", "조건", "서류", "자격", "갈아타기", "주의사항", "비교", "추천"],
    "어학·외국어": ["공부법", "독학", "시험", "일정", "교재"], "교육·학문": ["공부법", "시험", "일정", "추천", "준비"],
    ISSUE_TOPIC: ["가격", "출시", "일정", "명소", "후기"], MINE_TOPIC: GENERIC_HINTS,
    "국제·글로벌": ["환율", "직구", "물가", "여행", "전망", "트렌드"],
    NEWS_TOPIC: ["가격", "전망", "출시", "방법", "뜻", "정리", "일정"],
}
CAT_HINTS[CIVIC_TOPIC] = ["신청", "기간", "대상", "방법", "조회", "마감", "계산", "납부", "조건"]
TOPIC_GROUP_OF[CIVIC_TOPIC] = "생활"
for _l, _h in NEWS_HINTS.items():
    CAT_HINTS[news_topic(_l)] = _h
    TOPIC_GROUP_OF[news_topic(_l)] = "뉴스"

# 내 홈페이지 연계: 사이트에서 제공하는 서비스 → 이 단어가 들어간 키워드와 연결
OFFER_TRIGGERS = {
    "공연·티켓 예매": ["예매", "티켓", "티켓팅", "콘서트", "공연", "뮤지컬", "내한", "팬미팅", "페스티벌", "좌석", "전시", "연극",
                   "어워드", "어워즈", "시상식", "MMA", "MAMA"],
    "여행·투어": ["여행", "여행지", "투어", "패키지여행", "항공권", "가볼만한곳", "가볼만한 곳", "여행 코스", "해외여행", "당일치기",
               "축제", "불꽃", "빛축제", "벚꽃", "단풍", "명소", "해돋이", "일출", "숙소", "1박2일", "나들이", "크리스마스마켓"],
    "숙소·호텔": ["숙소", "호텔", "펜션", "리조트", "호캉스", "글램핑", "캠핑장", "독채"],
    "맛집·예약": ["맛집", "예약", "웨이팅", "오마카세", "코스요리"],
    "쇼핑·상품": ["최저가", "할인", "세일", "블랙프라이데이", "구매", "가격", "쿠폰"],
    "교육·클래스": ["클래스", "강의", "자격증", "원데이클래스", "강좌", "수강"],
}
OFFER_ACTION = {"공연·티켓 예매": "예매", "여행·투어": "예약", "숙소·호텔": "예약", "맛집·예약": "예약",
                "쇼핑·상품": "구매", "교육·클래스": "신청"}

# 주제와 어긋나는 키워드 제외
TOPIC_EXCLUDE = {"국내여행": ["해외", "일본", "유럽", "동남아", "베트남", "태국", "오사카", "도쿄", "삿포로"],
                 "세계여행": ["국내"], "맛집": ["레시피", "만들기"]}
NEWS_EXCLUDE = ["기사", "뉴스", "속보", "보도", "신문", "기자", "사설", "칼럼", "인터뷰", "ppt", "PPT", "영어로", "한자",
                "와이프", "남편", "아내", "부인", "재산", "나이", "이혼", "열애", "학력", "고향", "집안", "스파이", "국적",
                "고객센터", "전화번호", "콜센터", "나무위키", "위키", "인스타", "atm", "ATM"]
for _l in NEWS_HINTS:
    TOPIC_EXCLUDE[news_topic(_l)] = NEWS_EXCLUDE
TOPIC_EXCLUDE[news_topic("스포츠")] = NEWS_EXCLUDE + ["대출", "금리", "주가", "채용", "보험", "카드", "적금", "예금", "캐피탈", "할인", "혜택", "포켓몬", "편성표"]

BLOCK_WORDS = ["사망", "숨져", "숨진", "사고", "살인", "폭행", "흉기", "검찰", "기소", "구속", "재판", "판결", "경찰",
               "대통령", "국회", "탄핵", "선거", "정당", "민주당", "국민의힘", "장관", "총리", "외교",
               "전쟁", "테러", "화재", "참사", "성범죄", "마약", "자살", "지진", "북한", "퇴진", "논란", "혐의",
               "통상", "교섭", "본부장", "면담", "회담", "군수", "국방", "살균제", "피해자", "유족", "징역", "체포",
               "야동", "성인", "19금", "도박", "토토", "카지노",
               "미군", "주한", "전작권", "안보", "트럼프", "해킹", "정부", "여당", "야당", "시위", "집회", "파업",
               "정자법", "정치자금", "여론조사", "심서", "선고", "공판", "명태균", "윤석열", "이재명", "김건희", "특검"]
POLITICS_WORDS = [
    # 기관·직책
    "대통령", "대통령실", "청와대", "국회", "국회의원", "장관", "차관", "총리", "국무", "국정", "청문회", "도지사", "시장 후보",
    "당대표", "원내", "비대위", "최고위", "대변인", "정부", "여당", "야당", "여야", "정당", "정권", "행정부",
    # 정당
    "민주당", "국민의힘", "국힘", "조국혁신당", "개혁신당", "진보당", "정의당", "새로운미래",
    # 선거·여론
    "선거", "대선", "총선", "지선", "보궐", "투표", "공천", "출마", "후보", "경선", "여론조사", "지지율", "당선",
    # 사법·수사
    "검찰", "검사", "기소", "구속", "영장", "재판", "판결", "선고", "공판", "항소", "상고", "법원", "헌재", "헌법재판",
    "수사", "특검", "압수수색", "혐의", "피고인", "정자법", "정치자금", "뇌물", "횡령",
    # 정국·이념
    "탄핵", "계엄", "내란", "개헌", "시위", "집회", "파업", "규탄", "퇴진", "논란", "정쟁", "좌파", "우파", "보수", "진보",
    # 안보·외교·북한
    "북한", "대북", "통일부", "국방", "국방부", "미사일", "안보", "외교", "회담", "정상회담", "통상", "제재",
    "미군", "주한", "전작권", "트럼프", "바이든", "푸틴", "시진핑",
    # 인물(최근 정치 이슈)
    "윤석열", "이재명", "김건희", "한동훈", "조국", "명태균", "이준석", "홍준표", "김문수",
    "한덕수", "김민석", "추미애", "최민희", "이승만", "박정희", "통일교", "녹취", "피의자", "방화", "흉악", "실형", "징역형",
    "與", "野", "제명", "징계", "당 대표", "당대표", "친윤", "친명", "비명", "의총", "대표 측", "반란", "암살", "입건", "뺑소니",
    "실종", "수색", "송치", "체포", "검거", "고발", "고소", "배현진", "장동혁", "정점식",
]
SCANDAL_WORDS = ["음주운전", "성폭력", "성폭행", "성추행", "불륜", "스캔들", "부음", "부친상", "모친상", "별세", "사망", "숨져",
                 "추락", "충돌", "참변", "학대", "마약", "도박", "숨지", "치어", "치여", "흉기", "살해", "투신"]
BLOCK_WORDS = list(dict.fromkeys(BLOCK_WORDS + POLITICS_WORDS + SCANDAL_WORDS))
MEDIA_SUFFIX = ("일보", "신문", "뉴스", "방송", "TV", "tv")

# ------------------------------------------------------------------ 공통

_lock = threading.Lock()
JOB = {"running": False, "log": [], "result": None, "error": None, "stage": "", "pct": 0}


def log(msg):
    stamp = datetime.now(KST).strftime("%H:%M:%S")
    with _lock:
        JOB["log"].append(f"[{stamp}] {msg}")
    print(f"[{stamp}] {msg}", flush=True)


def progress(stage, pct):
    with _lock:
        JOB["stage"], JOB["pct"] = stage, int(pct)


# API_키.md: 사용자가 키를 적어 두는 개인 파일. 프로그램 폴더나 저장 폴더에 두면 실행할 때 읽어서 설정에 기억함.
# (AI에게 보내는 작가 지침·블로그 기억과는 별개 파일이며, 배포 압축 파일에도 넣지 않음)
KEY_FILE_NAMES = ("API_키.md", "api_keys.md")
KEY_ALIASES = {
    "gemini_api_key": ("gemini", "구글", "google", "gemini api", "gemini_api_key", "google api"),
    "anthropic_api_key": ("claude", "anthropic", "클로드", "claude api", "anthropic_api_key"),
    "searchad_api_key": ("검색광고 api key", "검색광고 액세스라이선스", "searchad_api_key"),
    "searchad_secret": ("검색광고 secret", "검색광고 비밀키", "searchad_secret"),
    "searchad_customer_id": ("검색광고 customer id", "customer id", "searchad_customer_id"),
    "naver_client_id": ("api hub client id", "네이버 client id", "client id", "naver_client_id"),
    "naver_client_secret": ("api hub client secret", "네이버 client secret", "client secret", "naver_client_secret"),
    "kakao_rest_key": ("카카오", "kakao", "kakao_rest_key"),
}


def read_key_file():
    found = {}
    for d in (Path(__file__).parent, DATA):
        for name in KEY_FILE_NAMES:
            p = d / name
            if not p.exists():
                continue
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    m = re.match(r"^\s*[-*]?\s*([^:=]+?)\s*[:=]\s*`?([^`\s]+)`?\s*$", line)
                    if not m:
                        continue
                    label, val = m.group(1).strip().lower(), m.group(2).strip()
                    if len(val) < 6 or "여기에" in val or "붙여" in val:
                        continue
                    for key, names in KEY_ALIASES.items():
                        if label in names or any(label == n for n in names):
                            found[key] = val
                            break
            except Exception as e:
                print(f"{name} 읽기 실패:", e)
    return found


_cfg_lock = threading.Lock()


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception as e:
            print("config.json 읽기 실패:", e)
    keys = read_key_file()
    changed = {k: v for k, v in keys.items() if cfg.get(k) != v}
    if changed:  # 키 파일 내용을 설정에 기억 (다음부터는 파일이 없어도 유지)
        cfg.update(changed)
        try:
            DATA.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            print("※ API_키.md에서 키를 읽어 기억했어요: " + ", ".join(changed))
        except Exception:
            pass
    if cfg.get("ai_provider") in ("gemini", "claude", "gemini_cli"):  # 유료 API 폐지(v42) · 개인 계정 Gemini CLI 중단 → Antigravity(v43)
        cfg["ai_provider"] = "antigravity"
    if cfg.get("ai_default_v", 0) < 2:  # v39: 기본 AI를 Gemini로 (예전 기본값 Claude Max였던 설치본도 한 번 전환)
        if cfg.get("ai_provider") in ("claude_code", None, ""):
            cfg["ai_provider"] = "antigravity"
        cfg["ai_default_v"] = 2
        try:
            DATA.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    if cfg.get("scale") not in SCALES:
        cfg["scale"] = "보통"
    return cfg


def save_config(cfg):
    DATA.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def has_naver(cfg):
    return bool(cfg.get("naver_client_id") and cfg.get("naver_client_secret"))


def has_searchad(cfg):
    return bool(cfg.get("searchad_api_key") and cfg.get("searchad_secret") and cfg.get("searchad_customer_id"))


# 네이버 검색·데이터랩 API는 2026년 7월 31일부터 신규 신청을 NAVER API HUB(네이버 클라우드)로만 받습니다.
# HUB 키를 먼저 시도하고, 예전 developers.naver.com 키라면 기존 주소로 자동 전환합니다.
NAVER_ENDPOINTS = {
    "hub": {"blog": "https://naverapihub.apigw.ntruss.com/search/v1/blog",
            "kin": "https://naverapihub.apigw.ntruss.com/search/v1/kin",
            "trend": "https://naverapihub.apigw.ntruss.com/search-trend/v1/search"},
    "legacy": {"blog": "https://openapi.naver.com/v1/search/blog.json",
               "kin": "https://openapi.naver.com/v1/search/kin.json",
               "trend": "https://openapi.naver.com/v1/datalab/search"},
}
_naver_mode = {"mode": None}


def naver_headers(cfg, mode):
    if mode == "hub":
        return {"X-NCP-APIGW-API-KEY-ID": cfg["naver_client_id"], "X-NCP-APIGW-API-KEY": cfg["naver_client_secret"]}
    return {"X-Naver-Client-Id": cfg["naver_client_id"], "X-Naver-Client-Secret": cfg["naver_client_secret"]}


def naver_call(cfg, api, params=None, body=None):
    """api: blog | kin | trend. 처음 성공한 방식(HUB/기존)을 기억해 이후 호출에 사용."""
    modes = [_naver_mode["mode"]] if _naver_mode["mode"] else ["hub", "legacy"]
    last = None
    for mode in modes:
        url = NAVER_ENDPOINTS[mode][api]
        try:
            if body is None:
                res = json.loads(http_get(url + "?" + urllib.parse.urlencode(params), naver_headers(cfg, mode)))
            else:
                res = http_post_json(url, body, naver_headers(cfg, mode))
            _naver_mode["mode"] = mode
            bump("trend" if api == "trend" else "search")
            return res
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (401, 403, 404):
                raise
        except urllib.error.URLError as e:
            last = e
    raise last


def kakao_blog_total(cfg, kw):
    """다음(카카오) 블로그 검색 결과 수."""
    url = "https://dapi.kakao.com/v2/search/blog?" + urllib.parse.urlencode({"query": kw, "size": 1})
    res = json.loads(http_get(url, {"Authorization": f"KakaoAK {cfg['kakao_rest_key']}"}))
    return int(res.get("meta", {}).get("total_count", 0))


def _open(req, timeout=12, retries=3):
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < retries - 1:  # 너무 빠르면 잠시 쉬고 재시도
                time.sleep(1.5 * (i + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if i < retries - 1:
                time.sleep(1)
                continue
            raise


def http_get(url, headers=None, timeout=12):
    return _open(urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})}), timeout)


def http_post_json(url, body, headers=None, timeout=12):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"User-Agent": UA, "Content-Type": "application/json", **(headers or {})})
    return json.loads(_open(req, timeout))


def strip_tags(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    for a, b in (("&quot;", '"'), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#39;", "'"), ("&apos;", "'")):
        s = s.replace(a, b)
    return s.strip()


def norm(s):
    return re.sub(r"\s+", "", s or "").lower()


def season_of(month):
    return {3: "봄", 4: "봄", 5: "봄", 6: "여름", 7: "여름", 8: "여름", 9: "가을", 10: "가을"}.get(month, "겨울")


# 제외어가 들어 있어도 생활 정보인 낱말 (예: '자동차 검사'의 검사 ≠ 검찰 검사)
BLOCK_SAFE = ["자동차 검사", "자동차검사", "정기검사", "종합검사", "건강검사", "수면다원검사", "검사 예약", "검사비", "내시경 검사",
              "화재보험", "사고이력", "정부 지원", "정부지원금", "정부 바우처", "보험처리", "교통사고 합의금", "교통사고 보험처리", "교통사고 보험", "정부24", "정부 창업지원금", "정부지원"]


def is_blocked(text):
    t = text or ""
    for w in sorted(BLOCK_SAFE, key=len, reverse=True):   # 긴 말부터 지워야 '교통사고 보험처리'가 통째로 빠짐
        t = t.replace(w, " ")
    return any(w in t for w in BLOCK_WORDS) or (text or "").endswith(MEDIA_SUFFIX)


def has_hangul(text):
    return bool(re.search(r"[가-힣]", text or ""))


def trend_blocked(t):
    """키워드 또는 연결된 뉴스 제목 중 하나라도 정치·사건사고 단어가 있으면 제외."""
    return is_blocked(t.get("keyword", "")) or any(is_blocked(n.get("title", "")) for n in t.get("news", []))


def korean_trend(t):
    """구글 트렌드 한국 피드에 섞여 들어오는 외국어 항목 제외 (키워드나 관련 기사에 한글이 있어야 함)."""
    return has_hangul(t.get("keyword")) or any(has_hangul(n.get("title")) for n in t.get("news", [])[:2])


def is_sentence(text):
    t = text.replace(" ", "")
    return bool(re.search(r"(다|요|네|까|죠|해|라)$", t)) and not t.endswith(("방법", "만들기"))


def looks_like_name(x, head):
    """'김장'→'김장훈'처럼 씨앗 뒤에 한 글자만 붙은 건 사람 이름일 가능성이 높아 제외."""
    t = x.replace(" ", "")
    return t.startswith(head) and len(t) == len(head) + 1 and "가" <= t[-1] <= "힣"


def josa(word, a, b):
    """받침 유무에 따라 조사 선택 (은/는, 이/가, 을/를)."""
    ch = (word or " ").strip()[-1:]
    if "가" <= ch <= "힣":
        return a if (ord(ch) - 0xAC00) % 28 else b
    return b if ch.isalpha() else a


# ------------------------------------------------------------------ 데이터 소스

def naver_autocomplete(q):
    url = "https://ac.search.naver.com/nx/ac?" + urllib.parse.urlencode({
        "q": q, "con": 1, "frm": "nv", "ans": 2, "r_format": "json", "r_enc": "UTF-8",
        "r_unicode": 0, "t_koreng": 1, "run": 2, "rev": 4, "q_enc": "UTF-8", "st": 100})
    d = json.loads(http_get(url, {"Referer": "https://www.naver.com/"}))
    items = d.get("items") or [[]]
    return [it[0] for it in items[0] if it and isinstance(it[0], str)]


def parse_google_trends_rss(xml_text):
    root = ET.fromstring(xml_text)
    out = []
    for item in root.iter():
        if not item.tag.endswith("item"):
            continue
        row = {"keyword": "", "traffic": "", "news": []}
        for ch in item:
            tag = ch.tag.split("}")[-1]
            if tag == "title":
                row["keyword"] = (ch.text or "").strip()
            elif tag == "approx_traffic":
                row["traffic"] = (ch.text or "").strip()
            elif tag == "news_item":
                n = {}
                for g in ch:
                    gt = g.tag.split("}")[-1]
                    if gt == "news_item_title":
                        n["title"] = strip_tags(g.text)
                    elif gt == "news_item_source":
                        n["source"] = (g.text or "").strip()
                    elif gt == "news_item_url":
                        n["url"] = (g.text or "").strip()
                if n.get("title"):
                    row["news"].append(n)
        if row["keyword"]:
            out.append(row)
    return out


def fetch_google_trends():
    return parse_google_trends_rss(http_get("https://trends.google.com/trending/rss?geo=KR"))


NEWS_STOP = set("""뉴스 기자 오늘 내일 어제 올해 내년 지난해 이번 최근 사실상 이후 이전 관련 대한 위해 통해 가운데 이유 결과 발표 공개
속보 단독 종합 영상 사진 자막뉴스 인터뷰 분석 전망 상황 문제 우려 가능성 계획 확인 시작 마감 지속 여파 영향 첫 최대 최소 국내 해외 글로벌
미국 한국 중국 일본 서울 정부 업계 시장 기업 사람 이번엔 만에 이상 이하 위한 대해 따라 있다 없다 했다 한다 된다 나선 나서 밝혀 밝혔다 직접 써보니
하락 상승 급등 급락 검토 공격 새로운 규명 위험 예방 투자 결혼 학교 증가 감소 개선 추진 도입 강화 확대 축소 논의 지원 조사 기록 역대 사상 신규
최고 최저 대표 회장 사장 CEO 출시 공식 발견 연구 개발 성공 실패 주의 경고 효과 방법 이유 비결 화제 인기 반응 근황 고백 공개해 깜짝 결국 드디어
개최 열려 열린 진행 운영 행사 참여 참가 모집 선정 수상 기념 대부분 토요일 일요일 주말 평일 오전 오후 밤부터 집에 냄새 문자 보낸 강화해야 제각각
멀티미디어 카드 한컷 수첩 단독 속보 종합 50대 60대 40대 30대 20대 10대
제자리 딴사람 경고 비교 역설 몰락 눈물 냉기 불똥 우려 실험 글쎄 파격가 원정""".split())
JOSA = ("에서는", "으로는", "에게서", "에서", "으로", "에게", "까지", "부터", "보다", "처럼", "은", "는", "을", "를", "의", "에", "와", "과")


def fetch_news_sections():
    """구글 뉴스(한국) 분야별 헤드라인. 정치·사건사고 기사는 제외."""
    out = {}
    for label in dict.fromkeys(l for _, l in NEWS_SECTIONS):
        out[label] = []
        NEWS_DROPPED[label] = 0

    def feed_url(code):
        if code.startswith("q:"):
            return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": code[2:], "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
        return f"https://news.google.com/rss/headlines/section/topic/{code}?hl=ko&gl=KR&ceid=KR:ko"

    def grab(code):
        try:
            return _open(urllib.request.Request(feed_url(code), headers={"User-Agent": UA}), timeout=8, retries=2)
        except Exception:
            return None
    ex = ThreadPoolExecutor(max_workers=6)
    futs = [ex.submit(grab, code) for code, _ in NEWS_SECTIONS]
    deadline = time.time() + 30          # 전체 30초 안에 온 것만 씀
    xmls = []
    for f in futs:
        try:
            xmls.append(f.result(timeout=max(0.1, deadline - time.time())))
        except Exception:
            xmls.append(None)
    ex.shutdown(wait=False)
    for (code, label), xml in zip(NEWS_SECTIONS, xmls):
        try:
            if not xml:
                continue
            root = ET.fromstring(xml)
            rows, dropped = [], 0
            for it in root.iter("item"):
                title = strip_tags(it.findtext("title") or "")
                src = ""
                if " - " in title:
                    title, src = title.rsplit(" - ", 1)
                if not title or not has_hangul(title):
                    continue
                if is_blocked(title):
                    dropped += 1
                    continue
                pub = ""
                try:
                    pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST).strftime("%m.%d %H:%M")
                except Exception:
                    pass
                rows.append({"title": title.strip(), "source": src.strip(), "link": (it.findtext("link") or "").strip(), "pub": pub})
            for r in rows:
                r["terms"] = clean_terms(title_terms(r["title"], 8))[:6]
            have = {norm(x["title"]) for x in out[label]}
            out[label] += [r for r in rows if norm(r["title"]) not in have]
            out[label] = out[label][:30]
            NEWS_DROPPED[label] = NEWS_DROPPED.get(label, 0) + dropped
        except Exception:
            pass
    return out


NEWS_DROPPED = {}
_news_cache = {"at": 0, "data": None}


def news_cached(refresh=False):
    if refresh or not _news_cache["data"] or time.time() - _news_cache["at"] > 600:
        _news_cache["data"] = fetch_news_sections()
        _news_cache["at"] = time.time()
    return _news_cache["data"]


def title_terms(title, limit=3):
    """기사 제목 하나에서 분석해 볼 만한 낱말 (조사 떼고, 일반어 제외)."""
    out = []
    for tok in re.findall(r"[가-힣A-Za-z0-9]{2,}", re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", title)):
        t = tok
        for j in JOSA:
            if len(t) > len(j) + 1 and t.endswith(j):
                t = t[: -len(j)]
                break
        if (len(t) < 2 or t in NEWS_STOP or t.isdigit() or is_blocked(t)
                or re.fullmatch(r"\d+(월|일|년|위|개|명|만|억|조|배|%)?", t) or t in out
                or (re.search(r"\d", t) and has_hangul(t))
                or (has_hangul(t) and t.endswith(("다", "요", "나", "져", "며", "니", "까", "게", "면", "냐", "네", "죠")))
                or (has_hangul(t) and len(t) >= 3 and t.endswith(("고", "라", "럴", "던", "는데")))):
            continue
        out.append(t)
    out.sort(key=lambda t: -(len(t) >= 3 or bool(re.fullmatch(r"[A-Za-z0-9]+", t))))
    return out[:limit]


def headline_terms(rows, limit=3):
    """여러 기사에 반복해서 나오는 핵심어 (블로그 씨앗용)."""
    df = {}
    first = {}
    for r in rows:
        for t in set(r.get("terms") or title_terms(r["title"], 6)):
            df[t] = df.get(t, 0) + 1
            first.setdefault(t, r)
    # 여러 기사에 반복된 말 중, 고유명사처럼 보이는 것(세 글자 이상 또는 영문) 우선
    weight = lambda t: df[t] * (1.6 if len(t) >= 3 or re.fullmatch(r"[A-Za-z0-9]+", t) else 1.0)
    ranked = sorted([t for t, c in df.items() if c >= 2], key=lambda t: (-weight(t), -len(t)))
    return [(t, df[t], first[t]) for t in ranked[:limit]]


def fetch_signal_bz():
    data = json.loads(http_get("https://api.signal.bz/news/realtime"))
    return [{"rank": x.get("rank"), "keyword": x.get("keyword")} for x in data.get("top10", []) if x.get("keyword")]


def searchad_volumes(cfg, keywords):
    """네이버 검색광고 키워드도구: 월간 검색수(PC+모바일)와 경쟁 정도. 5개씩 조회."""
    out = {}
    uri = "/keywordstool"

    def qcnt(v):
        if isinstance(v, (int, float)):
            return int(v)
        return 5 if "<" in str(v) else int(re.sub(r"\D", "", str(v)) or 0)  # "< 10" 은 5로 간주

    for i in range(0, len(keywords), 5):
        batch = [k.replace(" ", "") for k in keywords[i:i + 5]]
        ts = str(int(time.time() * 1000))
        sig = base64.b64encode(hmac.new(cfg["searchad_secret"].encode(), f"{ts}.GET.{uri}".encode(),
                                        hashlib.sha256).digest()).decode()
        url = "https://api.searchad.naver.com" + uri + "?" + urllib.parse.urlencode(
            {"hintKeywords": ",".join(batch), "showDetail": 1})
        bump("searchad")
        res = json.loads(http_get(url, {"X-Timestamp": ts, "X-API-KEY": cfg["searchad_api_key"],
                                        "X-Customer": str(cfg["searchad_customer_id"]), "X-Signature": sig}))
        wanted = {norm(b) for b in batch}
        for row in res.get("keywordList", []):
            k = norm(row.get("relKeyword"))
            if k in wanted:
                pc, mo = qcnt(row.get("monthlyPcQcCnt")), qcnt(row.get("monthlyMobileQcCnt"))
                clk = (row.get("monthlyAvePcClkCnt") or 0) + (row.get("monthlyAveMobileClkCnt") or 0)
                out[k] = {"pc": pc, "mobile": mo, "total": pc + mo, "comp": row.get("compIdx"),
                          "ad_depth": row.get("plAvgDepth"), "ad_clicks": round(clk, 1) if isinstance(clk, (int, float)) else None}
        time.sleep(0.15)
    return out


def searchad_bids(cfg, keywords, position=3, device="MOBILE"):
    """네이버 검색광고 예상 입찰가: 모바일 광고 3위에 노출되려면 광고주가 클릭당 얼마를 내야 하는지(원). 고단가의 직접 근거."""
    out = {}
    uri = "/estimate/average-position-bid/keyword"
    for i in range(0, len(keywords), 20):
        batch = [k.replace(" ", "") for k in keywords[i:i + 20]]
        ts = str(int(time.time() * 1000))
        sig = base64.b64encode(hmac.new(cfg["searchad_secret"].encode(), f"{ts}.POST.{uri}".encode(),
                                        hashlib.sha256).digest()).decode()
        bump("searchad")
        res = http_post_json("https://api.searchad.naver.com" + uri,
                             {"device": device, "items": [{"key": b, "position": position} for b in batch]},
                             {"X-Timestamp": ts, "X-API-KEY": cfg["searchad_api_key"],
                              "X-Customer": str(cfg["searchad_customer_id"]), "X-Signature": sig})
        for row in res.get("estimate", []):
            if row.get("bid") is not None:
                out[norm(row.get("keyword"))] = int(row["bid"])
        time.sleep(0.15)
    return out


def blog_stats(cfg, kw, today):
    """전체 글 수 + 상위 글 3개 (정확도순), 최근 7일 새 글 수 (최신순 100개 중)."""
    a = naver_call(cfg, "blog", {"query": kw, "display": 3, "sort": "sim"})
    top = [{"title": strip_tags(it.get("title")), "link": it.get("link"), "blogger": it.get("bloggername"),
            "date": it.get("postdate")} for it in a.get("items", [])]
    b = naver_call(cfg, "blog", {"query": kw, "display": 100, "sort": "date"})
    cutoff = (today - timedelta(days=7)).strftime("%Y%m%d")
    recent = sum(1 for it in b.get("items", []) if (it.get("postdate") or "0") >= cutoff)
    out = {"total": int(a.get("total", 0)), "recent7": recent, "recent7_capped": recent >= 100, "top": top}
    try:  # 지식iN 질문 수: 궁금해하는 사람이 많다는 신호
        out["kin_total"] = int(naver_call(cfg, "kin", {"query": kw, "display": 1}).get("total", 0))
    except Exception:
        out["kin_total"] = None
    if cfg.get("kakao_rest_key"):
        try:
            out["daum_total"] = kakao_blog_total(cfg, kw)
        except Exception:
            out["daum_total"] = None
    return out


ANCHOR = "유튜브"  # 데이터랩 값은 요청 안에서만 비교 가능해서, 매 요청에 같은 기준 키워드를 넣어 서로 비교


def datalab_trends(cfg, keywords, today):
    end = today - timedelta(days=1)
    start = end - timedelta(days=27)
    out = {}
    for i in range(0, len(keywords), 4):
        batch = keywords[i:i + 4]
        body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "timeUnit": "date",
                "keywordGroups": [{"groupName": "__anchor__", "keywords": [ANCHOR]}] +
                                 [{"groupName": k, "keywords": [k]} for k in batch]}
        res = naver_call(cfg, "trend", body=body)
        series = {g["title"]: [d["ratio"] for d in g.get("data", [])] for g in res.get("results", [])}
        anchor = series.get("__anchor__") or []
        a_avg = sum(anchor) / len(anchor) if anchor else 0
        for k in batch:
            vals = series.get(k) or []
            if len(vals) < 14:
                continue
            r, p = sum(vals[-7:]) / 7, sum(vals[:-7]) / len(vals[:-7])
            out[norm(k)] = {"growth": round((r - p) / p * 100, 1) if p else (100.0 if r else 0.0),
                            "index": round(sum(vals) / len(vals) / a_avg * 100, 2) if a_avg else None}
        time.sleep(0.1)
    return out, f"{start.isoformat()}~{end.isoformat()}"



# ------------------------------------------------------------------ 기록·사용량

def recent_keywords(days=3):
    kws = set()
    if not HISTORY.exists():
        return kws
    cutoff = datetime.now(KST) - timedelta(days=days)
    for p in sorted(HISTORY.glob("*.json"), reverse=True)[:10]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if datetime.fromisoformat(d["generated_at"]) < cutoff:
                continue
            for t in d.get("topics", []):
                kws.update(norm(it["keyword"]) for it in t.get("items", [])[:3])
        except Exception:
            pass
    return kws


def list_history():
    items = []
    if HISTORY.exists():
        for p in sorted(HISTORY.glob("*.json"), reverse=True)[:90]:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                items.append({"id": p.stem, "generated_at": d["generated_at"], "date": d.get("date"),
                              "count": d["stats"]["items"], "topics": len(d.get("selected_topics", []))})
            except Exception:
                pass
    return items


_usage_lock = threading.Lock()


def bump(api, n=1):
    """API별 오늘 호출 수 기록 (네이버 한도: 검색 25,000회/일, 검색어 트렌드 1,000회/일)."""
    with _usage_lock:
        try:
            u = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
        except Exception:
            u = {}
        day = datetime.now(KST).date().isoformat()
        if u.get("date") != day:
            u = {"date": day}
        u[api] = u.get(api, 0) + n
        DATA.mkdir(parents=True, exist_ok=True)
        USAGE_PATH.write_text(json.dumps(u), encoding="utf-8")


def usage_today():
    try:
        u = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
        if u.get("date") == datetime.now(KST).date().isoformat():
            return u
    except Exception:
        pass
    return {}


# ------------------------------------------------------------------ 제목·기획안

def classify(q):
    for words, titles, outline, add_year in INTENTS:
        for w in words:
            if q.endswith(w) or f" {w}" in q or q.replace(" ", "").endswith(w.replace(" ", "")):
                return words[0], titles, outline, add_year
    return None, *DEFAULT_INTENT


def make_titles(q, year, cat):
    key, titles, outline, add_year = classify(q)
    if key is None and EVERGREEN_META.get(norm(q), {}).get("type") == "생활해결":
        _, titles, outline, add_year = next(x for x in INTENTS if x[0][0] == "방법")   # 생활 문제 해결형은 방법 안내 틀
    elif key is None and cat in PRODUCT_CATS:
        titles, outline, add_year = PRODUCT_INTENT
    out = []
    last = q.split()[-1] if q.split() else q
    for tpl in titles:
        shown = f"{year} {q}" if add_year and "{y}" not in tpl and not re.search(r"(19|20)\d\d", q) else q
        t = tpl.format(q=shown, y=year)
        # 틀의 첫 낱말이 키워드 끝말과 같으면 빼기: '콘서트 일정 일정·장소' → '콘서트 일정·장소'
        t = re.sub(re.escape(shown) + r" " + re.escape(last) + r"([·\s,])", shown + r"\1", t, count=1)
        t = re.sub(r"(\S+) \1(?=[\s·,]|$)", r"\1", t)  # 같은 낱말 연속 반복 제거
        out.append(t)
    outline = [o.format(y=year) if "{y}" in o else o for o in outline]
    return out, outline, key


def make_brief(it, cat, sub, today):
    """키워드 하나에 대한 네이버 블로그 글 기획안 (문장)."""
    kw, m, y = it["keyword"], it["metrics"], today.year
    key = it["intent"]
    news_style = it["kind"] == "news" and not key
    if news_style:
        reader, what, promise = news_brief_of(it.get("src", {}).get("section"))[:3]
    elif it["kind"] == "trend" and norm(kw) == norm(it["seed"]):
        reader, what, promise = TREND_INFO
    elif key:
        reader, what, promise = INTENT_INFO[key]
    elif cat in PRODUCT_CATS:
        reader, what, promise = PRODUCT_INFO
    else:
        reader, what, promise = DEFAULT_INFO
        reader = reader.format(kw=kw)

    # 왜 지금
    why = []
    src = it.get("src", {})
    if it["kind"] == "trend":
        why.append(f"오늘 구글 트렌드 급상승 검색어에 '{it['seed']}'{josa(it['seed'], '이', '가')} 올랐습니다"
                   + (f"(검색 {src['traffic']})" if src.get("traffic") else "") + ".")
        if src.get("news"):
            why.append(f"관련 기사: “{src['news']}”.")
    elif it["kind"] == "season":
        dl = src.get("days_left")
        if dl is not None:
            why.append(f"'{it['seed']}'까지 {dl}일 남아, 지금부터 검색이 몰리는 시기입니다." if dl > 0
                       else f"오늘이 '{it['seed']}'입니다. 당일 검색이 가장 많습니다.")
        else:
            why.append(f"{src.get('month', today.month)}월은 '{it['seed']}' 관련 검색이 몰리는 시기입니다.")
    elif it["kind"] == "news":
        if src.get("news_list"):  # 키워드와 낱말이 가장 많이 겹치는 기사를 예시로
            words = [w for w in kw.split() if norm(w) != norm(it["seed"]) and len(w) >= 2]
            hit = lambda r: sum(norm(w) in norm(r["title"]) for w in words)
            best = max(src["news_list"], key=hit)
            if hit(best) or norm(kw) == norm(it["seed"]):
                src = {**src, "news": best["title"], "news_source": best["source"]}
            else:
                src = {**src, "news": ""}
        why.append(f"오늘 {src.get('section', '')} 뉴스에서 '{it['seed']}' 관련 보도가 "
                   + (f"{src['count']}건 이상 나왔습니다." if src.get("count", 2) >= 2 else "나왔습니다.")
                   + (f" 기사: “{src['news']}”" + (f"({src['news_source']})" if src.get("news_source") else "") + "." if src.get("news") else "")
                   + " 뉴스로 관심이 생긴 사람들이 쉽게 풀어 쓴 설명 글을 찾는 시점입니다.")
    elif it["kind"] == "civic":
        en = date.fromisoformat(src["end"])
        if src.get("days_to_start", 0) > 0:
            why.append(f"'{src['civic']}' 시기가 {src['days_to_start']}일 뒤 시작됩니다. {src['note']} 시작 전에 미리 올려 두면 검색이 몰릴 때 노출되기 좋습니다.")
        else:
            why.append(f"지금은 '{src['civic']}' 기간입니다. {src['note']} 마감({en.month}월 {en.day}일)까지 {src['days_left']}일 남아, 마감 전 확인하려는 사람이 많은 때입니다.")
    elif it["kind"] == "watch":
        why.append(f"관심 키워드 '{src.get('watch', it['seed'])}'에서 '{kw}' 검색이 나타나고 있습니다. "
                   "일정이 발표되기 전후로 검색이 몰리는 유형이라, 먼저 써 두면 상위 노출을 선점하기 좋습니다.")
    elif it["kind"] == "preempt":
        why.append(f"'{kw}'{josa(kw, '은', '는')} 다가오는 일정을 미리 찾는 검색어입니다. "
                   "날짜가 가까워질수록 검색이 늘어나는 유형이라 미리 써 두면 유리합니다.")
    elif it["kind"] == "mine":
        why.append(f"내 블로그에 사람을 데려온 검색어 '{it['seed']}'에서 넓힌 키워드입니다. "
                   "이미 검색 노출이 되는 주제라, 이어지는 글을 쓰면 유입을 늘리기 쉽습니다.")
    else:
        eg = src.get("evergreen") or {}
        if eg.get("verdict") in ("상시", "대체로 상시"):
            why.append(f"'{it['seed']}'{josa(it['seed'], '은', '는')} 상시 키워드 검증을 통과했습니다: {eg.get('reason', '')}"
                       " 유행을 타지 않아 한 번 써 두면 오래 유입이 들어오는 글감입니다.")
        else:
            why.append(f"'{it['seed']}'{josa(it['seed'], '은', '는')} 계절과 상관없이 꾸준히 찾는 주제입니다.")
    if m.get("growth") is not None:
        g = m["growth"]
        why.append(f"네이버 검색어 트렌드 기준 최근 7일 검색량이 직전 3주보다 {abs(g):.0f}% {'늘었' if g >= 0 else '줄었'}습니다.")
    if m.get("volume"):
        why.append(f"월간 검색수는 약 {m['volume']:,}회입니다.")

    # 무엇을
    words_kw = kw.split()
    # 연관어 정리: 지난 달 키워드, 끝말이 잘려 다른 뜻이 된 것('용인시 축제'→'용인시 축산') 제외
    good_rel = [r for r in it.get("related", []) if norm(r) != norm(kw) and not past_month(r)
                and (len(words_kw) < 2 or norm(words_kw[-1]) in norm(r) or norm(kw) in norm(r))]
    it = {**it, "related": good_rel}
    rel = good_rel[:2]
    content = f"{what}{josa(what, '을', '를')} 한 글에 정리합니다."
    if rel:
        content += " 함께 많이 찾는 " + ", ".join(f"'{r}'" for r in rel) + "까지 다루면 검색 유입을 넓힐 수 있습니다."

    # 어떻게 차별화
    total, rec = m.get("blog_total"), m.get("recent7")
    narrower = [r for r in it.get("related", []) if norm(kw) in norm(r) and len(norm(r)) > len(norm(kw))]
    longer = min(narrower, key=len) if narrower else None
    if total is None:
        angle = "경쟁 데이터가 없습니다(설정에서 네이버 키를 넣으면 표시). 직접 찍은 사진과 경험담 위주로 쓰는 것을 권장합니다."
    elif total < 30_000:
        angle = f"관련 블로그 글이 {total:,}건으로 적은 편이라, 기본 정보만 충실히 정리해도 상위 노출을 노려볼 만합니다."
    elif total < 300_000:
        angle = f"관련 글이 {total:,}건으로 경쟁은 보통입니다. 직접 찍은 사진, 날짜가 들어간 최신 정보로 차별화하세요."
    else:
        angle = f"관련 글이 {total:,}건으로 경쟁이 치열합니다."
        angle += (f" '{kw}'보다 범위를 좁힌 '{longer}'{josa(longer, '을', '를')} 제목 앞에 두는 편이 유리합니다." if longer
                  else " 지역·대상·상황을 좁혀 제목을 잡는 편이 유리합니다.")
    if rec is not None and rec >= 30:
        angle += f" 최근 7일에만 새 글이 {'100건 이상' if m.get('recent7_capped') else f'{rec}건'} 올라왔습니다. 지금 한창 쓰이는 주제라 빨리 올리는 게 좋습니다."

    flag = (EVERGREEN_META.get(norm(kw)) or EVERGREEN_META.get(norm(it["seed"])) or {}).get("flag")
    if it["kind"] == "civic":
        flag = "ymyl" if src.get("ymyl") else None
        angle += " 날짜·금액은 그해 공식 공고(기관 홈페이지)로 확인하고, 글에 '○월 ○일 기준'을 적어 두세요."
    if flag in FLAG_TEXT:
        angle += " " + FLAG_TEXT[flag]
    titles, outline, _ = make_titles(kw, y, cat)
    if it["kind"] == "trend" and norm(kw) == norm(it["seed"]):
        titles = [f"{kw} 뭐길래 다들 찾을까? 핵심만 정리", f"요즘 화제인 {kw}, 무슨 일인지 정리했어요"]
        outline = ["무슨 일인지", "왜 화제인지", "알아두면 좋은 점"]
    if news_style:
        nb = news_brief_of(src.get("section"))
        tpls = nb[3]
        if norm(kw) != norm(it["seed"]) and "무슨 일" in tpls[0]:
            tpls = ["{q} 쉽게 정리, 꼭 알아둘 핵심", tpls[1], "{y} {q} 한눈에 정리"]
        titles = [re.sub(r"(\S+) \1(?=[\s·,?]|$)", r"\1", t.format(q=kw, y=y)) for t in tpls]
        outline = list(nb[4])
    full_outline = [f"들어가며: 요즘 '{kw}' 많이 찾는 이유"] + outline + ["마무리: 한눈에 요약"]

    season_line = {"trend": "요즘 여기저기서 이야기가 많아서", "season": f"{today.month}월이 되니 주변에서도 많이 물어보셔서",
                   "evergreen": "늘 궁금해하시는 분들이 많아서",
                   "mine": "이웃분들이 많이 물어보셔서", "news": "뉴스를 보고 궁금해하시는 분들이 많아서"}.get(it["kind"], "궁금해하시는 분들이 많아서")
    intro = (f"요즘 '{kw}' 찾아보시는 분들 많으시죠? {season_line} 직접 알아보고 정리해 봤어요. "
             f"이 글 하나로 {promise}까지 한 번에 확인해 보세요.")
    tags = []
    for t in [kw] + it.get("related", []) + [it["seed"]] + ([sub] if sub in TOPICS else []):
        t = "#" + re.sub(r"[^\w가-힣]", "", t.replace(" ", ""))
        if len(t) > 1 and t not in tags:
            tags.append(t)
    if news_style:
        sec_name = it.get("src", {}).get("section", "")
        one_line = (f"오늘 {sec_name} 뉴스 ‘{it['seed']}’ 이슈를 " if norm(kw) != norm(it["seed"]) else f"오늘 {sec_name} 뉴스에 나온 ‘{kw}’, ") + \
                   f"{promise} 중심으로 쉽게 풀어 주는 글"
    elif reader.startswith("'"):  # 의도가 뚜렷하지 않은 키워드
        one_line = f"'{kw}'{josa(kw, '을', '를')} 찾는 사람이 궁금해할 {promise}{josa(promise, '을', '를')} 한 번에 정리하는 글"
    else:
        one_line = f"{reader}{josa(reader, '을', '를')} 위해 {promise}{josa(promise, '을', '를')} 정리하는 글"
    return {"one_line": one_line, "why": " ".join(why), "reader": reader,
            "content": content, "angle": angle, "titles": titles, "outline": full_outline,
            "intro": intro, "tags": tags[:10]}


# ------------------------------------------------------------------ 분석 파이프라인

def black_friday(y):
    d = date(y, 11, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7 + 21)  # 11월 넷째 금요일


# (행사 이름 패턴, 연도 → 날짜). 행사가 지나면 '날짜·선물·준비물'처럼 행사 전에 찾는 키워드는 뺌
PAST_EVENTS = [
    (r"수능|수학능력시험", lambda y: suneung_day(y)),
    (r"빼빼로", lambda y: date(y, 11, 11)),
    (r"블랙프라이데이|블프", black_friday),
    (r"크리스마스|성탄절", lambda y: date(y, 12, 25)),
    (r"동지", lambda y: date(y, 12, 22)),
    (r"할로윈|핼러윈", lambda y: date(y, 10, 31)),
    (r"추석", lambda y: None), (r"설날", lambda y: None),
]
PRE_EVENT_WORDS = re.compile(r"날짜|언제|디데이|d-?day|D-\d|몇일|며칠|시간표|선물|도시락|준비물|응원|입실|예약|사전|카운트다운|전날|당일|이벤트|세일|할인|선물세트|트리|케이크 예약|코디|데이트")


def past_event(kw, today=None):
    """이미 지난 행사(최근 45일)의 '행사 전' 키워드인지. 예: 수능 끝난 뒤의 '2026 수능 날짜'."""
    today = today or datetime.now(KST).date()
    for pat, fn in PAST_EVENTS:
        if not re.search(pat, kw):
            continue
        d = fn(today.year)
        if not d or not (0 < (today - d).days <= 45):
            continue
        years = [int(x) for x in re.findall(r"(20\d\d)", kw)]
        if any(yy > today.year for yy in years):  # '2027 수능 날짜'처럼 다음 해 것은 유지
            continue
        if PRE_EVENT_WORDS.search(kw) or norm(kw) in {norm(pat.split("|")[0]), norm(f"{today.year} " + pat.split("|")[0])}:
            return True
    return False


def season_seeds_for(today):
    out = []
    months = [today.month] + ([today.month % 12 + 1] if today.day >= 15 else [])
    for mo in months:
        for kw, cats, fixed in SEASON_SEEDS[mo]:
            days_left = None
            if past_event(kw, today):   # 수능·빼빼로데이처럼 이미 지난 행사의 씨앗은 쓰지 않음
                continue
            if fixed:
                yy = today.year + (1 if fixed[0] < today.month else 0)
                days_left = (date(yy, fixed[0], fixed[1]) - today).days
                if days_left < 0 or days_left > 40:
                    continue
            out.append({"seed": kw, "cats": cats, "days_left": days_left, "month": mo})
    return out


def urgency_of(kind, src):
    if kind == "civic":
        left = src.get("days_left", 30)
        return "오늘" if left <= 7 else "이번주" if left <= 21 else "이번달"
    dl = src.get("days_left")
    if dl is not None:
        return "오늘" if dl <= 3 else "이번주" if dl <= 10 else "이번달"
    return {"trend": "오늘", "news": "오늘", "season": "이번달", "mine": "이번주", "watch": "이번주", "preempt": "이번주"}.get(kind, "상시")


def build_seed_plan(cfg, today, trends, news=None):
    m, s, y = today.month, season_of(today.month), today.year
    topics = [t for t in cfg.get("topics", []) if t in TOPICS]
    plan = []  # (topic, topic, seed, kind, src)
    for t in topics:
        for sd in TOPICS[t]:
            plan.append((t, t, sd.format(m=m, s=s, y=y), "evergreen", {}))
    y2 = y + (1 if m >= 10 else 0)
    if cfg.get("include_issues", True):
        for c in civic_active(today):
            for sd in c["seeds"]:
                plan.append((CIVIC_TOPIC, CIVIC_TOPIC, sd.format(y=y, y2=y2), "civic",
                             {"civic": c["name"], "note": c["note"], "end": c["end_date"].isoformat(),
                              "start": c["start_date"].isoformat(), "days_left": c["days_left"],
                              "days_to_start": c["days_to_start"], "ymyl": bool(c.get("ymyl"))}))
    for t, kw, r in evergreen_seeds(topics, today):
        plan.append((t, t, kw, "evergreen", {"evergreen": {k: r.get(k) for k in ("verdict", "reason", "volume", "cv", "yoy") if r.get(k) is not None}}))
    for x in season_seeds_for(today):
        targets = set()
        for c in x["cats"]:
            targets.update([c] + SEASON_EXTRA.get(c, []))
        for t in targets & set(topics):
            plan.append((t, t, x["seed"], "season", {"days_left": x["days_left"], "month": x["month"]}))
    for kw in cfg.get("my_keywords", [])[:30]:
        kw = kw.strip()
        if kw and not is_blocked(kw):
            plan.append((MINE_TOPIC, MINE_TOPIC, kw, "mine", {}))
    if cfg.get("include_issues", True):
        for t in [t for t in trends if korean_trend(t) and len(norm(t["keyword"])) > 2]:
            if trend_blocked(t):
                continue
            plan.append((ISSUE_TOPIC, ISSUE_TOPIC, t["keyword"], "trend",
                         {"traffic": t.get("traffic"), "news": t["news"][0]["title"] if t.get("news") else "",
                          "news_source": t["news"][0].get("source") if t.get("news") else ""}))
        for label, rows in (news or {}).items():
            hts = headline_terms(rows, 40)
            df = {t: c for t, c, _ in hts}
            seeds = []  # (씨앗, 건수, 대표 기사, 관련 기사들)
            for term, cnt, row in hts[:3]:
                seeds.append((term, cnt, row, [r for r in rows if term in (r.get("terms") or [])]))
            # 기사별로 고른 키워드('용인시 축제', '일경험 드림')도 씨앗으로: 한 단어에 몰리지 않게
            for r in rows[:12]:
                if len(seeds) >= 6:
                    break
                k = news_keyword(r["title"], r.get("terms"), label, df)
                if k and len(norm(k)) >= 2 and not is_blocked(k) and all(norm(k) != norm(x[0]) for x in seeds):
                    seeds.append((k, 1, r, [r]))
            for term, cnt, row, same in seeds:
                plan.append((news_topic(label), news_topic(label), term, "news",
                             {"section": label, "count": cnt, "news": row["title"], "news_source": row.get("source", ""),
                              "news_list": [{"title": x["title"], "source": x.get("source", ""), "link": x.get("link", "")} for x in same[:8]]}))
    return plan


def collect_candidates(plan, scale, rng, avoid):
    """자동완성 1단계 + 2단계 확장. 후보마다 노출 순위·횟수로 '자동완성 지수'를 계산."""
    cache = {}

    def fetch_all(queries, label, base_pct, span):
        queries = [q for q in dict.fromkeys(queries) if q not in cache]
        done = 0

        def job(q):
            try:
                time.sleep(rng.random() * 0.2)
                return q, naver_autocomplete(q)
            except Exception:
                return q, None

        with ThreadPoolExecutor(max_workers=4) as ex:
            for q, res in ex.map(job, queries):
                cache[q] = res
                done += 1
                if done % 10 == 0 or done == len(queries):
                    progress(f"{label} ({done}/{len(queries)})", base_pct + span * done / max(1, len(queries)))

    log(f"1단계: 씨앗 키워드 {len(set(p[2] for p in plan))}개로 네이버 자동완성 수집")
    fetch_all([p[2] for p in plan], "키워드 수집 1차", 5, 20)

    cands = {}  # norm(keyword) -> candidate
    expand = []

    def add(cat, sub, seed, kind, src, q, pos, depth, parent):
        k = norm(q)
        c = cands.get(k)
        echo = k == norm(parent)  # 검색어 자기 자신이 1순위로 나오는 건 수요 근거가 아님
        score = None if echo else max(0.0, 100 - pos * 8) * (0.85 if depth == 2 else 1.0)
        if c is None:
            cands[k] = {"keyword": q, "cat": cat, "sub": sub, "seed": seed, "kind": kind, "src": src,
                        "ac_best": score, "ac_hits": 0 if echo else 1, "depth": depth, "related": [], "parent": parent}
        else:
            if not echo:
                c["ac_hits"] += 1
                c["ac_best"] = max(c["ac_best"] or 0, score)
            # 시즌·실시간 출처가 상시보다 우선
            prio = {"trend": 3, "watch": 3, "news": 2, "mine": 2, "season": 1, "preempt": 1}
            if prio.get(kind, 0) > prio.get(c["kind"], 0):
                c.update(cat=cat, sub=sub, seed=seed, kind=kind, src=src)

    def valid(x, head):
        return ((head in x or head in x.replace(" ", "")) and not is_blocked(x) and not is_sentence(x)
                and not looks_like_name(x, head) and len(x) <= 30)

    for cat, sub, seed, kind, src in plan:
        res = cache.get(seed) or []
        head = seed.split()[0]
        sugg = [x for x in res if valid(x, head)]
        if kind == "trend" and norm(seed) not in {norm(x) for x in sugg}:
            sugg = [seed] + sugg
        for pos, x in enumerate(sugg):
            add(cat, sub, seed, kind, src, x, pos, 1, seed)
        # 관련어 기록
        for x in sugg:
            cands[norm(x)]["related"] = [r for r in sugg if norm(r) != norm(x)][:6]
        longer = [x for x in sugg if norm(x) != norm(seed)]
        for x in longer[: scale["depth2"]]:
            expand.append((cat, sub, seed, kind, src, x))

    if expand:
        log(f"2단계: 연관 검색어 {len(expand)}개로 한 단계 더 수집")
        fetch_all([e[5] for e in expand], "키워드 수집 2차 (연관어 확장)", 25, 25)
        for cat, sub, seed, kind, src, parent in expand:
            res = cache.get(parent) or []
            head = parent.split()[0]
            sugg = [x for x in res if valid(x, head) and norm(x) != norm(parent)]
            for pos, x in enumerate(sugg):
                add(cat, sub, seed, kind, src, x, pos, 2, parent)
                c = cands[norm(x)]
                if not c["related"]:
                    c["related"] = [parent] + [r for r in sugg if norm(r) != norm(x)][:5]

    ok = sum(1 for v in cache.values() if v is not None)
    for c in cands.values():
        # 이 키워드로 검색했을 때 딸려 나오는 연관 검색어 수 (많을수록 검색이 활발하다는 신호)
        kids = cache.get(c["keyword"])
        head = c["keyword"].split()[0]
        c["ac_children"] = len([x for x in kids if valid(x, head)]) if kids else None
        pos = c["ac_best"] if c["ac_best"] is not None else 55.0
        hits = min(100, c["ac_hits"] * 25)
        kid = min(100, c["ac_children"] * 10) if c["ac_children"] is not None else 50
        c["ac_index"] = round(0.6 * pos + 0.25 * hits + 0.15 * kid, 1)
        c["fresh_penalty"] = norm(c["keyword"]) in avoid
    return list(cands.values()), len(cache), ok


def percentile_map(values):
    """값 → 0~100 백분위."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return lambda v: None
    n = len(vals)

    def f(v):
        if v is None:
            return None
        lo = sum(1 for x in vals if x < v)
        eq = sum(1 for x in vals if x == v)
        return round(100 * (lo + 0.5 * eq) / n, 1)
    return f


def fit_score(it):
    """글감 적합도: 검색 의도가 뚜렷하고, 분야에 맞고, 2~4어절 롱테일일수록 블로그 글로 쓰기 좋음."""
    kw = it["keyword"]
    words = len(kw.split())
    s = 40 + (25 if it.get("intent") else 0) + (15 if any(h in kw for h in CAT_HINTS.get(it["cat"], GENERIC_HINTS)) else 0)
    s += -15 if words == 1 and len(kw) <= 4 else 15 if 2 <= words <= 4 else 5
    return max(0, min(100, s))


def score_items(items):
    """기회 점수와 계산 근거."""
    vol_p = percentile_map([math.log10(i["metrics"]["volume"] + 1) for i in items if i["metrics"].get("volume") is not None])
    blog_p = percentile_map([math.log10(i["metrics"]["blog_total"] + 1) for i in items if i["metrics"].get("blog_total") is not None])
    sat_p = percentile_map([i["metrics"]["blog_total"] / max(i["metrics"]["volume"], 10) for i in items
                            if i["metrics"].get("blog_total") is not None and i["metrics"].get("volume")])
    idx_p = percentile_map([i["metrics"].get("dl_index") for i in items if i["metrics"].get("dl_index") is not None])
    for it in items:
        mt = it["metrics"]
        parts, notes = {}, []
        # 수요
        if mt.get("volume") is not None:
            parts["demand"] = vol_p(math.log10(mt["volume"] + 1))
            notes.append(f"수요 {parts['demand']:.0f}: 월간 검색수 {mt['volume']:,}회의 전체 후보 내 백분위")
        elif mt.get("dl_index") is not None:
            parts["demand"] = idx_p(mt["dl_index"])
            notes.append(f"수요 {parts['demand']:.0f}: 데이터랩 검색 지수의 백분위")
        else:
            parts["demand"] = it["ac_index"]
            notes.append(f"수요 {parts['demand']:.0f}: 자동완성 노출 순위·노출 횟수 {it['ac_hits']}회·딸린 연관어 "
                         f"{it['ac_children'] if it['ac_children'] is not None else '?'}개로 추정 (추정)")
        # 상승세
        if mt.get("growth") is not None:
            parts["growth"] = round(max(0, min(100, (mt["growth"] + 30) / 1.3)), 1)
            notes.append(f"상승세 {parts['growth']:.0f}: 최근 7일 검색량 변화 {mt['growth']:+.0f}% (-30%→0점, +100%→100점)")
        else:
            dl = it["src"].get("days_left")
            parts["growth"] = {"trend": 80, "news": 72, "watch": 70, "preempt": 65, "mine": 65,
                               "season": 75 if dl is not None and dl <= 14 else 60}.get(it["kind"], 40)
            notes.append(f"상승세 {parts['growth']:.0f}: " + {"trend": "오늘 급상승 검색어", "season": "이달의 시즌 이슈",
                                                            "evergreen": "상시 수요 주제", "mine": "내 블로그 유입어",
                                                            "watch": "관심 키워드의 예고성 검색어", "preempt": "다가오는 일정 검색어",
                                                            "news": "오늘 분야별 뉴스에 반복 등장"}.get(it["kind"], "상시 수요 주제") + " 기준 기본값 (추정)")
        # 경쟁 (높을수록 경쟁 심함)
        if mt.get("blog_total") is not None and mt.get("volume"):
            parts["competition"] = sat_p(mt["blog_total"] / max(mt["volume"], 10))
            notes.append(f"경쟁 {parts['competition']:.0f}: 블로그 글 수 ÷ 월간 검색수 = {mt['blog_total'] / max(mt['volume'], 10):.1f}의 백분위")
        elif mt.get("blog_total") is not None:
            parts["competition"] = blog_p(math.log10(mt["blog_total"] + 1))
            notes.append(f"경쟁 {parts['competition']:.0f}: 블로그 글 {mt['blog_total']:,}건의 백분위")
        elif mt.get("comp"):
            parts["competition"] = {"높음": 80, "중간": 50, "낮음": 20}.get(mt["comp"], 50)
            notes.append(f"경쟁 {parts['competition']:.0f}: 검색광고 경쟁 정도 '{mt['comp']}'")
        parts["fit"] = fit_score(it)
        notes.append(f"글감 적합도 {parts['fit']:.0f}: " + ", ".join(
            x for x in [("검색 의도 뚜렷함" if it.get("intent") else "검색 의도 불분명"),
                        ("분야와 잘 맞음" if any(h in it["keyword"] for h in CAT_HINTS.get(it["cat"], GENERIC_HINTS)) else ""),
                        f"{len(it['keyword'].split())}어절"] if x))
        weights = {"demand": 0.35, "growth": 0.25, "competition": 0.25, "fit": 0.15}
        tot_w = sum(w for k, w in weights.items() if parts.get(k) is not None)
        s = 0.0
        for k, w in weights.items():
            if parts.get(k) is not None:
                s += (100 - parts[k] if k == "competition" else parts[k]) * w
        score = s / tot_w if tot_w else 0
        if it.get("fresh_penalty"):
            score *= 0.8
            notes.append("최근 3일 안에 상위 추천된 키워드라 20% 감점")
        it["score"] = round(score, 1)
        it["parts"] = parts
        it["score_notes"] = notes
        it["score_formula"] = ("수요 35% + 상승세 25% + (100-경쟁) 25% + 글감 적합도 15%" if "competition" in parts
                               else "수요 47% + 상승세 33% + 글감 적합도 20% (경쟁 데이터 없음, 비율 재조정)")


def measure(cfg, items, today, rng, sources, pct_from=55, pct_to=90):
    """선택된 키워드의 실측 수치를 채움 (키가 있는 만큼)."""
    for c in items:
        c.setdefault("metrics", {})
    if not items:
        return
    if has_searchad(cfg):
        progress("월간 검색수 조회", pct_from)
        log("네이버 검색광고: 월간 검색수 조회 중…")
        try:
            vols = searchad_volumes(cfg, [c["keyword"] for c in items])
            for c in items:
                v = vols.get(norm(c["keyword"]))
                if v:
                    c["metrics"].update(volume=v["total"], volume_pc=v["pc"], volume_mobile=v["mobile"], comp=v["comp"])
            sources["월간 검색수"] = {"ok": True, "note": f"{len(vols)}개 키워드"}
        except Exception as e:
            sources["월간 검색수"] = {"ok": False, "note": key_error_text(e, "검색광고")}
    else:
        sources["월간 검색수"] = {"ok": False, "note": "검색광고 키 필요", "missing": True}

    if has_naver(cfg):
        log("블로그 발행량·최근 7일 새 글·지식iN 질문 수 측정 중…")
        done, fails, first_err = 0, 0, None

        def bjob(c):
            try:
                time.sleep(rng.random() * 0.3)
                return c, blog_stats(cfg, c["keyword"], today), None
            except Exception as e:
                return c, None, e

        span = (pct_to - pct_from) * 0.75
        with ThreadPoolExecutor(max_workers=3) as ex:
            for c, st, err in ex.map(bjob, items):
                done += 1
                if st:
                    c["metrics"].update(blog_total=st["total"], recent7=st["recent7"], recent7_capped=st["recent7_capped"],
                                        kin_total=st.get("kin_total"), daum_total=st.get("daum_total"))
                    c["top_posts"] = st["top"]
                else:
                    fails += 1
                    first_err = first_err or err
                if done % 8 == 0:
                    progress(f"블로그 경쟁도 측정 ({done}/{len(items)})", pct_from + 3 + span * done / len(items))
        ok = done - fails
        sources["블로그 발행량"] = {"ok": ok > 0, "note": f"{ok}개 측정" if ok else key_error_text(first_err, "API HUB")}

        progress("검색어 트렌드 조회", pct_from + 3 + span)
        # 데이터랩은 하루 1,000회 한도 → 1차 순위 상위 일부만
        targets = sorted(items, key=lambda c: -c.get("_pre", 0))[:min(len(items), 80)]
        log(f"네이버 검색어 트렌드: {len(targets)}개 키워드 추이 조회 중…")
        try:
            dl, period = datalab_trends(cfg, [c["keyword"] for c in targets], today)
            for c in targets:
                d = dl.get(norm(c["keyword"]))
                if d:
                    c["metrics"].update(growth=d["growth"], dl_index=d["index"])
            sources["검색어 트렌드"] = {"ok": True, "note": f"{len(dl)}개 · {period}"}
        except Exception as e:
            sources["검색어 트렌드"] = {"ok": False, "note": key_error_text(e, "API HUB")}
    else:
        sources["블로그 발행량"] = {"ok": False, "note": "API HUB 키 필요", "missing": True}
        sources["검색어 트렌드"] = {"ok": False, "note": "API HUB 키 필요", "missing": True}


def measure_one(keyword):
    """기획안을 열었는데 수치가 비어 있을 때: 그 키워드만 지금 다시 측정."""
    cfg = load_config()
    today = datetime.now(KST).date()
    it = {"keyword": keyword, "metrics": {}, "_pre": 0}
    sources = {}
    measure(cfg, [it], today, random.Random(), sources)
    errors = [f"{k}: {v['note']}" for k, v in sources.items() if not v.get("ok")]
    return {"keyword": keyword, "metrics": it["metrics"], "top_posts": it.get("top_posts", []), "errors": errors,
            "keys": {"searchad": has_searchad(cfg), "naver": has_naver(cfg)}}


def key_error_text(e, name):
    if isinstance(e, urllib.error.HTTPError):
        return {401: f"{name} 키가 맞지 않아요", 403: f"{name}에서 이 API 사용 신청이 필요해요",
                429: "오늘 호출 한도를 넘었어요"}.get(e.code, f"{name} 오류 {e.code}")
    return f"{name} 연결 실패" if e else f"{name} 실패"


def site_fit(kw, cfg):
    site = cfg.get("site") or {}
    if not site.get("name"):
        return None
    for offer in site.get("offers", []):
        if any(w in kw for w in OFFER_TRIGGERS.get(offer, [offer])):
            return offer
    return None


def site_plan(it, offer, cfg):
    site = cfg["site"]
    name, url, kw = site["name"], site.get("url", ""), it["keyword"]
    action = OFFER_ACTION.get(offer, "확인")
    where = {"티켓팅": "‘예매 일정’ 단락 바로 아래", "콘서트": "‘예매 일정·가격’ 단락 바로 아래",
             "가볼만한곳": "추천 장소 소개가 끝나는 곳"}.get(it.get("intent"), "핵심 정보를 정리한 단락 바로 뒤")
    return {
        "offer": offer,
        "placement": f"{where}와 글 마지막, 두 곳에 링크를 넣으세요.",
        "ctas": [f"{name}에서 {kw} 바로 {action}하기 →", f"{kw}, {name}에서 한 번에 {action}할 수 있어요",
                 f"👉 {name} 바로가기{(': ' + url) if url else ''}"],
        "section": f"{name}에서 {action}하는 방법",
        "caution": "링크는 1~2개만 넣고, 링크 앞뒤로 직접 정리한 정보를 충분히 쓰세요. "
                   "정보 없이 외부 링크만 많은 글은 네이버 검색에서 품질이 낮게 평가될 수 있습니다(일반적으로 알려진 경향).",
    }


_myblog_cache = {"at": 0, "id": "", "posts": [], "error": ""}


def my_blog_posts(cfg, refresh=False):
    """내 네이버 블로그 최근 글(공개 RSS). 이미 쓴 주제를 알아서 추천·초안에 반영. 1시간 캐시."""
    bid = re.sub(r"[^\w\-]", "", (cfg.get("blog_id") or "").strip().split("/")[-1])
    if not bid:
        return []
    if not refresh and _myblog_cache["id"] == bid and time.time() - _myblog_cache["at"] < 3600:
        return _myblog_cache["posts"]
    posts, err = [], ""
    try:
        root = ET.fromstring(http_get(f"https://rss.blog.naver.com/{bid}.xml", timeout=10))
        for it in root.iter("item"):
            t = strip_tags(it.findtext("title") or "").strip()
            if t:
                pub = ""
                try:
                    pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST).date().isoformat()
                except Exception:
                    pass
                posts.append({"title": t, "date": pub, "link": (it.findtext("link") or "").strip(),
                              "category": strip_tags(it.findtext("category") or "").strip()})
    except Exception as e:
        err = f"내 블로그 글을 읽지 못했어요({type(e).__name__}). 블로그 ID와 공개 설정을 확인해 주세요."
    _myblog_cache.update(at=time.time(), id=bid, posts=posts[:50], error=err)
    return posts[:50]


def apply_learning(items, cfg):
    """공부한 것 반영: 관심 없음(−), 내 블로그에 이미 쓴 주제(−), 저장·발행한 분야(+)."""
    dislikes = [norm(d) for d in cfg.get("dislikes", []) if d]
    posts = my_blog_posts(cfg)
    my_titles = [norm(p["title"]) for p in posts]
    liked_topics = {}
    try:
        for s_ in load_saved():
            t = s_.get("item", {}).get("topic")
            if t:
                liked_topics[t] = liked_topics.get(t, 0) + (2 if s_.get("status") == "발행 완료" else 1)
        for d in WRITER.index():
            if d.get("topic"):
                liked_topics[d["topic"]] = liked_topics.get(d["topic"], 0) + (2 if d.get("status") == "발행 완료" else 1)
    except Exception:
        pass
    for c in items:
        k = norm(c["keyword"])
        if any(d and (d == k or d in k) for d in dislikes):
            c["score"] = round(max(0.0, c["score"] - 25), 1)
            c["score_notes"].append("‘관심 없음’으로 표시한 글감과 비슷해 −25점 (내 선택 반영)")
            c["learned"] = "dislike"
            continue
        words = [norm(w) for w in c["keyword"].split() if len(w) >= 2]
        if my_titles and words and any(all(w in t for w in words) for t in my_titles):
            c["score"] = round(max(0.0, c["score"] - 10), 1)
            c["score_notes"].append("내 블로그에 이미 비슷한 글이 있어 −10점 (새 글보다 기존 글 업데이트를 고려)")
            c["learned"] = "written"
            continue
        n = liked_topics.get(c.get("cat") or c.get("topic"), 0)
        if n:
            bonus = min(6, 2 + n)
            c["score"] = round(min(100.0, c["score"] + bonus), 1)
            c["score_notes"].append(f"내가 자주 저장·작성하는 분야라 +{bonus}점 (내 선택 반영)")


def finalize(items, today, cfg=None):
    cfg = cfg or load_config()
    score_items(items)
    try:
        apply_learning(items, cfg)
    except Exception:
        traceback.print_exc()
    for c in items:
        offer = site_fit(c["keyword"], cfg)
        c["site_fit"] = offer
        if offer and cfg.get("site_boost", True):
            c["score"] = round(min(100.0, c["score"] + 6), 1)
            c["score_notes"].append(f"내 사이트({cfg['site']['name']}) {offer}와 연결되는 키워드라 +6점 (설정에서 끌 수 있음)")
    for c in items:
        c["id"] = uuid.uuid5(uuid.NAMESPACE_URL, c["keyword"] + c["cat"]).hex[:12]
        c["topic"] = c["cat"]
        c["urgency"] = urgency_of(c["kind"], c["src"])
        c["grade"] = "높음" if c["score"] >= 70 else "보통" if c["score"] >= 55 else "낮음"
        _w = c["keyword"].split()
        c["related"] = [r for r in c.get("related", []) if not past_month(r)
                        and (len(_w) < 2 or norm(_w[-1]) in norm(r) or norm(c["keyword"]) in norm(r))]
        c["brief"] = make_brief(c, c["cat"], c["sub"], today)
        if c["site_fit"]:
            sp = site_plan(c, c["site_fit"], cfg)
            c["brief"]["site"] = sp
            c["brief"]["outline"].insert(len(c["brief"]["outline"]) - 1, sp["section"])
        for k in ("_pre", "fresh_penalty", "sub", "cat", "parent", "ac_best"):
            c.pop(k, None)


def past_month(kw, today=None):
    """'10월 축제'처럼 이미 지난(1~4달 전) 달이 들어간 키워드."""
    mm = re.search(r"(?<!\d)(\d{1,2})월", kw)
    if not mm or not 1 <= int(mm.group(1)) <= 12:
        return False
    cur = (today or datetime.now(KST).date()).month
    return 1 <= (cur - int(mm.group(1))) % 12 <= 4


def pick_for_measure(cands, budget, rng, per_topic_min=6, per_seed=3):
    """주제별 1차 점수로 고르게 뽑아 정밀 측정 대상 결정."""
    groups = {}
    cands = [c for c in cands if not any(w in c["keyword"] for w in TOPIC_EXCLUDE.get(c["cat"], []))
             and not past_month(c["keyword"]) and not past_event(c["keyword"])]
    for c in cands:
        c["intent"] = classify(c["keyword"])[0]
        c["_pre"] = c["ac_index"] + 0.5 * fit_score(c) + rng.random() * 6 - (30 if c["fresh_penalty"] else 0)
        if c["kind"] == "trend" and len(c["keyword"].split()) == 1 and not c["intent"]:
            c["_pre"] -= 25  # '날씨', '일본' 같은 단독 명사 이슈는 글감으로 약함
        groups.setdefault(c["cat"], []).append(c)
    per = max(per_topic_min, budget // max(1, len(groups)))
    out = []
    for gname, arr in groups.items():
        if gname == CIVIC_TOPIC:  # 일정(건보료·종부세·수능…)마다 2개까지, 진행 중인 일정 수만큼 몫을 늘림
            arr.sort(key=lambda c: (c["src"].get("days_left", 99), -c["_pre"]))
            ev_n, picked = {}, []
            for c in sorted(arr, key=lambda c: -c["_pre"]):
                ev = c["src"].get("civic")
                if ev_n.get(ev, 0) >= 2:
                    continue
                ev_n[ev] = ev_n.get(ev, 0) + 1
                picked.append(c)
            out += picked[:max(per, 2 * len(ev_n))]
            continue
        arr.sort(key=lambda c: -c["_pre"])
        seed_n, picked = {}, []
        for c in arr:
            if c["kind"] == "trend" and norm(c["keyword"]) != norm(c["seed"]) and not c["intent"]:
                continue  # '배구 이재영 인스타' 같은 인물 검색 변형은 글감이 아님
            if seed_n.get(c["seed"], 0) >= per_seed:
                continue  # 같은 씨앗에서 나온 비슷한 키워드로 도배되지 않게
            seed_n[c["seed"]] = seed_n.get(c["seed"], 0) + 1
            picked.append(c)
        if len(picked) < per and arr and arr[0]["kind"] != "trend":  # 씨앗이 적은 주제는 제한을 조금 풀어 채움 (이슈는 제외)
            ids = {id(c) for c in picked}
            seed_n2 = dict(seed_n)
            for c in arr:
                if id(c) in ids or seed_n2.get(c["seed"], 0) >= per_seed * 2:
                    continue
                seed_n2[c["seed"]] = seed_n2.get(c["seed"], 0) + 1
                picked.append(c)
        out += picked[:per]
    return out


def run_job():
    t0 = time.time()
    cfg = load_config()
    scale = SCALES[cfg["scale"]]
    now = datetime.now(KST)
    today = now.date()
    rng = random.Random(time.time())
    sources = {}
    if not cfg.get("topics"):
        raise RuntimeError("먼저 내 블로그 주제를 골라 주세요.")

    progress("오늘의 이슈 확인 · 구글 트렌드·실시간 검색어·분야별 뉴스", 2)
    log("구글 트렌드·실시간 검색어·분야별 뉴스를 동시에 확인 중…")
    trends, signal, news = [], [], {}
    ex = ThreadPoolExecutor(max_workers=3)
    jobs = {"구글 트렌드": ex.submit(fetch_google_trends)}
    if cfg.get("use_signal_bz", True):
        jobs["실시간 검색어"] = ex.submit(fetch_signal_bz)
    if cfg.get("include_issues", True):
        jobs["분야별 뉴스"] = ex.submit(news_cached, True)
    deadline, done_n = time.time() + 40, 0     # 느린 곳이 있어도 40초 뒤엔 있는 자료로 진행
    for name, fut in jobs.items():
        try:
            res = fut.result(timeout=max(0.1, deadline - time.time()))
        except Exception as e:
            res = None
            sources[name] = {"ok": False, "note": "응답이 너무 느려 건너뜀" if isinstance(e, TimeoutError) or "Timeout" in type(e).__name__ else "연결 실패"}
            log(f"{name}: {sources[name]['note']}")
        done_n += 1
        progress(f"오늘의 이슈 확인 ({done_n}/{len(jobs)}) · {name} 완료", 2 + 6 * done_n / len(jobs))
        if res is None:
            continue
        if name == "구글 트렌드":
            trends = res
            sources[name] = {"ok": True, "note": f"급상승 {len(trends)}개"}
        elif name == "실시간 검색어":
            signal = res
            sources[name] = {"ok": True, "note": f"{len(signal)}개 (signal.bz)"}
        else:
            news = res
            n_news = sum(len(v) for v in news.values())
            sources[name] = {"ok": n_news > 0, "note": f"헤드라인 {n_news}건 (정치·사건 제외)" if n_news else "연결 실패"}
    ex.shutdown(wait=False)
    if not news and cfg.get("include_issues", True):
        news = _news_cache.get("data") or {}
    plan = build_seed_plan(cfg, today, trends, news)
    sources["시즌 캘린더"] = {"ok": True, "note": f"{today.month}월 이슈 {len(season_seeds_for(today))}개"}
    cands, n_q, n_ok = collect_candidates(plan, scale, rng, recent_keywords())
    sources["네이버 자동완성"] = {"ok": n_ok > 0, "note": f"{n_ok}회 조회 · 후보 {len(cands)}개"}
    log(f"후보 키워드 {len(cands)}개 확보")

    items = pick_for_measure(cands, scale["budget"], rng)
    log(f"정밀 분석 대상 {len(items)}개")
    measure(cfg, items, today, rng, sources)
    progress("행사 날짜 확인", 91)
    items, past = filter_past_events(items, today, limit=40)
    sources["행사 날짜 확인"] = {"ok": True, "note": f"지난 행사 {len(past)}개 제외"}
    if past:
        log("지난 행사 제외: " + ", ".join(it["keyword"] for it in past[:8]))
    progress("점수 계산·기획안 작성", 93)
    finalize(items, today, cfg)
    for it in items:
        if it.get("event"):
            it["event_line"] = event_line(it["event"])

    order = ([ISSUE_TOPIC, CIVIC_TOPIC] + [news_topic(l) for l in dict.fromkeys(l for _, l in NEWS_SECTIONS)]
             if cfg.get("include_issues", True) else []) + \
            ([MINE_TOPIC] if cfg.get("my_keywords") else []) + [t for t in TOPICS if t in cfg["topics"]]
    topics = []
    for t in order:
        arr = sorted([c for c in items if c["topic"] == t], key=lambda c: -c["score"])
        if arr:
            topics.append({"name": t, "group": TOPIC_GROUP_OF.get(t, ""), "items": arr})
    # 오늘 쓸 글 TOP 10: 주제가 한쪽으로 몰리지 않게 주제당 최대 2개
    top, per = [], {}
    civic_now = sorted([c for c in items if c["topic"] == CIVIC_TOPIC and c["src"].get("days_left", 99) <= 21],
                       key=lambda c: (c["src"].get("days_left", 99), -c["score"]))
    seen_ev = set()
    for c in civic_now:
        if c["src"].get("civic") in seen_ev or len(top) >= 2:
            continue
        seen_ev.add(c["src"].get("civic"))
        top.append(c["id"])
        per[CIVIC_TOPIC] = per.get(CIVIC_TOPIC, 0) + 1
    news_names = {news_topic(l) for _, l in NEWS_SECTIONS}
    for c in sorted(items, key=lambda c: -c["score"]):
        if c["id"] in top or per.get(c["topic"], 0) >= 2:
            continue
        if c["topic"] in news_names and per.get("_news", 0) >= 3:
            continue
        per[c["topic"]] = per.get(c["topic"], 0) + 1
        if c["topic"] in news_names:
            per["_news"] = per.get("_news", 0) + 1
        top.append(c["id"])
        if len(top) == 10:
            break

    hot = build_hot_issues(trends, signal, news)

    result = {"generated_at": now.isoformat(timespec="seconds"), "date": today.isoformat(), "scale": cfg["scale"],
              "sources": sources, "hot_issues": hot, "topics": topics, "top": top,
              "news": {k: v[:6] for k, v in news.items()},
              "selected_topics": cfg["topics"],
              "stats": {"queries": n_q, "candidates": len(cands), "items": len(items), "seconds": round(time.time() - t0)}}
    return _finish_job(result, now, t0, cands, items)


def build_hot_issues(trends, signal, news):
    hot, seen = [], set()
    for kw, summary, src in ([(t["keyword"], t["news"][0]["title"] if t.get("news") else "", f"구글 트렌드 {t.get('traffic', '')}")
                              for t in trends[:10] if not trend_blocked(t)] + [(x["keyword"], "", f"실시간 {x['rank']}위") for x in signal[:10]]):
        if (norm(kw) in seen or is_blocked(kw) or is_blocked(summary) or not (has_hangul(kw) or has_hangul(summary))
                or len(norm(kw)) <= 2):  # '집', '돈' 같은 두 글자 이하 단어는 글감이 아님
            continue
        seen.add(norm(kw))
        hot.append({"keyword": kw, "summary": summary, "source": src, "section": "실시간"})
    # 분야별로 한 건씩: 경제·국제·IT·연예·건강이 고루 보이게
    news_hot = []
    for label, rows in news.items():
        hts = headline_terms(rows, 40)
        terms = hts[:1]
        if terms:
            term, cnt, row = terms[0]
            term = news_keyword(row["title"], row.get("terms"), label, {t: c for t, c, _ in hts}) or term
            news_hot.append({"keyword": term, "summary": row["title"], "source": f"{label} 뉴스 {cnt}건", "section": label,
                             "news_source": row.get("source", "")})
        elif rows:
            news_hot.append({"keyword": rows[0]["title"][:18], "summary": rows[0]["title"], "source": f"{label} 뉴스", "section": label})
    mixed = []  # 실시간 1 · 분야 2 · 실시간 1 · 분야 2 … 순서로 섞어 화면이 낮아도 여러 분야가 보이게
    while hot or news_hot:
        if hot:
            mixed.append(hot.pop(0))
        mixed += news_hot[:2]
        news_hot = news_hot[2:]
    return mixed


_hot_cache = {"at": 0, "data": None}


def hot_now(refresh=False):
    """오늘의 이슈만 빠르게(2~5초): 구글 트렌드 + 실시간 검색어 + 분야별 뉴스. 5분 캐시."""
    if not refresh and _hot_cache["data"] and time.time() - _hot_cache["at"] < 300:
        return _hot_cache["data"]
    ex = ThreadPoolExecutor(max_workers=3)
    ft, fs, fn = ex.submit(fetch_google_trends), ex.submit(fetch_signal_bz), ex.submit(news_cached, refresh)
    out = []
    for f in (ft, fs, fn):
        try:
            out.append(f.result(timeout=25))
        except Exception:
            out.append([] if f is not fn else {})
    ex.shutdown(wait=False)
    trends = [t for t in out[0] if korean_trend(t)]
    data = {"hot_issues": build_hot_issues(trends, out[1], out[2]), "fetched_at": datetime.now(KST).isoformat(timespec="seconds")}
    _hot_cache.update(at=time.time(), data=data)
    return data


def _finish_job(result, now, t0, cands, items):
    HISTORY.mkdir(parents=True, exist_ok=True)
    rid = now.strftime("%Y-%m-%d_%H%M%S")
    (HISTORY / f"{rid}.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    result["id"] = rid
    progress("완료", 100)
    log(f"완료! 후보 {len(cands)}개 중 {len(items)}개 분석 ({round(time.time() - t0)}초)")
    return result


CULTURE_WORDS = ["특별전", "기획전", "전시회", "전시", "뮤지컬", "연극", "콘서트", "공연", "축제", "박람회", "페스티벌", "음악회",
                 "오페라", "발레", "신간", "박물관", "미술관", "도서관", "영화제"]
NOT_PLACE = {"전시", "개시", "표시", "지시", "도시", "제시", "게시", "감시", "무시", "동시", "당시", "수시", "즉시", "평시", "역시"}


def is_place(w):
    return bool(re.fullmatch(r"[가-힣]{1,4}(특례시|광역시|시|군|구)", w)) and w not in NOT_PLACE


def clean_terms(terms):
    """기사 낱말 다듬기: 조사·복수 '들' 떼기, 꾸밈말('불안한'·'시작된')·일반어 빼기."""
    out = []
    for x in terms or []:
        x = re.sub(r"(?<=..)(으로|로|만이|이란|라는|에도)$", "", x)
        x = re.sub(r"(?<=[시군구])(서|선)$", "", x)
        x = re.sub(r"(?<=..)들$", "", x)
        if (len(x) < 2 or re.match(r"\d", x) or re.search(r"(?<=.)(한|된|던|운|는|진|친|할|될)$", x)
                or x in ("글쎄", "전문가", "관계자", "업계", "정부", "당국", "시민", "주민", "객석", "무대", "발언자", "작품")
                or x in NEWS_STOP):
            continue
        if x not in out:
            out.append(x)
    return out


def news_keyword(title, terms, section, df=None):
    """기사 제목에서 블로그 키워드 고르기: 지역+행사 종류 > 따옴표 속 이름 > 지명이 아닌 핵심어."""
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", title)
    terms = clean_terms(terms or title_terms(title, 8))
    inst = lambda x: bool(re.search(r"(의회|시청|구청|군청|도청|교육청|공사|공단|위원회)$", x))
    place = next((x for x in terms if is_place(x)), "").replace("특례시", "시").replace("광역시", "시")
    cw = next((w for w in CULTURE_WORDS if w in t), None)
    if section == "문화" and cw and place:
        return f"{place} {cw}"
    quoted = []
    for x in re.findall(r"[‘'「《<]([^’'」》>]{2,24})[’'」》>]", t):  # 큰따옴표는 발언 인용이라 제외
        x = re.sub(r"\s+", " ", re.sub(r"[^\w가-힣 ]", " ", x)).strip()
        if (has_hangul(x) and 2 <= len(x.replace(" ", "")) <= 14 and not is_blocked(x) and x not in ("글쎄", "헉", "충격") and x not in NEWS_STOP
                and not re.search(r"(하락|상승|급등|급락|폭락|논란|했다|한다|이다|까지|으로|에서|도전|폭발|관계|승부|마무리|한마디)$", x)
                and not re.search(r"\d+(점|골|승|패|위|억|만)|(과|와|의|을|를|에|도) ", x)):
            quoted.append(x)
    if quoted:
        return quoted[0]
    main = next((x for x in terms if not is_place(x)), None)
    if df:  # 이 분야 기사들에서 자주 나온 핵심어가 있으면 그것을 (오늘 관심이 몰린 말)
        hot = max((x for x in terms if not is_place(x)), key=lambda x: df.get(x, 0), default=None)
        if hot and df.get(hot, 0) >= 2:
            main = hot
            compound = next((x for x in terms if hot in x and x != hot and not inst(x)), None)
            other = next((x for x in terms if x != hot and not is_place(x) and not inst(x) and len(x) >= 3 and hot not in x
                          and df.get(x, 0) >= 2), None)  # 묶을 말도 이 분야에서 두 번 이상 나온 말만
            if len(hot) <= 2 and compound:  # '청년' → 기사 속 '청년센터'
                main = compound
            elif len(hot) <= 2 and other:  # '청년' + '일자리'
                main = f"{hot} {other}"
    if section == "문화" and cw:
        return f"{main} {cw}" if main and cw not in main and main not in cw else cw
    return main or (terms[0] if terms else "")


def analyze_keyword(keyword, ctx=None):
    """직접 분석: 키워드 하나를 2단계로 확장하고 같은 기준으로 순위.
    ctx = {section, title, source}: 뉴스 기사에서 출발한 경우 기사 맥락이 들어간 기획안을 만듦."""
    cfg = load_config()
    today = datetime.now(KST).date()
    rng = random.Random(time.time())
    if ctx and ctx.get("title"):
        df = {}
        try:
            for term, cnt, _ in headline_terms(news_cached(False).get(ctx.get("section"), []), 40):
                df[term] = cnt
        except Exception:
            pass
        keyword = news_keyword(ctx["title"], None, ctx.get("section"), df) or keyword
    keyword = keyword.strip()[:40]
    topic = "직접 분석"
    kind, src = "evergreen", {}
    if ctx and ctx.get("section"):
        topic = news_topic(ctx["section"])
        kind = "news"
        src = {"section": ctx["section"], "count": 1, "news": ctx.get("title", "")[:120], "news_source": ctx.get("source", "")[:40],
               "news_list": [{"title": ctx.get("title", "")[:160], "source": ctx.get("source", "")[:40], "link": ctx.get("link", "")[:600]}]}
    words = keyword.split()
    variants = [keyword, keyword.replace(" ", "")]
    if len(words) >= 3:
        variants += [" ".join(words[:2]), " ".join(words[-2:])]
    elif len(words) == 2:
        variants += [words[0] + " " + words[1][:1]]  # '제주 겨' 처럼 덜 친 상태의 추천어
    plan = [(topic, topic, v, kind, dict(src)) for v in dict.fromkeys(variants) if v]
    cands, n_q, n_ok = collect_candidates(plan, {"depth2": 6}, rng, set())
    if len(words) >= 2:  # 부분 문구로 넓힌 결과 중 원래 키워드의 첫 단어가 없는 건 제외 ('제주 겨울 여행' → '일본 겨울 여행지' 제외)
        cands = [c for c in cands if words[0] in c["keyword"].replace(" ", "")]
    if norm(keyword) not in {norm(c["keyword"]) for c in cands}:
        cands.append({"keyword": keyword, "cat": topic, "sub": topic, "seed": keyword, "kind": kind, "src": dict(src),
                      "ac_best": None, "ac_hits": 0, "depth": 1, "related": [], "parent": keyword,
                      "ac_children": 0, "ac_index": 40.0, "fresh_penalty": False})
    items = pick_for_measure(cands, 40, rng, per_topic_min=40, per_seed=40)
    if norm(keyword) not in {norm(c["keyword"]) for c in items}:
        items = [c for c in cands if norm(c["keyword"]) == norm(keyword)] + items[:39]
    sources = {"네이버 자동완성": {"ok": n_ok > 0, "note": f"{n_ok}회 조회 · 후보 {len(cands)}개"}}
    measure(cfg, items, today, rng, sources)
    finalize(items, today, cfg)
    items.sort(key=lambda c: (norm(c["keyword"]) != norm(keyword), -c["score"]))
    return {"keyword": keyword, "items": items, "sources": sources, "context": ctx or None,
            "concepts": concept_groups(keyword, items), "records": keyword_records(keyword, cfg),
            "generated_at": datetime.now(KST).isoformat(timespec="seconds")}


# ---------- 검색한 키워드로 '어떤 글을 쓸지' 콘셉트 묶음 + 내 기록 ----------
FACETS = [  # (콘셉트 이름, 연관 검색어 패턴, 독자 상황, 제목 꼬리, 시리즈 순서)
    ("기준·조건", r"기준|조건|대상|자격|과실|비율|등급|요건|범위|기한|기간", "자기 상황이 어디에 해당하는지 먼저 알고 싶은 독자", "기준 정리", 1),
    ("절차·방법", r"방법|절차|순서|신청|처리|신고|접수|하는법|발급|조회|대처|요령", "지금 바로 무엇부터 해야 할지 찾는 독자", "처리 순서 총정리", 2),
    ("비용·금액", r"비용|가격|요금|금액|합의금|보상금|위자료|얼마|수수료|할인|환급|지원금|계산", "받을 돈·낼 돈을 미리 가늠하려는 독자", "금액 기준과 계산법", 3),
    ("보험·법률", r"보험|합의|형사|민사|소송|변호사|벌금|벌점|면허|처벌|과태료|특례", "보험·법적 처리에서 손해 보지 않으려는 독자", "보험·법적 처리 핵심", 4),
    ("병원·치료", r"병원|치료|한의원|한방|입원|통원|진단|후유증|물리치료|검사", "치료와 비용 처리를 함께 알아보는 독자", "치료·진료비 처리 정리", 5),
    ("서류·준비물", r"서류|준비물|증명|확인서|양식|사진|블랙박스|증거", "빠뜨리는 서류 없이 준비하려는 독자", "필요 서류 체크리스트", 6),
    ("비교·선택", r"비교|추천|차이|vs|순위|어디|종류|장단점", "여러 선택지 중 무엇이 나은지 고르려는 독자", "선택지 비교", 7),
    ("일정·발표", r"일정|날짜|언제|마감|발표|기한|시간", "날짜를 놓치지 않으려는 독자", "일정 한눈에 보기", 8),
    ("후기·사례", r"후기|사례|경험|실제|썰", "실제 사례로 감을 잡으려는 독자", "사례로 보는 정리", 9),
]


def concept_groups(keyword, items):
    """연관 검색어를 독자 상황별로 묶어 '글 콘셉트'로. 묶음마다 검색 수치 합과 대표 검색어."""
    out = []
    main = norm(keyword)
    prio = ["비용·금액", "보험·법률", "병원·치료", "서류·준비물", "일정·발표", "비교·선택", "후기·사례", "기준·조건", "절차·방법"]
    owner = {}  # 검색어 하나는 묶음 하나에만 (더 구체적인 묶음 우선)
    for c in items:
        for name in prio:
            pat = next(f[1] for f in FACETS if f[0] == name)
            if norm(c["keyword"]) != main and re.search(pat, c["keyword"]):
                owner[c["keyword"]] = name
                break
    for name, pat, reader, tail, order in FACETS:
        hit = [c for c in items if owner.get(c["keyword"]) == name]
        if not hit:
            continue
        hit.sort(key=lambda c: -(c.get("metrics", {}).get("volume") or 0) - c["score"])
        vol = sum((c.get("metrics", {}).get("volume") or 0) for c in hit)
        top = hit[:5]
        words = [c["keyword"] for c in top]
        out.append({"name": name, "reader": reader, "order": order, "volume": vol, "count": len(hit),
                    "keywords": [{"keyword": c["keyword"], "volume": c.get("metrics", {}).get("volume"), "score": c["score"], "id": c["id"]} for c in top],
                    "title": f"{keyword} {tail}: " + "·".join(w.replace(keyword, "").strip() or w for w in words[:3]),
                    "angle": f"{reader}를 위해 '{', '.join(words[:3])}'를 한 글에서 해결하는 {name} 중심 글",
                    "lead_id": top[0]["id"]})
    out.sort(key=lambda g: (-(g["volume"] or 0), -g["count"]))
    if len(out) < 4:  # 연관 검색어가 적을 때도 빈손으로 끝나지 않게: 독자 상황별 기본 콘셉트 (검색 확인 전)
        have = {g["name"] for g in out}
        lead = next((c["id"] for c in items if norm(c["keyword"]) == main), items[0]["id"] if items else "")
        for name, pat, reader, tail, order in sorted(FACETS, key=lambda f: f[4]):
            if name in have or name in ("후기·사례", "일정·발표"):
                continue
            out.append({"name": name, "reader": reader, "order": order, "volume": 0, "count": 0, "keywords": [],
                        "title": f"{keyword} {tail}", "angle": f"{reader}를 위한 {name} 중심 글", "lead_id": lead, "guess": True})
            if len(out) >= 6:
                break
    return out[:6]


def keyword_records(keyword, cfg):
    """내 기록 검토: 내 블로그에 이미 올린 글 · 지난 초안 · 유입(인기) 검색어 중 이 키워드와 관련된 것."""
    k = norm(keyword)
    words = [norm(w) for w in keyword.split() if len(w) >= 2] or [k]
    try:
        posts = [p for p in my_blog_posts(cfg) if any(w in norm(p["title"]) for w in words)][:8]
    except Exception:
        posts = []
    drafts = [{"id": d["id"], "title": d.get("title") or d.get("keyword"), "date": (d.get("created_at") or "")[:10]}
              for d in WRITER.index() if any(w in norm(d.get("keyword", "") + (d.get("title") or "")) for w in words)][:8]
    mine = [m for m in cfg.get("my_keywords", []) if any(w in norm(m) for w in words)][:8]
    return {"posts": posts, "drafts": drafts, "my_keywords": mine}


# ---------- AI 글 아이디어 (검색 수치 + 콘셉트 묶음 + 내 기록 + 최근 뉴스를 검토) ----------
IDEAS = {}  # keyword → {"running", "ideas", "error", "started"}


def start_ideas(keyword, items):
    k = norm(keyword)
    cur = IDEAS.get(k)
    if cur and cur.get("running"):
        return
    IDEAS[k] = {"running": True, "ideas": [], "error": "", "started": time.time()}
    cfg = cfg_with_posts()

    def work():
        try:
            news = []
            try:
                for sec, arr in news_cached(False).items():
                    news += [n.get("title", "") for n in arr if any(w in n.get("title", "") for w in keyword.split())]
            except Exception:
                pass
            data = {"keyword": keyword, "items": items[:30], "concepts": concept_groups(keyword, items),
                    "records": keyword_records(keyword, cfg), "news": news[:8],
                    "my_posts": [p["title"] for p in (cfg.get("_my_posts") or [])[:30]]}
            ideas = _writer.make_ideas(WRITER, cfg, data, datetime.now(KST).date())
            IDEAS[k].update(running=False, ideas=ideas)
        except _writer.WriterError as e:
            IDEAS[k].update(running=False, error=str(e))
        except Exception as e:
            traceback.print_exc()
            IDEAS[k].update(running=False, error=f"아이디어를 만들지 못했어요: {e}")
    threading.Thread(target=work, daemon=True).start()


# ------------------------------------------------------------------ 선제 글감: 사람들이 몰리기 전에 먼저 쓸 글

PREEMPT_SEEDS = ["콘서트 티켓팅", "{m2}월 콘서트", "연말 콘서트", "내한 공연", "팬미팅 예매", "페스티벌 라인업",
                 "티켓 오픈", "뮤지컬 예매", "{m2}월 개봉 영화", "개봉 예정 영화", "공개 예정 드라마", "{m2}월 축제",
                 "출시 예정", "사전예약", "{y2} 달라지는 제도", "얼리버드 예약"]
WATCH_SUFFIX = ["", " 콘서트", " 티켓팅"]
EVENT_RE = re.compile(r"티켓|예매|오픈|라인업|캐스팅|사전 ?예약|출시|개봉|공개|일정|콘서트|내한|팬미팅|페스티벌|축제|얼리버드|신청|달라지는|투어|시즌[0-9]|컴백")
TICKET_RE = re.compile(r"티켓|예매|좌석|취켓팅")


def guess_topic(kw):
    rules = [("빕스|애슐리|뷔페|레스토랑|맛집|오마카세", "맛집"), ("뮤지컬|연극|전시|축제|페스티벌", "공연·전시"), ("콘서트|내한|팬미팅|앨범|컴백|티켓|예매", "음악"),
             ("개봉|영화", "영화"), ("드라마|시즌", "드라마"), ("출시|사전 ?예약|얼리버드", "상품리뷰"),
             ("제도|지원|신청", "사회·정치")]
    for pat, t in rules:
        if re.search(pat, kw):
            return t
    return "일상·생각"


def publish_timing(it, today):
    kw = it["keyword"]
    mm = re.search(r"(\d{1,2})월", kw)
    if mm and 1 <= int(mm.group(1)) <= 12:
        mo = int(mm.group(1))
        yy = today.year + (1 if mo < today.month else 0)
        start = date(yy, mo, 1)
        best = max(today, start - timedelta(days=21))
        return f"{mo}월 시작 2~3주 전({best.month}월 {best.day}일 무렵)까지 발행하면 좋습니다."
    if TICKET_RE.search(kw):
        return "티켓 오픈 3~7일 전에 발행하세요. 예매 직전에 '일정·방법' 검색이 가장 많이 몰립니다(일반적인 경향, 추정). 공식 예매처 공지에서 오픈 날짜를 먼저 확인하세요."
    if re.search(r"라인업|캐스팅", kw):
        return "라인업·캐스팅 발표 직후 바로 쓰고, 발표 내용이 바뀌면 글을 고쳐 최신으로 유지하세요."
    if re.search(r"개봉|공개|출시|사전 ?예약", kw):
        return "공개·출시 1~2주 전에 발행하세요. 날짜가 확정되면 제목에 날짜를 넣어 고치는 게 좋습니다."
    if re.search(r"콘서트|내한|팬미팅|페스티벌|투어", kw):
        return "일정 발표 직후 또는 예매 오픈 1~2주 전에 발행하세요."
    return "이번 주 안에 발행하는 것을 권장합니다."


def preempt_scores(items):
    sat_vals = [math.log10(i["metrics"]["blog_total"] + 1) - (math.log10(i["metrics"]["volume"] + 1) if i["metrics"].get("volume") else 0)
                for i in items if i["metrics"].get("blog_total") is not None]
    sat_p = percentile_map(sat_vals)
    for it in items:
        m, p = it["metrics"], it["parts"]
        sat = None
        if m.get("blog_total") is not None:
            sat = sat_p(math.log10(m["blog_total"] + 1) - (math.log10(m["volume"] + 1) if m.get("volume") else 0))
        g, d = p.get("growth", 50), p.get("demand", 50)
        score = (0.4 * g + 0.35 * (100 - sat) + 0.25 * d) if sat is not None else (0.6 * g + 0.4 * d)
        if it.get("site_fit"):
            score += 4
        it["preempt"] = round(min(100.0, score), 1)
        it["preempt_label"] = "지금 선점" if it["preempt"] >= 68 else "준비해 두기" if it["preempt"] >= 55 else "지켜보기"
        sig = []
        if it["kind"] == "trend":
            sig.append("오늘 급상승")
        if it["kind"] == "watch":
            sig.append(f"관심: {it['src'].get('watch', it['seed'])}")
        if TICKET_RE.search(it["keyword"]):
            sig.append("예매 신호")
        elif re.search(r"개봉|공개|출시|사전 ?예약", it["keyword"]):
            sig.append("공개·출시 예정")
        if m.get("growth") is not None and m["growth"] >= 15:
            sig.append(f"검색 상승 +{round(m['growth'])}%")
        if m.get("blog_total") is not None and m["blog_total"] < 20000:
            sig.append(f"블로그 글 적음 {m['blog_total']:,}건")
        if it.get("site_fit"):
            sig.append("내 사이트 연계")
        it["signals"] = sig
        it["preempt_formula"] = ("상승세 40% + (100-포화도) 35% + 수요 25%" if sat is not None
                                 else "상승세 60% + 수요 40% (블로그 글 수 데이터 없음)") + (" + 내 사이트 연계 4점" if it.get("site_fit") else "")


def upcoming_calendar(today, days=75):
    out, seen = [], set()
    for k in range(0, 4):
        mo = (today.month - 1 + k) % 12 + 1
        for kw, cats, fixed in SEASON_SEEDS[mo]:
            if not fixed or kw in seen:
                continue
            yy = today.year + (1 if fixed[0] < today.month else 0)
            d = date(yy, fixed[0], fixed[1])
            dl = (d - today).days
            if 0 <= dl <= days:
                seen.add(kw)
                pub = max(today, d - timedelta(days=14))
                out.append({"name": kw, "date": d.isoformat(), "d_day": dl, "publish_by": pub.isoformat(),
                            "topics": sorted(set(cats))})
    for c in civic_active(today):  # 생활 제도: 마감일 기준
        if 0 <= c["days_left"] <= days:
            out.append({"name": c["name"] + " 마감", "date": c["end_date"].isoformat(), "d_day": c["days_left"],
                        "publish_by": max(today, c["end_date"] - timedelta(days=14)).isoformat(), "topics": [c["topic"]]})
    return sorted(out, key=lambda x: x["d_day"])


# ------------------------------------------------------------------ 생활 제도 달력: 매년 같은 시기에 돌아오는 신청·납부·마감

def suneung_day(y):
    """수능일: 보통 11월 셋째 목요일 (교육부 공고로 확정)."""
    d = date(y, 11, 1)
    first_thu = d + timedelta(days=(3 - d.weekday()) % 7)
    return first_thu + timedelta(days=14)


# start/end: (월, 일) 또는 함수(연도 → date). note: 해마다 반복되는 통상 시기(정확한 날짜는 그해 공고 확인).
CIVIC_CALENDAR = [
    {"name": "수능 이후 입시 일정", "start": lambda y: suneung_day(y) + timedelta(days=1), "end": (12, 31), "topic": "교육·학문",
     "seeds": ["수능 가채점", "수능 등급컷", "수능 성적 발표일", "정시 원서접수 기간", "정시 지원 전략"],
     "note": "수능 다음 날부터 가채점·등급컷, 12월 초 성적 통지, 12월 말 정시 원서접수로 이어집니다(날짜는 해마다 교육부·대교협 공고 확인)."},
    {"name": "지역가입자 건강보험료 조정", "start": (11, 1), "end": (11, 30), "topic": "비즈니스·경제", "ymyl": True,
     "seeds": ["건강보험료 조정신청", "지역가입자 건강보험료", "건강보험료 11월 인상"],
     "note": "지역가입자 보험료는 매년 11월분부터 새 소득·재산 자료로 다시 계산돼 1년 동안 적용됩니다. 고지서를 받고 조정 신청 방법을 찾는 시기입니다."},
    {"name": "연말정산 미리보기", "start": (10, 20), "end": (12, 31), "topic": "비즈니스·경제", "ymyl": True,
     "seeds": ["연말정산 미리보기", "연말정산 미리보기 서비스", "연말정산 카드 공제 한도", "연금저축 세액공제", "IRP 세액공제 한도"],
     "note": "국세청 홈택스 연말정산 미리보기가 열리는 시기라, 남은 기간 카드 사용·연금 납입 계획을 세우려는 검색이 몰립니다."},
    {"name": "고향사랑기부제 연말 마감", "start": (11, 15), "end": (12, 31), "topic": "비즈니스·경제", "ymyl": True,
     "seeds": ["고향사랑기부제", "고향사랑기부제 답례품", "고향사랑기부제 세액공제"],
     "note": "12월 31일까지 기부해야 그해 세액공제를 받을 수 있어 연말에 기부와 검색이 몰립니다."},
    {"name": "에너지바우처 신청", "start": (11, 1), "end": (12, 31), "topic": "비즈니스·경제", "ymyl": True,
     "seeds": ["에너지바우처 신청", "에너지바우처 대상", "에너지바우처 사용처"],
     "note": "동절기 난방비 지원이라 겨울 들어 검색이 늘고 연말에 신청이 마감되는 경우가 많습니다(신청 기간은 해마다 공고 확인)."},
    {"name": "종합부동산세 고지·납부", "start": (11, 20), "end": (12, 15), "topic": "비즈니스·경제", "ymyl": True,
     "seeds": ["종합부동산세 고지서", "종부세 납부 기간", "종부세 분납"],
     "note": "11월 말 고지서가 나오고 12월 1~15일에 납부합니다. 고지서를 받은 직후 검색이 가장 많습니다."},
    {"name": "국가장학금 1차 신청", "start": (11, 20), "end": (12, 31), "topic": "교육·학문",
     "seeds": ["국가장학금 신청 기간", "국가장학금 1차 신청", "국가장학금 소득분위"],
     "note": "다음 학년도 1학기 국가장학금 1차 신청이 보통 11월 말~12월에 열립니다(한국장학재단 공고 확인)."},
    {"name": "국가건강검진 연말 마감", "start": (11, 1), "end": (12, 31), "topic": "건강·의학", "ymyl": True,
     "seeds": ["국가건강검진 연말", "건강검진 미수검", "국가건강검진 대상자 조회"],
     "note": "국가건강검진은 해당 연도 12월 31일까지 받아야 해서 연말에 예약 검색이 몰립니다."},
    {"name": "12월 자동차세 납부", "start": (12, 10), "end": (12, 31), "topic": "자동차",
     "seeds": ["12월 자동차세 납부", "자동차세 조회", "자동차세 연납 신청"],
     "note": "자동차세 2기분 납부 시기이고, 다음 해 1월 연납 할인을 미리 알아보는 시기입니다."},
    {"name": "자동차세 연납 할인", "start": (1, 1), "end": (1, 31), "topic": "자동차",
     "seeds": ["자동차세 연납", "자동차세 연납 할인", "자동차세 연납 신청 방법"],
     "note": "1월에 한 해 자동차세를 미리 내면 할인을 받을 수 있어 1월에 검색이 몰립니다(할인율은 해마다 확인)."},
    {"name": "새해 달라지는 제도", "start": (12, 1), "end": (1, 20), "topic": "비즈니스·경제",
     "seeds": ["{y2} 달라지는 것", "{y2} 달라지는 제도", "{y2} 최저시급"],
     "note": "12월 초 예산·세법이 확정되고 연말연시에 '새해 달라지는 것' 정리 수요가 큽니다."},
    {"name": "소상공인 정책자금 공고", "start": (12, 20), "end": (1, 31), "topic": "비즈니스·경제", "ymyl": True,
     "seeds": ["소상공인 정책자금", "소상공인 정책자금 신청 방법", "소상공인 지원사업"],
     "note": "새해 정책자금·지원사업 공고가 연말연초에 나오는 경우가 많습니다(공고 시점은 추정, 공고 확인)."},
    {"name": "연말정산 간소화·환급", "start": (1, 10), "end": (2, 28), "topic": "비즈니스·경제", "ymyl": True,
     "seeds": ["연말정산 간소화 서비스", "연말정산 기간", "연말정산 환급금 지급일"],
     "note": "1월 중순 간소화 자료가 열리고 2월에 회사 연말정산이 마무리됩니다."},
    {"name": "부가세 확정신고(2기)", "start": (1, 1), "end": (1, 25), "topic": "비즈니스·경제", "ymyl": True,
     "seeds": ["부가세 신고 기간", "부가세 신고 방법", "간이과세자 부가세 신고"], "note": "개인사업자 2기 부가세 확정신고는 1월 25일까지입니다."},
    {"name": "부가세 확정신고(1기)", "start": (7, 1), "end": (7, 25), "topic": "비즈니스·경제", "ymyl": True,
     "seeds": ["부가세 신고 기간", "부가세 신고 방법"], "note": "개인사업자 1기 부가세 확정신고는 7월 25일까지입니다."},
    {"name": "근로·자녀장려금 정기신청", "start": (5, 1), "end": (5, 31), "topic": "비즈니스·경제", "ymyl": True,
     "seeds": ["근로장려금 신청", "근로장려금 자격", "자녀장려금 신청"], "note": "근로·자녀장려금 정기신청은 매년 5월입니다."},
    {"name": "종합소득세 신고", "start": (5, 1), "end": (5, 31), "topic": "비즈니스·경제", "ymyl": True,
     "seeds": ["종합소득세 신고 기간", "종합소득세 신고 방법", "종합소득세 환급"], "note": "종합소득세 신고·납부는 매년 5월 31일까지입니다."},
    {"name": "7월 재산세", "start": (7, 10), "end": (7, 31), "topic": "비즈니스·경제", "seeds": ["재산세 납부 기간", "재산세 조회"],
     "note": "주택분 재산세 1기분은 7월 16~31일에 납부합니다."},
    {"name": "9월 재산세", "start": (9, 10), "end": (9, 30), "topic": "비즈니스·경제", "seeds": ["9월 재산세", "재산세 조회"],
     "note": "주택분 재산세 2기분·토지분은 9월 16~30일에 납부합니다."},
    {"name": "8월 주민세", "start": (8, 10), "end": (8, 31), "topic": "비즈니스·경제", "seeds": ["주민세 납부", "주민세 조회"],
     "note": "주민세(개인분)는 8월 16~31일에 납부합니다."},
]
CIVIC_LEAD = 14  # 시작 2주 전부터 미리 쓰라고 알려 줌


def _civic_date(v, y):
    return v(y) if callable(v) else date(y, v[0], v[1])


def civic_active(today):
    """오늘 기준으로 '곧 시작'이거나 '진행 중'인 생활 제도 일정."""
    out = []
    for c in CIVIC_CALENDAR:
        for y in (today.year - 1, today.year, today.year + 1):
            st = _civic_date(c["start"], y)
            en = _civic_date(c["end"], y if _civic_date(c["end"], y) >= st else y + 1)
            if en < st:
                en = _civic_date(c["end"], y + 1)
            if st - timedelta(days=CIVIC_LEAD) <= today <= en:
                out.append({**c, "start_date": st, "end_date": en, "days_left": (en - today).days,
                            "days_to_start": (st - today).days})
                break
    return sorted(out, key=lambda c: c["days_left"])


# ------------------------------------------------------------------ 상시 키워드 사전 · 상시성 검증

def load_evergreen():
    try:
        d = json.loads((Path(__file__).parent / "evergreen.json").read_text(encoding="utf-8"))
        return ({t: [k for k in kws if not is_blocked(k)] for t, kws in d.get("topics", {}).items()},
                {norm(k): v for k, v in d.get("meta", {}).items()})
    except Exception:
        return {}, {}


EVERGREEN, EVERGREEN_META = load_evergreen()
FLAG_TEXT = {
    "ymyl": "돈·건강·법과 관련된 주제라 네이버도 신뢰도를 엄격히 봅니다. 기관 공식 자료(날짜 포함)를 근거로 쓰고, 승인·수익·효과·판결을 단정하지 마세요.",
    "changes": "앱 화면과 절차가 자주 바뀌는 주제입니다. 글에 확인 날짜를 적고, 직접 찍은 화면 캡처로 단계별로 보여 주세요.",
    "phone": "네이버가 검색 결과에 전화번호를 바로 보여 주는 경우가 많아 번호만 쓰면 클릭이 적을 수 있어요(추정). 운영시간·상담원 연결 순서·채팅 문의처럼 번호 외 정보를 함께 담으세요.",
}
EG_JOB = {"running": False, "pct": 0, "stage": "", "error": None}


def load_eg_check():
    try:
        return json.loads(EVERGREEN_CHECK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"checked_at": None, "results": {}}


def datalab_monthly(cfg, keywords, today):
    """최근 24개월 월별 검색 추이(네이버 데이터랩). 키워드마다 [24개 값] (요청 안 상대값이지만 모양 비교엔 충분)."""
    first_this = today.replace(day=1)
    end = first_this - timedelta(days=1)                       # 지난달 말
    start = date(end.year - 2, end.month, 1) + timedelta(days=32)
    start = start.replace(day=1)                                 # 24개월 전 달의 1일
    out = {}
    for i in range(0, len(keywords), 5):
        batch = keywords[i:i + 5]
        body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "timeUnit": "month",
                "keywordGroups": [{"groupName": k, "keywords": [k]} for k in batch]}
        res = naver_call(cfg, "trend", body=body)
        for g in res.get("results", []):
            pts = {d["period"][:7]: d["ratio"] for d in g.get("data", [])}
            months = []
            y, mo = start.year, start.month
            while (y, mo) <= (end.year, end.month):
                months.append(pts.get(f"{y:04d}-{mo:02d}", 0.0))
                mo += 1
                if mo > 12:
                    y, mo = y + 1, 1
            out[norm(g["title"])] = {"series": [round(v, 1) for v in months], "end": end.strftime("%Y-%m")}
        time.sleep(0.12)
    return out


def judge_evergreen(r):
    """24개월 추이·검색수로 판정. verdict: 상시 / 대체로 상시 / 계절형 / 하락 / 검색 적음 / 미검증."""
    vol = r.get("volume")
    ser = r.get("series")
    if vol is not None and vol < 100:
        return "검색 적음", "월 검색 100회 미만이라 글을 써도 유입이 거의 없어요."
    if not ser or sum(ser) == 0:
        if vol:
            return "미검증", f"월 {vol:,}회 검색되지만 1년 추이는 아직 확인 못 했어요(API HUB 키 필요)."
        if r.get("ac"):
            return "미검증", "네이버 자동완성에 나오는 검색어예요. 1년 추이·검색수는 키가 있어야 검증돼요."
        return "미검증", ("자동완성 확인에 실패했어요(잠시 후 다시 검증)." if r.get("ac") is None
                         else "자동완성에 안 나와요. 사람들이 이 표현으로는 잘 안 찾아요.")
    last12, prev12 = ser[-12:], ser[-24:-12]
    mean = sum(last12) / 12
    if mean == 0:
        return "검색 적음", "최근 1년 검색이 거의 없어요."
    sd = (sum((v - mean) ** 2 for v in last12) / 12) ** 0.5
    cv = sd / mean
    peak = max(last12) / mean
    yoy = (mean - sum(prev12) / 12) / (sum(prev12) / 12) * 100 if prev12 and sum(prev12) else None
    r.update(cv=round(cv, 2), peakiness=round(peak, 2), yoy=round(yoy, 1) if yoy is not None else None)
    # 피크 달: 평균의 1.4배 넘는 달 (최근 12개월 기준, 실제 달 이름으로)
    ey, em = map(int, r.get("end", "2000-12").split("-"))
    months = [((em - 11 + i - 1) % 12) + 1 for i in range(12)]
    peaks = [months[i] for i, v in enumerate(last12) if v >= mean * 1.4]
    r["peak_months"] = sorted(set(peaks))
    if yoy is not None and yoy <= -35:
        return "하락", f"1년 전보다 검색이 {abs(yoy):.0f}% 줄었어요. 관심이 식는 중이에요."
    if cv >= 0.45 or peak >= 1.9:
        pm = ", ".join(f"{m}월" for m in r["peak_months"]) or "특정 달"
        return "계절형", f"{pm}에 검색이 몰려요(변동 {cv:.2f}). 그 달 3~4주 전에 쓰면 좋아요."
    if cv < 0.25 and peak < 1.5:
        return "상시", f"최근 1년 매달 고르게 검색돼요(변동 {cv:.2f}" + (f", 1년 전 대비 {yoy:+.0f}%" if yoy is not None else "") + ")."
    return "대체로 상시", f"1년 내내 검색되지만 달마다 차이가 조금 있어요(변동 {cv:.2f})."


def eg_score(r):
    """상시 키워드 점수: 검색수(40) + 꾸준함(35) + 경쟁 적음(25). 없는 값은 빼고 재계산 (추정)."""
    parts = []
    if r.get("volume"):
        parts.append((min(100, math.log10(r["volume"] + 1) / 5 * 100), 40))
    if r.get("cv") is not None:
        parts.append((max(0, 100 - r["cv"] * 160), 35))
    if r.get("blog_total") is not None and r.get("volume"):
        ratio = r["blog_total"] / max(r["volume"], 1)        # 검색 1회당 글 수 (작을수록 유리)
        parts.append((max(0, min(100, 100 - math.log10(ratio + 0.01) * 35 - 20)), 25))
    if not parts:
        return None
    return round(sum(v * w for v, w in parts) / sum(w for _, w in parts), 1)


def run_evergreen_check():
    """사전 전체를 검증: 자동완성(무료) → 월간 검색수(검색광고) → 24개월 추이(데이터랩) → 블로그 글 수(API HUB)."""
    cfg = load_config()
    today = datetime.now(KST).date()
    kws = list(dict.fromkeys(k for ks in EVERGREEN.values() for k in ks))
    res = {norm(k): {"keyword": k} for k in kws}

    def st(stage, pct):
        EG_JOB.update(stage=stage, pct=int(pct))

    st("네이버 자동완성 확인", 3)

    def ac(k):
        try:
            sug = naver_autocomplete(k)
            return k, any(norm(x).startswith(norm(k)) or norm(k).startswith(norm(x)) for x in sug) or bool(sug)
        except Exception:
            return k, None
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, (k, ok) in enumerate(ex.map(ac, kws)):
            res[norm(k)]["ac"] = ok
            if i % 25 == 0:
                st(f"네이버 자동완성 확인 ({i}/{len(kws)})", 3 + 22 * i / len(kws))
    if has_searchad(cfg):
        st("월간 검색수 조회", 26)
        try:
            vols = searchad_volumes(cfg, kws)
            for k in kws:
                v = vols.get(norm(k))
                if v:
                    res[norm(k)].update(volume=v["total"], comp=v["comp"], ad_depth=v.get("ad_depth"), ad_clicks=v.get("ad_clicks"))
        except Exception as e:
            EG_JOB["error"] = key_error_text(e, "검색광고")
        st("광고 클릭 단가(예상 입찰가) 조회", 38)
        try:
            bids = searchad_bids(cfg, kws)
            for k in kws:
                if norm(k) in bids:
                    res[norm(k)]["cpc"] = bids[norm(k)]
        except Exception as e:
            print("[예상 입찰가 조회 실패]", e)  # 없어도 나머지 판정은 진행
    if has_naver(cfg):
        st("24개월 검색 추이 조회", 45)
        try:
            dl = datalab_monthly(cfg, kws, today)
            for k in kws:
                if norm(k) in dl:
                    res[norm(k)].update(dl[norm(k)])
        except Exception as e:
            EG_JOB["error"] = key_error_text(e, "API HUB 검색어 트렌드")
        st("블로그 글 수 조회", 70)
        try:  # 키가 안 맞으면 650번 헛돌지 않게 한 번 먼저 시험
            naver_call(cfg, "blog", {"query": kws[0], "display": 1})
            blog_ok = True
        except Exception as e:
            blog_ok = False
            EG_JOB["error"] = key_error_text(e, "API HUB")

        def bt(k):
            try:
                return k, int(naver_call(cfg, "blog", {"query": k, "display": 1}).get("total", 0))
            except Exception:
                return k, None
        with ThreadPoolExecutor(max_workers=3) as ex:
            for i, (k, tot) in enumerate(ex.map(bt, kws if blog_ok else [])):
                if tot is not None:
                    res[norm(k)]["blog_total"] = tot
                if i % 25 == 0:
                    st(f"블로그 글 수 조회 ({i}/{len(kws)})", 70 + 25 * i / len(kws))
    for k, r in res.items():
        r["verdict"], r["reason"] = judge_evergreen(r)
        r["score"] = eg_score(r)
        # 고단가 판정: 예상 클릭 단가가 있으면 그것으로, 없으면 광고 경쟁도로 (추정)
        cpc = r.get("cpc")
        r["high_value"] = bool((cpc is not None and cpc >= 1000) or (cpc is None and r.get("comp") == "높음" and (r.get("ad_depth") or 0) >= 10))
    data = {"checked_at": datetime.now(KST).isoformat(timespec="seconds"), "results": res,
            "level": {"searchad": has_searchad(cfg), "naver": has_naver(cfg)}}
    DATA.mkdir(parents=True, exist_ok=True)
    EVERGREEN_CHECK_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    st("완료", 100)
    return data


def start_evergreen_check():
    if EG_JOB["running"]:
        return False
    EG_JOB.update(running=True, pct=0, stage="준비 중", error=None)

    def w():
        try:
            run_evergreen_check()
        except Exception as e:
            traceback.print_exc()
            EG_JOB["error"] = str(e)
        finally:
            EG_JOB["running"] = False
    threading.Thread(target=w, daemon=True).start()
    return True


def evergreen_seeds(topics, today, per_topic=4):
    """오늘의 추천에 넣을 상시 키워드: 검증 결과가 있으면 '상시·대체로 상시' 중 점수 높은 것, 없으면 날짜별로 돌아가며."""
    chk = load_eg_check().get("results", {})
    out = []
    soon = {today.month, today.month % 12 + 1}
    for t in topics:
        kws = [k for k in EVERGREEN.get(t, []) if EVERGREEN_META.get(norm(k), {}).get("auto", True)]
        if not kws:
            continue
        # 계절형으로 판정된 키워드는 피크 달(이번 달·다음 달)에만 넣음: 건보료 조정(11월) 같은 것
        peak = [chk[norm(k)] for k in kws if chk.get(norm(k), {}).get("verdict") == "계절형"
                and soon & set(chk[norm(k)].get("peak_months") or [])]
        out += [(t, r["keyword"], r) for r in sorted(peak, key=lambda r: -(r.get("score") or 0))[:2]]
        good = [chk[norm(k)] for k in kws if chk.get(norm(k), {}).get("verdict") in ("상시", "대체로 상시")]
        if good:
            good.sort(key=lambda r: -(r.get("score") or 0))
            pool = good[:per_topic * 3]
            off = today.toordinal() % max(1, len(pool))      # 매일 조금씩 다른 키워드
            pick = (pool[off:] + pool[:off])[:per_topic]
            out += [(t, r["keyword"], r) for r in pick]
        else:
            seasonal_or_bad = {norm(k) for k in kws if chk.get(norm(k), {}).get("verdict") in ("계절형", "하락", "검색 적음")}
            rest = [k for k in kws if norm(k) not in seasonal_or_bad]
            off = (today.toordinal() * per_topic) % max(1, len(rest))
            pick = (rest[off:] + rest[:off])[:per_topic]
            out += [(t, k, chk.get(norm(k), {})) for k in pick]
    return out


# ------------------------------------------------------------------ 행사 날짜 확인 (지난 행사 거르기)

EVENT_WORDS = re.compile(r"콘서트|공연|페스티벌|축제|팬미팅|내한|투어|뮤지컬|연극|전시|박람회|시상식|어워드|어워즈|MMA|MAMA|라인업|티켓|예매|불꽃")
EVENT_STRIP = {"라인업", "티켓팅", "티켓", "예매", "일정", "가격", "좌석", "좌석배치도", "시간", "장소", "정보", "예약", "사전예약", "오픈",
               "방법", "후기", "출연진", "날짜", "시간표", "타임테이블", "셋리스트", "굿즈", "주차", "가는법", "위치", "할인", "취켓팅"}
EVENT_GENERIC = {"콘서트", "공연", "페스티벌", "축제", "팬미팅", "내한", "투어", "뮤지컬", "연극", "전시", "연말", "연초", "겨울", "여름", "가을", "봄",
                 "영화", "드라마", "개봉", "공개", "출시", "예정", "국내", "해외", "서울", "부산", "추천", "무료", "단독", "아이돌", "클래식", "내년", "올해"}
PAST_RE = re.compile(r"성료|폐막|막\s?내려|막내려|성황리|마무리|열렸다|개최됐|진행됐|끝났|마쳤|폐회|대장정|피날레|막 올렸다")
FUTURE_RE = re.compile(r"열린다|연다|개최한다|개최 예정|예정|앞두고|티켓 ?오픈|예매 ?오픈|사전 ?예약|D-\d|내달|다음 달|라인업 공개|라인업 발표|첫 공개")
_event_cache = {}


def event_core(kw):
    words = [w for w in kw.split() if w not in EVENT_STRIP and not re.fullmatch(r"(19|20)\d\d(년)?", w)]
    core = " ".join(words).strip()
    proper = [w for w in words if w not in EVENT_GENERIC and not re.fullmatch(r"\d{1,2}월", w)]
    return core, bool(proper)


def title_dates(title, pub):
    """제목 속 '10월 4일', '10.3~5' 같은 날짜 → date 목록 (기사 날짜의 해 기준)."""
    out = []
    for mo, d in re.findall(r"(\d{1,2})월\s?(\d{1,2})일", title) + re.findall(r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?![\d.])", title):
        mo, d = int(mo), int(d)
        if 1 <= mo <= 12 and 1 <= d <= 31:
            try:
                dt = date(pub.year, mo, d)
            except ValueError:
                continue
            if (pub - dt).days > 200:  # 연말 기사에 나온 '1월 5일'은 다음 해
                dt = date(pub.year + 1, mo, d)
            out.append(dt)
    for mo in re.findall(r"(\d{1,2})월\s?(?:중|초|말|개최|열려|예정)", title):
        mo = int(mo)
        if 1 <= mo <= 12:
            dt = date(pub.year + (1 if (pub.month - mo) > 6 else 0), mo, 15)
            out.append(dt)
    return out


def check_event(kw, today):
    """구글 뉴스로 행사가 이미 끝났는지 확인. status: upcoming / past / unknown / generic."""
    core, proper = event_core(kw)
    if not proper or not EVENT_WORDS.search(kw):
        return {"status": "generic"}
    key = norm(core)
    if key in _event_cache:
        return _event_cache[key]
    res = {"status": "unknown", "core": core}
    try:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": f"{core} when:150d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
        root = ET.fromstring(http_get(url, timeout=10))
        need = [norm(w) for w in core.split() if len(w) >= 2 and w not in EVENT_GENERIC] or [norm(core)]
        arts = []
        for it in root.iter("item"):
            title = strip_tags(it.findtext("title") or "")
            src = ""
            if " - " in title:
                title, src = title.rsplit(" - ", 1)
            if not all(n in norm(title) for n in need):
                continue
            try:
                pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST).date()
            except Exception:
                continue
            arts.append({"title": title.strip(), "source": src.strip(), "link": (it.findtext("link") or "").strip(),
                         "pub": pub, "dates": title_dates(title, pub)})
        arts.sort(key=lambda a: a["pub"], reverse=True)
        fut = [(d, a) for a in arts for d in a["dates"] if d >= today]
        past = [(d, a) for a in arts for d in a["dates"] if d < today and (today - d).days <= 150]
        past_sig = [a for a in arts if PAST_RE.search(a["title"]) and (today - a["pub"]).days <= 90
                    and not any(d >= today for d in a["dates"])]
        fut_sig = [a for a in arts if FUTURE_RE.search(a["title"]) and (today - a["pub"]).days <= 7
                   and not PAST_RE.search(a["title"])]
        # 가장 최근 기사가 '끝났다' 쪽이면 지난 행사로 (다음 회차 소식이 그 뒤에 나왔으면 예정으로)
        latest_past = max([a["pub"] for a in past_sig] + [a["pub"] for _, a in past], default=None)
        latest_fut = max([a["pub"] for _, a in fut] + [a["pub"] for a in fut_sig], default=None)
        if fut and (latest_past is None or latest_fut >= latest_past):
            d, a = min(fut, key=lambda x: x[0])
            res = {"status": "upcoming", "date": d.isoformat(), "evidence": a}
        elif fut_sig and (latest_past is None or latest_fut > latest_past):
            res = {"status": "upcoming", "evidence": fut_sig[0]}
        elif past or past_sig:
            d = max((x[0] for x in past), default=None)
            res = {"status": "past", "date": d.isoformat() if d else None,
                   "evidence": (max(past, key=lambda x: x[1]["pub"])[1] if past else past_sig[0])}
        elif arts:
            res = {"status": "unknown", "evidence": arts[0]}
        res["core"] = core
    except Exception:
        res = {"status": "unknown", "core": core, "error": True}
    if res.get("evidence"):
        ev = res["evidence"]
        res["evidence"] = {"title": ev["title"], "source": ev["source"], "link": ev["link"], "pub": ev["pub"].isoformat()}
    _event_cache[key] = res
    return res


def filter_past_events(items, today, limit=60):
    """행사형 키워드의 날짜를 뉴스로 확인해 이미 끝난 행사는 빼고, 나머지에는 확인 결과를 붙임."""
    targets = [it for it in items if EVENT_WORDS.search(it["keyword"])][:limit]
    with ThreadPoolExecutor(max_workers=6) as ex:
        for it, ev in zip(targets, ex.map(lambda it: check_event(it["keyword"], today), targets)):
            it["event"] = ev
    past = [it for it in items if it.get("event", {}).get("status") == "past"]
    return [it for it in items if it.get("event", {}).get("status") != "past"], past


def event_line(ev):
    """화면에 보여 줄 한 줄: 무엇을 근거로 판단했는지."""
    if not ev or ev.get("status") in (None, "generic"):
        return ""
    e = ev.get("evidence") or {}
    src = f" ({e.get('source', '')} {e.get('pub', '')[5:].replace('-', '.')})" if e else ""
    if ev["status"] == "upcoming":
        when = ""
        if ev.get("date"):
            dd = date.fromisoformat(ev["date"])
            when = f"{dd.month}월 {dd.day}일 예정 · "
        return f"일정 확인: {when}기사 “{e.get('title', '')}”{src}"
    if ev["status"] == "past":
        return f"지난 행사: “{e.get('title', '')}”{src}"
    return "일정 미확인: 최근 기사에서 날짜를 찾지 못했어요. 쓰기 전에 공식 공지·예매처에서 날짜를 꼭 확인하세요."


def run_preempt():
    t0 = time.time()
    cfg = load_config()
    now = datetime.now(KST)
    today = now.date()
    rng = random.Random(time.time())
    m2 = today.month % 12 + 1
    y2 = today.year + (1 if today.month >= 10 else 0)
    plan = [("선제", "선제", sd.format(m2=m2, y2=y2), "preempt", {}) for sd in PREEMPT_SEEDS]
    for name in cfg.get("watchlist", [])[:20]:
        name = name.strip()
        if name:
            plan += [("선제", "선제", name + suf, "watch", {"watch": name}) for suf in WATCH_SUFFIX]
    sources = {}
    trends = []
    try:
        trends = [t for t in fetch_google_trends() if korean_trend(t) and not is_blocked(t["keyword"])
                  and not trend_blocked(t)]
        sources["구글 트렌드"] = {"ok": True, "note": f"급상승 {len(trends)}개 확인"}
    except Exception:
        sources["구글 트렌드"] = {"ok": False, "note": "연결 실패"}
    for t in trends[:10]:
        plan.append(("선제", "선제", t["keyword"], "trend",
                     {"traffic": t.get("traffic"), "news": t["news"][0]["title"] if t.get("news") else ""}))
    cands, n_q, n_ok = collect_candidates(plan, {"depth2": 2}, rng, set())
    sources["네이버 자동완성"] = {"ok": n_ok > 0, "note": f"{n_ok}회 조회 · 후보 {len(cands)}개"}
    cands = [c for c in cands if EVENT_RE.search(c["keyword"])]
    for c in cands:
        c["cat"] = c["sub"] = guess_topic(c["keyword"])
    items = pick_for_measure(cands, 90, rng, per_topic_min=12, per_seed=3)
    items = sorted(items, key=lambda c: -c["_pre"])[:90]
    items, past = filter_past_events(items, today, limit=90)
    items = items[:70]
    n_up = sum(1 for it in items if it.get("event", {}).get("status") == "upcoming")
    sources["행사 날짜 확인"] = {"ok": True, "note": f"지난 행사 {len(past)}개 제외 · 날짜 확인 {n_up}개"}
    measure(cfg, items, today, rng, sources, 30, 90)
    finalize(items, today, cfg)
    preempt_scores(items)
    for it in items:
        it["timing"] = publish_timing(it, today)
        ev = it.get("event") or {}
        it["event_line"] = event_line(ev)
        if ev.get("status") == "upcoming" and ev.get("date"):
            dd = date.fromisoformat(ev["date"])
            left = (dd - today).days
            it["timing"] = (f"행사일 {dd.month}월 {dd.day}일(D-{left}) 기준, " +
                            ("지금 바로 발행하세요." if left <= 14 else f"{max(1, left - 21)}일 안에 발행하면 좋습니다.")) + " " + it["timing"]
        elif ev.get("status") == "unknown":
            it["preempt"] = round(it["preempt"] * 0.85, 1)  # 날짜를 못 찾은 건 조금 낮춰서
    items.sort(key=lambda c: -c["preempt"])
    result_past = [{"keyword": it["keyword"], "line": event_line(it.get("event"))} for it in past[:20]]
    result = {"generated_at": now.isoformat(timespec="seconds"), "items": items, "sources": sources,
              "calendar": upcoming_calendar(today), "watchlist": cfg.get("watchlist", []), "past_events": result_past,
              "stats": {"candidates": len(cands), "items": len(items), "seconds": round(time.time() - t0)}}
    DATA.mkdir(parents=True, exist_ok=True)
    PREEMPT_PATH.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def start_job():
    with _lock:
        if JOB["running"]:
            return False
        JOB.update(running=True, log=[], result=None, error=None, stage="준비 중", pct=0)

    def worker():
        try:
            res = run_job()
            with _lock:
                JOB["result"] = res
            try:
                auto_drafts(res)
            except Exception:
                traceback.print_exc()
        except Exception as e:
            traceback.print_exc()
            with _lock:
                JOB["error"] = str(e)
        finally:
            with _lock:
                JOB["running"] = False

    threading.Thread(target=worker, daemon=True).start()
    return True


# ------------------------------------------------------------------ 저장함

def load_saved():
    try:
        return json.loads(SAVED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def write_saved(items):
    DATA.mkdir(parents=True, exist_ok=True)
    SAVED_PATH.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ 웹 서버

SECRET_KEYS = ("naver_client_id", "naver_client_secret", "searchad_api_key", "searchad_secret",
               "searchad_customer_id", "kakao_rest_key", "anthropic_api_key", "gemini_api_key")


def mask(v):
    return (v[:3] + "•" * 6 + v[-2:]) if v and len(v) > 7 else ("•" * 6 if v else "")


def check_keys(cfg):
    out = {}
    today = datetime.now(KST).date()
    if has_searchad(cfg):
        try:
            v = searchad_volumes(cfg, ["블로그"])
            out["searchad"] = {"ok": bool(v), "message": "연결됨" if v else "연결됐지만 결과가 비어 있어요"}
        except Exception as e:
            out["searchad"] = {"ok": False, "message": key_error_text(e, "검색광고")}
    else:
        out["searchad"] = {"ok": False, "message": "키를 넣어 주세요"}
    if has_naver(cfg):
        try:
            naver_call(cfg, "blog", {"query": "블로그", "display": 1})
            msg = "블로그 검색 연결됨" + (" (예전 개발자센터 키)" if _naver_mode["mode"] == "legacy" else "")
            try:
                datalab_trends(cfg, ["블로그"], today)
                msg += " · 검색어 트렌드 연결됨"
                ok = True
            except Exception as e:
                msg += " · 검색어 트렌드: " + key_error_text(e, "API HUB")
                ok = False
            out["naver"] = {"ok": ok, "message": msg}
        except Exception as e:
            out["naver"] = {"ok": False, "message": key_error_text(e, "API HUB")}
    else:
        out["naver"] = {"ok": False, "message": "키를 넣어 주세요"}
    if cfg.get("kakao_rest_key"):
        try:
            kakao_blog_total(cfg, "블로그")
            out["kakao"] = {"ok": True, "message": "연결됨"}
        except Exception as e:
            out["kakao"] = {"ok": False, "message": key_error_text(e, "카카오")}
    else:
        out["kakao"] = {"ok": False, "message": "선택 사항"}
    return out


def app_state():
    cfg = load_config()
    auto_topics = False
    if not cfg.get("topics"):  # 처음이면 고르는 단계 없이 '공연·여행 (떠나셈 맞춤)'으로 바로 시작
        cfg["topics"] = list(TOPIC_PRESETS[0]["topics"])
        save_config(cfg)
        auto_topics = True
    stage = 1 + has_searchad(cfg) + has_naver(cfg)
    td = datetime.now(KST).date()
    fmt = dict(m=td.month, s=season_of(td.month), y=td.year)
    examples = {t: [sd.format(**fmt) for sd in seeds[:2]] for t, seeds in TOPICS.items()}
    return {"topics_catalog": {g: list(ts) for g, ts in TOPIC_GROUPS.items()}, "topics": cfg["topics"],
            "topic_examples": examples, "topic_presets": TOPIC_PRESETS, "version": APP_VERSION, "data_dir": str(DATA), "auto_topics": auto_topics,
            "include_issues": cfg.get("include_issues", True), "my_keywords": cfg.get("my_keywords", []),
            "update": {k: _update[k] for k in ("latest", "notes", "available", "error")},
            "auto": {"startup": bool(startup_shortcut_path() and startup_shortcut_path().exists()),
                     "windows": os.name == "nt", "hours": cfg.get("auto_refresh_hours", 4),
                     "drafts_per_day": cfg.get("auto_draft_per_day", 2)},
            "learn": {"blog_id": cfg.get("blog_id", ""), "dislikes": cfg.get("dislikes", [])[-30:],
                      "posts": len(_myblog_cache["posts"]) if _myblog_cache["id"] else None, "error": _myblog_cache["error"]},
            "ai": {"provider": cfg.get("ai_provider", "antigravity"), "agy_path": cfg.get("agy_path", ""), "agy_model": cfg.get("agy_model", ""),
                   "antigravity": bool(_writer.find_agy(cfg.get("agy_path", ""))), "web": cfg.get("ai_web_check", True),
                   "claude_code_path": cfg.get("claude_code_path", ""), "gemini_cli_path": cfg.get("gemini_cli_path", ""),
                   "gemini_cli": bool(_writer.find_gemini_cli(cfg.get("gemini_cli_path", ""))),
                   "claude": bool(cfg.get("anthropic_api_key")), "gemini": bool(cfg.get("gemini_api_key")),
                   "gemini_model": cfg.get("gemini_model", ""), "drafts": len(WRITER.index())},
            "scale": cfg["scale"], "scales": list(SCALES), "keys": {"searchad": has_searchad(cfg), "naver": has_naver(cfg),
                                                                    "kakao": bool(cfg.get("kakao_rest_key"))},
            "level": stage, "usage": usage_today(), "limits": DAILY_LIMITS,
            "masked": {k: mask(cfg.get(k, "")) for k in SECRET_KEYS},
            "watchlist": cfg.get("watchlist", []), "site": cfg.get("site", {}), "site_boost": cfg.get("site_boost", True),
            "offer_options": list(OFFER_TRIGGERS)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            html = (STATIC / "index.html").read_text(encoding="utf-8")
            html = html.replace("/static/app.css", f"/static/app.css?v={APP_VERSION}").replace(
                "/static/app.js", f"/static/app.js?v={APP_VERSION}")
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/version":
            return self._send(200, {"version": APP_VERSION})
        if path.startswith("/static/"):
            name = path[len("/static/"):]
            f = STATIC / name
            types = {".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                     ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2"}
            if not re.fullmatch(r"(fonts/)?[\w.-]+", name) or not f.exists() or f.suffix not in types:
                return self._send(404, {"error": "not found"})
            return self._send(200, f.read_bytes(), types[f.suffix])
        if path == "/api/state":
            return self._send(200, app_state())
        if path == "/api/status":
            with _lock:
                return self._send(200, {"running": JOB["running"], "log": JOB["log"][-30:], "error": JOB["error"],
                                        "stage": JOB["stage"], "pct": JOB["pct"],
                                        "result_id": (JOB["result"] or {}).get("id")})
        if path == "/api/history":
            return self._send(200, list_history())
        if path.startswith("/api/history/"):
            rid = path.rsplit("/", 1)[-1]
            p = HISTORY / f"{rid}.json"
            if not re.fullmatch(r"[\d_-]+", rid) or not p.exists():
                return self._send(404, {"error": "not found"})
            d = json.loads(p.read_text(encoding="utf-8"))
            d["id"] = rid
            return self._send(200, d)
        if path == "/api/saved":
            return self._send(200, load_saved())
        if path == "/api/ideas":
            k = norm(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("keyword", [""])[0])
            st = IDEAS.get(k) or {}
            return self._send(200, {"running": bool(st.get("running")), "ideas": st.get("ideas", []), "error": st.get("error", ""),
                                    "seconds": round(time.time() - st["started"]) if st.get("started") else 0})
        if path == "/api/update/check":
            return self._send(200, {**check_update(force=True), "current": APP_VERSION})
        if path == "/api/draft/status":
            return self._send(200, draft_status())
        if path == "/api/drafts":
            return self._send(200, WRITER.index())
        m = re.fullmatch(r"/api/drafts/([\w\-]+)(/docx)?", path)
        if m:
            rec = WRITER.get(m.group(1))
            if not rec:
                return self._send(404, {"error": "초안을 찾지 못했어요"})
            if m.group(2):
                data = _writer.build_docx(rec["text"], rec.get("title") or rec["keyword"])
                name = _writer.docx_filename(rec)
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                self.send_header("Content-Disposition", "attachment; filename=\"draft.docx\"; filename*=UTF-8''" + urllib.parse.quote(name))
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            return self._send(200, rec)
        if path == "/api/memory":
            return self._send(200, {"guide": WRITER.guide(), "memory": _writer.build_memory(WRITER, load_config(), load_saved()),
                                    "guide_path": str(WRITER.guide_path), "memory_path": str(WRITER.memory_path)})
        if path == "/api/hot":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._send(200, hot_now(refresh=q.get("refresh") == ["1"]))
        if path == "/api/evergreen":
            chk = load_eg_check()
            return self._send(200, {"topics": EVERGREEN, "meta": EVERGREEN_META, "results": chk.get("results", {}), "checked_at": chk.get("checked_at"),
                                    "level": chk.get("level"), "job": EG_JOB,
                                    "count": sum(len(v) for v in EVERGREEN.values())})
        if path == "/api/news":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            data = news_cached(refresh=q.get("refresh") == ["1"])
            return self._send(200, {"sections": data, "dropped": NEWS_DROPPED,
                                    "fetched_at": datetime.fromtimestamp(_news_cache["at"], KST).isoformat(timespec="seconds")})
        if path == "/api/preempt":
            try:
                return self._send(200, json.loads(PREEMPT_PATH.read_text(encoding="utf-8")))
            except Exception:
                return self._send(200, {"items": None, "calendar": upcoming_calendar(datetime.now(KST).date())})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        # 설정을 바꾸는 요청은 한 번에 하나씩: 동시에 들어와도 서로 덮어쓰지 않게
        if urllib.parse.urlparse(self.path).path in ("/api/prefs", "/api/keys", "/api/autostart"):
            with _cfg_lock:
                return self._do_post()
        return self._do_post()

    def _do_post(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except ValueError:
            return self._send(400, {"error": "잘못된 요청"})
        if path == "/api/generate":
            ok = start_job()
            return self._send(200 if ok else 409, {"started": ok})
        if path == "/api/prefs":
            cfg = load_config()
            if isinstance(body.get("topics"), list):
                cfg["topics"] = [t for t in body["topics"] if t in TOPICS]
            if "include_issues" in body:
                cfg["include_issues"] = bool(body["include_issues"])
            if isinstance(body.get("my_keywords"), list):
                cfg["my_keywords"] = [str(k).strip()[:40] for k in body["my_keywords"] if str(k).strip()][:30]
            if body.get("scale") in SCALES:
                cfg["scale"] = body["scale"]
            if isinstance(body.get("watchlist"), list):
                cfg["watchlist"] = [str(k).strip()[:30] for k in body["watchlist"] if str(k).strip()][:20]
            if isinstance(body.get("site"), dict):
                st = body["site"]
                cfg["site"] = {"name": str(st.get("name", "")).strip()[:30], "url": str(st.get("url", "")).strip()[:200],
                               "offers": [o for o in st.get("offers", []) if o in OFFER_TRIGGERS]}
            if "site_boost" in body:
                cfg["site_boost"] = bool(body["site_boost"])
            if "blog_id" in body:
                cfg["blog_id"] = re.sub(r"[^\w\-./:]", "", str(body["blog_id"]))[:80]
                _myblog_cache["at"] = 0
            if "auto_draft_per_day" in body:
                try:
                    cfg["auto_draft_per_day"] = max(0, min(5, int(body["auto_draft_per_day"])))
                except Exception:
                    pass
            if "auto_refresh_hours" in body:
                try:
                    cfg["auto_refresh_hours"] = max(0, min(24, float(body["auto_refresh_hours"])))
                except Exception:
                    pass
            if isinstance(body.get("dislike"), str) and body["dislike"].strip():
                d = body["dislike"].strip()[:60]
                cfg["dislikes"] = [x for x in cfg.get("dislikes", []) if x != d][-99:] + [d]
            if isinstance(body.get("undislike"), str):
                cfg["dislikes"] = [x for x in cfg.get("dislikes", []) if x != body["undislike"]]
            if "claude_code_path" in body:
                cfg["claude_code_path"] = str(body["claude_code_path"]).strip().strip('"')[:300]
            if "agy_path" in body:
                cfg["agy_path"] = str(body["agy_path"]).strip().strip('"')[:300]
            if "agy_model" in body:
                cfg["agy_model"] = re.sub(r"[^\w.\- ]", "", str(body["agy_model"]))[:60].strip()
            if "gemini_cli_path" in body:
                cfg["gemini_cli_path"] = str(body["gemini_cli_path"]).strip().strip('"')[:300]
            if body.get("ai_provider") in ("antigravity", "manual", "claude_code"):  # 유료 API 방식은 선택 불가
                cfg["ai_provider"] = body["ai_provider"]
            if "ai_web_check" in body:
                cfg["ai_web_check"] = bool(body["ai_web_check"])
            if "gemini_model" in body:
                cfg["gemini_model"] = re.sub(r"[^\w.\-]", "", str(body["gemini_model"]))[:60]
            save_config(cfg)
            return self._send(200, app_state())
        if path == "/api/preempt":
            try:
                return self._send(200, run_preempt())
            except Exception as e:
                traceback.print_exc()
                return self._send(500, {"error": f"선제 글감을 찾지 못했어요: {e}"})
        if path == "/api/autostart":
            ok, msg = set_autostart(bool(body.get("on")))
            return self._send(200 if ok else 400, {"ok": ok, "message": msg, "state": app_state()} if ok else {"error": msg})
        if path == "/api/myblog":
            posts = my_blog_posts(load_config(), refresh=True)
            return self._send(200, {"posts": posts, "error": _myblog_cache["error"]})
        if path == "/api/ai/check":
            return self._send(200, _writer.check_ai(load_config()))
        if path == "/api/draft/prompt":
            item = body.get("item") or {}
            return self._send(200, _writer.manual_prompt(WRITER, cfg_with_posts(), item, load_saved(), datetime.now(KST).date()))
        if path == "/api/draft/import":
            item = body.get("item") or {}
            try:
                where = str(body.get("where", "붙여넣기"))[:30]
                rec = _writer.save_draft(WRITER, load_config(), item, load_saved(), str(body.get("text", "")),
                                         "manual", where, None)
                return self._send(200, rec)
            except _writer.WriterError as e:
                return self._send(400, {"error": str(e)})
        if path == "/api/update/apply":
            ok, msg = apply_update()
            return self._send(200 if ok else 400, {"ok": ok, "message": msg} if ok else {"error": msg})
        if path == "/api/draft/cancel":
            j = body.get("job")
            ok = cancel_draft(int(j) if isinstance(j, (int, float, str)) and str(j).isdigit() else None)
            return self._send(200, {"ok": ok, "status": draft_status()})
        if path == "/api/draft":
            item = body.get("item")
            if not isinstance(item, dict) or not item.get("keyword"):
                return self._send(400, {"error": "어떤 글감으로 쓸지 정보가 없어요"})
            cfg = load_config()
            if cfg.get("ai_provider") == "manual":
                return self._send(400, {"error": "붙여넣기 방식에서는 요청문을 복사해 붙여 넣어 주세요."})
            if not ai_ready(cfg):
                return self._send(400, {"error": "글을 쓸 AI가 연결되지 않았어요. 설정 → AI 글쓰기에서 Gemini CLI 설치·로그인을 확인해 주세요."})
            job = enqueue_draft(item)
            return self._send(200, {"queued": True, "job": abs(job), "already": job < 0, "status": draft_status()})
        m = re.fullmatch(r"/api/drafts/([\w\-]+)", path)
        if m:
            act = body.get("action")
            if act == "delete":
                WRITER.delete(m.group(1))
                return self._send(200, WRITER.index())
            rec = WRITER.update(m.group(1), text=body.get("text") if act == "save" else None,
                                status=body.get("status") if act == "status" else None)
            if not rec:
                return self._send(404, {"error": "초안을 찾지 못했어요"})
            _writer.build_memory(WRITER, load_config(), load_saved())
            return self._send(200, WRITER.get(m.group(1)))
        if path == "/api/memory":
            if body.get("reset_guide"):
                WRITER.save_guide(WRITER.default_guide())
            elif isinstance(body.get("guide"), str) and body["guide"].strip():
                WRITER.save_guide(body["guide"][:60000])
            return self._send(200, {"guide": WRITER.guide()})
        if path == "/api/evergreen/check":
            start_evergreen_check()
            return self._send(200, {"job": EG_JOB})
        if path == "/api/measure":
            kw = str(body.get("keyword", "")).strip()[:60]
            if not kw:
                return self._send(400, {"error": "키워드가 없어요"})
            try:
                return self._send(200, measure_one(kw))
            except Exception as e:
                traceback.print_exc()
                return self._send(500, {"error": f"측정하지 못했어요: {e}"})
        if path == "/api/analyze":
            kw = str(body.get("keyword", "")).strip()
            if not kw:
                return self._send(400, {"error": "키워드를 입력해 주세요"})
            try:
                ctx = None
                if body.get("section"):
                    ctx = {"section": str(body.get("section"))[:20], "title": str(body.get("title", "")),
                           "source": str(body.get("source", "")), "link": str(body.get("link", ""))}
                return self._send(200, analyze_keyword(kw, ctx))
            except Exception as e:
                traceback.print_exc()
                return self._send(500, {"error": f"분석하지 못했어요: {e}"})
        if path == "/api/ideas":
            kw = str(body.get("keyword", "")).strip()[:40]
            if not kw:
                return self._send(400, {"error": "키워드가 없어요"})
            cfg = load_config()
            if not ai_ready(cfg):
                return self._send(400, {"error": "AI가 연결되지 않았어요. 설정 → AI 글쓰기에서 Antigravity(또는 Claude Max)를 연결해 주세요."})
            items = body.get("items") if isinstance(body.get("items"), list) else []
            start_ideas(kw, items)
            return self._send(200, {"ok": True})
        if path == "/api/saved":
            saved = load_saved()
            act = body.get("action")
            if act == "add" and isinstance(body.get("item"), dict):
                it = body["item"]
                if not any(s["item"]["keyword"] == it.get("keyword") for s in saved):
                    saved.insert(0, {"item": it, "status": "쓸 예정",
                                     "saved_at": datetime.now(KST).isoformat(timespec="seconds")})
            elif act == "status":
                for s in saved:
                    if s["item"]["keyword"] == body.get("keyword"):
                        s["status"] = body.get("status", "쓸 예정")
            elif act == "remove":
                saved = [s for s in saved if s["item"]["keyword"] != body.get("keyword")]
            write_saved(saved)
            return self._send(200, saved)
        if path == "/api/keys":
            cfg = load_config()
            for k in SECRET_KEYS:  # 비워 두면 기존 값 유지, 지우려면 clear 목록에
                v = str(body.get(k, "")).strip()
                if v and "•" not in v:
                    cfg[k] = v
            for k in body.get("clear", []):
                if k in SECRET_KEYS:
                    cfg[k] = ""
            save_config(cfg)
            _naver_mode["mode"] = None
            return self._send(200, app_state())
        if path == "/api/shutdown":
            # 새 버전이 실행되면서 예전 버전을 끌 때 사용 (이 PC 안에서만 접근 가능)
            if self.client_address[0] != "127.0.0.1":
                return self._send(403, {"error": "forbidden"})
            self._send(200, {"ok": True, "version": APP_VERSION})
            threading.Timer(0.3, lambda: os._exit(0)).start()
            return
        if path == "/api/keys/check":
            _naver_mode["mode"] = None
            return self._send(200, check_keys(load_config()))
        self._send(404, {"error": "not found"})


def find_old_data():
    """예전 버전처럼 프로그램 폴더 안 data 폴더에 키가 있으면 찾아냄 (이 폴더 → 다운로드·바탕화면·문서 순)."""
    found = []
    here = BASE / "data" / "config.json"
    if here.exists():
        found.append(here)
    home = Path.home()
    roots = [home / n for n in ("Downloads", "Desktop", "Documents", "다운로드", "바탕 화면", "문서")]
    roots += [home / "OneDrive" / n for n in ("Desktop", "Documents", "바탕 화면", "문서")]
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in ("*/data/config.json", "*/*/data/config.json", "*/*/*/data/config.json"):
            try:
                for cfgp in root.glob(pattern):
                    if (cfgp.parent.parent / "app.py").exists():
                        found.append(cfgp)
            except OSError:
                pass
    return max(found, key=lambda x: x.stat().st_mtime).parent if found else None


def migrate_old_data():
    if (DATA / "config.json").exists():
        return None
    old = find_old_data()
    if not old:
        return None
    DATA.mkdir(parents=True, exist_ok=True)
    for item in old.iterdir():
        dst = DATA / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst)
    return old


def port_free(port):
    try:
        t = ThreadingHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
        t.server_close()
        return True
    except OSError:
        return False


def stop_old_version(port):
    """포트를 차지한 예전 키워드 플래너를 끔. 우리 프로그램(/api/version 응답)일 때만 시도."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        pass
    for _ in range(10):
        if port_free(port):
            return True
        time.sleep(0.3)
    if sys.platform.startswith("win"):  # 종료 요청을 모르는 예전 버전: 그 포트를 듣는 프로세스를 직접 종료
        try:
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10).stdout
            pids = set()
            for line in out.splitlines():  # 예: TCP  127.0.0.1:8765  0.0.0.0:0  LISTENING  12345 (상태 글자는 언어별로 다를 수 있어 주소로 판별)
                parts = line.split()
                if len(parts) >= 4 and parts[1] == f"127.0.0.1:{port}" and parts[2] in ("0.0.0.0:0", "[::]:0", "*:*"):
                    pids.add(parts[-1])
            for pid in pids:
                if pid.isdigit() and int(pid) != os.getpid():
                    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=10)
        except Exception:
            pass
        for _ in range(10):
            if port_free(port):
                return True
            time.sleep(0.3)
    return False


def cfg_with_posts():
    cfg = load_config()
    try:
        cfg["_my_posts"] = my_blog_posts(cfg)
    except Exception:
        cfg["_my_posts"] = []
    return cfg


# ---------- 초안 작성 큐: 프로그램이 직접 씀 (누른 글감 + 자동으로 미리 쓰는 글감) ----------
DRAFT_Q = {"queue": [], "current": None, "events": [], "seq": 0}
_dq_lock = threading.Lock()
_dq_wake = threading.Event()


def enqueue_draft(item, auto=False):
    with _dq_lock:
        k = norm(item.get("keyword", ""))
        same = [j for j in ([DRAFT_Q["current"]] if DRAFT_Q["current"] else []) + DRAFT_Q["queue"] if norm(j["item"]["keyword"]) == k]
        if same:  # 이미 쓰는 중(자동 포함)이면 그 작업을 그대로 기다림
            if not auto:
                same[0]["auto"] = False
            return -same[0]["job"]
        DRAFT_Q["seq"] += 1
        job = {"job": DRAFT_Q["seq"], "item": item, "auto": auto, "keyword": item.get("keyword", "")}
        if auto:
            DRAFT_Q["queue"].append(job)
        else:  # 직접 누른 글감은 자동 초안보다 먼저
            n = next((i for i, q in enumerate(DRAFT_Q["queue"]) if q["auto"]), len(DRAFT_Q["queue"]))
            DRAFT_Q["queue"].insert(n, job)
    _dq_wake.set()
    return job["job"]


def cancel_draft(job=None):
    """job이 없으면 쓰는 중인 것 + 대기 중인 것 모두 취소."""
    with _dq_lock:
        cur = DRAFT_Q["current"]
        hit = False
        if job is None or (cur and cur["job"] == job):
            if cur:
                _writer.CANCEL.set()
                hit = True
        before = len(DRAFT_Q["queue"])
        DRAFT_Q["queue"] = [q for q in DRAFT_Q["queue"] if job is not None and q["job"] != job]
        removed = before - len(DRAFT_Q["queue"])
        return hit or removed > 0


def draft_status():
    with _dq_lock:
        cur = DRAFT_Q["current"]
        return {"current": {k: cur[k] for k in ("job", "keyword", "auto", "stage", "started")} if cur else None,
                "queue": [{"job": q["job"], "keyword": q["keyword"], "auto": q["auto"]} for q in DRAFT_Q["queue"]],
                "events": DRAFT_Q["events"][-15:]}


def draft_worker():
    while True:
        _dq_wake.wait(30)
        _dq_wake.clear()
        while True:
            with _dq_lock:
                if not DRAFT_Q["queue"]:
                    break
                job = DRAFT_Q["queue"].pop(0)
                job.update(stage="준비 중", started=time.time())
                _writer.CANCEL.clear()
                DRAFT_Q["current"] = job
            ev = {"job": job["job"], "keyword": job["keyword"], "auto": job["auto"], "item_id": job["item"].get("id"), "at": datetime.now(KST).isoformat(timespec="seconds")}
            try:
                cfg = cfg_with_posts()
                cfg["_auto"] = job["auto"]

                def say(msg, job=job):
                    job["stage"] = msg
                rec = _writer.make_draft(WRITER, cfg, job["item"], load_saved(), datetime.now(KST).date(), progress=say)
                ev.update(ok=True, id=rec["id"], title=rec.get("title", ""), check=f"{rec['check']['passed']}/{rec['check']['total']}")
                print(f"[{datetime.now(KST):%H:%M}] 초안 완성{' (자동)' if job['auto'] else ''}: {job['keyword']} · 양식 {ev['check']}")
            except _writer.DraftCancelled:
                ev.update(ok=False, cancelled=True, error="취소했어요")
                print(f"[{datetime.now(KST):%H:%M}] 초안 취소: {job['keyword']}")
            except _writer.WriterError as e:
                ev.update(ok=False, error=str(e))
            except Exception as e:
                traceback.print_exc()
                ev.update(ok=False, error=f"초안을 쓰지 못했어요: {e}")
            with _dq_lock:
                DRAFT_Q["current"] = None
                DRAFT_Q["events"] = (DRAFT_Q["events"] + [ev])[-30:]


def ai_ready(cfg):
    p = cfg.get("ai_provider", "antigravity")
    if p == "antigravity":
        return bool(_writer.find_agy(cfg.get("agy_path", "")))
    if p == "gemini_cli":
        return bool(_writer.find_gemini_cli(cfg.get("gemini_cli_path", "")))
    if p == "claude_code":
        return bool(_writer.find_claude_code(cfg.get("claude_code_path", "")))
    return False  # 붙여넣기·유료 API는 자동으로 쓰지 않음  # 붙여넣기는 자동으로 쓸 수 없음


def auto_drafts(result):
    """분석이 끝나면 오늘의 추천 상위 글감으로 초안을 미리 써 둠 (하루 N편, 이미 쓴 글감·관심 없음·내 블로그에 있는 주제는 건너뜀)."""
    cfg = load_config()
    try:
        per_day = int(float(cfg.get("auto_draft_per_day", 2) or 0))
    except Exception:
        per_day = 0
    if per_day <= 0 or not ai_ready(cfg) or not result:
        return
    today = datetime.now(KST).date().isoformat()
    idx = WRITER.index()
    done_today = sum(1 for r in idx if r.get("auto") and (r.get("created_at") or "").startswith(today))
    with _dq_lock:
        done_today += sum(1 for q in DRAFT_Q["queue"] if q["auto"]) + (1 if DRAFT_Q["current"] and DRAFT_Q["current"]["auto"] else 0)
    room = per_day - done_today
    if room <= 0:
        return
    written = {norm(r.get("keyword", "")) for r in idx}
    items = {c["id"]: c for t in result.get("topics", []) for c in t.get("items", [])}
    for cid in result.get("top", []):
        c = items.get(cid)
        if not c or c.get("learned") in ("dislike", "written") or norm(c["keyword"]) in written:
            continue
        if (enqueue_draft(c, auto=True) or 0) > 0:
            print(f"  → 자동 초안 예약: {c['keyword']}")
            room -= 1
        if room <= 0:
            break


# ---------- 자동 업데이트: GitHub 공개 저장소에서 새 버전을 받아 스스로 교체 (키·초안·설정은 AppData에 있어 그대로) ----------
UPDATE_REPO = "mielle3/keyword-planner"
UPDATE_FILES = ("app.py", "writer.py", "writer_guide.md", "README.md", "실행_윈도우.bat",
                "START_windows.bat", "실행_맥.command", "STOP_keywordplanner.bat")
_update = {"checked": 0, "latest": "", "notes": "", "available": False, "error": "", "applying": False}


def _ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def check_update(force=False):
    if not force and time.time() - _update["checked"] < 3600:
        return dict(_update)
    try:
        raw = http_get(f"https://raw.githubusercontent.com/{UPDATE_REPO}/main/version.json?t={int(time.time())}", timeout=10)
        info = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        latest = str(info.get("version", ""))
        _update.update(checked=time.time(), latest=latest, notes=str(info.get("notes", ""))[:300], error="",
                       available=_ver_tuple(latest) > _ver_tuple(APP_VERSION))
    except Exception as e:
        _update.update(checked=time.time(), error=f"새 버전 확인 실패({type(e).__name__})")
    return dict(_update)


def apply_update():
    """새 버전 zip을 받아 → 문법 검사 → 지금 파일을 백업 → 교체 → 새 버전을 띄움(새 버전이 이 창을 끄고 이어받음)."""
    import io, py_compile, shutil, zipfile
    if _update["applying"]:
        return False, "이미 업데이트 중이에요."
    _update["applying"] = True
    try:
        data = urllib.request.urlopen(urllib.request.Request(
            f"https://codeload.github.com/{UPDATE_REPO}/zip/refs/heads/main", headers={"User-Agent": "KeywordPlanner"}), timeout=60).read()
        tmp = DATA / "update_tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(tmp)
        roots = [p for p in tmp.iterdir() if p.is_dir()]
        if not roots or not (roots[0] / "app.py").exists():
            raise RuntimeError("받은 파일에 app.py가 없어요")
        src = roots[0]
        for f in ("app.py", "writer.py"):  # 깨진 파일로 바꾸지 않게
            py_compile.compile(str(src / f), doraise=True, cfile=str(tmp / (f + "c")))
        here = Path(__file__).parent
        bak = DATA / "backup" / APP_VERSION
        bak.mkdir(parents=True, exist_ok=True)
        for f in UPDATE_FILES:
            if (here / f).exists():
                shutil.copy2(here / f, bak / f)
            if (src / f).exists():
                shutil.copy2(src / f, here / f)
        if (src / "static").is_dir():
            if (here / "static").is_dir():
                shutil.copytree(here / "static", bak / "static", dirs_exist_ok=True)
            shutil.copytree(src / "static", here / "static", dirs_exist_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
        flags = 0x00000010 if os.name == "nt" else 0  # 새 검은 창에서 실행
        subprocess.Popen([sys.executable, str(here / "app.py"), "--no-browser"], cwd=str(here), creationflags=flags,
                         start_new_session=(os.name != "nt"))
        return True, f"업데이트를 받았어요. 새 버전으로 다시 시작합니다. (예전 파일 백업: {bak})"
    except Exception as e:
        traceback.print_exc()
        return False, f"업데이트하지 못했어요: {e}"
    finally:
        _update["applying"] = False


def update_loop():
    time.sleep(15)
    while True:
        try:
            check_update(force=True)
        except Exception:
            pass
        time.sleep(6 * 3600)


def startup_shortcut_path():
    appdata = os.environ.get("APPDATA")
    if os.name != "nt" or not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "KeywordPlanner.lnk"


def set_autostart(on):
    """윈도우 시작프로그램에 바로가기를 만들거나 지움. 켜질 때는 창을 최소화하고 브라우저는 열지 않음."""
    lnk = startup_shortcut_path()
    if not lnk:
        return False, "윈도우에서만 쓸 수 있어요."
    if not on:
        try:
            lnk.unlink()
        except FileNotFoundError:
            pass
        return True, "자동 실행을 껐어요."
    bat = Path(__file__).parent / "START_windows.bat"
    if not bat.exists():
        bat = Path(__file__).parent / "실행_윈도우.bat"
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
          "$s.TargetPath=$env:BAT;$s.Arguments='--no-browser';$s.WorkingDirectory=$env:DIR;$s.WindowStyle=7;"
          "$s.Description='KeywordPlanner auto start';$s.Save()")
    env = dict(os.environ, LNK=str(lnk), BAT=str(bat), DIR=str(bat.parent))
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], env=env,
                       capture_output=True, timeout=30, creationflags=0x08000000)
    except Exception as e:
        return False, f"바로가기를 만들지 못했어요: {e}"
    return (lnk.exists(), "컴퓨터를 켜면 자동으로 실행돼요(창은 최소화, 브라우저는 안 열림)." if lnk.exists()
            else "바로가기를 만들지 못했어요. 이 폴더를 옮겼다면 다시 켜 주세요.")


def auto_refresh_loop():
    """프로그램이 켜져 있는 동안 스스로 다시 분석: 마지막 분석 후 N시간(기본 4)이 지나면, 오전 7시~밤 11시 사이에."""
    time.sleep(20)
    while True:
        try:
            cfg = load_config()
            hours = float(cfg.get("auto_refresh_hours", 4) or 0)
            now = datetime.now(KST)
            if hours > 0 and 7 <= now.hour < 23 and cfg.get("topics") and not JOB["running"]:
                files = sorted(HISTORY.glob("*.json"), reverse=True) if HISTORY.exists() else []
                last = None
                if files:
                    try:
                        last = datetime.fromisoformat(json.loads(files[0].read_text(encoding="utf-8"))["generated_at"])
                    except Exception:
                        last = None
                if last is None or (now - last).total_seconds() > hours * 3600:
                    print(f"[{now:%H:%M}] 자동 업데이트: 마지막 분석 후 {hours:g}시간이 지나 새로 분석합니다.")
                    start_job()
        except Exception:
            traceback.print_exc()
        time.sleep(600)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        moved = migrate_old_data()
        if moved:
            print(f"※ 예전 버전의 키와 기록을 가져왔어요: {moved}")
    except Exception as e:
        print(f"※ 예전 키를 가져오지 못했어요 ({e}). 설정에서 다시 넣어 주세요.")
    print(f"  키·기록 저장 위치: {DATA}")
    cfg = load_config()
    base_port = int(cfg.get("port", 8765))
    srv, port, old_running = None, base_port, False
    for port in range(base_port, base_port + 10):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            # 이 포트에 이미 무언가 떠 있음: 같은 버전이면 그 창을 그대로 열고, 예전 버전이면 다음 포트로
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version", timeout=2) as r:
                    running = json.loads(r.read().decode("utf-8")).get("version")
            except Exception:
                running = None
            if running == APP_VERSION:
                print(f"이미 실행 중이에요. 브라우저에서 http://127.0.0.1:{port} 을 열게요.")
                webbrowser.open(f"http://127.0.0.1:{port}")
                return
            if running and stop_old_version(port):  # 예전 버전이면 끄고 이 자리를 이어받음
                print(f"※ 예전 버전({running})을 끄고 새 버전으로 바꿨어요.")
                try:
                    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
                    break
                except OSError:
                    pass
            old_running = True
    if srv is None:
        print("빈 포트를 찾지 못했어요. 열려 있는 검은 창을 모두 닫고 다시 실행해 주세요.")
        input("엔터를 누르면 닫힙니다.")
        return
    url = f"http://127.0.0.1:{port}"
    if old_running:
        print("※ 예전 버전의 키워드 플래너 창이 아직 켜져 있어요. 그 검은 창은 닫아도 됩니다.")
    print("=" * 56)
    print(f"  키워드 플래너 {APP_VERSION} 실행 중  →  {url}")
    print("  이 창을 닫으면 프로그램이 종료됩니다.")
    print("=" * 56)
    threading.Thread(target=auto_refresh_loop, daemon=True).start()
    threading.Thread(target=draft_worker, daemon=True).start()
    threading.Thread(target=update_loop, daemon=True).start()
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("종료합니다.")


class _QueuedWriter:
    """print가 검은 창 때문에 멈춰도(윈도우 '선택' 모드 등) 분석은 계속되도록, 실제 출력은 뒤에서 따로 함."""

    def __init__(self, real):
        import queue
        self.real, self.q = real, queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            txt = self.q.get()
            try:
                self.real.write(txt)
                self.real.flush()
            except Exception:
                pass

    def write(self, txt):
        self.q.put(txt)
        return len(txt)

    def flush(self):
        pass

    def isatty(self):
        return False


def disable_quick_edit():
    """윈도우 명령 창의 '빠른 편집(선택) 모드'를 끔: 창을 클릭해도 프로그램이 멈추지 않게."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-10)  # 입력 핸들
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(h, ctypes.byref(mode)):
            k32.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080)  # QUICK_EDIT 끄고 EXTENDED_FLAGS 켬
    except Exception:
        pass


if __name__ == "__main__":
    # 윈도우 콘솔에서 이모지·특수문자 때문에 멈추지 않게
    for _st in (sys.stdout, sys.stderr):
        try:
            _st.reconfigure(errors="replace")
        except Exception:
            pass
    disable_quick_edit()
    sys.stdout, sys.stderr = _QueuedWriter(sys.stdout), _QueuedWriter(sys.stderr)
    print(f"  Python {sys.version.split()[0]} · 키워드 플래너 {APP_VERSION}")
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        print("\n[오류] 프로그램이 멈췄어요. 아래 내용을 캡처해서 보내 주세요.\n")
        print(err)
        for d in (DATA, Path(__file__).parent):
            try:
                (d / "오류기록.txt").write_text(f"{datetime.now(KST).isoformat()} {APP_VERSION}\n{err}", encoding="utf-8")
                print(f"오류 내용을 저장했어요: {d / '오류기록.txt'}")
                break
            except Exception:
                pass
        try:
            input("엔터를 누르면 닫힙니다.")
        except Exception:
            pass
