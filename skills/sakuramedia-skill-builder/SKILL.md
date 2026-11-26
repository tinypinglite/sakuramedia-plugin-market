---
name: sakuramedia-skill-builder
description: Plan and scaffold new Sakuramedia agent skills from the backend's real endpoints. Use when the user wants a new skill for their SakuraMedia server ("make a skill that", "add a skill for", "teach my agent to") or wants to extend an existing skill's endpoint coverage.
---

# Sakuramedia Skill Builder

Turn a capability request into a skill package that talks to the user's own backend: list the real endpoints, scaffold the files, keep every state change behind confirmation. Reply in the user's language.

## Connection

Two environment variables, shared by every Sakuramedia skill:

- `SAKURAMEDIA_BASE_URL`
- `SAKURAMEDIA_API_KEY`

Never print the API key.

## Workflow

`python3 scripts/skill_builder.py <command>`

1. **Clarify the capability.** What should the agent do end to end, and which of those steps change server state?
2. **List endpoints** with `describe` (`--filter`, `--method`, `--json` to narrow). Every endpoint is labelled `read`, `read-like` or `WRITE`:
   - `read` — GET, no side effects.
   - `read-like` — POST without local writes: previews, number parsing, `*/test` probes. No `--confirm`, but they may call external services.
   - `WRITE` — everything else. Generated commands always require `--confirm`.
3. **Read the source when semantics matter.** Schema summaries are thin ("Get Movie Detail"). `describe` prints `backend_version`; clone that tag (`git clone --depth 1 --branch <version>`) into a working directory you pick, then read `src/api/routers/**` and `src/service/**` for ordering, validation and side effects. Read only — never run the cloned code or install its dependencies.
4. **Scaffold** with `scaffold --name ... --description ... --endpoint METHOD:/path ...`. It writes `skill.json`, `SKILL.md` and a runnable CLI where each endpoint is a subcommand.
5. **Fill the gaps.** The generated CLI maps parameters one to one; add the real workflow (step ordering, persisted plan/state, bounded polling) and keep the write gate intact.
6. **Validate** with `validate --skill-dir <dir>`. It fails on a name/folder mismatch, missing author, a write command without `--confirm`, a hardcoded URL, or a literal API key.

Pass `--schema <file>` when the backend is unreachable so `describe` and `scaffold` can work from a saved `openapi.json`.

## Rules for generated skills

- Every state-changing command requires `--confirm`; without it the command exits with a reason instead of calling the API.
- Never put the API key, full magnet links or large raw JSON in replies.
- After a timeout, check state instead of replaying the call.
- Multi-step flows persist intermediate state (for example a plan id) instead of re-searching and silently switching targets.
- Skills speak HTTP to the backend only; they never import backend code.
