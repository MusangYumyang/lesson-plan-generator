"""교안 원본 보관함 — Supabase Storage `lesson_docs` 버킷에 강사용 교안 원본(PDF)을 올리고, 문서마다 잠깐만 열리는 내려받기 링크를 보여 줍니다.

실행: streamlit run lesson_docs.py
필요: .env 에 SUPABASE_URL, SUPABASE_KEY (guestbook.py 와 같은 값)

버킷(비공개)과 허용(올리기 insert, 보기 select)은 Supabase 대시보드에서 미리 만들어 둡니다.
버킷이 비공개라 내려받기 링크는 서명된 주소(SIGNED_URL_SECONDS 동안만 유효)로 만든다.
"""

import base64
import binascii
import datetime as dt
import pathlib
import re
import uuid

import streamlit as st

from guestbook import get_client

BUCKET = "lesson_docs"
MAX_MB = 20
PAGE = 100  # Storage list() 는 한 번에 100개씩 가져온다
SIGNED_URL_SECONDS = 10 * 60
KST = dt.timezone(dt.timedelta(hours=9))
# lesson_images.py 와 같은 3D 고양이: Microsoft Fluent Emoji (MIT 라이선스, https://github.com/microsoft/fluentui-emoji)
CAT_ICON_URL = "https://cdn.jsdelivr.net/gh/microsoft/fluentui-emoji@main/assets/Cat%20face/3D/cat_face_3d.png"
# 시각_번호_원래이름(base64url).pdf
NAME_RE = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{6}_([A-Za-z0-9_-]+)\.pdf$")


def _kst(created_at: str) -> str:
    try:
        return dt.datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return created_at[:16].replace("T", " ")


def _size(n: int) -> str:
    return f"{n / 1024 / 1024:.1f}MB" if n >= 1024 * 1024 else f"{max(n // 1024, 1)}KB"


def _storage_name(original: str) -> str:
    """Storage 파일 이름에는 한글을 쓸 수 없어, 원래 이름을 영문·숫자(base64url)로 바꿔 담고 앞에 시각과 짧은 번호를 붙인다."""
    stem = pathlib.Path(original).stem[:60] or "교안"
    encoded = base64.urlsafe_b64encode(stem.encode("utf-8")).decode("ascii").rstrip("=")
    stamp = dt.datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{uuid.uuid4().hex[:6]}_{encoded}.pdf"


def display_name(path: str) -> str:
    """_storage_name 으로 만든 이름이면 원래 한글 이름을, 아니면 Storage 이름을 그대로 돌려준다."""
    m = NAME_RE.match(path)
    if not m:
        return path
    encoded = m.group(1)
    try:
        return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8") + ".pdf"
    except (binascii.Error, UnicodeDecodeError):
        return path


def upload_doc(name: str, data: bytes) -> str:
    path = _storage_name(name)
    get_client().storage.from_(BUCKET).upload(path, data, {"content-type": "application/pdf", "upsert": "false"})
    return path


def fetch_docs() -> list[dict]:
    """버킷 맨 위 칸의 문서를 모두(최근 것부터) 가져온다. 폴더와 빈 폴더 표시 파일은 뺀다."""
    bucket = get_client().storage.from_(BUCKET)
    items: list[dict] = []
    offset = 0
    while True:
        page = bucket.list("", {"limit": PAGE, "offset": offset, "sortBy": {"column": "created_at", "order": "desc"}})
        items.extend(i for i in page if i.get("id") and not i["name"].startswith("."))
        if len(page) < PAGE:
            return items
        offset += PAGE


def download_url(path: str) -> str:
    """내려받을 때 원래 이름으로 저장되도록 download 에 이름을 넣는다."""
    res = get_client().storage.from_(BUCKET).create_signed_url(
        path, SIGNED_URL_SECONDS, {"download": display_name(path)}
    )
    return res["signedURL"]


def render_lesson_docs() -> None:
    """교안 원본 보관함 화면 본문."""
    # st.title 에는 그림을 넣을 수 없어, 같은 h1 을 직접 쓰고 고양이를 글자 높이(1em)로 맞춘다
    st.markdown(
        f'<h1><img src="{CAT_ICON_URL}" alt="" style="height:1em;vertical-align:-0.12em;margin-right:0.25em">'
        "교안 원본 보관함</h1>",
        unsafe_allow_html=True,
    )
    st.caption("강사용 교안 원본(PDF)을 올려 두고, 필요할 때 내려받습니다.")

    with st.form("lesson_doc_form", clear_on_submit=True):
        files = st.file_uploader(
            f"교안 PDF 고르기 (여러 개 가능, 하나에 {MAX_MB}MB 까지)",
            type=["pdf"],
            accept_multiple_files=True,
        )
        submitted = st.form_submit_button("올리기", width="stretch")

    if submitted:
        if not files:
            st.warning("올릴 PDF 를 먼저 골라 주세요.")
        for f in files or []:
            data = f.getvalue()
            if f.size > MAX_MB * 1024 * 1024:
                st.warning(f"{f.name} 은(는) {MAX_MB}MB 보다 커서 올리지 않았습니다.")
                continue
            if not data.startswith(b"%PDF"):
                st.warning(f"{f.name} 은(는) PDF 파일이 아니어서 올리지 않았습니다.")
                continue
            try:
                upload_doc(f.name, data)
                st.success(f"{f.name} 을(를) 올렸습니다.")
            except RuntimeError as e:  # .env 값이 비어 있을 때
                st.error(str(e))
                st.stop()
            except Exception as e:  # noqa: BLE001
                st.error(f"{f.name} 을(를) 올리지 못했습니다: {e}")

    st.divider()

    try:
        docs = fetch_docs()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()
    except Exception as e:  # noqa: BLE001
        st.error(f"문서 목록을 불러오지 못했습니다: {e}")
        st.info(f"Supabase Storage 에 {BUCKET} 버킷과 보기(select) 허용이 있는지 확인하세요.")
        st.stop()

    st.metric("올라와 있는 교안", f"{len(docs)}개")
    if not docs:
        st.info("아직 올린 교안이 없습니다. 위에서 첫 교안을 올려 보세요.")
        return
    st.caption(f"내려받기 링크는 화면을 연 뒤 {SIGNED_URL_SECONDS // 60}분 동안만 열립니다. 지나면 새로고침하세요.")

    for item in docs:
        size = (item.get("metadata") or {}).get("size")
        info = _kst(str(item.get("created_at", ""))) + (f" · {_size(size)}" if size else "")
        with st.container(border=True):
            st.markdown(f"**📄 {display_name(item['name'])}**")
            st.caption(info)
            try:
                st.link_button("내려받기", download_url(item["name"]), width="stretch")
            except Exception as e:  # noqa: BLE001
                st.warning(f"내려받기 링크를 만들지 못했습니다: {e}")


if __name__ == "__main__":
    st.set_page_config(page_title="교안 원본 보관함", page_icon=CAT_ICON_URL, layout="centered")
    render_lesson_docs()
