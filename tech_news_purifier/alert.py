from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from datetime import UTC, datetime

import httpx


def _command(*args: str) -> str:
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=10)
    return result.stdout.strip()


def _sanitize(value: str) -> str:
    value = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", value)
    value = re.sub(r"(?i)(token|key|secret)=\S+", r"\1=[REDACTED]", value)
    return value[-3000:]


def build_payload(unit: str) -> dict[str, object]:
    properties = _command(
        "systemctl", "show", unit, "--property=Result,ExecMainStatus", "--no-pager"
    )
    summary = _command("journalctl", "-u", unit, "-n", "20", "--no-pager", "-o", "cat")
    status = dict(
        line.split("=", 1) for line in properties.splitlines() if "=" in line
    )
    return {
        "service": "tech-news-pipeline",
        "unit": unit,
        "host": socket.gethostname(),
        "timestamp": datetime.now(UTC).isoformat(),
        "result": status.get("Result", "unknown"),
        "exit_status": status.get("ExecMainStatus", "unknown"),
        "summary": _sanitize(summary),
    }


def send_alert(webhook_url: str, payload: dict[str, object]) -> None:
    response = httpx.post(webhook_url, json=payload, timeout=15)
    response.raise_for_status()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m tech_news_purifier.alert <systemd-unit>", file=sys.stderr)
        return 2
    webhook_url = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    payload = build_payload(args[0])
    if not webhook_url:
        print(json.dumps(payload, ensure_ascii=False))
        print("ALERT_WEBHOOK_URL 未配置，仅记录本地告警", file=sys.stderr)
        return 0
    send_alert(webhook_url, payload)
    print(json.dumps({"alert_sent": True, "unit": args[0]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
