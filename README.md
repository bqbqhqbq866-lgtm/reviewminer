# ReviewMiner

네이버 스마트스토어 리뷰 자동 분석 웹앱

---

## 📁 파일 구조

```
reviewminer/
├── app.py           ← Streamlit 웹앱 (UI + 흐름)
├── analyzer.py      ← 분석 엔진 (크롤링 + 분석 로직)
├── requirements.txt ← 패키지 목록
└── README.md
```

---

## 💻 로컬 실행 방법

### 1) Python 설치 확인 (3.10 이상)
```bash
python --version
```

### 2) 패키지 설치
```bash
pip install -r requirements.txt
```

### 3) 실행
```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 자동 열림

---

## 🚀 인터넷 배포 — Streamlit Cloud (가장 쉬움)

초보자 기준 **Streamlit Cloud** 추천:
- 무료, GitHub 계정만 있으면 됨
- 클릭 5번으로 배포 완료

### 배포 순서

**① GitHub 레포 만들기**
1. [github.com](https://github.com) 접속 → 로그인
2. 우측 상단 `+` → `New repository`
3. Repository name: `reviewminer`
4. `Add a README file` 체크 → `Create repository`

**② 파일 올리기**
1. 레포 페이지에서 `Add file` → `Upload files`
2. `app.py`, `analyzer.py`, `requirements.txt` 세 파일 드래그
3. `Commit changes` 클릭

**③ Streamlit Cloud 배포**
1. [share.streamlit.io](https://share.streamlit.io) 접속
2. GitHub로 로그인
3. `New app` 클릭
4. Repository: `내아이디/reviewminer`
5. Main file path: `app.py`
6. `Deploy!` 클릭

→ 1~2분 후 `https://내아이디-reviewminer-app-랜덤.streamlit.app` 링크 발급

---

## ⚠ 주의사항

- 네이버 비공개 API 사용 → 정책 변경 시 수집 중단 가능
- 봇 탐지 걸리면 딜레이 3~5초로 늘리거나 쿠키 입력
- Streamlit Cloud 무료 플랜: 앱 1개, 메모리 1GB 제한
  (리뷰 500건 이하면 충분)

---

## 🔧 코드 수정 시

`analyzer.py` 수정 → GitHub에 업로드하면 Streamlit Cloud 자동 재배포
