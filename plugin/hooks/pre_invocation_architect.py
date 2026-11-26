#!/usr/bin/env python3
"""Read-only 0-token PreInvocation hook for bare '/gravity-architect'."""

from __future__ import annotations

from pathlib import Path
import sys

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from _shared import hook_runtime  # noqa: E402


def main() -> int:
    hook_runtime.configure_utf8_stdio()
    payload = hook_runtime.read_stdin_json(timeout_s=1.0)
    if not payload or not hook_runtime.is_initial_invocation(payload):
        hook_runtime.emit_passthrough()
        return 0

    cmd = hook_runtime.normalize_command(
        hook_runtime.first_str_arg(payload, "lastUserInput", "userInput", "prompt")
    )
    if cmd not in ("/gravity-architect", "/gravity-architect:gravity-architect"):
        hook_runtime.emit_passthrough()
        return 0

    try:
        from scripts import atelier_status  # noqa: E402

        status_payload = atelier_status.collect_atelier_status()
        md = atelier_status.format_status_markdown(status_payload)
        hook_runtime.emit_user_markdown(
            md,
            system_message="Gravity Architect status (read-only).",
        )
    except Exception:
        hook_runtime.emit_passthrough()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
