---
name: sakuramedia-acquire
description: Acquire movies for SakuraMedia — resolve a movie, check whether it is already playable, search download candidates, submit a download, follow progress, trigger import, and retry failed imports with metadata candidates. Use when the user says things like "查一下/补一下某部片", "为什么这个番号没入库", "下载完成后帮我导入", "导入失败帮我重试", or otherwise asks to find, download or import a movie. Every write operation must be explicitly confirmed by the user.
---

# SakuraMedia Acquire

Move one movie from "not present locally" to "imported and playable", or report which step is blocking it. Reply in the user's language.

## Connection

Two environment variables, shared by every Sakuramedia skill:

- `SAKURAMEDIA_BASE_URL`
- `SAKURAMEDIA_API_KEY`

Never print the API key.

## Workflow

`python3 scripts/sakuramedia_acquire.py <command>`

1. `check` — verify the connection.
2. `plan --query ABC-123` — statuses: `ambiguous` means ask the user for the exact movie number instead of guessing; `already_available` means stop; `ready` means show the first few candidates with `selection_evaluation`. Keep the returned `plan_id` and reuse it later.
3. Show the movie number and title, each candidate's title, size, seeders, indexer and client, whether the policy allows it and why not, and whether a download task already exists. Submit only after the user confirms; if the user says to just pick, `recommended_candidate_index` is fine, but report which candidate you took.
4. `submit --plan-id <plan_id> --candidate-index 0 --confirm` — returns `download_task`.
5. `status --movie-number ABC-123` — poll a bounded number of times, then report the current stage.
6. `import --task-id 123 --confirm` — then `task-run --task-run-id 456` with the returned id.
7. Failed import: `failures --task-run-id 456`, then `metadata-candidates --task-run-id 456 --item-id <item_id> --movie-number ABC-123`, then `retry --task-run-id 456 --item-id <item_id> --candidate-id <candidate_id> --confirm` once the user picks a candidate.
8. `verify --movie-number ABC-123` — only `playable=true` counts as imported and playable.

## Rules

- Writes need an explicit `--confirm`. Never delete download tasks or files, blocklist releases, change subscriptions, or run batch maintenance.
- After a timeout, check status instead of submitting again.
- Stop when playable media already exists.
- On a failed import, show the failed items and candidates instead of retrying the same candidate blindly.
- Never paste the API key, full magnet links or large raw JSON payloads into replies.
