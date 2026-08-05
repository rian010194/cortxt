#!/usr/bin/env python3
"""Buzz return channel — post run status / approvals into a Buzz channel.

Makes Buzz a live operator surface by publishing status updates back from the
Hermes control plane into a Buzz channel, using the installed `buzz.exe` CLI.

Security: the private key is read ONLY from the environment or the
credential-manager store. It is never printed, logged, or written to disk by
this script or its subprocesses.

Usage:
    BUZZ_PRIVATE_KEY=<...> python harness/scripts/buzz-return.py send \
        --channel <uuid> --message @-          # read message from stdin
    BUZZ_PRIVATE_KEY=<...> BUZZ_RELAY_URL=<wss://...> python harness/scripts/buzz-return.py send \
        --channel <uuid> --content "Run complete: run-xxx [DONE]"
    python harness/scripts/buzz-return.py send ... --dry-run   # no network; prints payload

Assumes `buzz.exe` on system (C:\\Users\\rikar\\AppData\\Local\\Buzz\\buzz.exe) or on PATH.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HOSTED_CHANNEL = "265caa75-334c-4075-8363-be88ef4077f9"
HOSTED_RELAY = "wss://cortxt.communities.buzz.xyz"
BUZZ_CANDIDATES = [
    Path(r"C:\Users\rikar\AppData\Local\Buzz\buzz.exe"),
]

TYPE_TAG = {"status": "9", "approval": "9", "forum": "45001"}


def find_buzz() -> str | None:
    for p in BUZZ_CANDIDATES:
        if p.exists():
            return str(p)
    return shutil.which("buzz")


def _env_key() -> str | None:
    k = os.environ.get("BUZZ_PRIVATE_KEY")
    if k:
        return k
    # Fallback: read persistent user-scope env set via `setx` (never printed).
    try:
        import subprocess as _sp
        out = _sp.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "[Environment]::GetEnvironmentVariable('BUZZ_PRIVATE_KEY','User')"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return out or None
    except Exception:
        return None


def _key_available() -> bool:
    return _env_key() is not None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--relay", default=os.environ.get("BUZZ_RELAY_URL", HOSTED_RELAY))
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the resolved command without executing it.")
    sub = ap.add_subparsers(dest="command")

    send = sub.add_parser("send")
    send.add_argument("--channel", default=HOSTED_CHANNEL)
    send.add_argument("--content", default=None,
                      help="Message body. Use '@-' to read from stdin.")
    send.add_argument("--kind", choices=sorted(TYPE_TAG), default="status")

    args = ap.parse_args(argv)
    buzz = find_buzz()
    if buzz is None:
        print("BUZZ_RETURN_ERROR: buzz.exe not found", file=sys.stderr)
        return 4

    if args.command == "send":
        if not _key_available() and not args.dry_run:
            print(
                "BUZZ_RETURN_BLOCKED: BUZZ_PRIVATE_KEY not set in environment.\n"
                "Inject a valid key (NOT the exposed desktop identity) via\n"
                "credential-manager / approved secret injection, then retry.",
                file=sys.stderr,
            )
            return 3

        content = args.content
        if content == "@-":
            content = sys.stdin.read()

        payload = ["--format", "compact", "messages", "send",
                   "--channel", args.channel, "--content", content]
        # --kind maps to a message kind tag only for forum posts
        if args.kind == "forum":
            payload += ["--kind", "45001"]

        cmd = [buzz, "--relay", args.relay] + payload

        if args.dry_run:
            # Redact any secret that would otherwise appear.
            safe = [c if "PRIVATE" not in c.upper() else "<redacted>" for c in cmd]
            safe_payload = payload  # content is not a secret
            print("[dry-run] buzz:", " ".join(str(x) for x in [buzz, "--relay", "<relay>"] + payload))
            return 0

        env = os.environ.copy()
        key = _env_key()
        if key is None:
            print("BUZZ_RETURN_BLOCKED: unable to resolve BUZZ_PRIVATE_KEY", file=sys.stderr)
            return 3
        # Inject the resolved key into the subprocess env so buzz.exe sees it
        # even when the caller's process env was stale. Never print it.
        env["BUZZ_PRIVATE_KEY"] = key
        res = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
        if res.returncode == 0:
            print("BUZZ_RETURN_OK:", res.stdout.strip())
            return 0
        print("BUZZ_RETURN_FAIL:", res.stderr.strip() or res.stdout.strip(), file=sys.stderr)
        return 1

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
