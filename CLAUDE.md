# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this workspace is

This is primarily a requirements/planning workspace with a single-file Streamlit MVP ([app.py](app.py)). Run it with `pip install -r requirements.txt` then `streamlit run app.py`; it needs `ANTHROPIC_API_KEY`. There is no build system, linter, or test suite — do not invent one. It is a git repository: work is committed on `main` and pushed to GitHub (`origin`), and the app is deployed on Streamlit Community Cloud. `.env` is git-ignored and never committed. The workspace defines the MVP for a lesson-plan (교안) and artifact auto-generator used by a solo offline AI instructor who teaches senior learners 5 days/week and needs a new lesson topic prepared each time.

Core flow: 강의 주제 입력 (enter lecture topic) → 상세 교안·아티팩트 생성 (generate detailed lesson plan + artifact) → 저장된 목록 관리 (manage saved list) → 오픈채팅방 공유 (share via KakaoTalk open chat). A generated lesson plan must be detailed enough to teach directly from — not a one-page summary.

## Start here

Read **[AGENTS.md](AGENTS.md)** first — it is the authoritative instruction set for this repo (project purpose, working principles, Notion integration guidance, and verification steps) and is kept in sync with the docs below. Don't duplicate its content into new instructions; update it in place when requirements or flows change.

Key docs it points to:
- [PRD.md](PRD.md) — product requirements (problem, personas, user stories, scope, screen flow, acceptance criteria)
- [tasks.md](tasks.md) — screen-by-screen task checklist, generated from the PRD's acceptance criteria
- [idea/topic.md](idea/topic.md) — confirmed MVP topic/one-liner
- [idea/scope.md](idea/scope.md) — in-scope vs. out-of-scope features
- [idea/flow.md](idea/flow.md) — user flow as a Mermaid diagram (also sketched in [idea/flow.excalidraw](idea/flow.excalidraw))
- [idea/problems.md](idea/problems.md) — pain points motivating the product
- [idea/ipo.md](idea/ipo.md) — exploration of output/artifact shapes

## Working principles

- The only application code is [app.py](app.py) (Streamlit + Anthropic Python SDK, data in `data/store.json` scoped by `INSTRUCTOR_ID`). The exception is the floating bottom-right `상담 챗봇` widget (inquiry → reply draft), which calls Gemini via google-genai using `GEMINI_API_KEY`. Keys (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `KAKAO_REST_API_KEY`, `INSTRUCTOR_ID`, `APP_BASE_URL`) are read by [app_keys.py](app_keys.py) under the same names from `.env` locally and from the deployment's Secrets on Streamlit Community Cloud (`.env` wins if both exist; neither existing must not crash the screen). Screen files should get keys through it rather than reading `.env` directly. Don't assume a Notion SDK without evidence in these docs.
- Before implementing anything, check the relevant requirement doc for scope and non-goals first.
- Design must work on both PC and mobile.
- Lesson plans need concrete click-by-click steps and individual practice steps, not abstract descriptions.
- Don't frame learners around family roles or default to repeatedly calling them "어르신" — learners are senior but AI-literate, working individually rather than in pairs/groups.
- If a real app screen or screenshot can't be fetched due to network limits, say so explicitly and name the substitute used.
- Keep generated 교안 (lesson plans) and 아티팩트 (artifacts) as separate entities, and keep each instructor's data scoped to that instructor (no cross-instructor bleed).
- Artifact locking is placed on the 저장된 목록 screen: each artifact card has a 잠그기/풀기 toggle that sets `locked`, and a locked artifact's student share screen blocks 프롬프트 만들기 (see [tasks.md](tasks.md)).
- Duplicate-lecture detection and login are named in the PRD but not yet placed in the screen flow ([idea/flow.md](idea/flow.md)) or [tasks.md](tasks.md). Don't invent where they go — extend the requirement docs first (see [tasks.md](tasks.md)'s "화면이 정해지지 않은 기능" section).

## Working with Notion

Notion is not currently integrated into this workspace. If asked to do Notion-related work, first confirm which of these is the actual goal: document structure design, a manual-import format, live Notion API integration, or a share-link flow. Don't implement unconfirmed Notion API behavior as if it were verified.

When designing a Notion database or import format, keep these four concepts distinct: 교안 (lesson plan: flow, explanations, individual practice steps, materials, anticipated sticking points), 아티팩트 (artifact: student-facing output or prompt generator, share link, lock state), 강의 기록 (lecture record: topic, level, date, duplicate status vs. existing topics), and 소유권 (ownership: instructor identity and their own lesson/artifact lists). Keep `잠금` (lock), `공유 링크` (share link), `강사 소유자` (instructor owner), and `중복 판정` (duplicate flag) as filterable/searchable fields, not buried in body text — and never split 교안 and 아티팩트 into a single undifferentiated bucket. Never write tokens or database IDs into docs/source/output files; use environment variables or a secret store instead, and verify share-link scope and lock behavior before handing out a link.

## Verification

"Verification" means: cross-document links resolve, the PRD/tasks/idea docs agree with each other, any new structure is usable on mobile, and after an app change `python -m py_compile app.py` passes and `streamlit run app.py` walks all five screens without breaking. Once Notion integration exists, at minimum test auth failure, per-instructor data isolation, duplicate-topic detection, blocked generation on a locked artifact, and share-link permissions. When a change affects requirements, update only the specific files it touches among `PRD.md`, the relevant `idea/*.md`, and `tasks.md`.

## Unrelated legacy content

[01_docs/](01_docs/), [02_output/](02_output/), and [99_backup/](99_backup/) contain CSV/XLSX sales-data files from an earlier, unrelated exercise (data cleanup/reporting) — they are not part of the lesson-plan generator MVP described above.
