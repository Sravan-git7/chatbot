"""Offline repair of a hand-copied SAP ``pagecontent`` response whose JSON is malformed.

Browser "Copy response" on a pagecontent call can yield text in which the HTML inside
``data.body`` contains *bare* double quotes (``<html lang="en-us">``) - invalid JSON.
Everything outside ``body`` is ordinary, valid JSON. The repair is therefore confined to
the ``body`` string and is deterministic:

1. ``head``  = text before ``,"body":"``      -> must parse (after closing the two open objects);
2. ``tail``  = text from the first ``","<key>":`` after the body start that parses as the
   remaining object members (normally ``isMachineTranslated`` / ``githubLink``);
3. ``body``  = what lies between; bare quotes (not preceded by an odd number of backslashes)
   and raw control characters are escaped, then the string is decoded with ``json``. Existing
   valid escapes (``\\n``, ``\\u003c``, ``\\"``) are decoded as usual, nothing else is changed.

The body text is never edited, trimmed or re-encoded. Anything that does not fit this
structure raises ``RepairError`` (no guessing).
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Tuple

from .intake import strip_bom

_BODY_KEY = re.compile(r',\s*"body"\s*:\s*"')
_TAIL_CANDIDATE = re.compile(r'"\s*,\s*(?="[A-Za-z_][A-Za-z_0-9]*"\s*:)')
_VALID_ESC = set('"\\/bfnrtu')


class RepairError(ValueError):
    pass


def _escape_bare_quotes(raw: str) -> Tuple[str, int]:
    out, n, i = [], 0, 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\":
            if i + 1 >= len(raw) or raw[i + 1] not in _VALID_ESC:
                raise RepairError(f"invalid escape sequence inside body at offset {i}: {raw[i:i + 6]!r}")
            out.append(raw[i:i + 2])
            i += 2
            continue
        if ch == '"':
            out.append('\\"')
            n += 1
        else:
            out.append(ch)
        i += 1
    return "".join(out), n


def repair_pagecontent_text(text: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """-> (response_dict, report). Raises ``RepairError`` when the structure is not the expected one."""
    text = strip_bom(text).strip()
    m = _BODY_KEY.search(text)
    if not m or len(_BODY_KEY.findall(text)) != 1:
        raise RepairError('expected exactly one `"body":"` member')
    head_text, rest = text[:m.start()], text[m.end():]
    try:
        head = json.loads(head_text + "}}")
        data = head["data"]
        assert isinstance(data, dict)
    except (ValueError, KeyError, AssertionError) as e:
        raise RepairError(f"everything before `body` must be valid JSON ({{status, data{{...}}}}): {e}") from e

    chosen = None
    candidates = 0
    for c in _TAIL_CANDIDATE.finditer(rest):
        tail_text = rest[c.end():]
        m_end = re.search(r"\}\s*\}\s*$", tail_text)       # closes `data` and the response object
        if not m_end:
            continue
        candidates += 1
        try:
            tail = json.loads("{" + tail_text[:m_end.start() + 1])
        except ValueError:
            continue
        chosen = (c, tail)
        break
    if chosen is None:
        raise RepairError('could not find the end of `body` (`","<key>":...}}` tail that parses as JSON)')
    c, tail = chosen
    body_raw = rest[:c.start()]
    escaped, n_bare = _escape_bare_quotes(body_raw)
    try:
        body = json.loads('"' + escaped + '"', strict=False)
    except ValueError as e:
        raise RepairError(f"body is not decodable after escaping bare quotes: {e}") from e
    data = dict(data)
    data["body"] = body
    data.update(tail)
    resp = dict(head)
    resp["data"] = data
    report = {
        "bare_quotes_escaped": n_bare,
        "body_chars": len(body),
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "tail_keys": list(tail),
        "tail_candidates_examined": candidates,
        "head_keys": list(data)[:-1 - len(tail)],
    }
    return resp, report
