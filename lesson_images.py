"""교안 그림 보관함 — Supabase Storage `lesson_images` 버킷에 그림을 올리고, 올라온 그림을 모두 보여 줍니다.

실행: streamlit run lesson_images.py
필요: .env 에 SUPABASE_URL, SUPABASE_KEY (guestbook.py 와 같은 값)

버킷과 허용(올리기 insert, 보기 select)은 Supabase 대시보드에서 미리 만들어 둡니다.
버킷이 비공개여도 보이도록 그림 주소는 서명된 주소(SIGNED_URL_SECONDS 동안 유효)로 만든다.
"""

import datetime as dt
import pathlib
import re
import uuid

import streamlit as st

from guestbook import get_client
from korean_page import korean_page

BUCKET = "lesson_images"
ALLOWED_TYPES = ["png", "jpg", "jpeg", "gif", "webp"]
MAX_MB = 5
PAGE = 100  # Storage list() 는 한 번에 100개씩 가져온다
COLUMNS = 3
SIGNED_URL_SECONDS = 60 * 60
KST = dt.timezone(dt.timedelta(hours=9))
# app.py 상담 챗봇 버튼과 같은 3D 고양이: Microsoft Fluent Emoji (MIT 라이선스, https://github.com/microsoft/fluentui-emoji)
# app.py 를 import 하면 앱 전체가 실행되므로 주소만 같은 값으로 둔다
CAT_ICON_URL = "https://cdn.jsdelivr.net/gh/microsoft/fluentui-emoji@main/assets/Cat%20face/3D/cat_face_3d.png"


def _kst(created_at: str) -> str:
    try:
        return dt.datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return created_at[:16].replace("T", " ")


def _storage_name(original: str) -> str:
    """Storage 파일 이름에는 한글을 쓸 수 없어, 영문·숫자만 남기고 앞에 시각과 짧은 번호를 붙인다."""
    path = pathlib.Path(original)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", path.stem).strip("_")[:40] or "image"
    stamp = dt.datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{uuid.uuid4().hex[:6]}_{stem}{path.suffix.lower()}"


def upload_image(name: str, data: bytes, content_type: str) -> str:
    path = _storage_name(name)
    get_client().storage.from_(BUCKET).upload(path, data, {"content-type": content_type, "upsert": "false"})
    return path


def fetch_images() -> list[dict]:
    """버킷 맨 위 칸의 그림을 모두(최근 것부터) 가져온다. 폴더와 빈 폴더 표시 파일은 뺀다."""
    bucket = get_client().storage.from_(BUCKET)
    items: list[dict] = []
    offset = 0
    while True:
        page = bucket.list("", {"limit": PAGE, "offset": offset, "sortBy": {"column": "created_at", "order": "desc"}})
        items.extend(i for i in page if i.get("id") and not i["name"].startswith("."))
        if len(page) < PAGE:
            return items
        offset += PAGE


def signed_urls(paths: list[str]) -> dict[str, str]:
    if not paths:
        return {}
    res = get_client().storage.from_(BUCKET).create_signed_urls(paths, SIGNED_URL_SECONDS)
    return {r["path"]: r["signedURL"] for r in res if r.get("signedURL")}


def render_lesson_images() -> None:
    """교안 그림 보관함 화면 본문."""
    # st.title 에는 그림을 넣을 수 없어, 같은 h1 을 직접 쓰고 고양이를 글자 높이(1em)로 맞춘다
    st.markdown(
        f'<h1><img src="{CAT_ICON_URL}" alt="" style="height:1em;vertical-align:-0.12em;margin-right:0.25em">'
        "교안 그림 보관함</h1>",
        unsafe_allow_html=True,
    )
    st.caption("교안에 넣을 그림을 올려 두고, 올린 그림을 한눈에 봅니다.")

    with st.form("lesson_image_form", clear_on_submit=True):
        files = st.file_uploader(
            f"그림 고르기 (여러 장 가능, 한 장에 {MAX_MB}MB 까지)",
            type=ALLOWED_TYPES,
            accept_multiple_files=True,
        )
        submitted = st.form_submit_button("올리기", width="stretch")

    if submitted:
        if not files:
            st.warning("올릴 그림을 먼저 골라 주세요.")
        for f in files or []:
            if f.size > MAX_MB * 1024 * 1024:
                st.warning(f"{f.name} 은(는) {MAX_MB}MB 보다 커서 올리지 않았습니다.")
                continue
            try:
                upload_image(f.name, f.getvalue(), f.type or "application/octet-stream")
                st.success(f"{f.name} 을(를) 올렸습니다.")
            except RuntimeError as e:  # .env 값이 비어 있을 때
                st.error(str(e))
                st.stop()
            except Exception as e:  # noqa: BLE001
                st.error(f"{f.name} 을(를) 올리지 못했습니다: {e}")

    st.divider()

    try:
        images = fetch_images()
        urls = signed_urls([i["name"] for i in images])
    except RuntimeError as e:
        st.error(str(e))
        st.stop()
    except Exception as e:  # noqa: BLE001
        st.error(f"그림을 불러오지 못했습니다: {e}")
        st.info(f"Supabase Storage 에 {BUCKET} 버킷과 보기(select) 허용이 있는지 확인하세요.")
        st.stop()

    st.metric("올라와 있는 그림", f"{len(images)}장")
    if not images:
        st.info("아직 올린 그림이 없습니다. 위에서 첫 그림을 올려 보세요.")
        return

    cols = st.columns(COLUMNS)
    for n, item in enumerate(images):
        with cols[n % COLUMNS]:
            url = urls.get(item["name"])
            if url:
                st.image(url, width="stretch")
            else:
                st.warning("그림 주소를 만들지 못했습니다.")
            st.caption(f"{_kst(str(item.get('created_at', '')))}  \n{item['name']}")


if __name__ == "__main__":
    st.set_page_config(page_title="교안 그림 보관함", page_icon=CAT_ICON_URL, layout="wide")
    korean_page()  # 크롬이 영어 페이지로 알고 다시 번역하지 않게 한다
    render_lesson_images()
