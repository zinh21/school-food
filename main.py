import re
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# =========================================================
# 기본 설정
# =========================================================

st.set_page_config(
    page_title="오늘의 급식",
    page_icon="🍚",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =========================================================
# 학교 정보
# =========================================================

SCHOOLS = {
    "당곡고등학교": ("B10", "B100000406"),
    "관악고등학교": ("B10", "B100000390"),
    "삼성고등학교": ("B10", "B100000448"),
    "신림고등학교": ("B10", "B100000484"),
    "동작고등학교": ("B10", "B100000427"),
    "서울고등학교": ("B10", "B100000456"),
}

API_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"


# =========================================================
# API KEY 가져오기
# =========================================================

def get_api_key():
    """
    Streamlit Cloud나 로컬의 secrets.toml에서
    NEIS_API_KEY 값을 가져옵니다.
    """

    if "NEIS_API_KEY" in st.secrets:
        return st.secrets["NEIS_API_KEY"]

    return None


# =========================================================
# 유틸리티 함수
# =========================================================

def clean_html(text):
    """<br/> 등을 줄바꿈으로 변경"""

    if not text:
        return ""

    text = text.replace("<br/>", "\n")
    text = text.replace("<br>", "\n")
    text = re.sub(r"<[^>]+>", "", text)

    return text.strip()


def format_date_kr(value):
    """YYYYMMDD 혹은 date 객체 -> YYYY년 MM월 DD일"""

    if not value:
        return ""

    try:
        dt = pd.to_datetime(value)
        return dt.strftime("%Y년 %m월 %d일")
    except Exception:
        return str(value)


def get_korea_today():
    """오늘 날짜 (로컬 서버 기준)"""

    return date.today()


def extract_calorie(value):
    """'734.2 Kcal' -> 734.2 로 변환"""

    if not value:
        return None

    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(value))

    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


# =========================================================
# NEIS API 호출 (에러 원인을 자세히 보여주는 버전)
# =========================================================

@st.cache_data(ttl=60 * 30)
def get_meals(school_name, start_date, end_date):
    """
    NEIS에서 학교 급식 데이터를 가져옵니다.
    문제가 생기면 화면에 원인을 표시합니다.
    """

    if school_name not in SCHOOLS:
        st.error(f"등록되지 않은 학교입니다: {school_name}")
        return pd.DataFrame()

    office_code, school_code = SCHOOLS[school_name]

    api_key = get_api_key()

    if not api_key:
        st.error(
            "❌ API 키가 설정되지 않았습니다.\n\n"
            "`.streamlit/secrets.toml` 파일에 아래처럼 넣어주세요.\n\n"
            '```\nNEIS_API_KEY = "발급받은_키값"\n```'
        )
        return pd.DataFrame()

    start_ymd = start_date.strftime("%Y%m%d")
    end_ymd = end_date.strftime("%Y%m%d")

    params = {
        "KEY": api_key,
        "Type": "json",
        "pIndex": 1,
        "pSize": 1000,
        "ATPT_OFCDC_SC_CODE": office_code,
        "SD_SCHUL_CODE": school_code,
        "MLSV_FROM_YMD": start_ymd,
        "MLSV_TO_YMD": end_ymd,
    }

    try:
        response = requests.get(API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

    except requests.RequestException as e:
        st.error(f"❌ 네트워크 요청 실패: {e}")
        return pd.DataFrame()

    except ValueError:
        st.error("❌ NEIS API에서 올바른 JSON 데이터를 받지 못했습니다.")
        return pd.DataFrame()

    # -----------------------------------------------------
    # NEIS 응답 구조 확인
    # 정상: {"mealServiceDietInfo": [ {head}, {row} ]}
    # 에러: {"RESULT": {"CODE": "...", "MESSAGE": "..."}}
    # -----------------------------------------------------

    if "RESULT" in data:
        code = data["RESULT"].get("CODE", "알 수 없음")
        message = data["RESULT"].get("MESSAGE", "알 수 없음")

        # 데이터가 단순히 없는 경우 (정상적인 상황)
        if code == "INFO-200":
            return pd.DataFrame()

        st.error(f"❌ NEIS API 오류\n\n코드: {code}\n메시지: {message}")
        return pd.DataFrame()

    if "mealServiceDietInfo" not in data:
        st.warning("⚠️ 예상치 못한 응답 형식입니다.")
        return pd.DataFrame()

    try:
        rows = data["mealServiceDietInfo"][1]["row"]
    except (KeyError, IndexError, TypeError):
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    for col in [
        "MLSV_YMD",
        "MMEAL_SC_NM",
        "DDISH_NM",
        "CAL_INFO",
        "NTR_INFO",
        "ORPLC_INFO",
    ]:
        if col not in df.columns:
            df[col] = ""

    df["급식일"] = pd.to_datetime(df["MLSV_YMD"], format="%Y%m%d", errors="coerce")
    df["식사"] = df["MMEAL_SC_NM"].fillna("")
    df["메뉴"] = df["DDISH_NM"].apply(clean_html)
    df["칼로리"] = df["CAL_INFO"].fillna("")
    df["영양정보"] = df["NTR_INFO"].apply(clean_html)
    df["원산지"] = df["ORPLC_INFO"].apply(clean_html)
    df["학교"] = school_name

    return df[
        ["학교", "급식일", "식사", "메뉴", "칼로리", "영양정보", "원산지"]
    ].sort_values(["급식일", "식사"])


@st.cache_data(ttl=60 * 30)
def get_multiple_schools_meals(school_names, start_date, end_date):
    frames = []

    for school in school_names:
        df = get_meals(school, start_date, end_date)

        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


# =========================================================
# CSS
# =========================================================

st.markdown(
    """
    <style>
    .main-title {
        font-size: 42px;
        font-weight: 800;
        margin-bottom: 5px;
    }
    .subtitle {
        color: #777;
        font-size: 17px;
        margin-bottom: 25px;
    }
    .meal-card {
        background: linear-gradient(135deg, #ffffff, #f8f9ff);
        border: 1px solid #eeeeee;
        border-radius: 18px;
        padding: 24px;
        margin-bottom: 15px;
        box-shadow: 0 5px 20px rgba(0, 0, 0, 0.05);
    }
    .meal-title {
        font-size: 22px;
        font-weight: 700;
        margin-bottom: 12px;
    }
    .meal-menu {
        font-size: 17px;
        line-height: 1.8;
        white-space: pre-line;
    }
    .calorie {
        color: #666;
        margin-top: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# 헤더
# =========================================================

st.markdown('<div class="main-title">🍚 오늘의 급식</div>', unsafe_allow_html=True)

st.markdown(
    '<div class="subtitle">학교를 선택하고 오늘의 급식을 확인해보세요.</div>',
    unsafe_allow_html=True,
)


# =========================================================
# API 키 상태 표시 (사이드바 최상단)
# =========================================================

with st.sidebar:

    st.header("⚙️ 설정")

    # API 키가 제대로 설정되어 있는지 미리 확인해서 보여줌
    if get_api_key():
        st.success("✅ API 키가 설정되어 있습니다.")
    else:
        st.error(
            "❌ API 키가 없습니다.\n\n"
            ".streamlit/secrets.toml 파일을 확인하세요."
        )

    selected_schools = st.multiselect(
        "🏫 학교 선택",
        options=list(SCHOOLS.keys()),
        default=["당곡고등학교"],
        help="여러 학교를 선택하면 급식을 비교할 수 있습니다.",
    )

    selected_date = st.date_input(
        "📅 날짜",
        value=get_korea_today(),
    )

    st.divider()

    st.caption("급식 데이터는 NEIS 교육정보 개방포털 API를 사용합니다.")


# =========================================================
# 학교 선택 확인
# =========================================================

if not selected_schools:
    st.warning("학교를 하나 이상 선택해주세요.")
    st.stop()


# =========================================================
# 선택한 날짜의 급식
# =========================================================

today_df = get_multiple_schools_meals(
    selected_schools,
    selected_date,
    selected_date,
)


st.subheader(f"📅 {format_date_kr(selected_date)} 급식")


if today_df.empty:
    st.info(
        "선택한 날짜에는 등록된 급식 정보가 없습니다.\n\n"
        "(주말, 방학, 공휴일에는 급식이 없을 수 있어요.)"
    )

else:
    for school in selected_schools:

        school_df = today_df[today_df["학교"] == school]

        if school_df.empty:
            st.warning(f"**{school}**의 급식 정보가 없습니다.")
            continue

        st.markdown(f"### 🏫 {school}")

        cols = st.columns(min(max(len(school_df), 1), 3))

        for i, (_, row) in enumerate(school_df.iterrows()):

            with cols[i % len(cols)]:

                menu = row["메뉴"]
                calorie = row["칼로리"]

                st.markdown(
                    f"""
                    <div class="meal-card">
                    <div class="meal-title">🍽️ {row["식사"]}</div>
                    <div class="meal-menu">{menu}</div>
                    <div class="calorie">🔥 {calorie}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


# =========================================================
# 일주일 급식
# =========================================================

st.divider()
st.subheader("📆 이번 주 급식")

week_start = selected_date
week_end = selected_date + timedelta(days=6)

week_df = get_multiple_schools_meals(selected_schools, week_start, week_end)


if week_df.empty:
    st.info("선택한 기간에 급식 데이터가 없습니다.")

else:
    for school in selected_schools:

        school_week = week_df[week_df["학교"] == school].copy()

        if school_week.empty:
            continue

        st.markdown(f"### 🏫 {school}")

        display_df = school_week.copy()
        display_df["날짜"] = display_df["급식일"].dt.strftime("%m/%d")
        display_df = display_df[["날짜", "식사", "메뉴", "칼로리"]]

        st.dataframe(display_df, use_container_width=True, hide_index=True)


# =========================================================
# 칼로리 그래프
# =========================================================

st.divider()
st.subheader("🔥 급식 칼로리 그래프")

if week_df.empty:
    st.info("그래프를 그릴 급식 데이터가 없습니다.")

else:
    chart_df = week_df.copy()
    chart_df["칼로리_숫자"] = chart_df["칼로리"].apply(extract_calorie)
    chart_df = chart_df.dropna(subset=["칼로리_숫자"])

    if chart_df.empty:
        st.info("칼로리 정보가 있는 급식이 없습니다.")

    else:
        chart_df["날짜"] = chart_df["급식일"].dt.strftime("%m/%d")

        fig = px.bar(
            chart_df,
            x="날짜",
            y="칼로리_숫자",
            color="학교",
            facet_col="식사",
            barmode="group",
            text_auto=".0f",
            labels={
                "날짜": "날짜",
                "칼로리_숫자": "칼로리 (kcal)",
                "학교": "학교",
                "식사": "식사",
            },
            title="학교별 급식 칼로리",
        )

        fig.update_layout(height=500, legend_title_text="학교", hovermode="x unified")

        st.plotly_chart(fig, use_container_width=True)


# =========================================================
# 알레르기 정보
# =========================================================

with st.expander("ℹ️ 알레르기 번호 보는 법"):
    st.markdown(
        """
        NEIS 급식 메뉴에는 음식 뒤에 알레르기 번호가 붙어 있을 수 있습니다.

        예: `돈까스1.5.6.10`

        같은 형태라면 해당 음식에 알레르기 유발 식품이 포함될 수 있다는 의미입니다.

        **알레르기가 있는 경우 반드시 학교에서 제공하는 공식 알레르기 정보를 함께 확인하세요.**
        """
    )


# =========================================================
# Footer
# =========================================================

st.divider()
st.caption("🍚 오늘의 급식 · NEIS 교육정보 개방포털 데이터를 이용합니다.")
