"""
ReviewMiner — Streamlit 웹앱
실행: streamlit run app.py
"""

import json
import io
import streamlit as st
import pandas as pd
from analyzer import NaverReviewAnalyzer, CrawlError

# ──────────────────────────────────────────────────────────
# 페이지 기본 설정
# ──────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ReviewMiner · 네이버 리뷰 분석기",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────
# 커스텀 CSS
# ──────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;600;700&display=swap');
  html, body, [class*="css"] { font-family: 'Noto Sans KR', sans-serif; }

  .rm-header {
    background: linear-gradient(135deg, #0f1117 0%, #1a2035 100%);
    border-radius: 12px; padding: 28px 32px; margin-bottom: 24px;
    border: 1px solid #2a2f42;
  }
  .rm-header h1 { color: #03C75A; margin: 0; font-size: 28px; font-weight: 700; }
  .rm-header p  { color: #9aa0b8; margin: 6px 0 0; font-size: 14px; }

  .phrase-chip {
    display: inline-block; background: rgba(3,199,90,.1);
    color: #03C75A; border: 1px solid rgba(3,199,90,.3);
    border-radius: 20px; padding: 4px 12px; font-size: 13px;
    margin: 3px; font-weight: 500;
  }
  .neg-chip {
    display: inline-block; background: rgba(232,84,84,.1);
    color: #e85454; border: 1px solid rgba(232,84,84,.3);
    border-radius: 20px; padding: 4px 12px; font-size: 13px;
    margin: 3px; font-weight: 500;
  }
  .warning-box {
    background: rgba(245,166,35,.1); border: 1px solid rgba(245,166,35,.4);
    border-radius: 8px; padding: 12px 16px; font-size: 13px; color: #f5a623;
  }
  .error-box {
    background: rgba(232,84,84,.1); border: 1px solid rgba(232,84,84,.4);
    border-radius: 8px; padding: 14px 18px; font-size: 14px; color: #e85454;
  }
  .info-note {
    background: rgba(79,142,247,.08); border-left: 3px solid #4f8ef7;
    border-radius: 0 6px 6px 0; padding: 10px 14px;
    font-size: 12px; color: #9aa0b8; margin: 10px 0;
  }
  div[data-testid="stMetric"] label { font-size: 12px !important; }
  .stTabs [data-baseweb="tab"] { font-size: 14px; font-weight: 600; }
  .stProgress > div > div { background: #03C75A !important; }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────
# session_state 초기화 (페이지 재실행돼도 결과 유지)
# ──────────────────────────────────────────────────────────
if "result" not in st.session_state:
    st.session_state.result = None
if "log_lines" not in st.session_state:
    st.session_state.log_lines = []
if "product_url" not in st.session_state:
    st.session_state.product_url = ""
if "max_reviews" not in st.session_state:
    st.session_state.max_reviews = 300
if "sort_multi" not in st.session_state:
    st.session_state.sort_multi = ["도움순(REVIEW_RANKING)", "최신순(RECENT)", "낮은평점순(LOW_SCORE)"]
if "delay_base" not in st.session_state:
    st.session_state.delay_base = 1.5
if "cookie" not in st.session_state:
    st.session_state.cookie = ""

# ──────────────────────────────────────────────────────────
# 헤더
# ──────────────────────────────────────────────────────────
st.markdown("""
<div class="rm-header">
  <h1>🔍 ReviewMiner</h1>
  <p>네이버 스마트스토어 리뷰 자동 분析 · 실제 표현 추출 · 마찰 포인트 파악</p>
</div>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ 분析 설정")

    product_url = st.text_input(
        "스마트스토어 상품 URL *",
        placeholder="https://smartstore.naver.com/가게명/products/숫자ID",
        key="product_url",
    )
    max_reviews = st.number_input(
        "최대 수집 리뷰 수", min_value=20, max_value=2000, step=20,
        key="max_reviews",
    )
    sort_multi = st.multiselect(
        "수집 정렬 기준",
        options=["도움순(REVIEW_RANKING)", "최신순(RECENT)", "낮은평점순(LOW_SCORE)"],
        key="sort_multi",
    )
    delay_base = st.slider("요청 딜레이 (초)", 1.0, 5.0, 0.5,
        key="delay_base",
        help="1.5초 이상 권장 — 낮을수록 빠르지만 차단 위험 증가")
    cookie = st.text_area(
        "네이버 쿠키 (선택)", placeholder="NID_AUT=...; NID_SES=...;",
        height=80, key="cookie",
    )
    st.markdown("---")
    run_btn   = st.button("▶ 분析 시작", type="primary", use_container_width=True)
    clear_btn = st.button("🗑 결과 초기화", use_container_width=True)

    st.markdown("""
    <div class="info-note">
    ⚠ 이 도구는 네이버 비공개 API를 사용합니다.<br>
    네이버 정책 변경 시 동작이 중단될 수 있습니다.
    </div>
    """, unsafe_allow_html=True)

# 초기화 버튼
if clear_btn:
    for k, v in {
        "result": None, "log_lines": [],
        "product_url": "", "max_reviews": 300,
        "sort_multi": ["도움순(REVIEW_RANKING)", "최신순(RECENT)", "낮은평점순(LOW_SCORE)"],
        "delay_base": 1.5, "cookie": "",
    }.items():
        st.session_state[k] = v
    st.rerun()


# ──────────────────────────────────────────────────────────
# 헬퍼 함수
# ──────────────────────────────────────────────────────────
def render_rating_dist(dist: dict, total: int):
    for star in range(5, 0, -1):
        cnt = dist.get(star, 0)
        pct = cnt / total * 100 if total else 0
        col1, col2, col3 = st.columns([1, 6, 1])
        col1.markdown(f"**{star}점**")
        col2.progress(pct / 100)
        col3.markdown(f"{cnt}개")


def phrase_chips(items, cls="phrase-chip", max_n=15):
    html = ""
    for item in items[:max_n]:
        html += f'<span class="{cls}">{item["text"]} <b>{item["count"]}</b></span>'
    st.markdown(html, unsafe_allow_html=True)


def download_pair(result: dict):
    c1, c2 = st.columns(2)
    reviews_df = pd.DataFrame(result["reviews"])
    csv_buf    = io.StringIO()
    reviews_df.to_csv(csv_buf, index=False, encoding="utf-8-sig")
    c1.download_button(
        "⬇ 리뷰 CSV 다운로드",
        data=csv_buf.getvalue().encode("utf-8-sig"),
        file_name="reviews.csv", mime="text/csv",
        use_container_width=True,
    )

    def to_ser(obj):
        if isinstance(obj, pd.DataFrame): return obj.to_dict(orient="records")
        if isinstance(obj, dict):  return {k: to_ser(v) for k, v in obj.items()}
        if isinstance(obj, list):  return [to_ser(i) for i in obj]
        return obj

    json_str = json.dumps(to_ser(result), ensure_ascii=False, indent=2, default=str)
    c2.download_button(
        "⬇ 전체 분析 JSON 다운로드",
        data=json_str.encode("utf-8"),
        file_name="analysis.json", mime="application/json",
        use_container_width=True,
    )


def render_results(result: dict):
    """분析 결과 전체 렌더 — session_state에서 꺼내도 동일하게 동작"""
    pi    = result["product_info"]
    dist  = result["rating_dist"]
    total = len(result["reviews"])

    # ── 성공 배너
    st.success(f"✅ 분析 완료 — {total}개 리뷰 · {result['analyzed_at']}")

    # ── 상품 정보
    st.markdown("---")
    st.subheader("📦 상품 정보")
    c1, c2, c3 = st.columns([3, 1, 1])
    c1.markdown(f"**{pi['name']}**")
    c2.metric("가격", pi["price"])
    c3.metric("수집 리뷰", f"{total}건")
    if pi.get("options"):
        st.caption("옵션: " + " / ".join(pi["options"][:6]))
    st.markdown(f"[🔗 상품 페이지 바로가기]({pi['url']})")

    # ── 핵심 지표
    st.markdown("---")
    st.subheader("📊 핵심 지표")
    pos  = sum(v for k, v in dist.items() if k >= 4)
    neg  = sum(v for k, v in dist.items() if k <= 2)
    fric = len(result["friction"])
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("평균 평점",   f"⭐ {result['avg_rating']}")
    m2.metric("긍정 리뷰",   f"{pos}건",  delta=f"{pos/total*100:.0f}%" if total else "0%")
    m3.metric("부정 리뷰",   f"{neg}건",  delta=f"-{neg/total*100:.0f}%" if total else "0%",
              delta_color="inverse")
    m4.metric("마찰 포인트", f"{fric}건")

    with st.expander("📈 평점 분포"):
        render_rating_dist(dist, total)

    # ── 다운로드
    st.markdown("---")
    download_pair(result)

    # ── 탭
    st.markdown("---")
    tabs = st.tabs(["💬 실제 표현", "⚡ 마찰 포인트", "📦 옵션별 분析", "🔑 결정 키워드", "📋 원본 리뷰"])
    ph = result["phrases"]

    with tabs[0]:
        st.markdown("""
        <div class="info-note">
        JTBD 카테고리 분류 없이 실제 리뷰에서 자주 나온 표현을 그대로 추출합니다.
        </div>""", unsafe_allow_html=True)
        st.markdown("#### 🟢 긍정 리뷰 자주 나온 표현 (4~5점)")
        phrase_chips(ph["positive_phrases"])
        st.markdown("#### 🔴 낮은 평점 리뷰 자주 나온 표현 (1~3점)")
        if ph["negative_phrases"]:
            phrase_chips(ph["negative_phrases"], cls="neg-chip")
        else:
            st.caption("낮은 평점 리뷰에서 반복 표현이 없습니다.")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 단어 TOP 20")
            if ph["top_words"]:
                st.dataframe(pd.DataFrame(ph["top_words"]).rename(
                    columns={"text":"단어","count":"빈도"}),
                    hide_index=True, use_container_width=True)
        with c2:
            st.markdown("#### 2단어 표현 TOP 20")
            if ph["top_bigrams"]:
                st.dataframe(pd.DataFrame(ph["top_bigrams"]).rename(
                    columns={"text":"표현","count":"빈도"}),
                    hide_index=True, use_container_width=True)
        if ph["top_trigrams"]:
            st.markdown("#### 3단어 표현 TOP 20")
            st.dataframe(pd.DataFrame(ph["top_trigrams"]).rename(
                columns={"text":"표현","count":"빈도"}),
                hide_index=True, use_container_width=True)

    with tabs[1]:
        st.markdown("""
        <div class="info-note">
        3~4점 리뷰 중 긍정·부정 표현이 혼재하는 리뷰입니다.<br>
        ⚠ 키워드 사전 기반이므로 사전에 없는 불만은 누락될 수 있습니다.
        </div>""", unsafe_allow_html=True)
        friction = result["friction"]
        if not friction:
            st.info("마찰 포인트로 분류된 리뷰가 없습니다.")
        else:
            for r in friction[:20]:
                with st.expander(
                    f"{"⭐"*r["rating"]}{"☆"*(5-r["rating"])}  "
                    f"불안 {r["neg_score"]} / 만족 +{r["pos_score"]}  |  "
                    f"{r["content"][:40]}…"
                ):
                    st.markdown(f"> {r['content']}")
                    cc1, cc2, cc3 = st.columns(3)
                    cc1.metric("평점", r["rating"])
                    cc2.metric("불안 점수", r["neg_score"])
                    cc3.metric("만족 점수", f"+{r['pos_score']}")
                    st.caption(f"옵션: {r['option']}")

    with tabs[2]:
        st.markdown("""
        <div class="info-note">
        ⚠ <strong>review_share</strong>(리뷰 점유율)입니다.
        실제 침투율(주문수 대비)이 아닙니다.
        </div>""", unsafe_allow_html=True)
        opt_df = result["option_share"]
        if opt_df.empty:
            st.info("옵션 정보가 없거나 매칭되지 않았습니다.")
        else:
            df_disp = opt_df.rename(columns={
                "option":"옵션명","count":"리뷰수",
                "review_share":"리뷰 점유율(%)","avg_rating":"평균 평점","vs_avg":"기준(4.5) 대비"
            })
            st.dataframe(df_disp, hide_index=True, use_container_width=True)
            st.bar_chart(opt_df.set_index("option")["review_share"], use_container_width=True)

    with tabs[3]:
        st.markdown("""
        <div class="info-note">
        4.5점 이상 고평점 리뷰 기반 키워드입니다.<br>
        ⚠ 약식 감성 점수 기반 — 직접 검토 필요.
        </div>""", unsafe_allow_html=True)
        kw_df = result["keywords"]
        if kw_df.empty:
            st.info("결정 키워드 조건에 해당하는 단어가 없습니다.")
        else:
            df_kw = kw_df.rename(columns={
                "keyword":"키워드","freq":"빈도",
                "avg_sentiment":"감성 점수","weight":"가중치"
            })
            st.dataframe(df_kw, hide_index=True,
                column_config={"가중치": st.column_config.ProgressColumn(
                    "가중치", min_value=0,
                    max_value=float(df_kw["가중치"].max()), format="%.1f")},
                use_container_width=True)

    with tabs[4]:
        reviews_df = pd.DataFrame(result["reviews"])
        fc1, fc2   = st.columns(2)
        min_r = fc1.selectbox("최소 평점", [1,2,3,4,5], index=0)
        max_r = fc2.selectbox("최대 평점", [1,2,3,4,5], index=4)
        filtered = reviews_df[
            (reviews_df["rating"] >= min_r) & (reviews_df["rating"] <= max_r)
        ]
        st.caption(f"{len(filtered)}건 표시 중")
        st.dataframe(
            filtered[["rating","content","option","date","helpful"]].rename(columns={
                "rating":"평점","content":"내용","option":"옵션",
                "date":"날짜","helpful":"도움"
            }),
            hide_index=True, use_container_width=True, height=500,
        )


# ──────────────────────────────────────────────────────────
# 분析 실행
# ──────────────────────────────────────────────────────────
if run_btn:
    if not product_url or "/products/" not in product_url:
        st.markdown("""
        <div class="error-box">
        ❌ URL 형식이 올바르지 않습니다.<br>
        올바른 형식: <code>https://smartstore.naver.com/가게명/products/숫자ID</code>
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    status_txt   = st.empty()
    prog_bar     = st.progress(0.0)
    log_expander = st.expander("📋 수집 로그 (상세)", expanded=False)
    log_lines: list = []

    def progress_cb(msg: str, pct):
        status_txt.markdown(f"⏳ **{msg}**")
        if pct is not None:
            prog_bar.progress(min(float(pct), 1.0))
        log_lines.append(msg)
        st.session_state.log_lines = log_lines.copy()
        with log_expander:
            st.code("\n".join(log_lines[-30:]), language=None)

    try:
        analyzer = NaverReviewAnalyzer(product_url, cookie=cookie.strip())
        result   = analyzer.run_all(
            max_reviews=int(max_reviews),
            sort_orders=selected_sorts,
            delay_base=float(delay_base),
            progress_cb=progress_cb,
        )
        # ★ session_state 저장 — 탭 클릭·스크롤해도 결과 유지
        st.session_state.result = result

    except CrawlError as e:
        prog_bar.empty()
        status_txt.empty()
        st.markdown(f"""
        <div class="error-box">
        ❌ <strong>수집 실패 — 분析을 중단합니다</strong><br><br>
        {str(e).replace(chr(10), "<br>")}
        </div>
        """, unsafe_allow_html=True)
        st.markdown("""
        **해결 방법:**
        - URL이 실제 스마트스토어 상품 페이지인지 확인
        - 잠시 후 다시 시도 (봇 탐지 일시적일 수 있음)
        - 네이버 로그인 쿠키를 사이드바에 입력 후 재시도
        - 딜레이를 3~5초로 늘려보기
        """)
        st.stop()

    except Exception as e:
        prog_bar.empty()
        status_txt.empty()
        st.error(f"예기치 않은 오류: {e}")
        st.stop()

    # ★ rerun 없이 즉시 렌더 — rerun은 session_state 초기화 위험 있음
    prog_bar.empty()
    status_txt.empty()
    render_results(st.session_state.result)
    if st.session_state.log_lines:
        with st.expander("📋 수집 로그", expanded=False):
            st.code("\n".join(st.session_state.log_lines[-50:]), language=None)
    st.stop()   # 아래 중복 렌더 방지


# ──────────────────────────────────────────────────────────
# 결과 표시 (session_state에서 꺼냄 — 항상 유지됨)
# ──────────────────────────────────────────────────────────
if st.session_state.result is not None:
    render_results(st.session_state.result)
    if st.session_state.log_lines:
        with st.expander("📋 수집 로그", expanded=False):
            st.code("\n".join(st.session_state.log_lines[-50:]), language=None)
else:
    st.markdown("""
    ### 사용 방법

    1. **왼쪽 사이드바**에 스마트스토어 상품 URL을 붙여넣기
    2. 수집할 리뷰 수와 정렬 기준 선택
    3. **▶ 분析 시작** 버튼 클릭
    4. 결과 확인 후 CSV / JSON 다운로드

    ---
    **분析 항목:**
    - 💬 실제 표현 — 리뷰에서 자주 나온 단어·문구 직접 추출
    - ⚡ 마찰 포인트 — 긍부정 혼재 리뷰 추출
    - 📦 옵션별 리뷰 비중 및 평점
    - 🔑 고평점 기반 결정 키워드

    > ⚠ 네이버 비공개 API 사용 — 봇 탐지 또는 API 구조 변경 시 수집이 중단될 수 있습니다.
    """)
