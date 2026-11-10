"""챗봇 (미니 앱)

빈칸에 넣은 말을 Gemini 에 보내고 받은 답을 보여 준다.
.env 의 키는 「있음 / 없음」으로만 보여 주고, 값은 화면에 내보내지 않는다.

실행:
  streamlit run helper.py
"""

import os
import pathlib

import streamlit as st
from google import genai

from app_keys import load_keys

# 확인할 키 이름. .env 에 들어 있는 이름과 같아야 한다.
KEY_NAME = "GEMINI_API_KEY"
# 모델 이름 (https://ai.google.dev/gemini-api/docs/models)
MODEL = "gemini-3.5-flash"
# 이 시간(초) 안에 답이 없으면 기다리지 않고 안내를 띄운다
TIMEOUT_SECONDS = 30

# 내 컴퓨터에서는 .env, 올린 곳에서는 Secrets 의 키를 os.environ 에 넣는다
load_keys()
api_key = os.environ.get(KEY_NAME, "").strip()

st.set_page_config(page_title="챗봇", page_icon="💬")
st.title("💬 챗봇")

if api_key:
    st.success("키 있음")
else:
    st.error(f"키 없음. .env (올린 곳에서는 Secrets) 에 {KEY_NAME} 가 있는지 확인하세요.")
    st.stop()

# busy: 답을 기다리는 중인지. 기다리는 동안은 버튼을 잠가 두 번 보내지 않게 한다.
# result: 화면을 다시 그려도 남아 있어야 하는 마지막 답 또는 안내 ("답"/"경고"/"오류", 글)
st.session_state.setdefault("busy", False)
st.session_state.setdefault("result", None)


def start_sending():
    st.session_state.busy = True


question = st.text_area(
    "물어볼 말",
    placeholder="예: 오늘 저녁 메뉴를 세 가지 추천해 줘",
)
st.button(
    "보내는 중..." if st.session_state.busy else "보내기",
    type="primary",
    disabled=st.session_state.busy,
    on_click=start_sending,
    key="send",
)

if st.session_state.busy:
    if not question.strip():
        st.session_state.result = ("경고", "빈칸에 물어볼 말을 넣어 주세요.")
    else:
        try:
            with st.spinner("답을 기다리는 중... 붐비면 1분 가까이 걸릴 수 있습니다."):
                client = genai.Client(api_key=api_key)
                interaction = client.interactions.create(
                    model=MODEL, input=question, timeout=TIMEOUT_SECONDS
                )
            st.session_state.result = ("답", interaction.output_text)
        except Exception as err:
            if "API_KEY_INVALID" in str(err):
                st.session_state.result = ("오류", f"키가 올바르지 않습니다. .env 의 {KEY_NAME} 값을 새 키로 바꾼 뒤 화면을 새로 고치세요.")
            elif "Timeout" in type(err).__name__ or "high demand" in str(err):
                st.session_state.result = ("경고", "지금 Gemini 가 붐벼서 답이 늦습니다. 잠시 뒤 다시 보내 주세요.")
            else:
                st.session_state.result = ("오류", f"답을 받지 못했습니다. ({type(err).__name__})")
    # 다 끝났으니 버튼을 다시 풀고 화면을 새로 그린다
    st.session_state.busy = False
    st.rerun()

if st.session_state.result:
    kind, text = st.session_state.result
    if kind == "답":
        st.markdown("**답**")
        st.write(text)
    elif kind == "경고":
        st.warning(text)
    else:
        st.error(text)
