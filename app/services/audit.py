from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings


def append_audit(event: str, payload: dict[str, Any], path: Path | None = None) -> None:
    target = path or settings.audit_log_path
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "event": event,
        "created_at": datetime.now(UTC).isoformat(),
        **payload,
    }
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

