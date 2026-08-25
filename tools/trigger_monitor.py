#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Durable trigger-debug.log anomaly monitor.

Backs the Claude-session monitor so anomaly reporting survives when no session
is open: finds renpy_cue/trigger-debug.log under the pGames games root, files
one GitHub issue per distinct (kind, video) problem -- deduped against already
open trigger-anomaly issues -- then truncates each processed log so old
problems aren't re-reported.

Fails safe: a log is cleared only after every anomaly in it was either filed or
matched an existing open issue; any gh failure keeps the log intact so the next
run retries.

Runs from cron (user crontab).  --dry-run only reports what would happen.

Host tool, system Python 3.  Uses the gh CLI (already authed as the repo owner)
for GitHub API calls.
"""

import re
import subprocess
import sys
from pathlib import Path

GAMES_ROOT = Path("/mnt/e/Porn/pGames")
REPO = "guanzo/renpy-cue"
GH = "/usr/bin/gh"
SEP = "=" * 60
RING_LINES = 15  # evidence ring lines captured per anomaly marker
MAX_EVIDENCE = 40  # evidence lines kept per issue body

MARKER_RE = re.compile(r"^\[[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]+\]\s+TD-ANOMALY type=(\S+)\s+(.*)$")
VID_RE = re.compile(r"\bvid=([^\s]+)")

KIND_MEANING = {
    "late": "marker fired past the late threshold",
    "missed": "marker skipped entirely (past-due, never fired)",
    "play-failed": "marker reached but playback produced no sound",
    "gate-closed": "movie layer up but no video channel (stuck gate)",
    "stall": "engine tick gap larger than the stall threshold",
    "marker-beyond-duration": "marker time past the video duration (likely a marker-data typo)",
    "restart-burst": "abnormally many video restarts inside the burst window",
}


def find_logs(root):
    """All non-empty renpy_cue trigger-debug.log files under the games root."""
    if not root.is_dir():
        return []
    return [p for p in root.rglob("trigger-debug.log") if "renpy_cue" in str(p) and p.stat().st_size > 0]


def parse_blocks(text):
    """One entry per TD-ANOMALY marker: kind, details, vid, evidence ring.

    Snapshot blocks are split by the 60-char separator; the first line of each
    chunk is the marker, the rest are the ring lines that followed it."""
    blocks = []
    for chunk in text.split(SEP):
        lines = [ln for ln in chunk.splitlines() if ln.strip()]
        if not lines:
            continue
        m = MARKER_RE.match(lines[0].strip())
        if not m:
            continue
        kind = m.group(1)
        details = m.group(2).strip()
        vid = VID_RE.search(details)
        blocks.append(
            {
                "kind": kind,
                "details": details,
                "vid": vid.group(1) if vid else None,
                "evidence": lines[: RING_LINES + 1],
            }
        )
    return blocks


def group_by_problem(blocks):
    """Distinct (kind, vid) problems within one log, with aggregated evidence."""
    groups = {}
    for b in blocks:
        key = (b["kind"], b["vid"])
        if key not in groups:
            groups[key] = {"kind": b["kind"], "vid": b["vid"], "markers": [], "evidence": []}
        groups[key]["markers"].append(b["details"])
        groups[key]["evidence"].extend(b["evidence"])
    for g in groups.values():
        seen = set()
        dedup = []
        for ln in g["evidence"]:
            if ln not in seen:
                seen.add(ln)
                dedup.append(ln)
        g["evidence"] = dedup[:MAX_EVIDENCE]
    return list(groups.values())


def title_for(group, game_name):
    return "trigger-anomaly: {} {}".format(group["kind"], group["vid"] or game_name)


def _gh(args):
    """Run a gh subcommand; return the CompletedProcess, or None on failure."""
    try:
        return subprocess.run([GH] + args, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        print("gh run failed: {}".format([GH] + args), file=sys.stderr)
        return None


def issue_exists(title):
    """True when an open issue already has this exact title; None when unknown."""
    out = _gh(
        ["issue", "list", "--repo", REPO, "--state", "open", "--search", 'in:title "{}"'.format(title), "--limit", "1"]
    )
    if out is None:
        return None
    if out.returncode != 0:
        print("gh issue list -> {} {}".format(out.returncode, out.stderr.strip()), file=sys.stderr)
        return None
    return bool(out.stdout.strip())


def file_issue(title, body):
    """Create the issue; True on success."""
    out = _gh(["issue", "create", "--repo", REPO, "--title", title, "--body", body, "--label", "bug"])
    if out is None:
        return False
    if out.returncode != 0:
        print("gh issue create -> {} {}".format(out.returncode, out.stderr.strip()), file=sys.stderr)
        return False
    return True


def build_body(group, game, path):
    lines = ["Found by the trigger-debug anomaly monitor (durable cron).", ""]
    lines.append("Game: {} ({})".format(game, GAMES_ROOT / game))
    lines.append("Anomaly type: {} -- {}".format(group["kind"], KIND_MEANING.get(group["kind"], group["kind"])))
    lines.append("Occurrences: {}".format(len(group["markers"])))
    lines.append("")
    lines.append("Evidence ({}):".format(path))
    lines.append("```")
    lines.extend(group["evidence"])
    lines.append("```")
    return "\n".join(lines)


def process_log(path, dry_run):
    """File issues for a log's anomalies; clear it only when every anomaly was
    handled (filed or already tracked)."""
    out = {"filed": 0, "deduped": 0, "cleared": 0, "failed": 0}
    blocks = parse_blocks(path.read_text(errors="replace"))
    if not blocks:
        out["failed"] = 1  # unparseable content; never clear
        return out
    game = path.relative_to(GAMES_ROOT).parts[0]
    for group in group_by_problem(blocks):
        title = title_for(group, game)
        exists = issue_exists(title)
        if exists is None:
            out["failed"] = 1
            continue
        if exists:
            out["deduped"] += 1
            continue
        if dry_run:
            print("  would file: {}".format(title))
            out["filed"] += 1
            continue
        if file_issue(title, build_body(group, game, path)):
            out["filed"] += 1
        else:
            out["failed"] = 1
    if out["failed"] == 0 and not dry_run:
        with open(path, "w"):
            pass
        out["cleared"] = 1
    elif out["failed"] == 0 and dry_run:
        out["cleared"] = 1  # would clear
    return out


def main():
    dry_run = "--dry-run" in sys.argv[1:]
    logs = find_logs(GAMES_ROOT)
    if not logs:
        print("trigger-monitor: no logs found")
        return 0
    totals = {"filed": 0, "deduped": 0, "cleared": 0, "failed": 0}
    for path in sorted(logs):
        result = process_log(path, dry_run)
        print(
            "{}: filed={} deduped={} cleared={} failed={}".format(
                path, result["filed"], result["deduped"], result["cleared"], result["failed"]
            )
        )
        for key in totals:
            totals[key] += result[key]
    if totals["failed"]:
        print("trigger-monitor: {} file(s) failed -- logs retained".format(totals["failed"]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
