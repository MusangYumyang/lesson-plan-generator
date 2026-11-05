"""점심 맛집 대시보드 (미니 앱)

역이나 동네 이름을 카카오에서 찾아 기준 장소로 삼고, 그 둘레 반경 안의 음식점을 표와 차트로 보여 준다.
카카오는 [검색] 버튼을 눌렀을 때만 부른다. 정렬·거르기는 받아 둔 결과로만 처리한다.
카카오 응답에는 평점·리뷰가 없어서, 맛 순위가 아니라 거리와 업종으로 비교한다.

실행:
  streamlit run lunch.py

호출 방법: https://developers.kakao.com/docs/ko/local/dev-guide
"""

import math
import os
import pathlib
from urllib.parse import quote

import altair as alt
import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
from dotenv import load_dotenv

# 확인할 키 이름. .env 에 들어 있는 이름과 같아야 한다.
KEY_NAME = "KAKAO_REST_API_KEY"
ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"
# 카테고리 그룹 코드: FD6 = 음식점
RESTAURANT_CODE = "FD6"
# 한 페이지 최대 15곳, 한 검색에서 받을 수 있는 최대 45곳이라 3쪽이면 끝난다
PAGE_SIZE = 15
MAX_PAGES = 3
# 기준 장소가 여러 곳일 때 화면에 함께 보여 줄 후보 수
CENTER_CANDIDATES = 5
# 이 시간(초) 안에 답이 없으면 기다리지 않고 안내를 띄운다
TIMEOUT_SECONDS = 10

DEFAULT_CENTER = "전주 객사"
FOOD_CHOICES = ["한식", "중식", "일식", "양식", "분식", "국밥", "고기", "치킨"]
FETCH_ORDERS = {"가까운 순": "distance", "카카오 정확도 순": "accuracy"}
BAR_COLOR = "#2a78d6"
NAVER_SEARCH_URL = "https://map.naver.com/p/search/"
MAP_HEIGHT = 440
DISTANCE_STEP = 50


class KakaoError(Exception):
    """화면에 그대로 보여 줘도 되는 안내 글을 담는 오류."""


def call_kakao(url, api_key, params):
    """카카오를 한 번 부르고 JSON 을 돌려준다.

    카카오의 오류 글(msg)에는 앱 키가 들어갈 수 있어서 화면에 옮기지 않고, 코드로만 구분한다.
    """
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"KakaoAK {api_key}"},
            params=params,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        raise KakaoError("카카오 응답이 늦습니다. 잠시 뒤 다시 검색해 주세요.") from None
    except requests.RequestException as err:
        raise KakaoError(f"카카오에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요. ({type(err).__name__})") from None

    if response.ok:
        try:
            return response.json()
        except ValueError:
            raise KakaoError("카카오 응답을 읽지 못했습니다. 잠시 뒤 다시 검색해 주세요.") from None

    status = response.status_code
    try:
        body = response.json()
        code = body.get("code") if isinstance(body, dict) else None
    except ValueError:
        code = None

    if status == 429 or code == -10:
        message = "오늘 쓸 수 있는 호출량을 넘겼거나 너무 빨리 불렀습니다. 앱 관리 페이지의 [통계] > [쿼터]를 확인해 주세요."
    elif status == 401:
        message = f"키를 쓸 수 없습니다. .env 의 {KEY_NAME} 값과 앱의 호출 허용 IP 설정을 확인해 주세요."
    elif status == 403:
        message = "이 앱에서 로컬 API 를 쓸 권한이 없습니다. 앱 관리 페이지의 [카카오맵] > [사용 설정]에서 [상태]를 [ON]으로 바꿔 주세요."
    elif status == 400:
        message = "카카오가 검색 조건을 받아들이지 않았습니다. 입력한 값을 확인해 주세요."
    else:
        message = "카카오 쪽 문제로 답을 받지 못했습니다. 잠시 뒤 다시 검색해 주세요."
    detail = f"HTTP {status}" if code is None else f"HTTP {status}, 코드 {code}"
    raise KakaoError(f"{message} ({detail})")


def find_center(api_key, query):
    """기준 장소 이름을 카카오에서 찾는다. 화면에 쓰는 이름·주소는 모두 카카오 응답 그대로다.

    동네 이름을 키워드로 찾으면 그 동네의 엉뚱한 명소가 먼저 나와서 주소 검색을 먼저 한다.
    역·건물 이름은 주소 검색에 나오지 않으므로 그때 키워드로 찾는다.
    """
    data = call_kakao(ADDRESS_URL, api_key, {"query": query, "size": CENTER_CANDIDATES})
    if data["documents"]:
        candidates = [
            {"name": doc["address_name"], "address": doc["address_name"], "x": doc["x"], "y": doc["y"]}
            for doc in data["documents"]
        ]
        return {**candidates[0], "total": data["meta"]["total_count"], "candidates": candidates}

    data = call_kakao(KEYWORD_URL, api_key, {"query": query, "size": CENTER_CANDIDATES})
    if not data["documents"]:
        raise KakaoError(f"'{query}' 장소를 카카오에서 찾지 못했습니다. 이름을 조금 바꿔 다시 검색해 주세요.")
    candidates = [
        {
            "name": doc["place_name"],
            "address": doc["road_address_name"] or doc["address_name"],
            "x": doc["x"],
            "y": doc["y"],
        }
        for doc in data["documents"]
    ]
    # 역·건물 이름은 관련 장소가 늘 함께 나오므로 같은 이름이 여러 곳이라는 경고는 띄우지 않는다
    return {**candidates[0], "total": 1, "candidates": candidates}


def find_restaurants(api_key, center, keyword, radius, order):
    """기준 장소 둘레 반경 안의 음식점을 끝까지 받아 (목록, 전체 개수)로 돌려준다."""
    params = {
        "category_group_code": RESTAURANT_CODE,
        "x": center["x"],
        "y": center["y"],
        "radius": radius,
        "sort": order,
        "size": PAGE_SIZE,
    }
    if keyword:
        url = KEYWORD_URL
        params["query"] = keyword
    else:
        url = CATEGORY_URL

    places = []
    total = 0
    for page in range(1, MAX_PAGES + 1):
        data = call_kakao(url, api_key, {**params, "page": page})
        places.extend(data["documents"])
        total = data["meta"]["total_count"]
        if data["meta"]["is_end"]:
            break
    return places, total


def to_table(places):
    """카카오 응답을 표로 바꾼다. 전화·도로명 주소·거리는 빈 값으로 올 수 있다."""
    rows = []
    for place in places:
        # 예: "음식점 > 한식 > 육류,고기" -> 업종 "한식", 세부 "육류,고기"
        parts = place["category_name"].split(" > ")
        rows.append(
            {
                "name": place["place_name"],
                "category": parts[1] if len(parts) > 1 else "기타",
                "detail": " > ".join(parts[2:]),
                "distance": pd.to_numeric(place.get("distance"), errors="coerce"),
                "phone": place["phone"],
                "address": place["road_address_name"] or place["address_name"],
                "url": place["place_url"],
                "lat": pd.to_numeric(place["y"], errors="coerce"),
                "lon": pd.to_numeric(place["x"], errors="coerce"),
            }
        )
    return pd.DataFrame(
        rows, columns=["name", "category", "detail", "distance", "phone", "address", "url", "lat", "lon"]
    )


def restaurant_map(shown, center, radius):
    """파란 점은 음식점, 주황 점은 기준 장소, 둥근 선은 검색 반경이다."""
    center_lat = float(center["y"])
    center_lon = float(center["x"])
    spots = [
        {
            "lat": row.lat,
            "lon": row.lon,
            "tip": f"{row.name}\n{row.category}" + ("" if pd.isna(row.distance) else f" · {row.distance:,.0f}m"),
        }
        for row in shown.dropna(subset=["lat", "lon"]).itertuples()
    ]
    base = [{"lat": center_lat, "lon": center_lon, "tip": f"기준 장소: {center['name']}"}]
    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            base,
            get_position=["lon", "lat"],
            get_radius=radius,
            filled=False,
            stroked=True,
            get_line_color=[235, 104, 52],
            line_width_min_pixels=2,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            spots,
            get_position=["lon", "lat"],
            get_radius=1,
            radius_min_pixels=7,
            radius_max_pixels=7,
            get_fill_color=[42, 120, 214],
            stroked=True,
            get_line_color=[255, 255, 255],
            line_width_min_pixels=2,
            pickable=True,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            base,
            get_position=["lon", "lat"],
            get_radius=1,
            radius_min_pixels=9,
            radius_max_pixels=9,
            get_fill_color=[235, 104, 52],
            stroked=True,
            get_line_color=[255, 255, 255],
            line_width_min_pixels=2,
            pickable=True,
        ),
    ]
    # 반경 원이 지도 높이 안에 다 들어오는 확대 수준을 계산한다
    meters_per_pixel_at_zero = 78271 * math.cos(math.radians(center_lat))
    zoom = math.log2(meters_per_pixel_at_zero * MAP_HEIGHT / (2.3 * radius))
    return pdk.Deck(
        layers=layers,
        map_style=None,
        initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom),
        tooltip={"text": "{tip}"},
    )


def category_chart(table):
    counts = table.groupby("category").size().reset_index(name="count")
    return (
        alt.Chart(counts)
        .mark_bar(color=BAR_COLOR, size=18, cornerRadiusEnd=4)
        .encode(
            x=alt.X("count:Q", title="음식점 수", axis=alt.Axis(format="d", tickMinStep=1)),
            y=alt.Y("category:N", title=None, sort="-x"),
            tooltip=[alt.Tooltip("category:N", title="업종"), alt.Tooltip("count:Q", title="음식점 수")],
        )
        .properties(height=max(160, 30 * len(counts)))
    )


def distance_chart(table):
    # 가장 먼 곳에 맞춰 막대 폭을 정한다
    farthest = table["distance"].max()
    step = 50 if farthest <= 500 else 100 if farthest <= 1500 else 500
    return (
        alt.Chart(table.dropna(subset=["distance"]))
        .mark_bar(color=BAR_COLOR, binSpacing=2, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("distance:Q", bin=alt.Bin(step=step), title=f"기준 위치에서 거리 (m, {step}m 단위)"),
            y=alt.Y("count():Q", title="음식점 수", axis=alt.Axis(format="d", tickMinStep=1)),
            tooltip=[
                alt.Tooltip("distance:Q", bin=alt.Bin(step=step), title="거리 (m)"),
                alt.Tooltip("count():Q", title="음식점 수"),
            ],
        )
        .properties(height=260)
    )


def show_candidates(center):
    """카카오가 함께 돌려준 후보 중에서 기준 장소를 바꾼다. 버튼을 눌러야 다시 찾는다."""
    candidates = center["candidates"]
    current = next(
        (
            index
            for index, candidate in enumerate(candidates)
            if (candidate["x"], candidate["y"]) == (center["x"], center["y"])
        ),
        0,
    )
    with st.expander("찾는 곳이 아닌가요? 다른 후보에서 고르기", expanded=center["total"] > 1):
        picked = st.radio(
            "기준 장소 후보",
            range(len(candidates)),
            index=current,
            format_func=lambda index: (
                candidates[index]["name"]
                if candidates[index]["name"] == candidates[index]["address"]
                else f"{candidates[index]['name']} ({candidates[index]['address']})"
            ),
            label_visibility="collapsed",
        )
        st.button(
            "이 장소로 다시 찾기",
            disabled=picked == current or st.session_state.busy,
            on_click=choose_center,
            args=(candidates[picked],),
        )


def show_results(result):
    center = result["center"]
    table = result["table"]

    # 앱을 고치기 전에 받아 둔 결과에는 좌표와 후보가 없다
    if "lat" not in table.columns or "candidates" not in center:
        st.info("화면이 새로 바뀌었습니다. [검색] 버튼을 한 번 더 눌러 주세요.")
        return

    st.subheader(f"{center['name']} 둘레 {result['radius']:,}m 안의 {result['food'] or '음식점'}")
    st.markdown(f"**카카오에서 찾은 기준 장소:** {center['name']}")
    st.markdown(f"**주소:** {center['address'] or '카카오 응답에 주소 없음'}")
    st.caption(f"입력한 장소: {result['query']} · {result['order']}")
    if center["total"] > 1:
        st.warning(
            f"'{result['query']}'(으)로 찾은 곳이 {center['total']}곳이라 첫 번째를 썼습니다. "
            "다른 곳이면 아래 후보에서 고르거나 시·구 이름까지 넣어 검색해 주세요."
        )
    if len(center["candidates"]) > 1:
        show_candidates(center)

    if table.empty:
        st.info("이 조건에 맞는 음식점이 없습니다. 반경을 넓히거나 찾을 음식을 바꿔 보세요.")
        return

    if result["total"] > len(table):
        st.info(
            f"이 조건에 맞는 곳은 {result['total']:,}곳이지만, 카카오는 한 검색에 최대 45곳만 줍니다. "
            f"아래 지도와 표, 차트는 받은 {len(table)}곳만 다룹니다."
        )

    # 아래 거르기·정렬은 받아 둔 결과만 다루므로 카카오를 부르지 않는다
    left, right = st.columns([3, 2])
    text = left.text_input("결과에서 찾기", placeholder="이름 또는 주소")
    sort_by = right.radio("정렬", ["가까운 순", "먼 순", "이름 순", "업종 순"], horizontal=True)

    counts = table["category"].value_counts()
    categories = st.pills(
        "업종 (누르면 그 업종만 보여요. 숫자는 받은 곳 수)",
        list(counts.index),
        selection_mode="multi",
        format_func=lambda name: f"{name} {counts[name]}",
    )

    shown = table
    farthest = table["distance"].max()
    if pd.notna(farthest) and farthest > DISTANCE_STEP:
        slider_end = math.ceil(farthest / DISTANCE_STEP) * DISTANCE_STEP
        limit = st.slider(
            "이 거리 안만 보기", DISTANCE_STEP, slider_end, slider_end, step=DISTANCE_STEP, format="%d m"
        )
        shown = shown[shown["distance"].isna() | (shown["distance"] <= limit)]
    if text.strip():
        word = text.strip()
        shown = shown[
            shown["name"].str.contains(word, case=False, regex=False)
            | shown["address"].str.contains(word, case=False, regex=False)
        ]
    if categories:
        shown = shown[shown["category"].isin(categories)]

    if shown.empty:
        st.info("거르기 조건에 맞는 곳이 없습니다. 조건을 지워 보세요.")
        return

    sort_rules = {
        "가까운 순": (["distance"], [True]),
        "먼 순": (["distance"], [False]),
        "이름 순": (["name"], [True]),
        "업종 순": (["category", "distance"], [True, True]),
    }
    columns, ascending = sort_rules[sort_by]
    shown = shown.sort_values(columns, ascending=ascending, kind="stable")

    tiles = st.columns(4)
    tiles[0].metric("보이는 음식점", f"{len(shown)}곳")
    tiles[1].metric("업종 수", f"{shown['category'].nunique()}개")
    if shown["distance"].notna().any():
        tiles[2].metric("가장 가까운 곳", f"{shown['distance'].min():,.0f}m")
        tiles[3].metric("거리 중앙값", f"{shown['distance'].median():,.0f}m")

    st.markdown("**지도**")
    st.caption("파란 점: 음식점 · 주황 점: 기준 장소 · 주황 선: 검색 반경. 점에 마우스를 올리면 이름과 거리가 나옵니다.")
    st.pydeck_chart(restaurant_map(shown, center, result["radius"]), height=MAP_HEIGHT)

    chart_left, chart_right = st.columns(2)
    with chart_left:
        st.markdown("**업종별 음식점 수**")
        st.altair_chart(category_chart(shown))
    with chart_right:
        st.markdown("**거리별 음식점 수**")
        if shown["distance"].notna().any():
            st.altair_chart(distance_chart(shown))
        else:
            st.info("거리 정보가 없습니다.")

    # 받아 둔 이름과 주소로 만들므로 카카오를 부르지 않는다. 주소의 빈칸·기호는 주소창에 맞게 바꾼다.
    shown = shown.assign(
        naver_url=[
            NAVER_SEARCH_URL + quote(f"{name} {address}", safe="")
            for name, address in zip(shown["name"], shown["address"])
        ]
    )

    st.dataframe(
        shown,
        hide_index=True,
        column_order=["name", "category", "detail", "distance", "phone", "address", "url", "naver_url"],
        column_config={
            "name": "이름",
            "category": "업종",
            "detail": "세부 업종",
            "distance": st.column_config.NumberColumn("거리", format="%d m"),
            "phone": "전화",
            "address": "주소",
            "url": st.column_config.LinkColumn("카카오맵", display_text="열기"),
            "naver_url": st.column_config.LinkColumn("네이버 지도", display_text="열기"),
        },
    )


# override=True: .env 를 고친 뒤 화면만 새로 고쳐도 새 값을 읽는다
load_dotenv(pathlib.Path(__file__).with_name(".env"), override=True)
api_key = os.environ.get(KEY_NAME, "").strip()

st.set_page_config(page_title="점심 맛집 대시보드", page_icon="🍽️", layout="wide")
st.title("🍽️ 점심 맛집 대시보드")
st.caption("카카오 로컬 API 에는 평점·리뷰가 없습니다. 거리와 업종으로 고르고, 후기는 카카오맵 링크에서 확인하세요.")

if not api_key:
    st.error(f"키 없음. .env 에 {KEY_NAME}=... 줄이 있는지 확인하세요.")
    st.stop()

# busy: 답을 기다리는 중인지. 기다리는 동안은 버튼을 잠가 두 번 부르지 않게 한다.
# result: 화면을 다시 그려도 남아 있어야 하는 마지막 검색 결과
# error: 마지막 검색이 실패했을 때 보여 줄 안내
# chosen: 후보에서 고른 기준 장소. 있으면 그 장소로 음식점만 다시 찾는다.
st.session_state.setdefault("busy", False)
st.session_state.setdefault("result", None)
st.session_state.setdefault("error", None)
st.session_state.setdefault("chosen", None)


def start_search():
    st.session_state.busy = True


def choose_center(candidate):
    st.session_state.chosen = candidate
    st.session_state.busy = True


# 폼 안의 입력은 버튼을 눌러야 반영된다. Enter 로는 검색되지 않게 막아 둔다.
with st.form("search_form", enter_to_submit=False):
    place_col, keyword_col = st.columns(2)
    center_query = place_col.text_input(
        "기준 장소", value=DEFAULT_CENTER, placeholder="역이나 동네 이름. 예: 전주역, 서신동"
    )
    keyword = keyword_col.text_input("찾을 음식 (직접 입력)", placeholder="예: 비빔밥, 칼국수. 비우면 음식점 전체")
    food_pick = st.pills("찾을 음식 (빠른 선택. 직접 입력한 말이 있으면 그 말로 찾아요)", FOOD_CHOICES)
    radius_col, order_col = st.columns([3, 2])
    radius = radius_col.slider("반경", 100, 5000, 1000, step=100, format="%d m")
    order = order_col.radio("가져오는 기준", list(FETCH_ORDERS), horizontal=True)
    st.form_submit_button(
        "검색 중..." if st.session_state.busy else "검색",
        type="primary",
        disabled=st.session_state.busy,
        on_click=start_search,
    )

if st.session_state.busy:
    chosen = st.session_state.chosen
    previous = st.session_state.result
    if chosen and previous:
        # 후보만 바꾼 것이므로 조건은 지난 검색 그대로 쓴다
        center_query = previous["query"]
        keyword = previous["food"]
        radius = previous["radius"]
        order = previous["order"]
    else:
        center_query = center_query.strip()
        keyword = keyword.strip() or food_pick or ""
    st.session_state.result = None
    st.session_state.error = None
    try:
        if not center_query:
            raise KakaoError("기준 장소를 넣어 주세요.")
        with st.spinner("카카오에서 음식점을 찾는 중..."):
            if chosen and previous:
                center = {**previous["center"], **chosen}
            else:
                center = find_center(api_key, center_query)
            places, total = find_restaurants(api_key, center, keyword, radius, FETCH_ORDERS[order])
        st.session_state.result = {
            "query": center_query,
            "food": keyword,
            "center": center,
            "radius": radius,
            "order": order,
            "total": total,
            "table": to_table(places),
        }
    except KakaoError as err:
        st.session_state.error = str(err)
    finally:
        # 다 끝났으니 버튼을 다시 푼다. 도중에 끊겨도 다시 부르지 않는다.
        st.session_state.busy = False
        st.session_state.chosen = None
    st.rerun()

if st.session_state.error:
    st.error(st.session_state.error)
elif st.session_state.result:
    show_results(st.session_state.result)
else:
    st.info("조건을 확인하고 [검색] 버튼을 누르세요. 버튼을 누르기 전에는 카카오를 부르지 않습니다.")
