"""키 읽기 — 내 컴퓨터에서는 .env, Streamlit Community Cloud 에서는 배포 설정의 Secrets 에서 같은 이름으로 읽는다.

.env 도 Secrets 도 없으면 빈 값("")으로 볼 뿐 오류를 내지 않는다. 키가 없을 때의 안내는 각 화면이 띄운다.
"""

import os
import pathlib

import streamlit as st
from dotenv import dotenv_values, load_dotenv

ENV_PATH = pathlib.Path(__file__).with_name(".env")
KEY_NAMES = (
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "KAKAO_REST_API_KEY",
    "INSTRUCTOR_ID",
    "APP_BASE_URL",
)


def _from_secrets(name: str) -> str:
    try:
        value = st.secrets.get(name)
    except Exception:  # noqa: BLE001 - secrets.toml 이 없는 내 컴퓨터에서는 오류가 나므로 없음으로 본다
        return ""
    return "" if value is None else str(value).strip()


def get_key(name: str) -> str:
    """.env 의 값을 먼저 보고, 비어 있으면 Secrets 를 본다. 시스템 환경 변수(os.environ)는 보지 않는다."""
    return (dotenv_values(ENV_PATH).get(name) or "").strip() or _from_secrets(name)


def load_keys() -> None:
    """KEY_NAMES 를 os.environ 에 넣는다. anthropic SDK 처럼 os.environ 에서 직접 키를 읽는 곳을 위해서다."""
    for name in KEY_NAMES:
        if not os.environ.get(name, "").strip():
            value = _from_secrets(name)
            if value:
                os.environ[name] = value
    # .env 는 마지막에 읽는다: Streamlit 이 Secrets 를 처음 읽을 때 그 값들을 os.environ 에 덮어쓰기 때문이다
    # override=True: .env 를 고친 뒤 화면만 새로 고쳐도 새 값을 읽는다
    load_dotenv(ENV_PATH, override=True)
