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


def secrets_problem(name: str) -> str:
    """Secrets 에서 name 을 못 찾은 까닭을 키 값 없이 한 줄로 알려 준다. 이름은 보여 주되 값은 보여 주지 않는다."""
    try:
        secrets = st.secrets.to_dict()
    except Exception as ex:  # noqa: BLE001 - 파일이 없을 때와 형식이 틀렸을 때를 메시지로 가른다
        if "pars" in str(ex).lower():
            return 'Secrets 글이 TOML 형식이 아니라 읽지 못했습니다. 각 줄을 이름 = "값" 처럼 값에 큰따옴표를 붙여 적어 주세요.'
        return "올린 곳이라면 이 앱의 Secrets 가 비어 있습니다. Save 를 눌렀는지, 다른 앱에 넣지 않았는지 확인하세요."
    if name in secrets:
        return f"Secrets 에 {name} 는 있지만 값이 비어 있습니다."
    for section, values in secrets.items():
        if isinstance(values, dict) and name in values:
            return f"{name} 가 [{section}] 아래에 있습니다. [{section}] 줄을 지워 키를 맨 위에 두세요."
    names = ", ".join(secrets) or "(없음)"
    return f"Secrets 에 있는 이름: {names}. 이 중에 {name} 가 없으니 이름 철자를 확인하세요."


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
