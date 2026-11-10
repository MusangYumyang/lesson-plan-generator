"""수강생용 방 두 개 — 자료방과 결과물방. 파일은 Supabase Storage 에, 목록은 Supabase 표에 남깁니다.

배포한 앱(Streamlit Community Cloud)은 다시 뜰 때 앱 폴더에 저장한 파일을 잃으므로, 파일은 앱에 두지 않고
Storage 에 올린 뒤 표에는 경로(file_path)만 적습니다.

필요: .env (올린 곳에서는 Secrets) 에 SUPABASE_URL, SUPABASE_KEY (guestbook.py 와 같은 값)

Supabase 에 만들어 둔 것 (SQL 은 이미 실행됨):
    표 materials : id, created_at, owner, category, title, note, file_path, link, hidden
    표 showcase  : id, created_at, owner, lesson_title, student_name, note, file_path, link, hidden
    버킷 materials, showcase (둘 다 공개)
    접근 규칙은 읽기(select)와 넣기(insert)만 있다. 지우기·고치기 권한이 없으므로 그런 코드는 넣지 않는다.
    숨기기는 Supabase 화면에서 hidden 을 true 로 바꾸면 되고, 목록은 hidden 이 true 인 줄을 보여 주지 않는다.

owner 는 강사 ID. 공유 링크 ?share=materials:강사ID / ?share=results:강사ID 의 강사ID 로 그 강사 것만 보여 준다.
"""

from __future__ import annotations

import datetime as dt
import html
import pathlib
import re
import uuid

import streamlit as st

from guestbook import get_client

MATERIALS_TABLE = MATERIALS_BUCKET = "materials"
# 결과물방: 공유 링크에서는 ?share=results:강사ID 로 부르지만, Supabase 의 표·버킷 이름은 showcase 다
SHOWCASE_TABLE = SHOWCASE_BUCKET = "showcase"

LIMIT = 200
MAX_FILE_MB = 20
MAX_NAME = 20
MAX_TITLE = 60
MAX_NOTE = 100
IMAGE_TYPES = ["png", "jpg", "jpeg", "gif", "webp"]
DOC_TYPES = ["pdf", "txt", "md", "hwp", "hwpx", "docx", "pptx", "xlsx", "csv", "zip"]
KST = dt.timezone(dt.timedelta(hours=9))


def _kst(created_at: str) -> str:
    try:
        return dt.datetime.fromisoformat(created_at).astimezone(KST).strftime("%Y-%m-%d")
    except ValueError:
        return created_at[:10]


def _safe_dir(owner: str) -> str:
    """Storage 경로에는 영문·숫자만 안전하므로 강사 ID 를 그렇게 바꾼다 (표의 owner 에는 원래 값을 적는다)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", owner) or "owner"


def _upload(bucket: str, owner: str, upload) -> str:
    """파일을 Storage 에 올리고 경로를 돌려준다. 이름은 겹치지 않게 uuid 로 짓는다."""
    ext = pathlib.Path(upload.name).suffix.lower()
    path = f"{_safe_dir(owner)}/{uuid.uuid4().hex}{ext}"
    get_client().storage.from_(bucket).upload(
        path, upload.getvalue(), {"content-type": upload.type or "application/octet-stream", "upsert": "false"}
    )
    return path


def _public_url(bucket: str, path: str) -> str:
    return get_client().storage.from_(bucket).get_public_url(path)


def _fetch(table: str, owner: str) -> list[dict]:
    res = (
        get_client().table(table).select("*")
        .eq("owner", owner).eq("hidden", False)  # hidden 이 null 인 줄도 안 보인다 (넣을 때 false 로 적는다)
        .order("created_at", desc=True).limit(LIMIT).execute()
    )
    return res.data or []


def _check_input(upload, link: str) -> str | None:
    """올릴 거리가 맞는지 보고, 문제가 있으면 안내 문구를 돌려준다."""
    if not upload and not link:
        return "파일을 고르거나 링크를 넣어 주세요."
    if link and not re.match(r"https?://", link):
        return "링크는 http:// 또는 https:// 로 시작해야 합니다."
    if upload and upload.size > MAX_FILE_MB * 1024 * 1024:
        return f"파일은 {MAX_FILE_MB}MB 까지 올릴 수 있습니다."
    return None


def _show_item(bucket: str, row: dict) -> None:
    """파일(그림이면 바로 보이게)과 링크를 보여 준다."""
    if row.get("file_path"):
        url = _public_url(bucket, row["file_path"])
        if pathlib.Path(row["file_path"]).suffix.lower().lstrip(".") in IMAGE_TYPES:
            st.image(url)
        st.link_button("📥 파일 열기·내려받기", url, use_container_width=True)
    if row.get("link"):
        st.link_button("🔗 링크 열기", row["link"], use_container_width=True)


def _supabase_ready() -> bool:
    try:
        get_client()
    except RuntimeError as e:  # .env·Secrets 값이 비어 있을 때
        st.error(str(e))
        return False
    return True


# ---------------------------------------------------------------------------
# 자료방: 강사가 주제별로 올리고, 수강생은 보고 내려받는다
# ---------------------------------------------------------------------------
def render_materials(owner: str, can_upload: bool, share_link: str = "") -> None:
    st.title("📚 자료방")
    st.caption("주제별로 묶인 교재자료입니다. 누르면 열리거나 내려받아집니다.")
    if not _supabase_ready():
        return
    try:
        rows = _fetch(MATERIALS_TABLE, owner)
    except Exception as e:  # noqa: BLE001
        st.error(f"자료를 불러오지 못했습니다: {e}")
        return

    if can_upload:
        categories = list(dict.fromkeys(r.get("category") or "기타" for r in rows))
        with st.expander("➕ 자료 올리기", expanded=not rows):
            with st.form("materials_form", clear_on_submit=True):
                category = st.selectbox("주제", categories, index=None, accept_new_options=True,
                                        placeholder="고르거나 새 주제를 적으세요")
                title = st.text_input("자료 이름", max_chars=MAX_TITLE, placeholder="예: 3강 실습 예시 프롬프트 모음")
                note = st.text_input("한 줄 설명 (선택)", max_chars=MAX_NOTE)
                upload = st.file_uploader("파일 (선택)", type=IMAGE_TYPES + DOC_TYPES)
                link = st.text_input("또는 링크 (선택)", placeholder="https://")
                submitted = st.form_submit_button("올리기", type="primary", use_container_width=True)
            if submitted:
                category, title, link = (category or "").strip(), title.strip(), link.strip()
                problem = "주제와 자료 이름을 넣어 주세요." if not category or not title else _check_input(upload, link)
                if problem:
                    st.warning(problem)
                else:
                    try:
                        path = _upload(MATERIALS_BUCKET, owner, upload) if upload else None
                        get_client().table(MATERIALS_TABLE).insert({
                            "owner": owner, "category": category, "title": title, "note": note.strip() or None,
                            "file_path": path, "link": link or None, "hidden": False,
                        }).execute()
                    except Exception as e:  # noqa: BLE001
                        st.error(f"올리지 못했습니다: {e}")
                    else:
                        st.success("올렸습니다.")
                        st.rerun()
        if share_link:
            st.markdown("**수강생에게 줄 링크** (오른쪽 위 복사 버튼 → 오픈채팅방에 붙여 넣기)")
            st.code(share_link, language=None)
        st.divider()

    if not rows:
        st.info("아직 올라온 자료가 없습니다.")
        return
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row.get("category") or "기타", []).append(row)
    for category, items in groups.items():
        st.subheader(f"📂 {category} ({len(items)})")
        for row in items:
            with st.container(border=True):
                st.markdown(f"**{row.get('title') or '(이름 없음)'}**")
                if row.get("note"):
                    st.markdown(row["note"])
                st.caption(_kst(str(row.get("created_at", ""))))
                _show_item(MATERIALS_BUCKET, row)


# ---------------------------------------------------------------------------
# 결과물방: 수강생이 올리고 모두가 본다 (표·버킷 이름은 showcase)
# ---------------------------------------------------------------------------
def render_showcase(owner: str, lesson_titles: list[str]) -> None:
    st.title("🖼️ 결과물방")
    st.caption("실습으로 만든 결과물을 올리고, 다른 수강생 것도 구경해 보세요.")
    if not _supabase_ready():
        return

    with st.expander("➕ 내 결과물 올리기", expanded=True):
        with st.form("showcase_form", clear_on_submit=True):
            student_name = st.text_input("이름", max_chars=MAX_NAME, placeholder="예: 김영희")
            lesson_title = st.selectbox("어느 수업 결과물인가요?", lesson_titles, index=None,
                                        accept_new_options=True, placeholder="고르거나 수업 이름을 적으세요")
            note = st.text_input("한 줄 설명", max_chars=MAX_NOTE, placeholder="예: 제주 3박 4일 일정표를 만들었어요")
            upload = st.file_uploader("파일 (그림·PDF 등)", type=IMAGE_TYPES + DOC_TYPES)
            link = st.text_input("또는 링크", placeholder="https://")
            submitted = st.form_submit_button("올리기", type="primary", use_container_width=True)
        if submitted:
            student_name, note, link = student_name.strip(), note.strip(), link.strip()
            lesson_title = (lesson_title or "").strip()
            problem = ("이름, 수업, 한 줄 설명을 모두 넣어 주세요." if not (student_name and lesson_title and note)
                       else _check_input(upload, link))
            if problem:
                st.warning(problem)
            else:
                try:
                    path = _upload(SHOWCASE_BUCKET, owner, upload) if upload else None
                    get_client().table(SHOWCASE_TABLE).insert({
                        "owner": owner, "lesson_title": lesson_title, "student_name": student_name, "note": note,
                        "file_path": path, "link": link or None, "hidden": False,
                    }).execute()
                except Exception as e:  # noqa: BLE001
                    st.error(f"올리지 못했습니다: {e}")
                else:
                    st.success("올렸습니다. 아래 목록에서 확인하세요.")

    st.divider()
    try:
        rows = _fetch(SHOWCASE_TABLE, owner)
    except Exception as e:  # noqa: BLE001
        st.error(f"결과물을 불러오지 못했습니다: {e}")
        return
    if not rows:
        st.info("아직 올라온 결과물이 없습니다. 첫 결과물을 올려 보세요.")
        return
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row.get("lesson_title") or "기타", []).append(row)
    for lesson_title, items in groups.items():
        st.subheader(f"📘 {lesson_title} ({len(items)})")
        for row in items:
            with st.container(border=True):
                st.markdown(f"**{html.escape(row.get('student_name') or '이름 없음')}** · "
                            f"<span class='small-muted'>{_kst(str(row.get('created_at', '')))}</span>",
                            unsafe_allow_html=True)
                if row.get("note"):
                    st.markdown(row["note"])
                _show_item(SHOWCASE_BUCKET, row)
