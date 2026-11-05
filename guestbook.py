"""한 줄 방명록 — Supabase `guestbook` 표에 글이 쌓입니다.

실행: streamlit run guestbook.py  (또는 app.py 사이드바의 '한 줄 방명록' 버튼)
필요: .env 에 SUPABASE_URL, SUPABASE_KEY

Supabase SQL Editor에서 표를 먼저 만들어 두세요:

    create table if not exists guestbook (
      id         bigint generated always as identity primary key,
      name       text not null,
      message    text not null,
      created_at timestamptz not null default now()
    );
    alter table guestbook enable row level security;
    create policy "anyone can read"  on guestbook for select using (true);
    create policy "anyone can write" on guestbook for insert with check (true);
"""

import os

import streamlit as st
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

TABLE = "guestbook"
MAX_NAME = 20
MAX_MESSAGE = 100
LIMIT = 50


@st.cache_resource
def get_client() -> Client:
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError(".env 의 SUPABASE_URL / SUPABASE_KEY 가 비어 있습니다.")
    return create_client(url, key)


def fetch_entries(client: Client) -> list[dict]:
    res = (
        client.table(TABLE)
        .select("id, name, message, created_at")
        .order("created_at", desc=True)
        .limit(LIMIT)
        .execute()
    )
    return res.data or []


def add_entry(client: Client, name: str, message: str) -> None:
    client.table(TABLE).insert({"name": name, "message": message}).execute()


def render_guestbook(show_title: bool = True) -> None:
    """방명록 화면 본문. app.py 의 한 화면으로도, 단독 페이지로도 쓰인다."""
    if show_title:
        st.title("📝 한 줄 방명록")

    try:
        client = get_client()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    with st.form("guestbook_form", clear_on_submit=True):
        name = st.text_input("이름", max_chars=MAX_NAME, placeholder="홍길동")
        message = st.text_input("한 줄 남기기", max_chars=MAX_MESSAGE, placeholder="오늘 수업 재미있었어요!")
        submitted = st.form_submit_button("남기기", use_container_width=True)

    if submitted:
        name, message = name.strip(), message.strip()
        if not name or not message:
            st.warning("이름과 한 줄 메시지를 모두 입력해 주세요.")
        else:
            try:
                add_entry(client, name, message)
                st.success("방명록에 남겼습니다.")
            except Exception as e:
                st.error(f"저장에 실패했습니다: {e}")

    st.divider()

    try:
        entries = fetch_entries(client)
    except Exception as e:
        st.error(f"방명록을 불러오지 못했습니다: {e}")
        st.stop()

    st.caption(f"최근 {len(entries)}개")
    if not entries:
        st.info("아직 글이 없습니다. 첫 글을 남겨 보세요.")
    for row in entries:
        when = str(row.get("created_at", ""))[:16].replace("T", " ")
        st.markdown(f"**{row['name']}** · {when}  \n{row['message']}")


if __name__ == "__main__":
    st.set_page_config(page_title="한 줄 방명록", page_icon="📝", layout="centered")
    render_guestbook()
