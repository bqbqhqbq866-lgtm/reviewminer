"""
ReviewMiner — Streamlit 웹앱 v4.2
수정 사항:
  1. [치명적 버그 수정] run_btn 블록 내 render_results() 제거 → st.rerun()으로 교체
     (버튼이 False가 되는 다음 rerun에서 elif 분기로 안정적 렌더링)
  2. [버그 수정] 캐시 복원 시 reviews 등 모든 list 필드 타입 검증 추가
  3. [개선] 예외 발생 시 로그 출력 추가 (조용한 실패 방지)
"""

import json, io, os, uuid, glob, traceback
import streamlit as st
import pandas as pd
from analyzer import NaverReviewAnalyzer, CrawlError

st.set_page_config(
    page_title="ReviewMiner · 네이버 리뷰 분析기",
    page_icon="🔍", layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;600;700&display=swap');
  html, body, [class*="css"] { font-family: 'Noto Sans KR', sans-serif; }
  .rm-header { background:linear-gradient(135deg,#0f1117,#1a2035); border-radius:12px;
    padding:28px 32px; margin-bottom:24px; border:1px solid #2a2f42; }
  .rm-header h1 { color:#03C75A; margin:0; font-size:28px; font-weight:700; }
  .rm-header p  { color:#9aa0b8; margin:6px 0 0; font-size:14px; }
  .phrase-chip { display:inline-block; background:rgba(3,199,90,.1); color:#03C75A;
    border:1px solid rgba(3,199,90,.3); border-radius:20px; padding:4px 12px;
    font-size:13px; margin:3px; font-weight:500; }
  .neg-chip { display:inline-block; background:rgba(232,84,84,.1); color:#e85454;
    border:1px solid rgba(232,84,84,.3); border-radius:20px; padding:4px 12px;
    font-size:13px; margin:3px; font-weight:500; }
  .info-note { background:rgba(79,142,247,.08); border-left:3px solid #4f8ef7;
    border-radius:0 6px 6px 0; padding:10px 14px; font-size:12px;
    color:#9aa0b8; margin:10px 0; }
  .error-box { background:rgba(232,84,84,.1); border:1px solid rgba(232,84,84,.4);
    border-radius:8px; padding:14px 18px; font-size:14px; color:#e85454; }
  .stProgress > div > div { background:#03C75A !important; }
</style>
""", unsafe_allow_html=True)

# ── session_state 초기화 ─────────────────────────────────
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())[:8]

CACHE_FILE = f"result_cache_{st.session_state.session_id}.json"

for k, v in {
    "result": None, "log_lines": [],
    "product_url": "", "max_reviews": 300,
    "sort_multi": ["도움순(REVIEW_RANKING)", "최신순(RECENT)", "낮은평점순(LOW_SCORE)"],
    "delay_base": 1.5, "cookie": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── 파일 캐시 복원 ──────────────────────────────────────
# [수정 2] reviews 포함 모든 list 필드 타입 검증 추가
if st.session_state.result is None and os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            cached = json.load(f)

        # DataFrame 필드 복원
        cached["option_share"] = pd.DataFrame(cached.get("option_share") or [])
        cached["keywords"]     = pd.DataFrame(cached.get("keywords") or [])

        # list 필드 타입 보장 (JSON 파싱 후 None 방어)
        for list_field in ("reviews", "friction"):
            val = cached.get(list_field)
            if not isinstance(val, list):
                cached[list_field] = []

        # phrases 내부 list 필드 보장
        phrases = cached.get("phrases") or {}
        for pf in ("positive_phrases", "negative_phrases", "top_words", "top_bigrams", "top_trigrams"):
            if not isinstance(phrases.get(pf), list):
                phrases[pf] = []
        cached["phrases"] = phrases

        # rating_dist 키를 int로 복원 (JSON은 key가 string)
        raw_dist = cached.get("rating_dist") or {}
        cached["rating_dist"] = {int(k): v for k, v in raw_dist.items()}

        st.session_state.result = cached
    except Exception:
        # [수정 3] 조용한 실패 방지 — 로그 출력
        st.session_state._cache_restore_error = traceback.format_exc()

# ── 헬퍼 ────────────────────────────────────────────────
def save_cache(result: dict):
    def ser(obj):
        if isinstance(obj, pd.DataFrame): return obj.to_dict(orient="records")
        if isinstance(obj, dict):  return {k: ser(v) for k, v in obj.items()}
        if isinstance(obj, list):  return [ser(i) for i in obj]
        return obj
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(ser(result), f, ensure_ascii=False, default=str)

def phrase_chips(items, cls="phrase-chip", max_n=15):
    html = "".join(
        f'<span class="{cls}">{it["text"]} <b>{it["count"]}</b></span>'
        for it in items[:max_n]
    )
    st.markdown(html, unsafe_allow_html=True)

def download_pair(result: dict):
    c1, c2 = st.columns(2)
    buf = io.StringIO()
    pd.DataFrame(result["reviews"]).to_csv(buf, index=False, encoding="utf-8-sig")
    c1.download_button("⬇ 리뷰 CSV", buf.getvalue().encode("utf-8-sig"),
        "reviews.csv", "text/csv", use_container_width=True)
    def ser(obj):
        if isinstance(obj, pd.DataFrame): return obj.to_dict(orient="records")
        if isinstance(obj, dict):  return {k: ser(v) for k, v in obj.items()}
        if isinstance(obj, list):  return [ser(i) for i in obj]
        return obj
    c2.download_button("⬇ 전체 JSON", json.dumps(ser(result), ensure_ascii=False,
        indent=2, default=str).encode(), "analysis.json",
        "application/json", use_container_width=True)

def render_results(result: dict):
    pi    = result["product_info"]
    dist  = result["rating_dist"]
    total = len(result["reviews"])
    st.success(f"✅ 분析 완료 — {total}개 리뷰 · {result['analyzed_at']}")
    st.markdown("---")
    st.subheader("📦 상품 정보")
    c1, c2, c3 = st.columns([3,1,1])
    c1.markdown(f"**{pi['name']}**")
    c2.metric("가격", pi["price"])
    c3.metric("수집 리뷰", f"{total}건")
    if pi.get("options"):
        st.caption("옵션: " + " / ".join(pi["options"][:6]))
    st.markdown(f"[🔗 상품 페이지]({pi['url']})")

    st.markdown("---"); st.subheader("📊 핵심 지표")
    pos  = sum(v for k,v in dist.items() if k >= 4)
    neg  = sum(v for k,v in dist.items() if k <= 2)
    fric = len(result["friction"])
    m1,m2,m3,m4 = st.columns(4)
    m1.metric("평균 평점",   f"⭐ {result['avg_rating']}")
    m2.metric("긍정 리뷰",   f"{pos}건",  delta=f"{pos/total*100:.0f}%" if total else "0%")
    m3.metric("부정 리뷰",   f"{neg}건",  delta=f"-{neg/total*100:.0f}%" if total else "0%", delta_color="inverse")
    m4.metric("마찰 포인트", f"{fric}건")
    with st.expander("📈 평점 분포"):
        for star in range(5, 0, -1):
            cnt = dist.get(star, 0)
            a,b,c = st.columns([1,6,1])
            a.markdown(f"**{star}점**")
            b.progress(cnt/total if total else 0)
            c.markdown(f"{cnt}개")

    st.markdown("---"); download_pair(result)
    st.markdown("---")
    tabs = st.tabs(["💬 실제 표현","⚡ 마찰 포인트","📦 옵션별 분析","🔑 결정 키워드","📋 원본 리뷰"])
    ph = result["phrases"]

    with tabs[0]:
        st.markdown('<div class="info-note">실제 리뷰에서 자주 나온 표현 직접 추출 — 마케팅 문구로 바로 활용 가능</div>', unsafe_allow_html=True)
        st.markdown("#### 🟢 긍정 표현 (4~5점)")
        phrase_chips(ph["positive_phrases"])
        st.markdown("#### 🔴 낮은 평점 표현 (1~3점)")
        phrase_chips(ph["negative_phrases"], "neg-chip") if ph["negative_phrases"] else st.caption("반복 표현 없음")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 단어 TOP 20")
            if ph["top_words"]:
                st.dataframe(pd.DataFrame(ph["top_words"]).rename(columns={"text":"단어","count":"빈도"}), hide_index=True, use_container_width=True)
        with c2:
            st.markdown("#### 2단어 표현 TOP 20")
            if ph["top_bigrams"]:
                st.dataframe(pd.DataFrame(ph["top_bigrams"]).rename(columns={"text":"표현","count":"빈도"}), hide_index=True, use_container_width=True)
        if ph["top_trigrams"]:
            st.markdown("#### 3단어 표현 TOP 20")
            st.dataframe(pd.DataFrame(ph["top_trigrams"]).rename(columns={"text":"표현","count":"빈도"}), hide_index=True, use_container_width=True)

    with tabs[1]:
        st.markdown('<div class="info-note">3~4점 리뷰 중 긍정·부정 혼재 — 키워드 사전 기반이므로 누락 가능성 있음</div>', unsafe_allow_html=True)
        friction = result["friction"]
        if not friction:
            st.info("마찰 포인트 리뷰 없음")
        else:
            for r in friction[:20]:
                stars = "⭐"*r["rating"] + "☆"*(5-r["rating"])
                with st.expander(f"{stars}  불안 {r['neg_score']} / 만족 +{r['pos_score']}  |  {r['content'][:40]}…"):
                    st.markdown(f"> {r['content']}")
                    a,b,c = st.columns(3)
                    a.metric("평점", r["rating"]); b.metric("불안", r["neg_score"]); c.metric("만족", f"+{r['pos_score']}")

    with tabs[2]:
        st.markdown('<div class="info-note">⚠ review_share = 리뷰 점유율 (실제 판매 침투율 아님)</div>', unsafe_allow_html=True)
        opt_df = result["option_share"] if isinstance(result["option_share"], pd.DataFrame) else pd.DataFrame(result["option_share"])
        if opt_df.empty:
            st.info("옵션 정보 없음")
        else:
            st.dataframe(opt_df.rename(columns={"option":"옵션","count":"리뷰수","review_share":"점유율(%)","avg_rating":"평균 평점","vs_avg":"기준대비"}), hide_index=True, use_container_width=True)
            st.bar_chart(opt_df.set_index("option")["review_share"])

    with tabs[3]:
        st.markdown('<div class="info-note">4.5점↑ 고평점 기반 — 광고·상세페이지 문구용 / 약식 감성 점수</div>', unsafe_allow_html=True)
        kw_df = result["keywords"] if isinstance(result["keywords"], pd.DataFrame) else pd.DataFrame(result["keywords"])
        if kw_df.empty:
            st.info("조건 미달 키워드 없음")
        else:
            st.dataframe(kw_df.rename(columns={"keyword":"키워드","freq":"빈도","avg_sentiment":"감성","weight":"가중치"}),
                column_config={"가중치": st.column_config.ProgressColumn("가중치", min_value=0, max_value=float(kw_df["weight"].max()), format="%.1f")},
                hide_index=True, use_container_width=True)

    with tabs[4]:
        rv = pd.DataFrame(result["reviews"])
        f1, f2 = st.columns(2)
        min_r = f1.selectbox("최소 평점", [1,2,3,4,5], index=0)
        max_r = f2.selectbox("최대 평점", [1,2,3,4,5], index=4)
        filtered = rv[(rv["rating"]>=min_r)&(rv["rating"]<=max_r)]
        st.caption(f"{len(filtered)}건")
        st.dataframe(filtered[["rating","content","option","date","helpful"]].rename(
            columns={"rating":"평점","content":"내용","option":"옵션","date":"날짜","helpful":"도움"}),
            hide_index=True, use_container_width=True, height=500)

    if st.session_state.log_lines:
        with st.expander("📋 수집 로그", expanded=False):
            st.code("\n".join(st.session_state.log_lines[-50:]), language=None)

# ── 헤더 ────────────────────────────────────────────────
st.markdown("""
<div class="rm-header">
  <h1>🔍 ReviewMiner</h1>
  <p>네이버 스마트스토어 리뷰 자동 분析 · 실제 표현 추출 · 마찰 포인트 파악</p>
</div>""", unsafe_allow_html=True)

# ── 캐시 복원 오류 표시 (있을 경우) ─────────────────────
if hasattr(st.session_state, "_cache_restore_error"):
    with st.expander("⚠️ 캐시 복원 오류 (이전 결과 로드 실패)", expanded=False):
        st.code(st.session_state._cache_restore_error, language="python")
    del st.session_state._cache_restore_error

# ── 사이드바 ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ 분析 설정")
    product_url = st.text_input("스마트스토어 상품 URL *",
        placeholder="https://smartstore.naver.com/가게명/products/숫자ID", key="product_url")
    max_reviews = st.number_input("최대 수집 리뷰 수", min_value=20, max_value=2000, step=20, key="max_reviews")
    sort_multi  = st.multiselect("수집 정렬 기준",
        options=["도움순(REVIEW_RANKING)","최신순(RECENT)","낮은평점순(LOW_SCORE)"], key="sort_multi")
    SORT_MAP = {"도움순(REVIEW_RANKING)":"REVIEW_RANKING","최신순(RECENT)":"RECENT","낮은평점순(LOW_SCORE)":"LOW_SCORE"}
    selected_sorts = [SORT_MAP[s] for s in sort_multi] if sort_multi else ["REVIEW_RANKING"]
    delay_base  = st.slider("요청 딜레이 (초)", 1.0, 5.0, 1.5, key="delay_base",
        help="1.5초 이상 권장")
    cookie      = st.text_area("네이버 쿠키 (선택)", placeholder="NID_AUT=...; NID_SES=...;",
        height=80, key="cookie")
    st.markdown("---")
    run_btn   = st.button("▶ 分析 시작", type="primary", use_container_width=True)
    clear_btn = st.button("🗑 결과 초기화", use_container_width=True)
    st.markdown('<div class="info-note">⚠ 네이버 비공개 API — 정책 변경 시 중단될 수 있습니다.</div>', unsafe_allow_html=True)

# ── 초기화 ───────────────────────────────────────────────
if clear_btn:
    for k, v in {"result":None,"log_lines":[],"product_url":"","max_reviews":300,
        "sort_multi":["도움순(REVIEW_RANKING)","최신순(RECENT)","낮은평점순(LOW_SCORE)"],
        "delay_base":1.5,"cookie":""}.items():
        st.session_state[k] = v
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
    for old_f in glob.glob("result_cache_*.json"):
        try:
            os.remove(old_f)
        except Exception:
            pass
    st.rerun()

# ── 분析 실행 ─────────────────────────────────────────────
if run_btn:
    if not product_url or "/products/" not in product_url:
        st.error("❌ URL 형식 오류: https://smartstore.naver.com/가게명/products/숫자ID")
        st.stop()

    st.session_state.result    = None
    st.session_state.log_lines = []

    status_txt = st.empty()
    prog_bar   = st.progress(0.0)
    log_box    = st.expander("📋 수집 로그 (상세)", expanded=False)
    log_lines: list = []

    def progress_cb(msg: str, pct):
        status_txt.markdown(f"⏳ **{msg}**")
        if pct is not None:
            prog_bar.progress(min(float(pct), 1.0))
        log_lines.append(msg)
        st.session_state.log_lines = log_lines.copy()
        with log_box:
            st.code("\n".join(log_lines[-30:]), language=None)

    try:
        analyzer = NaverReviewAnalyzer(product_url, cookie=cookie.strip())
        result   = analyzer.run_all(
            max_reviews=int(max_reviews),
            sort_orders=selected_sorts,
            delay_base=float(delay_base),
            progress_cb=progress_cb,
        )
        st.session_state.result = result
        save_cache(result)
        prog_bar.empty()
        status_txt.empty()
        # [수정 1] render_results() 직접 호출 제거 → st.rerun()으로 elif 분기에서 안정 렌더링
        # run_btn=True 상태에서 렌더하면 다음 위젯 조작 시 run_btn=False → 결과 사라짐
        st.rerun()

    except CrawlError as e:
        prog_bar.empty(); status_txt.empty()
        st.markdown(f'<div class="error-box">❌ <b>수집 실패</b><br><br>{str(e).replace(chr(10),"<br>")}</div>',
            unsafe_allow_html=True)
        st.markdown("**해결:** 딜레이 3~5초로 올리기 / 쿠키 입력 / 잠시 후 재시도")

    except Exception as e:
        prog_bar.empty(); status_txt.empty()
        st.error(f"예기치 않은 오류: {e}")
        with st.expander("상세 traceback"):
            st.code(traceback.format_exc(), language="python")

# ── 결과 표시 (session_state 또는 파일 캐시에서) ───────────
elif st.session_state.result is not None:
    render_results(st.session_state.result)

else:
    st.markdown("""
### 사용 방법
1. 왼쪽 사이드바에 스마트스토어 상품 URL 붙여넣기
2. 수집할 리뷰 수·정렬 기준 선택
3. **▶ 분析 시작** 클릭
4. 결과 확인 후 CSV / JSON 다운로드

---
- 💬 실제 표현 — 리뷰에서 자주 나온 단어·문구 추출
- ⚡ 마찰 포인트 — 긍부정 혼재 리뷰
- 📦 옵션별 리뷰 비중·평점
- 🔑 고평점 결정 키워드

> ⚠ 네이버 비공개 API — 봇 탐지 또는 구조 변경 시 수집 중단될 수 있습니다.
""")
