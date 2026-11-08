"""AI 기록 — AI가 답할 때마다 넣은 것(question)과 받은 답(answer)을 Supabase `chat_log` 표에 남깁니다.

app.py 가 AI 를 부르는 네 곳(교안 생성, 아티팩트 설계, 프롬프트 생성기, 상담 챗봇)에서 save_log() 를 부르고,
사이드바의 'AI 기록' 버튼으로 render_ai_logs() 화면을 엽니다.
필요: .env 에 SUPABASE_URL, SUPABASE_KEY (guestbook.py 와 같은 값)

Supabase 에 만들어 둔 표 (열: id, created_at, question, answer):

    create table chat_log (
      id         bigint generated always as identity primary key,
      created_at timestamptz not null default now(),
      question   text,
      answer     text
    );
"""

import datetime as dt

import streamlit as st

from guestbook import get_client

TABLE = "chat_log"
LIMIT = 50
KST = dt.timezone(dt.timedelta(hours=9))  # Supabase 는 UTC 로 저장하므로 목록에는 한국 시간으로 보여 준다


def _kst(created_at: str) -> str:
    try:
        return dt.datetime.fromisoformat(created_at).astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return created_at[:16].replace("T", " ")


def save_log(question: str, answer: str) -> None:
    """한 번의 AI 답을 남긴다. 기록이 실패해도 수업 준비 흐름은 멈추지 않고 짧은 안내만 띄운다."""
    try:
        get_client().table(TABLE).insert({"question": question, "answer": answer}).execute()
    except Exception as e:  # noqa: BLE001 - 기록은 부가 기능이라 본 기능을 막지 않는다
        st.toast(f"AI 기록을 남기지 못했습니다: {type(e).__name__}", icon="⚠️")


def fetch_logs(day: dt.date | None = None) -> list[dict]:
    """day 를 주면 그날(한국 시간) 기록만, 없으면 최근 기록을 가져온다."""
    query = get_client().table(TABLE).select("id, created_at, question, answer")
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

    day = st.date_input("날짜 고르기", value=None, format="YYYY-MM-DD", key="ai_log_date")

    try:
        rows = fetch_logs(day)
    except RuntimeError as e:  # .env 값이 비어 있을 때
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
