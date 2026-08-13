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
