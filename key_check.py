"""Claude 키 확인 (미니 앱)

.env 의 ANTHROPIC_API_KEY 가 채워져 있는지만 보여 주고, 값은 화면에 내보내지 않는다.

실행:
  streamlit run key_check.py
"""

import pathlib

import streamlit as st
from dotenv import dotenv_values

# 확인할 키 이름. .env 에 들어 있는 이름과 같아야 한다.
KEY_NAME = "ANTHROPIC_API_KEY"

# os.environ 은 보지 않는다: 시스템 환경 변수에 같은 키가 있어도 .env 가 비어 있으면 비었다고 알려 주기 위해서다
api_key = (dotenv_values(pathlib.Path(__file__).with_name(".env")).get(KEY_NAME) or "").strip()

st.set_page_config(page_title="Claude 키 확인", page_icon="🔑")
st.title("🔑 Claude 키 확인")

if api_key:
    st.success(f".env 의 {KEY_NAME} 가 채워져 있습니다.")
else:
    st.error(f".env 의 {KEY_NAME} 가 비어 있습니다.")
