"""크롬 자동 번역 막기 — Streamlit 은 페이지를 <html lang="en"> 으로 내보내서, 크롬이 한국어 화면을 영어로 알고 다시 번역한다 (잠그기 → 운동하기).

set_page_config() 바로 다음에 korean_page() 를 부르면 페이지를 한국어(lang="ko")로 바꾸고 번역하지 말라는 표시(translate="no", notranslate)를 붙인다.
"""

import streamlit as st

_SCRIPT = """
<script>
  document.documentElement.lang = "ko";
  document.documentElement.setAttribute("translate", "no");
  document.body.classList.add("notranslate");
  if (!document.querySelector('meta[name="google"]')) {
    const meta = document.createElement("meta");
    meta.name = "google";
    meta.content = "notranslate";
    document.head.appendChild(meta);
  }
</script>
"""


def korean_page() -> None:
    st.html(_SCRIPT, unsafe_allow_javascript=True)
