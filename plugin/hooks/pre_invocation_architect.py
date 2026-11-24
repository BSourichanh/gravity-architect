#!/usr/bin/env python3
"""Hook PreInvocation lecture seule 0-token pour '/gravity-architect' sans argument."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import threading
from typing import Any, Optional

HOOKS_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = HOOKS_DIR.parent

_STRIP_META_RE = re.compile(
    r"<ADDITIONAL_METADATA>.*?(?:</ADDITIONAL_METADATA>|$)"
    r"|<USER_SETTINGS_CHANGE>.*?(?:</USER_SETTINGS_CHANGE>|$)"
    r"|</?USER_REQUEST>",
    re.DOTALL,
)


def _configure_utf8_stdio() -> None:
    """Force UTF-8 sur stdin/stdout/stderr pour éviter les erreurs cp1252 sous Windows."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _read_stdin_text(timeout_s: float = 1.0) -> str:
    """Lit stdin en sécurité avec timeout sans bloquer si aucun flux n'est pipé."""
    if sys.stdin is None or sys.stdin.isatty():
        return ""
    buf: list[str] = []

    def _reader() -> None:
        try:
            buf.append(sys.stdin.read())
        except Exception:
            pass

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    thread.join(timeout=timeout_s)
    return buf[0].strip() if buf else ""


def _emit_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _extract_user_input(payload: dict[str, Any]) -> str:
    for key in ("lastUserInput", "userInput", "prompt"):
        val = payload.get(key)
        if isinstance(val, str):
            return val
    return ""


def _normalize_command(raw_text: str) -> str:
    cleaned = _STRIP_META_RE.sub("", raw_text)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def _is_initial_invocation(payload: dict[str, Any]) -> bool:
    inv_num: Optional[Any] = payload.get("invocationNum")
    if inv_num is None:
        return True
    if isinstance(inv_num, bool):
        return False
    return inv_num == 0


def main() -> int:
    _configure_utf8_stdio()
    raw = _read_stdin_text(timeout_s=1.0)
    if not raw:
        _emit_json({})
        return 0

    try:
        payload = json.loads(raw)
    except ValueError:
        _emit_json({})
        return 0

    if not isinstance(payload, dict) or not _is_initial_invocation(payload):
        _emit_json({})
        return 0

    cmd = _normalize_command(_extract_user_input(payload))
    if cmd not in ("/gravity-architect", "/gravity-architect:gravity-architect"):
        _emit_json({})
        return 0

    try:
        if str(PLUGIN_ROOT) not in sys.path:
            sys.path.insert(0, str(PLUGIN_ROOT))
        from scripts import atelier_status  # noqa: E402

        status_payload = atelier_status.collect_atelier_status()
        md = atelier_status.format_status_markdown(status_payload)
        _emit_json(
            {
                "injectSteps": [
                    {
                        "systemMessage": {
                            "systemMessage": "Gravity Architect status (read-only).",
                            "metadata": {"user_markdown": md},
                        }
                    }
                ],
                "terminationBehavior": "terminate",
            }
        )
    except Exception:
        _emit_json({})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
