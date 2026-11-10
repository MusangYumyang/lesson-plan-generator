"""AI 기록 — AI가 답할 때마다 넣은 것(question)과 받은 답(answer)을 Supabase `chat_log` 표에 남깁니다.

app.py 가 AI 를 부르는 네 곳(교안 생성, 아티팩트 만들기·고치기, 프롬프트 생성기, 상담 챗봇)에서 save_log() 를 부르고,
사이드바의 'AI 기록' 버튼으로 render_ai_logs() 화면을 엽니다.
필요: .env (올린 곳에서는 Secrets) 에 SUPABASE_URL, SUPABASE_KEY (guestbook.py 와 같은 값)

Supabase 에 만들어 둔 표 (열: id, created_at, question, answer, owner):

    create table chat_log (
      id         bigint generated always as identity primary key,
      created_at timestamptz not null default now(),
      question   text,
      answer     text,
      owner      text  -- AI 기록 화면의 이름 칸에 넣은 이름. 비어 있으면 null (예전 줄도 null)
    );
"""

import datetime as dt

import streamlit as st

from guestbook import get_client

TABLE = "chat_log"
LIMIT = 50
OWNER_KEY = "ai_log_owner"  # 이름 칸 값을 화면을 옮겨도 남게 따로 기억해 두는 자리
KST = dt.timezone(dt.timedelta(hours=9))  # Supabase 는 UTC 로 저장하므로 목록에는 한국 시간으로 보여 준다


def _kst(created_at: str) -> str:
    try:
        return dt.datetime.fromisoformat(created_at).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return created_at[:16].replace("T", " ")


def save_log(question: str, answer: str) -> None:
    """한 번의 AI 답을 남긴다. 기록이 실패해도 수업 준비 흐름은 멈추지 않고 짧은 안내만 띄운다."""
    try:
        row = {"question": question, "answer": answer}
        owner = st.session_state.get(OWNER_KEY, "")
        if owner:  # 이름이 비어 있으면 owner 없이 남긴다
            row["owner"] = owner
        get_client().table(TABLE).insert(row).execute()
    except Exception as e:  # noqa: BLE001 - 기록은 부가 기능이라 본 기능을 막지 않는다
        st.toast(f"AI 기록을 남기지 못했습니다: {type(e).__name__}", icon="⚠️")


def fetch_logs(owner: str, day: dt.date | None = None) -> list[dict]:
    """owner 의 기록만 가져온다. day 를 주면 그날(한국 시간) 기록만, 없으면 최근 기록."""
    query = get_client().table(TABLE).select("id, created_at, question, answer, owner").eq("owner", owner)
    if day:
        start = dt.datetime.combine(day, dt.time.min, tzinfo=KST)
        end = start + dt.timedelta(days=1)
        query = query.gte("created_at", start.isoformat()).lt("created_at", end.isoformat())
    res = query.order("created_at", desc=True).limit(LIMIT).execute()
    return res.data or []


def render_ai_logs() -> None:
    """지난 AI 기록 목록 화면."""
    st.title("🗂 AI 기록")
    st.caption("AI가 답할 때마다 넣은 것과 받은 답이 여기에 쌓입니다.")

    # 위젯 값은 화면을 떠나면 지워지므로, 기억해 둔 이름을 다시 채워 넣고 바뀐 값은 OWNER_KEY 에 옮겨 둔다
    if "ai_log_name" not in st.session_state:
        st.session_state["ai_log_name"] = st.session_state.get(OWNER_KEY, "")
    col_day, col_name = st.columns(2)
    with col_day:
        day = st.date_input("날짜 고르기", value=None, format="YYYY-MM-DD", key="ai_log_date")
    with col_name:
        owner = st.text_input("이름", key="ai_log_name", placeholder="예: 김강사").strip()
    st.session_state[OWNER_KEY] = owner

    if not owner:
        st.info("이름을 넣어 주세요")
        return

    try:
        rows = fetch_logs(owner, day)
    except RuntimeError as e:  # .env·Secrets 값이 비어 있을 때
        st.error(str(e))
        return
    except Exception as e:  # noqa: BLE001
        st.error(f"AI 기록을 불러오지 못했습니다: {e}")
        st.info(f"Supabase 에 {TABLE} 표가 있는지 확인하세요.")
        return

    st.caption(f"{day} 기록 {len(rows)}개" if day else f"최근 {len(rows)}개")
    if not rows:
        if day:
            st.info(f"{day} 에는 기록이 없습니다. 다른 날짜를 고르거나 날짜를 지워 전체 목록을 보세요.")
        else:
            st.info("아직 기록이 없습니다. 교안을 만들거나 챗봇에 물어보면 여기에 쌓입니다.")
    for row in rows:
        when = _kst(str(row.get("created_at", "")))
        question = (row.get("question") or "").strip()
        first_line = question.splitlines()[0][:40] if question else "(빈 입력)"
        with st.expander(f"{when} · {first_line}"):
            st.markdown("**넣은 것**")
            st.code(question, language=None, wrap_lines=True)
            st.markdown("**받은 답**")
            st.code(row.get("answer") or "", language=None, wrap_lines=True)
