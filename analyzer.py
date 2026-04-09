"""
ReviewMiner — 분석 엔진 v3.1
피드백 반영:
  - crawl_product_detail 실패 시 즉시 예외 발생 (조용한 샘플 대체 제거)
  - 다중 정렬(REVIEW_RANKING + RECENT + LOW_RATING) 수집 지원
  - penetration_rate → review_share (명칭 정확화)
  - 버전 표기 통일 v3
  - 감성 분석 한계 명시 (힌트용 레이블 추가)
"""

import re
import time
import random
import requests
from bs4 import BeautifulSoup
from collections import Counter, defaultdict
from datetime import datetime
import pandas as pd


# ──────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────
POSITIVE_KEYWORDS = {
    '인생': 5, '최고': 4, '완벽': 4, '강추': 4, '만족': 3,
    '편안': 2, '괜찮': 2, '추천': 3, '좋았': 2, '훌륭': 3,
}
NEGATIVE_KEYWORDS = {
    '실망': -4, '최악': -5, '불편': -3, '아쉬': -2, '별로': -2,
    '불만': -3, '후회': -4, '돈아깝': -5, '흔들': -2, '삐걱': -3,
}
NEGATION_PATTERNS = [
    r'(안\s*|전혀\s*|절대\s*)(\S{1,6})',
    r'(\S{1,6})(하지\s*않|지\s*않)',
]
STOPWORDS = {
    '정말','너무','진짜','매우','배송','빨라요','포장',
    '감사합니다','잘받았습니다','감사','빠르게','친절','오늘',
    '이거','제품','상품','구매','구입','사용','사용해','했어요',
    '합니다','해요','있어요','없어요','같아요','같습니다',
}
PHRASE_STOPWORDS = {
    '정말','너무','진짜','아주','그냥','조금','많이',
    '배송','포장','감사','감사합니다','잘받았습니다',
    '구매','구입','제품','상품','사용','사용했습니다',
    '합니다','했어요','있어요','없어요','같아요','좋아요',
}

SORT_ORDERS = ['REVIEW_RANKING', 'RECENT', 'LOW_SCORE']


# ──────────────────────────────────────────────────────────
# 예외 클래스
# ──────────────────────────────────────────────────────────
class CrawlError(Exception):
    """크롤링 실패 — 조용히 대체하지 않고 명시적으로 올림"""


# ──────────────────────────────────────────────────────────
# 메인 클래스
# ──────────────────────────────────────────────────────────
class NaverReviewAnalyzer:

    def __init__(self, product_url: str, cookie: str = ''):
        self.product_url = product_url.strip()
        self.product_id  = self._extract_product_id(self.product_url)
        if not self.product_id:
            raise CrawlError(
                f"URL에서 product_id를 추출할 수 없습니다.\n"
                f"올바른 형식: https://smartstore.naver.com/가게명/products/숫자ID\n"
                f"입력된 URL: {product_url}"
            )
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept':          'application/json, text/html, */*',
            'Accept-Language': 'ko-KR,ko;q=0.9',
            'Referer':         self.product_url,
        }
        if cookie:
            headers['Cookie'] = cookie
        self.session = requests.Session()
        self.session.headers.update(headers)
        self.reviews:      list = []
        self.product_info: dict = {}

    # ─── 유틸 ──────────────────────────────────
    @staticmethod
    def _extract_product_id(url: str):
        m = re.search(r'/products/(\d+)', url)
        return m.group(1) if m else None

    def _sentiment_score(self, text: str) -> float:
        """약식 힌트용 감성 점수 (정밀 분석 아님)"""
        negated = set()
        for pat in NEGATION_PATTERNS:
            for m in re.finditer(pat, text):
                negated.add(m.group(0))
        score = 0.0
        for w, v in POSITIVE_KEYWORDS.items():
            if w in text:
                score += -v if any(w in n for n in negated) else v
        for w, v in NEGATIVE_KEYWORDS.items():
            if w in text:
                score += -v if any(w in n for n in negated) else v
        return score

    # ─── 1) 상품 정보 ──────────────────────────
    def crawl_product_detail(self) -> dict:
        """
        실패 시 샘플로 대체하지 않고 CrawlError를 올린다.
        상품명/가격 없이 리뷰만 분석하는 옵션을 원하면
        호출자가 try-except로 처리할 것.
        """
        try:
            resp = self.session.get(self.product_url, timeout=12)
            resp.raise_for_status()
        except Exception as e:
            raise CrawlError(f"상품 페이지 요청 실패: {e}")

        soup = BeautifulSoup(resp.text, 'html.parser')

        def first(selectors):
            for sel in selectors:
                tag = soup.select_one(sel)
                if tag and tag.text.strip():
                    return tag.text.strip()
            return None

        def multi(selectors):
            for sel in selectors:
                tags = soup.select(sel)
                if tags:
                    return [t.text.strip() for t in tags if t.text.strip()]
            return []

        name = first(['h3._22kNQuEXmb', 'h3[class*="Product_title"]',
                       '[class*="productTitle"]', 'h1'])
        price = first(['span.bd_2tcyy', 'span[class*="price"]',
                        'strong[class*="price"]'])
        opts  = multi(['button._3S2pRql9KW', 'button[class*="option"]',
                        'li[class*="option"]'])

        # 상품명이 없으면 셀렉터가 깨진 것 — 사용자에게 알림
        if not name:
            raise CrawlError(
                "상품명을 찾지 못했습니다. 네이버 HTML 구조가 변경됐을 수 있습니다.\n"
                "URL이 실제 상품 페이지인지 확인하거나, 잠시 후 다시 시도해주세요."
            )

        self.product_info = {
            'name':    name,
            'price':   price or '가격 정보 없음',
            'options': opts,
            'url':     self.product_url,
        }
        return self.product_info

    # ─── 2) 리뷰 수집 ──────────────────────────
    def crawl_reviews(
        self,
        max_reviews: int = 500,
        sort_orders: list = None,
        delay_base: float = 1.5,
        progress_cb=None,        # fn(message: str, pct: float)
    ) -> list:
        """
        sort_orders: 여러 정렬로 수집 후 합산 (기본: RANKING + RECENT + LOW_SCORE)
        progress_cb: Streamlit 등 UI에 진행 상황 콜백
        """
        if sort_orders is None:
            sort_orders = SORT_ORDERS

        all_seen:  set  = set()
        all_data:  list = []
        base_url = (
            f"https://smartstore.naver.com/i/v1/reviews/products/{self.product_id}"
        )
        per_sort = max(max_reviews // len(sort_orders), 20)

        for sort_idx, sort_order in enumerate(sort_orders):
            sort_label = {'REVIEW_RANKING':'도움순','RECENT':'최신순',
                          'LOW_SCORE':'낮은평점순'}.get(sort_order, sort_order)
            page        = 1
            total_pages = None

            while True:
                if len(all_data) >= max_reviews:
                    break

                try:
                    params = {'page': page, 'pageSize': 20, 'sort': sort_order}
                    resp   = self.session.get(base_url, params=params, timeout=12)

                    if resp.status_code == 429:
                        if progress_cb:
                            progress_cb(f"⚠ Rate limit — 10초 대기 중…", None)
                        time.sleep(10)
                        continue

                    if resp.status_code != 200:
                        break   # 이 정렬에서 더 이상 못 가져옴

                    data = resp.json()
                    if not isinstance(data, dict):
                        break

                    if total_pages is None:
                        total_pages = (
                            data.get('totalPages')
                            or (data.get('pagination') or {}).get('totalPages')
                            or (data.get('pageInfo') or {}).get('totalPages')
                        )

                    reviews = data.get('reviews', [])
                    if not reviews:
                        break

                    added = 0
                    for r in reviews:
                        content = (r.get('reviewContent')        or '').strip()
                        option  = (r.get('productOptionContent') or '').strip()
                        date    = (r.get('createDate')           or '').strip()
                        rating  = r.get('reviewScore', 0)
                        key     = (content, option, date, rating)
                        if key in all_seen or not content:
                            continue
                        all_seen.add(key)
                        all_data.append({
                            'rating':  rating,
                            'content': content,
                            'option':  option,
                            'date':    date,
                            'helpful': r.get('helpfulCount', 0),
                        })
                        added += 1
                        if len(all_data) >= max_reviews:
                            break

                    pct = min(
                        (sort_idx * per_sort + len(all_data) - sort_idx * per_sort)
                        / max_reviews * 100, 99
                    )
                    if progress_cb:
                        progress_cb(
                            f"[{sort_label}] 페이지 {page} 완료 / "
                            f"추가 {added}개 / 누적 {len(all_data)}개",
                            pct / 100
                        )

                    if total_pages and page >= total_pages:
                        break
                    if added == 0:
                        break

                    page += 1
                    time.sleep(delay_base + random.random())

                except requests.exceptions.Timeout:
                    time.sleep(4)
                    continue
                except Exception:
                    break

        self.reviews = all_data
        return self.reviews

    # ─── 3) 옵션 매칭 ──────────────────────────
    def match_options(self) -> dict:
        options   = self.product_info.get('options', [])
        norm_opts = sorted(
            [(re.sub(r'\s+', ' ', o.lower()).strip(), o) for o in options],
            key=lambda x: -len(x[0])
        )
        counter: dict = defaultdict(int)
        for review in self.reviews:
            rv_opt = re.sub(r'\s+', ' ', review.get('option', '').lower()).strip()
            matched = '미분류'
            if rv_opt:
                exact = next((o for n, o in norm_opts if n == rv_opt), None)
                if exact:
                    matched = exact
                else:
                    for n, o in norm_opts:
                        if n and n in rv_opt:
                            matched = o
                            break
            review['matched_option'] = matched
            counter[matched] += 1
        return dict(counter)

    # ─── 4) 실제 표현 조사 ─────────────────────
    def analyze_review_phrases(self, min_count: int = 2) -> dict:
        def clean(text):
            text = re.sub(r'[^가-힣0-9\s]', ' ', text)
            return re.sub(r'\s+', ' ', text).strip()

        def tok(text):
            return [w for w in re.findall(r'[가-힣]{2,}', clean(text))
                    if w not in PHRASE_STOPWORDS and len(w) >= 2]

        ug, bg, tg = Counter(), Counter(), Counter()
        pos_bg, neg_bg = Counter(), Counter()

        for r in self.reviews:
            t = tok(r['content'])
            for w in set(t): ug[w] += 1
            for i in range(len(t)-1):
                p = f"{t[i]} {t[i+1]}"
                if all(x not in PHRASE_STOPWORDS for x in p.split()):
                    bg[p] += 1
                    if r['rating'] >= 4: pos_bg[p] += 1
                    if r['rating'] <= 3: neg_bg[p] += 1
            for i in range(len(t)-2):
                p = f"{t[i]} {t[i+1]} {t[i+2]}"
                if all(x not in PHRASE_STOPWORDS for x in p.split()):
                    tg[p] += 1

        def fmt(counter, n=20):
            return [{'text': k, 'count': v}
                    for k, v in counter.most_common(n) if v >= min_count]

        return {
            'top_words':        fmt(ug),
            'top_bigrams':      fmt(bg),
            'top_trigrams':     fmt(tg),
            'positive_phrases': fmt(pos_bg, 15),
            'negative_phrases': fmt(neg_bg, 15),
        }

    # ─── 5) Friction 분석 ──────────────────────
    def analyze_friction(self) -> list:
        """
        3~4점 혼합 감정 리뷰.
        주의: 키워드 사전에 없는 불만은 누락될 수 있음.
        """
        result = []
        for r in self.reviews:
            if not (3 <= r['rating'] <= 4):
                continue
            text = r['content']
            neg  = sum(v for w, v in NEGATIVE_KEYWORDS.items() if w in text)
            pos  = sum(v for w, v in POSITIVE_KEYWORDS.items() if w in text)
            if neg < 0 and pos > 0:
                result.append({
                    'content':    text,
                    'rating':     r['rating'],
                    'neg_score':  neg,
                    'pos_score':  pos,
                    'net':        pos + neg,
                    'option':     r.get('matched_option', '미분류'),
                })
        result.sort(key=lambda x: x['neg_score'])
        return result

    # ─── 6) 옵션별 리뷰 비중 ───────────────────
    def analyze_option_review_share(self) -> pd.DataFrame:
        """
        명칭 수정: penetration_rate → review_share
        (실제 침투율=주문수 대비가 아닌 리뷰 점유율임을 명확히 함)
        """
        stats: dict = defaultdict(lambda: {'count': 0, 'ratings': []})
        for r in self.reviews:
            opt = r.get('matched_option', '미분류')
            stats[opt]['count'] += 1
            stats[opt]['ratings'].append(r['rating'])

        total = max(len(self.reviews), 1)
        rows  = []
        for opt, s in stats.items():
            avg = sum(s['ratings']) / len(s['ratings']) if s['ratings'] else 0
            rows.append({
                'option':       opt,
                'count':        s['count'],
                'review_share': round(s['count'] / total * 100, 1),
                'avg_rating':   round(avg, 2),
                'vs_avg':       round(avg - 4.5, 2),
            })

        if not rows:
            return pd.DataFrame(columns=['option','count','review_share',
                                          'avg_rating','vs_avg'])
        return (pd.DataFrame(rows)
                  .sort_values('review_share', ascending=False)
                  .reset_index(drop=True))

    # ─── 7) 결정 키워드 ────────────────────────
    def extract_decisive_keywords(self, top_n: int = 20) -> pd.DataFrame:
        """4.5점 이상 고평점 리뷰 기반 광고/상세페이지 문구용 키워드"""
        kw: dict = defaultdict(lambda: {'count': 0, 'sum': 0.0})
        for r in self.reviews:
            if r['rating'] < 4.5:
                continue
            sent  = self._sentiment_score(r['content'])
            words = set(w for w in re.findall(r'[가-힣]{2,}', r['content'])
                        if w not in STOPWORDS)
            for w in words:
                kw[w]['count'] += 1
                kw[w]['sum']   += sent

        rows = []
        for w, d in kw.items():
            if d['count'] < 2:
                continue
            avg = d['sum'] / d['count']
            rows.append({'keyword': w, 'freq': d['count'],
                         'avg_sentiment': round(avg, 2),
                         'weight': round(d['count'] * avg, 1)})

        if not rows:
            return pd.DataFrame(columns=['keyword','freq','avg_sentiment','weight'])
        return (pd.DataFrame(rows)
                  .sort_values('weight', ascending=False)
                  .head(top_n)
                  .reset_index(drop=True))

    # ─── 통합 실행 ─────────────────────────────
    def run_all(
        self,
        max_reviews: int = 500,
        sort_orders: list = None,
        delay_base:  float = 1.5,
        progress_cb=None,
    ) -> dict:
        """
        크롤링 → 매칭 → 분석 → 결과 반환.
        실패 시 CrawlError 발생 (조용한 대체 없음).
        """
        if progress_cb:
            progress_cb("상품 정보 수집 중…", 0.02)
        self.crawl_product_detail()

        if progress_cb:
            progress_cb("리뷰 수집 시작…", 0.05)
        self.crawl_reviews(
            max_reviews=max_reviews,
            sort_orders=sort_orders,
            delay_base=delay_base,
            progress_cb=progress_cb,
        )

        if not self.reviews:
            raise CrawlError(
                "리뷰를 한 건도 수집하지 못했습니다.\n"
                "네이버 봇 탐지에 걸렸거나 API 경로가 변경됐을 수 있습니다."
            )

        if progress_cb:
            progress_cb("분석 중…", 0.85)

        self.match_options()
        phrases  = self.analyze_review_phrases()
        friction = self.analyze_friction()
        opt_df   = self.analyze_option_review_share()
        kw_df    = self.extract_decisive_keywords()

        ratings     = [r['rating'] for r in self.reviews if r['rating'] > 0]
        avg_rating  = round(sum(ratings) / len(ratings), 2) if ratings else 0
        rating_dist = dict(Counter(int(r) for r in ratings))

        if progress_cb:
            progress_cb("완료", 1.0)

        return {
            'product_info': self.product_info,
            'reviews':      self.reviews,
            'avg_rating':   avg_rating,
            'rating_dist':  rating_dist,
            'phrases':      phrases,
            'friction':     friction,
            'option_share': opt_df,
            'keywords':     kw_df,
            'analyzed_at':  datetime.now().strftime('%Y-%m-%d %H:%M'),
        }
