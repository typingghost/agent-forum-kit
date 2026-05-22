from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    db_path: Path
    audit_log_path: Path
    review_root: Path
    review_roots: tuple[Path, ...]
    upload_root: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        db_path = Path(os.environ.get("FORUM_DB_PATH", PROJECT_ROOT / "data" / "forum.db"))
        audit_log_path = Path(
            os.environ.get("FORUM_AUDIT_LOG_PATH", PROJECT_ROOT / "data" / "audit_log.jsonl")
        )
        default_root = PROJECT_ROOT / "data" / "review"
        review_root = Path(os.environ.get("FORUM_REVIEW_ROOT", default_root))
        review_roots = parse_review_roots(review_root)
        return cls(
            db_path=db_path.expanduser(),
            audit_log_path=audit_log_path.expanduser(),
            review_root=review_root.expanduser(),
            review_roots=review_roots,
            upload_root=Path(os.environ.get("FORUM_UPLOAD_ROOT", PROJECT_ROOT / "data" / "uploads")).expanduser(),
        )


def parse_review_roots(review_root: Path) -> tuple[Path, ...]:
    configured = os.environ.get("FORUM_REVIEW_ROOTS")
    if configured:
        roots = [Path(part).expanduser() for part in configured.split(os.pathsep) if part.strip()]
        return tuple(dict.fromkeys(root.resolve() for root in roots))

    return (review_root.expanduser().resolve(),)


settings = Settings.from_env()
