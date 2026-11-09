"""교안·아티팩트 자동 생성기 (Streamlit MVP)

화면 흐름 (idea/flow.md):
  강의 주제 입력 → 기존 자료 확인 → 교안 및 아티팩트 → 프롬프트 생성기 / 저장된 목록 → 오픈채팅방 공유

실행:
  streamlit run app.py

환경 변수:
  ANTHROPIC_API_KEY  Claude API 키 (필수)
  GEMINI_API_KEY     Gemini API 키. 오른쪽 아래 상담 챗봇에서만 쓴다 (.env 에서 읽음)
  INSTRUCTOR_ID      강사 식별자. 저장 데이터는 이 값으로 분리된다 (기본값: local-instructor)
  APP_BASE_URL       공유 링크에 쓸 기본 주소 (기본값: http://localhost:8501)
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import uuid

import anthropic
import streamlit as st
from dotenv import load_dotenv
from google import genai

from ai_log import render_ai_logs, save_log
from guestbook import render_guestbook
from korean_page import korean_page

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------
MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

APP_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
STORE_PATH = DATA_DIR / "store.json"

OWNER = os.environ.get("INSTRUCTOR_ID", "local-instructor")
BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8501").rstrip("/")

SCREENS = ["주제 입력", "기존 자료 확인", "교안 및 아티팩트", "프롬프트 생성기", "저장된 목록"]
GUESTBOOK_SCREEN = "한 줄 방명록"  # 사이드바 버튼으로만 진입하는 부가 화면
AI_LOG_SCREEN = "AI 기록"  # 사이드바 버튼으로만 진입하는 부가 화면 (Supabase ai_logs 표)

# 오른쪽 아래 상담 챗봇은 helper.py 와 같은 방식으로 Gemini 를 부른다
# (https://ai.google.dev/gemini-api/docs/interactions)
GEMINI_KEY_NAME = "GEMINI_API_KEY"
# 공식 모델 목록의 안정 모델 중 가장 빠른 것 (https://ai.google.dev/gemini-api/docs/models)
CHAT_MODEL = "gemini-3.5-flash-lite"
CHAT_TIMEOUT_SECONDS = 30  # 이 시간(초) 안에 답이 없으면 기다리지 않고 안내를 띄운다

# override=True: .env 를 고친 뒤 화면만 새로 고쳐도 새 값을 읽는다
load_dotenv(APP_DIR / ".env", override=True)

st.set_page_config(page_title="교안 자동 생성기", page_icon="📘", layout="centered")
korean_page()  # 크롬이 영어 페이지로 알고 다시 번역하지 않게 한다

# 모바일에서 버튼·입력칸이 작아지지 않도록 최소한의 스타일만 적용
st.markdown(
    """
    <style>
      .stButton > button { width: 100%; min-height: 3rem; font-size: 1.05rem; }
      textarea, input { font-size: 1.05rem !important; }
      .block-container { padding-top: 1.5rem; padding-bottom: 3rem; max-width: 56rem; }
      .small-muted { color: #6b7280; font-size: 0.9rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# 저장소 (강사별로 분리된 로컬 JSON)
# ---------------------------------------------------------------------------
def _empty_store() -> dict:
    return {"lessons": [], "artifacts": [], "records": []}


def load_store() -> dict:
    if not STORE_PATH.exists():
        return _empty_store()
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    for key in ("lessons", "artifacts", "records"):
        data.setdefault(key, [])
    return data


def save_store(store: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def mine(items: list[dict]) -> list[dict]:
    """현재 강사 소유 항목만 돌려준다 (강사 간 데이터 섞임 방지)."""
    return [i for i in items if i.get("owner") == OWNER]


def find_item(kind: str, item_id: str, any_owner: bool = False) -> dict | None:
    store = load_store()
    pool = store[kind] if any_owner else mine(store[kind])
    return next((i for i in pool if i["id"] == item_id), None)


def set_locked(artifact_id: str, locked: bool) -> None:
    """현재 강사 소유 아티팩트의 잠금 상태를 바꿔 저장한다."""
    store = load_store()
    for artifact in mine(store["artifacts"]):
        if artifact["id"] == artifact_id:
            artifact["locked"] = locked
    save_store(store)


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 중복 강의 스캔
# ---------------------------------------------------------------------------
def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower())


def _bigrams(text: str) -> set[str]:
    t = _normalize(text)
    if len(t) < 2:
        return {t} if t else set()
    return {t[i : i + 2] for i in range(len(t) - 1)}


def similarity(a: str, b: str) -> float:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.85
    ba, bb = _bigrams(a), _bigrams(b)
    return len(ba & bb) / len(ba | bb) if ba | bb else 0.0


def scan_overlap(topic: str, threshold: float = 0.3) -> list[dict]:
    store = load_store()
    hits: list[dict] = []
    for rec in mine(store["records"]):
        score = max(similarity(topic, rec["topic"]), similarity(topic, rec.get("title", "")))
        if score >= threshold:
            lesson = next((l for l in store["lessons"] if l["id"] == rec.get("lesson_id")), None)
            hits.append({"record": rec, "lesson": lesson, "score": score})
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits


# ---------------------------------------------------------------------------
# Claude 호출
# ---------------------------------------------------------------------------
LESSON_SYSTEM = """당신은 시니어 대상 오프라인 AI 수업을 10년 넘게 설계해 온 교육 설계 전문가입니다.
강사 한 명이 혼자 진행하는 수업의 교안을 씁니다. 강사는 이 교안만 보고 그대로 수업을 진행합니다.

수강생 전제
- AI에 어느 정도 익숙한 시니어 학습자. 초보가 아니므로 기초 개념 반복은 짧게, 새로 배우는 조작과 활용은 길게.
- 각자 자기 기기(스마트폰 또는 노트북)로 개별 실습한다. 짝 활동, 조별 활동은 넣지 않는다.
- 호칭은 "수강생" 또는 "여러분"으로 통일한다. "어르신"이라는 호칭을 반복하지 않는다.
- 가족(자녀·손주)과 연결 지어 동기 부여하지 않는다. 학습자 본인의 관심과 생활을 기준으로 쓴다.

교안 작성 규칙
- 한국어, Markdown. 한 장 요약이 아니라 수업 전체를 끌고 갈 수 있는 상세 교안이어야 한다.
- 모든 조작은 "클릭 단위"로 쓴다. 예: "화면 오른쪽 위 ⋮ 버튼을 누른다 → '새 대화'를 누른다". 추상적인 지시("설정을 바꾼다")는 금지.
- 개별 실습은 번호가 붙은 단계로 쓰고, 각 단계마다 수강생이 화면에서 무엇을 보게 되는지 적는다.
- 화면 캡처가 들어갈 자리는 반드시 `> 🖼️ 이미지: (무엇을 보여줄 화면인지 구체적으로)` 형식의 인용문으로 표시한다.
- 실제 앱 화면을 확인할 수 없다면 그 사실을 교안 안에 밝히고, 메뉴 이름이 다를 수 있다는 안내를 덧붙인다.

반드시 포함할 섹션 (이 순서로)
1. 수업 개요: 주제, 대상 수준, 총 시간, 수업 목표 3개, 준비물(기기·앱·계정·와이파이), 강사 사전 준비
2. 수업 흐름표: 시간대별 표 (도입 / 설명 / 실습 / 공유·정리), 각 구간의 분 단위 배분
3. 도입 (질문·동기): 강사가 실제로 말할 스크립트
4. 핵심 설명: 개념을 2~3개로 나누고, 각 개념마다 강사 설명 스크립트 + 보여줄 화면
5. 개별 실습: 실습을 2~3개로 나누고, 각 실습마다 (목표 / 클릭 단위 단계 / 완성 확인 기준 / 빨리 끝낸 수강생용 추가 과제)
6. 예상 막힘과 해결: 표 형식 (막히는 지점 / 증상 / 강사가 할 말과 조작)
7. 마무리: 오늘 배운 것 정리 스크립트, 집에서 해볼 과제 1개, 다음 수업 연결
8. 강사 메모: 시간 부족 시 줄일 부분, 여유 있을 때 더할 부분
"""

ARTIFACT_SYSTEM = """당신은 시니어 AI 수업용 '프롬프트 생성기' 아티팩트를 설계합니다.
아티팩트는 수강생이 수업 중에 링크로 열어 쓰는 화면입니다. 수강생이 몇 가지 칸만 채우면
수업 맥락(대상, 기기, 수업 흐름)이 이미 녹아 있는 완성 프롬프트가 나와야 합니다.

규칙
- 한국어. 수강생을 "수강생" 또는 "여러분"으로 부른다. "어르신" 반복 호칭, 가족 역할 프레이밍 금지.
- 입력 칸(fields)은 3~5개. 각 칸에는 짧은 라벨, 안내 문구(placeholder), 예시 값을 넣는다.
- prompt_template 에는 각 칸의 key 를 {key} 형태로 넣는다. 예: "{topic}에 대해 ..."
- 결과 프롬프트는 수강생이 ChatGPT·Gemini·Claude 등 어떤 챗봇에 붙여 넣어도 바로 쓸 수 있게 완결된 문장으로 쓴다.
"""

ARTIFACT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "아티팩트 이름 (예: '여행 일정 프롬프트 생성기')"},
        "purpose": {"type": "string", "description": "이 아티팩트로 수강생이 얻는 것, 1~2문장"},
        "student_guide": {"type": "string", "description": "수강생에게 보여줄 사용 안내, 3~5문장"},
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "영문 snake_case 키"},
                    "label": {"type": "string"},
                    "placeholder": {"type": "string"},
                    "example": {"type": "string"},
                },
                "required": ["key", "label", "placeholder", "example"],
                "additionalProperties": False,
            },
        },
        "prompt_template": {"type": "string", "description": "{key} 자리표시자가 들어간 프롬프트 틀"},
        "example_output": {"type": "string", "description": "예시 값을 넣었을 때 완성되는 프롬프트"},
    },
    "required": ["title", "purpose", "student_guide", "fields", "prompt_template", "example_output"],
    "additionalProperties": False,
}

PROMPT_SYSTEM = """당신은 시니어 AI 수업에서 쓰는 프롬프트 작성 도우미입니다.
주어진 아티팩트 틀과 수강생이 입력한 조건을 바탕으로, 어떤 챗봇에 붙여 넣어도 바로 쓸 수 있는
완성 프롬프트 하나만 한국어로 출력합니다. 설명, 머리말, 코드 블록 없이 프롬프트 본문만 출력합니다.
수강생이 비워 둔 칸은 합리적인 기본값으로 채우되, 채운 값은 프롬프트 안에 자연스럽게 녹입니다.
"""


@st.cache_resource(show_spinner=False)
def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


class GenerationRefused(RuntimeError):
    pass


def _check_stop(message) -> None:
    if message.stop_reason == "refusal":
        detail = ""
        if getattr(message, "stop_details", None) is not None:
            detail = f" ({message.stop_details.category}: {message.stop_details.explanation})"
        raise GenerationRefused("생성이 거부되었습니다" + detail)
    if message.stop_reason == "max_tokens":
        st.warning("출력 길이 제한에 걸려 끝부분이 잘렸을 수 있습니다.")


def stream_text(system: str, user: str, effort: str, max_tokens: int):
    """Claude 응답을 토막 단위로 돌려주는 제너레이터. st.write_stream 에 바로 넘긴다."""
    client = get_client()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort},
        betas=[FALLBACK_BETA],
        fallbacks="default",
    ) as stream:
        for chunk in stream.text_stream:
            yield chunk
        _check_stop(stream.get_final_message())


def generate_artifact_spec(topic: str, lesson_md: str) -> dict:
    client = get_client()
    user = (
        f"강의 주제: {topic}\n\n"
        "아래는 이 주제의 교안입니다. 교안의 실습과 맞물리는 프롬프트 생성기 아티팩트를 설계하세요.\n\n"
        f"<교안>\n{lesson_md}\n</교안>"
    )
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=16000,
        system=ARTIFACT_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": ARTIFACT_SCHEMA}},
        betas=[FALLBACK_BETA],
        fallbacks="default",
    ) as stream:
        message = stream.get_final_message()
    _check_stop(message)
    text = next(b.text for b in message.content if b.type == "text")
    save_log(user, text)
    return json.loads(text)


def describe_api_error(err: Exception) -> str:
    if isinstance(err, GenerationRefused):
        return str(err)
    if isinstance(err, anthropic.AuthenticationError):
        return "API 키가 올바르지 않습니다. ANTHROPIC_API_KEY 환경 변수를 확인하세요."
    if isinstance(err, anthropic.RateLimitError):
        return "요청이 너무 많습니다. 잠시 후 다시 시도하세요."
    if isinstance(err, anthropic.BadRequestError):
        return f"요청 형식 오류: {err.message}"
    if isinstance(err, anthropic.APIStatusError):
        return f"API 오류 ({err.status_code}): {err.message}"
    if isinstance(err, anthropic.APIConnectionError):
        return "네트워크 연결에 실패했습니다. 인터넷 연결을 확인하세요."
    return f"알 수 없는 오류: {err}"


# ---------------------------------------------------------------------------
# 세션 상태
# ---------------------------------------------------------------------------
def init_state() -> None:
    ss = st.session_state
    ss.setdefault("screen", "주제 입력")
    ss.setdefault("topic", "")
    ss.setdefault("level", "중급 (AI 챗봇을 써 본 수강생)")
    ss.setdefault("duration", 90)
    ss.setdefault("overlaps", [])
    ss.setdefault("current_lesson_id", None)
    ss.setdefault("current_artifact_id", None)
    ss.setdefault("generated_prompt", "")


def go(screen: str) -> None:
    st.session_state["screen"] = screen
    st.rerun()


# ---------------------------------------------------------------------------
# 공유 링크
# ---------------------------------------------------------------------------
def share_url(kind: str, item_id: str) -> str:
    return f"{BASE_URL}/?share={kind}:{item_id}"


def share_message(lesson: dict | None, artifact: dict | None) -> str:
    lines = []
    if lesson:
        lines.append(f"📘 오늘 수업 교안: {lesson['title']}")
        lines.append(share_url("lesson", lesson["id"]))
    if artifact:
        if lines:
            lines.append("")
        lines.append(f"🧰 실습 아티팩트: {artifact['title']}")
        lines.append(share_url("artifact", artifact["id"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 화면 1. 강의 주제 입력
# ---------------------------------------------------------------------------
def screen_topic() -> None:
    st.title("📘 교안 자동 생성기")
    st.caption("강의 주제를 넣으면 수업을 그대로 진행할 수 있는 상세 교안과 실습용 아티팩트를 만듭니다.")

    with st.form("topic_form"):
        topic = st.text_input(
            "강의 주제",
            value=st.session_state["topic"],
            placeholder="예: ChatGPT로 여행 일정 짜기, Canva로 모임 포스터 만들기",
        )
        submitted = st.form_submit_button("만들기", type="primary")
        col1, col2 = st.columns(2)
        with col1:
            level = st.selectbox(
                "수강생 수준",
                ["입문 (AI 챗봇을 처음 써 봄)", "중급 (AI 챗봇을 써 본 수강생)", "심화 (프롬프트를 직접 다듬어 봄)"],
                index=1,
            )
        with col2:
            duration = st.select_slider("수업 시간(분)", options=[60, 90, 120, 150, 180], value=st.session_state["duration"])

    if submitted:
        if not topic.strip():
            st.error("강의 주제를 입력하세요.")
            return
        st.session_state.update(topic=topic.strip(), level=level, duration=duration)
        st.session_state["overlaps"] = scan_overlap(topic.strip())
        go("기존 자료 확인")

    saved = mine(load_store()["lessons"])
    if saved:
        st.divider()
        if st.button(f"저장된 목록 보기 ({len(saved)}개)"):
            go("저장된 목록")


# ---------------------------------------------------------------------------
# 화면 2. 기존 자료 확인
# ---------------------------------------------------------------------------
def screen_overlap() -> None:
    topic = st.session_state["topic"]
    st.title("기존 자료 확인")
    st.markdown(f"**입력한 주제:** {topic}")

    overlaps = st.session_state["overlaps"]
    if overlaps:
        st.warning(f"기존 교안·강의 기록과 겹치는 자료가 {len(overlaps)}개 있습니다.")
        for hit in overlaps:
            rec, lesson = hit["record"], hit["lesson"]
            with st.container(border=True):
                st.markdown(f"**{rec.get('title') or rec['topic']}**")
                st.markdown(
                    f"<span class='small-muted'>주제: {rec['topic']} · 수준: {rec.get('level','-')} · "
                    f"만든 날: {rec['created_at'][:10]} · 유사도 {hit['score']:.0%}</span>",
                    unsafe_allow_html=True,
                )
                if lesson and st.button("이 교안 열기", key=f"open_{rec['id']}"):
                    st.session_state["current_lesson_id"] = lesson["id"]
                    st.session_state["current_artifact_id"] = lesson.get("artifact_id")
                    go("교안 및 아티팩트")
    else:
        st.success("겹치는 기존 자료가 없습니다.")

    st.subheader("자료를 생성하시겠습니까?")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("생성하기", type="primary"):
            run_generation()
    with col2:
        if st.button("처음 화면으로 돌아가기"):
            go("주제 입력")


def run_generation() -> None:
    topic = st.session_state["topic"]
    level = st.session_state["level"]
    duration = st.session_state["duration"]
    today = dt.date.today().isoformat()

    user_msg = (
        f"강의 주제: {topic}\n"
        f"수강생 수준: {level}\n"
        f"총 수업 시간: {duration}분\n"
        f"수업 날짜: {today}\n\n"
        "위 조건으로 교안을 작성하세요."
    )

    st.subheader("교안 생성 중…")
    try:
        with st.container(border=True):
            lesson_md = st.write_stream(stream_text(LESSON_SYSTEM, user_msg, effort="high", max_tokens=32000))
        save_log(user_msg, lesson_md)
        with st.spinner("실습용 아티팩트(프롬프트 생성기) 설계 중…"):
            spec = generate_artifact_spec(topic, lesson_md)
    except Exception as err:  # noqa: BLE001 - 사용자에게 원인을 보여주고 멈춘다
        st.error(describe_api_error(err))
        return

    store = load_store()
    lesson_id, artifact_id, record_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    title = _extract_title(lesson_md) or topic

    store["lessons"].append(
        {
            "id": lesson_id,
            "owner": OWNER,
            "title": title,
            "topic": topic,
            "level": level,
            "duration": duration,
            "content_md": lesson_md,
            "artifact_id": artifact_id,
            "record_id": record_id,
            "created_at": now_iso(),
        }
    )
    store["artifacts"].append(
        {
            "id": artifact_id,
            "owner": OWNER,
            "lesson_id": lesson_id,
            "title": spec["title"],
            "kind": "prompt_generator",
            "spec": spec,
            "locked": False,  # 저장된 목록의 잠그기 버튼으로 바꾼다 (tasks.md 참고)
            "created_at": now_iso(),
        }
    )
    store["records"].append(
        {
            "id": record_id,
            "owner": OWNER,
            "lesson_id": lesson_id,
            "topic": topic,
            "title": title,
            "level": level,
            "date": today,
            "duplicate_of": [h["record"]["id"] for h in st.session_state["overlaps"]],
            "created_at": now_iso(),
        }
    )
    save_store(store)

    st.session_state["current_lesson_id"] = lesson_id
    st.session_state["current_artifact_id"] = artifact_id
    st.session_state["generated_prompt"] = ""
    go("교안 및 아티팩트")


def _extract_title(md: str) -> str | None:
    for line in md.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return None


# ---------------------------------------------------------------------------
# 화면 3. 교안 및 아티팩트
# ---------------------------------------------------------------------------
def render_artifact_card(artifact: dict) -> None:
    spec = artifact["spec"]
    st.markdown(f"### 🧰 {spec['title']}")
    st.markdown(spec["purpose"])
    with st.expander("수강생 안내문", expanded=False):
        st.markdown(spec["student_guide"])
    st.markdown("**입력 칸**")
    for f in spec["fields"]:
        st.markdown(f"- **{f['label']}** — {f['placeholder']} (예: {f['example']})")
    with st.expander("프롬프트 틀 보기"):
        st.code(spec["prompt_template"], language="text")
    with st.expander("예시 결과 프롬프트"):
        st.code(spec["example_output"], language="text")


def screen_result() -> None:
    lesson = find_item("lessons", st.session_state.get("current_lesson_id") or "")
    if not lesson:
        st.info("표시할 교안이 없습니다. 주제를 입력해 새로 만드세요.")
        if st.button("처음 화면으로 돌아가기"):
            go("주제 입력")
        return
    artifact = find_item("artifacts", lesson.get("artifact_id") or "")

    st.title("교안 및 아티팩트")
    st.markdown(
        f"<span class='small-muted'>주제: {lesson['topic']} · {lesson['level']} · {lesson['duration']}분 · "
        f"만든 날: {lesson['created_at'][:10]}</span>",
        unsafe_allow_html=True,
    )

    tab_lesson, tab_artifact = st.tabs(["📘 교안", "🧰 아티팩트"])
    with tab_lesson:
        st.markdown(lesson["content_md"])
        st.download_button(
            "교안 Markdown 내려받기",
            data=lesson["content_md"].encode("utf-8"),
            file_name=f"{lesson['title']}.md",
            mime="text/markdown",
        )
    with tab_artifact:
        if artifact:
            render_artifact_card(artifact)
            st.markdown(
                f"<span class='small-muted'>{'🔒 잠김' if artifact.get('locked') else '🔓 열림'}</span>",
                unsafe_allow_html=True,
            )
            if artifact.get("locked"):
                if st.button("🔓 풀기", key=f"result_unlock_{artifact['id']}"):
                    set_locked(artifact["id"], False)
                    st.rerun()
            elif st.button("🔒 잠그기", key=f"result_lock_{artifact['id']}"):
                set_locked(artifact["id"], True)
                st.rerun()
        else:
            st.info("이 교안에 연결된 아티팩트가 없습니다.")

    st.divider()
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("프롬프트 생성기 열기", type="primary", disabled=artifact is None):
            go("프롬프트 생성기")
    with col2:
        if st.button("저장된 목록 보기"):
            go("저장된 목록")
    with col3:
        if st.button("처음 화면으로 돌아가기"):
            st.session_state["topic"] = ""
            go("주제 입력")


# ---------------------------------------------------------------------------
# 화면 4. 프롬프트 생성기
# ---------------------------------------------------------------------------
def prompt_generator_form(artifact: dict, key_prefix: str, allow_generate: bool) -> None:
    spec = artifact["spec"]
    st.markdown(spec["student_guide"])

    with st.form(f"{key_prefix}_form"):
        values: dict[str, str] = {}
        for f in spec["fields"]:
            values[f["key"]] = st.text_input(f["label"], placeholder=f"{f['placeholder']} (예: {f['example']})")
        extra = st.text_area("추가 조건 (선택)", placeholder="예: 결과를 표로 보여줘, 300자 이내로")
        submitted = st.form_submit_button("프롬프트 만들기", type="primary", disabled=not allow_generate)

    if submitted:
        filled = "\n".join(f"- {f['label']} ({f['key']}): {values[f['key']] or '(비움)'}" for f in spec["fields"])
        user_msg = (
            f"<아티팩트 틀>\n{spec['prompt_template']}\n</아티팩트 틀>\n\n"
            f"<수강생 입력>\n{filled}\n- 추가 조건: {extra or '(없음)'}\n</수강생 입력>"
        )
        try:
            with st.container(border=True):
                result = st.write_stream(stream_text(PROMPT_SYSTEM, user_msg, effort="low", max_tokens=4000))
            st.session_state["generated_prompt"] = result
        except Exception as err:  # noqa: BLE001
            st.error(describe_api_error(err))
            return
        save_log(user_msg, result)  # 공유 링크로 수강생이 쓴 것도 남는다

    if st.session_state.get("generated_prompt"):
        st.markdown("**완성 프롬프트** (아래 상자 오른쪽 위 복사 버튼을 누르세요)")
        st.code(st.session_state["generated_prompt"], language="text")


def screen_prompt() -> None:
    artifact = find_item("artifacts", st.session_state.get("current_artifact_id") or "")
    if not artifact:
        st.info("열 수 있는 아티팩트가 없습니다.")
        if st.button("결과 화면으로 돌아가기"):
            go("교안 및 아티팩트")
        return

    st.title("프롬프트 생성기")
    st.markdown(f"### 🧰 {artifact['title']}")
    prompt_generator_form(artifact, key_prefix="instructor", allow_generate=True)

    st.divider()
    if st.button("결과 화면으로 돌아가기"):
        go("교안 및 아티팩트")


# ---------------------------------------------------------------------------
# 화면 5. 저장된 목록 + 오픈채팅방 공유
# ---------------------------------------------------------------------------
def screen_list() -> None:
    store = load_store()
    lessons = sorted(mine(store["lessons"]), key=lambda l: l["created_at"], reverse=True)
    artifacts = sorted(mine(store["artifacts"]), key=lambda a: a["created_at"], reverse=True)
    artifact_by_id = {a["id"]: a for a in artifacts}

    st.title("저장된 목록")
    st.caption(f"강사: {OWNER} · 교안 {len(lessons)}개 · 아티팩트 {len(artifacts)}개")

    if not lessons and not artifacts:
        st.info("아직 저장된 자료가 없습니다.")
    else:
        tab_lessons, tab_artifacts = st.tabs([f"📘 교안 ({len(lessons)})", f"🧰 아티팩트 ({len(artifacts)})"])

        with tab_lessons:
            for lesson in lessons:
                with st.container(border=True):
                    st.markdown(f"**{lesson['title']}**")
                    st.markdown(
                        f"<span class='small-muted'>{lesson['topic']} · {lesson['level']} · {lesson['duration']}분 · "
                        f"{lesson['created_at'][:10]}</span>",
                        unsafe_allow_html=True,
                    )
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("열기", key=f"lesson_open_{lesson['id']}"):
                            st.session_state["current_lesson_id"] = lesson["id"]
                            st.session_state["current_artifact_id"] = lesson.get("artifact_id")
                            go("교안 및 아티팩트")
                    with c2:
                        if st.button("오픈채팅방 공유", key=f"lesson_share_{lesson['id']}"):
                            st.session_state["share_target"] = ("lesson", lesson["id"])

        with tab_artifacts:
            for artifact in artifacts:
                with st.container(border=True):
                    st.markdown(f"**{artifact['title']}**")
                    lesson = next((l for l in lessons if l["id"] == artifact.get("lesson_id")), None)
                    st.markdown(
                        f"<span class='small-muted'>연결 교안: {lesson['title'] if lesson else '-'} · "
                        f"{artifact['created_at'][:10]} · {'🔒 잠김' if artifact.get('locked') else '🔓 열림'}</span>",
                        unsafe_allow_html=True,
                    )
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        if st.button("열기", key=f"artifact_open_{artifact['id']}"):
                            st.session_state["current_artifact_id"] = artifact["id"]
                            st.session_state["current_lesson_id"] = artifact.get("lesson_id")
                            go("프롬프트 생성기")
                    with c2:
                        if st.button("오픈채팅방 공유", key=f"artifact_share_{artifact['id']}"):
                            st.session_state["share_target"] = ("artifact", artifact["id"])
                    with c3:
                        if artifact.get("locked"):
                            if st.button("🔓 풀기", key=f"artifact_unlock_{artifact['id']}"):
                                set_locked(artifact["id"], False)
                                st.rerun()
                        elif st.button("🔒 잠그기", key=f"artifact_lock_{artifact['id']}"):
                            set_locked(artifact["id"], True)
                            st.rerun()

    target = st.session_state.get("share_target")
    if target:
        kind, item_id = target
        if kind == "lesson":
            lesson = next((l for l in lessons if l["id"] == item_id), None)
            artifact = artifact_by_id.get(lesson.get("artifact_id")) if lesson else None
        else:
            artifact = artifact_by_id.get(item_id)
            lesson = None
        st.divider()
        st.subheader("오픈채팅방에 붙여 넣을 내용")
        st.caption("상자 오른쪽 위 복사 버튼을 누른 뒤 카카오톡 오픈채팅방에 붙여 넣으세요.")
        st.code(share_message(lesson, artifact), language="text")
        st.markdown(
            "<span class='small-muted'>링크는 APP_BASE_URL 환경 변수의 주소를 기준으로 만들어집니다. "
            "수강생이 열려면 이 앱이 외부에서 접속 가능한 주소로 실행 중이어야 합니다.</span>",
            unsafe_allow_html=True,
        )

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("결과 화면으로 돌아가기", disabled=st.session_state.get("current_lesson_id") is None):
            go("교안 및 아티팩트")
    with col2:
        if st.button("처음 화면으로 돌아가기"):
            go("주제 입력")


# ---------------------------------------------------------------------------
# 공유 링크로 열었을 때 (수강생용 읽기 전용 화면)
# ---------------------------------------------------------------------------
def screen_shared(share: str) -> None:
    kind, _, item_id = share.partition(":")
    if kind == "lesson":
        lesson = find_item("lessons", item_id, any_owner=True)
        if not lesson:
            st.error("교안을 찾을 수 없습니다.")
            return
        st.title(lesson["title"])
        st.markdown(lesson["content_md"])
        return

    if kind == "artifact":
        artifact = find_item("artifacts", item_id, any_owner=True)
        if not artifact:
            st.error("아티팩트를 찾을 수 없습니다.")
            return
        st.title(f"🧰 {artifact['title']}")
        if artifact.get("locked"):
            st.warning("이 아티팩트는 강사가 잠가 두었습니다. 수업 시간에 강사가 열면 사용할 수 있습니다.")
        prompt_generator_form(artifact, key_prefix="student", allow_generate=not artifact.get("locked"))
        return

    st.error("올바르지 않은 공유 링크입니다.")


# ---------------------------------------------------------------------------
# 부가 화면. 한 줄 방명록 (guestbook.py 를 그대로 사용)
# ---------------------------------------------------------------------------
def screen_guestbook() -> None:
    if st.button("← 교안 자동 생성기로 돌아가기"):
        go("주제 입력")
    render_guestbook()


# ---------------------------------------------------------------------------
# 부가 화면. AI 기록 (ai_log.py 사용, Supabase chat_log 표)
# ---------------------------------------------------------------------------
def screen_ai_logs() -> None:
    if st.button("← 교안 자동 생성기로 돌아가기"):
        go("주제 입력")
    render_ai_logs()


# ---------------------------------------------------------------------------
# 미니 상담 챗봇 (오른쪽 아래 고양이 버튼). 문의 글을 넣으면 Gemini 가 답변 초안을 쓴다
# ---------------------------------------------------------------------------
# 3D 고양이 아이콘: Microsoft Fluent Emoji (MIT 라이선스, https://github.com/microsoft/fluentui-emoji)
CHAT_ICON_URL = "https://cdn.jsdelivr.net/gh/microsoft/fluentui-emoji@main/assets/Cat%20face/3D/cat_face_3d.png"

# 상담 챗봇의 고정 지시문. 글은 chat_system.md 에 있다
CHAT_SYSTEM = (APP_DIR / "chat_system.md").read_text(encoding="utf-8").rstrip("\n")

# 채팅창의 말투 칸. 고른 말투의 설명이 CHAT_SYSTEM 끝에 [말투] 로 붙는다
CHAT_TONES = {
    "정중하게": "격식 있는 정중한 존댓말. 군더더기 없이 예의 바르게.",
    "따뜻하게": "다정하고 친근한 존댓말. 문의해 준 것에 고마움을 짧게 표현한다.",
    "짧게": "세 문장을 각각 짧게. 꾸밈말 없이 핵심만.",
    "공지처럼": "공지문처럼 또박또박. 날짜·시간·준비물 같은 항목을 분명하게 밝힌다.",
}

# 고양이 버튼과 채팅창을 화면 오른쪽 아래에 띄운다 (st.container(key=...) 가 붙이는 st-key-* 클래스 사용)
# 고양이는 늘 원을 가득 채우고, 창이 열려 있을 때(chat_fab_cat_open)만 오른쪽 위에 작은 ✕ 표시를 붙인다
CHAT_CSS = """
<style>
  [class*="st-key-chat_fab"] { position: fixed; right: 1.25rem; bottom: 1.25rem; z-index: 1000; width: auto !important; }
  [class*="st-key-chat_fab"] button {
    width: 4rem !important; min-height: 4rem !important; border-radius: 50% !important;
    font-size: 1.8rem !important; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
  }
  [class*="st-key-chat_fab_cat"] button {
    background: #ffe3b3 url("__ICON__") center / 118% no-repeat !important;
    border: none !important; color: transparent !important; overflow: visible;
  }
  [class*="st-key-chat_fab_cat"] button:hover { transform: scale(1.06); }
  .st-key-chat_fab_cat_open button::after {
    content: "✕"; position: absolute; top: -0.2rem; right: -0.2rem;
    width: 1.4rem; height: 1.4rem; line-height: 1.4rem; border-radius: 50%;
    background: #444; color: #fff; font-size: 0.8rem; text-align: center;
  }
  .st-key-chat_panel {
    position: fixed; right: 1.25rem; bottom: 6.25rem; z-index: 1000;
    width: min(23rem, calc(100vw - 2rem)); max-height: calc(100vh - 8rem); overflow-y: auto;
    background: __BG__; border-radius: 0.75rem; padding: 0.75rem;
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.22);
  }
</style>
"""


CHAT_MAX_CHARS = 300  # 답이 이 글자 수를 넘으면 점검에서 떨어진다
CHAT_CHECK_PASS = "강사님께 확인이 필요한 내용이에요"  # 이 말로 시작하는 답은 점검 없이 통과


def _chat_answer_ok(answer: str) -> bool:
    """답이 정확히 세 줄(빈 줄 없이)이고 CHAT_MAX_CHARS 자 이하인지 본다."""
    answer = answer.strip()
    if answer.startswith(CHAT_CHECK_PASS):
        return True
    lines = answer.split("\n")
    return len(lines) == 3 and all(line.strip() for line in lines) and len(answer) <= CHAT_MAX_CHARS


def _ask_gemini(api_key: str, text: str, tone: str) -> None:
    """chat_log 에 AI 답 또는 안내를 붙인다. 이어서 묻기는 previous_interaction_id 로 잇는다.
    점검(_chat_answer_ok)에서 떨어지면 한 번 더 묻고, 두 번 다 떨어지면 답 대신 다시 시도 안내를 띄운다."""
    ss = st.session_state
    system = (f"{CHAT_SYSTEM}\n\n[말투] {tone}: {CHAT_TONES[tone]}\n"
              "말투는 문장 모양만 바꾼다. 짧게 쓰더라도 모르는 사실은 지어내지 말고 [확인 필요: 무엇] 으로 남긴다.")
    try:
        client = genai.Client(api_key=api_key)
        kwargs = {"model": CHAT_MODEL, "input": text, "system_instruction": system, "timeout": CHAT_TIMEOUT_SECONDS}
        if ss.chat_last_id:
            kwargs["previous_interaction_id"] = ss.chat_last_id
        # 다시 물을 때도 같은 앞 대화에 잇는다. 떨어진 답은 대화에 이어 붙이지 않는다
        for _ in range(2):
            interaction = client.interactions.create(**kwargs)
            answer = interaction.output_text or ""
            if _chat_answer_ok(answer):
                ss.chat_last_id = interaction.id
                ss.chat_log.append({"role": "ai", "text": answer})
                save_log(f"[말투: {tone}]\n{text}", answer)
                return
        ss.chat_log.append({"role": "경고", "text": "다시 시도해 주세요"})
        save_log(f"[말투: {tone}]\n{text}", f"[점검 두 번 실패, 화면에 안 보임]\n{answer}")
    except Exception as err:  # noqa: BLE001
        if "API_KEY_INVALID" in str(err):
            msg = ("오류", f"키가 올바르지 않습니다. .env 의 {GEMINI_KEY_NAME} 값을 새 키로 바꾼 뒤 화면을 새로 고치세요.")
        elif "Timeout" in type(err).__name__ or "high demand" in str(err):
            msg = ("경고", "지금 Gemini 가 붐벼서 답이 늦습니다. 잠시 뒤 다시 보내 주세요.")
        else:
            msg = ("오류", f"답을 받지 못했습니다. ({type(err).__name__})")
        ss.chat_log.append({"role": msg[0], "text": msg[1]})


def chat_widget() -> None:
    ss = st.session_state
    ss.setdefault("chat_open", False)
    ss.setdefault("chat_busy", False)  # 답을 기다리는 중. 이때는 보내기를 잠가 두 번 보내지 않게 한다
    ss.setdefault("chat_log", [])  # [{"role": "user"/"ai"/"경고"/"오류", "text": ...}]
    ss.setdefault("chat_last_id", None)  # 이어서 묻기용 마지막 Gemini interaction id
    ss.setdefault("chat_notice", "")  # 빈칸으로 보냈을 때 보여 줄 안내 한 줄

    bg = "#0e1117" if st.context.theme.type == "dark" else "#ffffff"
    st.markdown(CHAT_CSS.replace("__BG__", bg).replace("__ICON__", CHAT_ICON_URL), unsafe_allow_html=True)

    with st.container(key="chat_fab_cat_open" if ss.chat_open else "chat_fab_cat"):
        if st.button("🐱", key="chat_toggle", disabled=ss.chat_busy,
                     help="상담 챗봇 닫기" if ss.chat_open else "상담 챗봇 열기"):
            ss.chat_open = not ss.chat_open
            st.rerun()
    if not ss.chat_open:
        return

    with st.container(key="chat_panel"):
        head, reset = st.columns([3, 1], vertical_alignment="center")
        head.markdown("**상담 챗봇**")
        if reset.button("새 대화", key="chat_reset", disabled=ss.chat_busy):
            ss.update(chat_log=[], chat_last_id=None, chat_notice="")
            st.rerun()

        api_key = os.environ.get(GEMINI_KEY_NAME, "").strip()
        if not api_key:
            st.error(f"키 없음. .env 에 {GEMINI_KEY_NAME}=... 줄이 있는지 확인하세요.")
            return

        log = st.container(height=300)
        with log:
            if not ss.chat_log:
                st.caption("받은 문의 글을 넣으면 답변 초안을 만들어 드립니다. "
                           "예: 다음 주 수업에 노트북을 꼭 가져가야 하나요?")
            for m in ss.chat_log:
                if m["role"] == "user":
                    with st.chat_message("user"):
                        st.markdown(m["text"])
                elif m["role"] == "ai":
                    with st.chat_message("assistant", avatar=CHAT_ICON_URL):
                        st.caption("AI가 쓴 초안입니다. 보내기 전에 꼭 읽고 고쳐 주세요.")
                        st.code(m["text"], language=None, wrap_lines=True)
                elif m["role"] == "경고":
                    st.warning(m["text"])
                else:
                    st.error(m["text"])

        # 말투는 다음 답부터 적용된다. 잠그면 값이 사라질 수 있어 기다리는 중에도 잠그지 않는다
        st.segmented_control("말투", list(CHAT_TONES), default="정중하게", key="chat_tone")
        with st.form("chat_form", clear_on_submit=True, border=False):
            text = st.text_input("문의 글", label_visibility="collapsed", placeholder="문의 글을 넣으세요")
            sent = st.form_submit_button("답을 기다리는 중..." if ss.chat_busy else "보내기",
                                         type="primary", disabled=ss.chat_busy)
        if ss.chat_notice:
            st.warning(ss.chat_notice)

        if sent:
            if not text.strip():
                # 빈칸이면 AI 를 부르지 않고 안내 한 줄만 보여 준다
                ss.chat_notice = "문의 글을 넣은 뒤 보내기를 눌러 주세요."
            else:
                ss.chat_log.append({"role": "user", "text": text.strip()})
                ss.update(chat_busy=True, chat_notice="")
            st.rerun()

        if ss.chat_busy:
            # 방금 넣은 문의가 대화창에 보인 상태에서, 그 아래에 스피너를 돌리며 답을 기다린다
            with log:
                with st.chat_message("assistant", avatar=CHAT_ICON_URL):
                    with st.spinner("답을 기다리는 중입니다"):
                        # 말투 버튼을 다시 눌러 선택이 풀리면 기본값으로
                        _ask_gemini(api_key, ss.chat_log[-1]["text"], ss.get("chat_tone") or "정중하게")
            ss.chat_busy = False
            st.rerun()


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------
def main() -> None:
    init_state()

    share = st.query_params.get("share")
    if share:
        screen_shared(share)
        return

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        st.warning("ANTHROPIC_API_KEY 환경 변수가 없습니다. 교안·프롬프트 생성은 실패합니다.")

    with st.sidebar:
        st.markdown(f"**강사:** {OWNER}")
        st.markdown(f"**모델:** {MODEL}")
        st.markdown("---")
        current = st.session_state["screen"]
        # 갈 수 있는 화면만 누를 수 있다: 주제가 있어야 기존 자료 확인, 교안·아티팩트가 있어야 그 화면이 열린다
        reachable = {
            "주제 입력": True,
            "기존 자료 확인": bool(st.session_state["topic"]),
            "교안 및 아티팩트": find_item("lessons", st.session_state.get("current_lesson_id") or "") is not None,
            "프롬프트 생성기": find_item("artifacts", st.session_state.get("current_artifact_id") or "") is not None,
            "저장된 목록": True,
        }
        for name in SCREENS:
            if name == current:
                st.markdown(f"➡️ {name}")
            elif st.button(name, key=f"nav_{name}", use_container_width=True, disabled=not reachable[name]):
                go(name)
        st.markdown("---")
        if st.button(f"📝 {GUESTBOOK_SCREEN}", use_container_width=True,
                     disabled=current == GUESTBOOK_SCREEN):
            go(GUESTBOOK_SCREEN)
        if st.button(f"🗂 {AI_LOG_SCREEN}", use_container_width=True,
                     disabled=current == AI_LOG_SCREEN):
            go(AI_LOG_SCREEN)

    screen = st.session_state["screen"]
    if screen == "주제 입력":
        screen_topic()
    elif screen == "기존 자료 확인":
        screen_overlap()
    elif screen == "교안 및 아티팩트":
        screen_result()
    elif screen == "프롬프트 생성기":
        screen_prompt()
    elif screen == "저장된 목록":
        screen_list()
    elif screen == GUESTBOOK_SCREEN:
        screen_guestbook()
    elif screen == AI_LOG_SCREEN:
        screen_ai_logs()

    chat_widget()


main()
