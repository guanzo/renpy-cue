#!/usr/bin/env python3
"""Rewrite screen-language source in place for Ren'Py < 7.4 compatibility.

The committed cue_lib targets 7.4+ / 8.x, but the harness also boots it under
7.2.x, whose screen parser and atl Transform reject two idioms the modern
SDKs accept:

1. Multi-line statement calls -- `use foo(` with args on the following
   indented lines. 7.2.x parses each physical line as its own statement and
   raises IndentationError on the first continuation. Rejoining the lines
   (bracket-balanced, via Python's tokenizer) is a semantics no-op for every
   SDK.

2. Transform keyword props `xsize`/`ysize`. 7.2.x's Transform has `size` but
   not the individual width/height props. When both are given they are folded
   into `size=(X, Y)`, which every SDK accepts.

The harness runs this on its per-run copy of cue_lib (never the repo source)
so committed code can stay on the modern idiom. Prints a line per rewritten
file.

Usage: transform_legacy_screens.py <dir>...
"""

import io
import os
import sys
import tokenize


def _tok_text(tokens):
    return "".join(t.string for t in tokens)


def _split_args(arg_tokens):
    """Split a token list on top-level commas -> list of token lists."""
    args = []
    cur = []
    depth = 0
    for t in arg_tokens:
        if t.type == tokenize.OP:
            if t.string in "([{":
                depth += 1
            elif t.string in ")]}":
                depth -= 1
            elif t.string == "," and depth == 0:
                args.append(cur)
                cur = []
                continue
        cur.append(t)
    if cur:
        args.append(cur)
    return args


def fold_transform_size(text):
    """Rewrite Transform(...) calls that pass both xsize and ysize."""
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    line_offsets = []
    pos = 0
    for seg in text.split("\n"):
        line_offsets.append(pos)
        pos += len(seg) + 1

    def off(tok):
        row, col = tok.start
        return line_offsets[row - 1] + col

    out = []
    i = 0
    n = len(tokens)
    last = 0
    while i < n:
        tok = tokens[i]
        is_transform = (
            tok.type == tokenize.NAME and tok.string == "Transform"
            and i + 1 < n and tokens[i + 1].type == tokenize.OP
            and tokens[i + 1].string == "(")
        if not is_transform:
            i += 1
            continue
        # Collect tokens up to the matching close paren.
        depth = 0
        j = i + 1
        while j < n:
            t = tokens[j]
            if t.type == tokenize.OP:
                if t.string == "(":
                    depth += 1
                elif t.string == ")":
                    depth -= 1
                    if depth == 0:
                        break
            j += 1
        arg_tokens = tokens[i + 2:j]
        xsize = ysize = None
        kept = []
        for a in _split_args(arg_tokens):
            eq = next((k for k, t in enumerate(a)
                       if t.type == tokenize.OP and t.string == "="), None)
            if eq is None:
                kept.append(a)
                continue
            name = _tok_text(a[:eq]).strip()
            value_toks = a[eq + 1:]
            value = text[off(value_toks[0]):off(value_toks[-1]) + len(value_toks[-1].string)].strip()
            if name == "xsize":
                xsize = value
            elif name == "ysize":
                ysize = value
            else:
                kept.append(a)
        end_off = off(tokens[j]) + len(tokens[j].string)
        out.append(text[last:off(tok)])
        if xsize is not None and ysize is not None:
            # Splice by original spans so kept args keep their spacing.
            parts = [text[off(a[0]):off(a[-1]) + len(a[-1].string)]
                     for a in kept]
            parts.append("size=({}, {})".format(xsize, ysize))
            out.append("Transform(" + ", ".join(parts) + ")")
        else:
            out.append(text[off(tok):end_off])
        last = end_off
        i = j + 1
    out.append(text[last:])
    return "".join(out)


def join_multiline(text):
    """Collapse statement calls whose args span physical lines."""
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    by_line = {}
    for tok in tokens:
        if tok.type in (tokenize.ENCODING, tokenize.NL, tokenize.NEWLINE,
                        tokenize.INDENT, tokenize.DEDENT):
            continue
        ln = tok.start[0]
        by_line.setdefault(ln, []).append(tok)

    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        line_no = i + 1
        toks = by_line.get(line_no, [])
        # Trigger: line ends with an open paren that stays unclosed (the
        # statement's expression continues on the lines below).
        if toks and toks[-1].type == tokenize.OP and toks[-1].string == "(":
            depth = sum(t.string.count("(") - t.string.count(")")
                        for t in toks if t.type == tokenize.OP)
            if depth > 0:
                buf = [cur.strip()]
                j = i + 1
                abort = False
                while j < len(lines) and depth > 0:
                    jt = by_line.get(j + 1, [])
                    # Comment-only continuation line: drop it.
                    if jt and all(t.type in (tokenize.COMMENT, tokenize.NL,
                                             tokenize.NEWLINE) for t in jt):
                        j += 1
                        continue
                    # An inline comment or multi-line string in the args is
                    # not safe to fuse; emit verbatim and let newer SDKs
                    # handle it (7.2.x would reject it anyway).
                    for t in jt:
                        if t.type == tokenize.COMMENT:
                            abort = True
                        if t.type == tokenize.STRING and "\n" in t.string:
                            abort = True
                    if abort:
                        break
                    depth += sum(t.string.count("(") - t.string.count(")")
                                 for t in jt if t.type == tokenize.OP)
                    buf.append(lines[j].strip())
                    j += 1
                if depth <= 0 and not abort:
                    indent = cur[: len(cur) - len(cur.lstrip())]
                    out.append(indent + " ".join(buf))
                    i = j
                    continue
        out.append(cur)
        i += 1
    return "\n".join(out)


def transform_file(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    out = fold_transform_size(join_multiline(text))
    if out != text:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(out)
        return True
    return False


def main(argv):
    changed = []
    for root in argv:
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if f.endswith(".rpy"):
                    p = os.path.join(dirpath, f)
                    if transform_file(p):
                        changed.append(p)
    for p in changed:
        print("transformed: {}".format(p))
    print("{} file(s) rewritten".format(len(changed)))


if __name__ == "__main__":
    main(sys.argv[1:])
