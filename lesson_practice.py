"""교안 관리 — Supabase `lesson_practice` 표를 보고, 수업 시간을 고치고, 잠그거나 풀고, 지웁니다.

실행: streamlit run lesson_practice.py
필요: .env (올린 곳에서는 Secrets) 에 SUPABASE_URL, SUPABASE_KEY

잠긴 교안은 풀기 전까지 수업 시간을 고치거나 지울 수 없습니다.
쓰기 요청은 모두 고른 줄의 id 를 조건으로 걸어, 그 한 줄만 바뀝니다.
"""

import datetime as dt

import streamlit as st
from supabase import Client, create_client

from app_keys import get_key

TABLE = "lesson_practice"
COLUMNS = "id, created_at, title, topic, minutes, locked"
PAGE_SIZE = 1000  # Supabase 는 한 번에 줄 수를 제한하므로, 합계가 틀리지 않게 끝까지 나눠서 읽는다
KST = dt.timezone(dt.timedelta(hours=9))  # Supabase 는 UTC 로 저장하므로 목록에는 한국 시간으로 보여 준다
NO_CHANGE = "바뀐 줄이 없습니다. 이미 지워졌거나 잠겼을 수 있고, Supabase 권한(RLS)이 막았을 수도 있습니다."


@st.cache_resource
def get_client() -> Client:
    # os.environ 은 보지 않는다: 시스템 환경 변수가 아니라 .env (올린 곳에서는 Secrets) 의 값만 쓰기 위해서다
    url = get_key("SUPABASE_URL")
    key = get_key("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError(".env (올린 곳에서는 Secrets) 의 SUPABASE_URL / SUPABASE_KEY 가 비어 있습니다.")
    return create_client(url, key)


def fetch_lessons(client: Client) -> list[dict]:
    rows: list[dict] = []
    while True:
        res = (
            client.table(TABLE)
            .select(COLUMNS)
            .order("id")
            .range(len(rows), len(rows) + PAGE_SIZE - 1)
            .execute()
        )
        if not res.data:
            return rows
        rows += res.data


# 아래 세 함수는 RLS 가 막으면 오류 없이 0줄만 돌려주므로, 실제로 바뀐 줄이 있는지를 돌려준다
def update_minutes(client: Client, lesson_id: int, minutes: int) -> bool:
    res = client.table(TABLE).update({"minutes": minutes}).eq("id", lesson_id).eq("locked", False).execute()
    return bool(res.data)


def update_locked(client: Client, lesson_id: int, locked: bool) -> bool:
    res = client.table(TABLE).update({"locked": locked}).eq("id", lesson_id).execute()
    return bool(res.data)


def delete_lesson(client: Client, lesson_id: int) -> bool:
    res = client.table(TABLE).delete().eq("id", lesson_id).eq("locked", False).execute()
    return bool(res.data)


def _kst(created_at: str) -> str:
    try:
        return dt.datetime.fromisoformat(created_at).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return created_at[:16].replace("T", " ")


def _apply(write, *args, done: str) -> bool:
    """쓰기를 한 번 실행하고, 결과 안내를 다음 화면 위쪽에 띄울 수 있게 남긴다."""
    st.session_state.pop("confirm_delete_id", None)
    try:
        changed = write(get_client(), *args)
    except Exception as e:  # noqa: BLE001
        st.session_state["notice"] = ("error", f"저장에 실패했습니다: {e}")
        return False
    st.session_state["notice"] = ("success", done) if changed else ("warning", NO_CHANGE)
    return changed


def _on_save_minutes(lesson_id: int) -> None:
    minutes = st.session_state[f"minutes_{lesson_id}"]
    _apply(update_minutes, lesson_id, minutes, done=f"#{lesson_id} 수업 시간을 {minutes}분으로 고쳤습니다.")


def _on_toggle_lock(lesson_id: int, locked: bool) -> None:
    word = "잠갔습니다" if locked else "풀었습니다"
    _apply(update_locked, lesson_id, locked, done=f"#{lesson_id} 교안을 {word}.")


def _on_ask_delete(lesson_id: int) -> None:
    st.session_state["confirm_delete_id"] = lesson_id


def _on_cancel_delete() -> None:
    st.session_state.pop("confirm_delete_id", None)


def _on_confirm_delete(lesson_id: int) -> None:
    if _apply(delete_lesson, lesson_id, done=f"#{lesson_id} 교안을 지웠습니다."):
        st.session_state.pop("selected_id", None)


def _render_actions(row: dict) -> None:
    """고른 한 줄을 고치고, 잠그고, 지우는 부분."""
    lesson_id, locked = row["id"], bool(row.get("locked"))

    if locked:
        st.info("🔒 잠긴 교안입니다. 고치거나 지우려면 먼저 잠금을 풀어 주세요.")

    st.number_input(
        "수업 시간(분)",
        min_value=1,
        step=5,
        value=max(row.get("minutes") or 1, 1),
        key=f"minutes_{lesson_id}",
        disabled=locked,
    )
    st.button("시간 저장", on_click=_on_save_minutes, args=(lesson_id,), disabled=locked, width="stretch")

    lock_col, delete_col = st.columns(2)
    lock_col.button(
        "🔓 잠금 풀기" if locked else "🔒 잠그기",
        on_click=_on_toggle_lock,
        args=(lesson_id, not locked),
        width="stretch",
    )
    delete_col.button("🗑 지우기", on_click=_on_ask_delete, args=(lesson_id,), disabled=locked, width="stretch")

    if st.session_state.get("confirm_delete_id") == lesson_id and not locked:
        st.warning(f"#{lesson_id} 「{row.get('title')}」 교안을 정말 지울까요? 지우면 되돌릴 수 없습니다.")
        yes_col, no_col = st.columns(2)
        yes_col.button("네, 지웁니다", type="primary", on_click=_on_confirm_delete, args=(lesson_id,), width="stretch")
        no_col.button("아니요", on_click=_on_cancel_delete, width="stretch")


def render_lesson_practice() -> None:
    st.title("📚 교안 관리")

    notice = st.session_state.pop("notice", None)
    if notice:
        kind, message = notice
        getattr(st, kind)(message)

    try:
        rows = fetch_lessons(get_client())
    except RuntimeError as e:  # .env·Secrets 값이 비어 있을 때
        st.error(str(e))
        return
    except Exception as e:  # noqa: BLE001
        st.error(f"교안을 불러오지 못했습니다: {e}")
        st.info(f"Supabase 에 {TABLE} 표가 있는지 확인하세요.")
        return

    count_col, locked_col, minutes_col = st.columns(3)
    count_col.metric("교안 줄 수", len(rows))
    locked_col.metric("잠긴 교안 수", sum(1 for row in rows if row.get("locked")))
    minutes_col.metric("수업 시간 합계(분)", sum(row.get("minutes") or 0 for row in rows))

    if not rows:
        st.info("아직 교안이 없습니다.")
        return

    st.dataframe(
        [
            {
                **row,
                "created_at": _kst(str(row.get("created_at", ""))),
                "locked": "🔒 잠김" if row.get("locked") else "풀림",
            }
            for row in rows
        ],
        column_order=["id", "title", "topic", "minutes", "locked", "created_at"],
        column_config={
            "id": st.column_config.NumberColumn("id", format="%d", width="small"),
            "title": "교안",
            "topic": "주제",
            "minutes": st.column_config.NumberColumn("수업 시간(분)", format="%d"),
            "locked": "잠금",
            "created_at": "만든 때",
        },
        hide_index=True,
        width="stretch",
    )

    by_id = {row["id"]: row for row in rows}
    if st.session_state.get("selected_id") not in by_id:  # 다른 곳에서 지워진 줄이 골라져 있지 않게 한다
        st.session_state.pop("selected_id", None)

    st.subheader("고를 교안")
    selected_id = st.selectbox(
        "고칠 교안을 고르세요",
        options=list(by_id),
        index=None,
        format_func=lambda i: f"#{i} · {by_id[i].get('title')} · {by_id[i].get('minutes')}분"
        + (" · 🔒" if by_id[i].get("locked") else ""),
        placeholder="교안을 고르세요",
        key="selected_id",
        on_change=_on_cancel_delete,
    )
    if selected_id is not None:
        _render_actions(by_id[selected_id])


if __name__ == "__main__":
    st.set_page_config(page_title="교안 관리", page_icon="📚", layout="centered")
    render_lesson_practice()
