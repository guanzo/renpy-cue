---
name: issue-handoff
description: Produce a technical handoff summary of the current debugging issue for another LLM
---

# /issue-handoff

Produce a technical handoff summary of the current debugging issue. The summary must be self-contained and ready to paste to another LLM — include enough context that they can pick up without asking basic questions.

Structure:

1. **Goal** — what we're trying to accomplish (one sentence)
2. **Current symptom** — exact error message or behavior
3. **What we've tried** — chronological list of attempts, with technical details (file paths, code snippets, config changes)
4. **What worked / didn't** — each attempt marked SUCCESS or FAILED with why
5. **Current state** — where things stand right now
6. **Constraints** — relevant project constraints (Python 2.7 compat, Ren'Py versions, etc.)
7. **Relevant files** — list of files involved with brief descriptions

Be concise. Use exact error messages, file paths, and line numbers. This is for an engineer to read and immediately understand the problem space.

## Clipboard auto-copy

Copy the handoff document to the user's clipboard automatically — they shouldn't have to run /copy afterward.

1. Write ONLY the handoff document (the Goal→Relevant files content, with its header if you give it one) to a temp file:
   `TMP=$(mktemp -t cue-handoff.XXXXXX.md)` and write the document to `$TMP`. The file must contain only the document — no meta-commentary, and never the confirmation text.
2. Copy it: `xclip -selection clipboard < "$TMP"`.
3. Verify the copy succeeded. If `xclip` is missing, the copy fails, or there is no usable clipboard, print the document normally and tell the user to run `/copy` instead.
4. After a successful copy, end your reply with a standalone confirmation line, separated from the document by a blank line, e.g. `Copied my response to your clipboard.` (you may add the temp file path in parentheses). This confirmation is only spoken in the reply — it is NOT part of the document and must never appear in the temp file or on the clipboard.
