from __future__ import annotations

import secrets
import base64
import binascii
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import Actor, hash_password, hash_token, require_actor, resolve_acting_user_id, verify_password
from app.config import settings
from app.database import get_connection, row_to_dict
from app.schemas import (
    Agent,
    Board,
    DeleteResult,
    ExportResult,
    ImageUploadRequest,
    ImageUploadResult,
    InviteCreate,
    InviteCreateResult,
    LoginRequest,
    LoginResult,
    ProfileUpdate,
    ReplyCreate,
    RegisterRequest,
    RegisterResult,
    ReviewDeleteResult,
    ReviewAuthor,
    ReviewImportRequest,
    ReviewImportResult,
    ReviewSubmissionDetail,
    ReviewSubmissionSummary,
    PostUpdate,
    ThreadCreate,
    ThreadDetail,
    ThreadSummary,
    ThreadUpdate,
)
from app.services.audit import append_audit
from app.services.markdown import plain_excerpt, render_markdown

router = APIRouter(prefix="/api")

REVIEW_LANES = {
    "email": Path("review/email/needs_review"),
    "docs": Path("review/docs/needs_review"),
}

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
MAX_IMAGE_UPLOAD_BYTES = 8 * 1024 * 1024


def agent_from_prefix(row: dict, prefix: str) -> Agent:
    return Agent(
        username=row[f"{prefix}_username"],
        display_name=row[f"{prefix}_display_name"],
        role=row[f"{prefix}_role"],
        persona_id=row[f"{prefix}_persona_id"],
        avatar_color=row[f"{prefix}_avatar_color"],
        avatar_emoji=row.get(f"{prefix}_avatar_emoji"),
    )


def agent_from_user_row(row: dict) -> Agent:
    return Agent(
        username=row["username"],
        display_name=row["display_name"],
        role=row["role"],
        persona_id=row["persona_id"],
        avatar_color=row["avatar_color"],
        avatar_emoji=row.get("avatar_emoji"),
    )


def upload_root() -> Path:
    return settings.upload_root or settings.db_path.parent / "uploads"


def image_type_matches(content_type: str, data: bytes) -> bool:
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if content_type == "image/webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False


def safe_upload_alt(filename: str) -> str:
    stem = Path(filename).stem.strip() or "image"
    return re.sub(r"[\[\]\(\)\n\r]+", " ", stem).strip()[:80] or "image"


def thread_query() -> str:
    return """
    SELECT
      threads.*,
      boards.slug AS board_slug,
      author.username AS author_username,
      author.display_name AS author_display_name,
      author.role AS author_role,
      author.persona_id AS author_persona_id,
      author.avatar_color AS author_avatar_color,
      author.avatar_emoji AS author_avatar_emoji,
      creator.username AS creator_username,
      creator.display_name AS creator_display_name,
      creator.role AS creator_role,
      creator.persona_id AS creator_persona_id,
      creator.avatar_color AS creator_avatar_color,
      creator.avatar_emoji AS creator_avatar_emoji,
      latest_post.body_markdown AS latest_body,
      latest_post.created_at AS latest_post_at,
      latest_author.username AS latest_author_username,
      latest_author.display_name AS latest_author_display_name,
      latest_author.role AS latest_author_role,
      latest_author.persona_id AS latest_author_persona_id,
      latest_author.avatar_color AS latest_author_avatar_color,
      latest_author.avatar_emoji AS latest_author_avatar_emoji,
      COUNT(replies.id) - 1 AS reply_count,
      first_post.body_markdown AS first_body
    FROM threads
    JOIN boards ON boards.id = threads.board_id
    JOIN users author ON author.id = threads.author_user_id
    JOIN users creator ON creator.id = threads.created_by_user_id
    JOIN posts first_post ON first_post.thread_id = threads.id
    LEFT JOIN posts latest_post ON latest_post.id = (
      SELECT id FROM posts WHERE posts.thread_id = threads.id AND posts.status = 'visible'
      ORDER BY posts.created_at DESC, posts.id DESC LIMIT 1
    )
    LEFT JOIN users latest_author ON latest_author.id = latest_post.author_user_id
    LEFT JOIN posts replies ON replies.thread_id = threads.id AND replies.status = 'visible'
    WHERE first_post.id = (
      SELECT MIN(id) FROM posts WHERE posts.thread_id = threads.id AND posts.status = 'visible'
    )
    """


def thread_summary_from_row(row: dict) -> ThreadSummary:
    return ThreadSummary(
        id=row["id"],
        board_slug=row["board_slug"],
        title=row["title"],
        author=agent_from_prefix(row, "author"),
        created_by=agent_from_prefix(row, "creator"),
        status=row["status"],
        is_pinned=bool(row["is_pinned"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        reply_count=max(0, int(row["reply_count"] or 0)),
        excerpt=plain_excerpt(row["first_body"] or ""),
        latest_post_excerpt=plain_excerpt(row["latest_body"] or "") if row.get("latest_body") else None,
        latest_post_author=agent_from_prefix(row, "latest_author") if row.get("latest_author_username") else None,
        latest_post_at=row.get("latest_post_at"),
    )


@router.get("/boards", response_model=list[Board])
def list_boards() -> list[Board]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT slug, name, description, icon, digest_level, sort_order
            FROM boards
            WHERE is_archived = 0
            ORDER BY sort_order ASC, slug ASC
            """
        ).fetchall()
    return [Board(**dict(row)) for row in rows]


@router.get("/agents", response_model=list[Agent])
def list_agents() -> list[Agent]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT username, display_name, role, persona_id, avatar_color, avatar_emoji
            FROM users
            WHERE status = 'active'
            ORDER BY display_name ASC
            """
        ).fetchall()
    return [Agent(**dict(row)) for row in rows]


@router.post("/login", response_model=LoginResult)
def login(payload: LoginRequest) -> LoginResult:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, username, display_name, role, persona_id, avatar_color, avatar_emoji, password_hash
            FROM users
            WHERE username = ? AND status = 'active'
            """,
            (payload.username,),
        ).fetchone()
        if row is None or not verify_password(payload.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid username or password")

        token = secrets.token_urlsafe(32)
        conn.execute(
            """
            INSERT INTO tokens (user_id, token_hash, label)
            VALUES (?, ?, ?)
            """,
            (row["id"], hash_token(token), "password login"),
        )
        conn.commit()

    data = dict(row)
    append_audit(
        "auth.login",
        {
            "performed_by": data["username"],
            "acting_as": data["username"],
            "source": "api",
        },
    )
    return LoginResult(token=token, agent=agent_from_user_row(data))


@router.get("/me", response_model=Agent)
def get_current_agent(actor: Actor = Depends(require_actor)) -> Agent:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT username, display_name, role, persona_id, avatar_color, avatar_emoji
            FROM users
            WHERE id = ? AND status = 'active'
            """,
            (actor.id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return Agent(**dict(row))


@router.patch("/me/profile", response_model=Agent)
def update_profile(payload: ProfileUpdate, actor: Actor = Depends(require_actor)) -> Agent:
    updates = []
    params: list[object] = []
    if payload.display_name is not None:
        updates.append("display_name = ?")
        params.append(payload.display_name.strip())
    if payload.avatar_color is not None:
        updates.append("avatar_color = ?")
        params.append(payload.avatar_color.strip())
    if payload.avatar_emoji is not None:
        updates.append("avatar_emoji = ?")
        params.append(payload.avatar_emoji.strip() or None)
    if updates:
        updates.append("updated_at = ?")
        params.append(datetime.now(UTC).isoformat())
        params.append(actor.id)
        with get_connection() as conn:
            conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ? AND status = 'active'", tuple(params))
            conn.commit()
    return get_current_agent(actor)


@router.post("/uploads/images", response_model=ImageUploadResult, status_code=status.HTTP_201_CREATED)
def upload_image(payload: ImageUploadRequest, actor: Actor = Depends(require_actor)) -> ImageUploadResult:
    content_type = payload.content_type.split(";", 1)[0].strip().lower()
    extension = ALLOWED_IMAGE_TYPES.get(content_type)
    if extension is None:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, GIF, and WebP images are allowed")

    encoded = payload.data_base64.strip()
    if encoded.startswith("data:") and "," in encoded:
        encoded = encoded.split(",", 1)[1]
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Invalid base64 image data") from None

    if not data:
        raise HTTPException(status_code=400, detail="Image is empty")
    if len(data) > MAX_IMAGE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image is larger than 8 MB")
    if not image_type_matches(content_type, data):
        raise HTTPException(status_code=400, detail="Image bytes do not match declared content type")

    target_dir = upload_root() / "forum-images"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    filename = f"{stamp}-{actor.username}-{secrets.token_hex(6)}{extension}"
    path = target_dir / filename
    path.write_bytes(data)

    url = f"/uploads/forum-images/{filename}"
    alt = safe_upload_alt(payload.filename)
    append_audit(
        "upload.image",
        {
            "performed_by": actor.username,
            "acting_as": actor.username,
            "source": "api",
            "filename": filename,
            "size_bytes": len(data),
            "content_type": content_type,
        },
    )
    return ImageUploadResult(url=url, markdown=f"![{alt}]({url})", filename=filename, size_bytes=len(data))


def invite_expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed < datetime.now(UTC)


@router.post("/register", response_model=RegisterResult, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest) -> RegisterResult:
    username = normalized_username(payload.username)
    if username != payload.username.strip().lower():
        raise HTTPException(status_code=400, detail="Username may contain lowercase letters, numbers, and underscores only")
    code_hash = hash_token(payload.invite_code)
    with get_connection() as conn:
        invite = conn.execute(
            """
            SELECT * FROM invites
            WHERE code_hash = ? AND revoked_at IS NULL
            """,
            (code_hash,),
        ).fetchone()
        if invite is None or invite_expired(invite["expires_at"]):
            raise HTTPException(status_code=400, detail="Invalid invite code")
        if int(invite["used_count"]) >= int(invite["max_uses"]):
            raise HTTPException(status_code=400, detail="Invite code has already been used")
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing is not None:
            raise HTTPException(status_code=409, detail="Username already exists")
        role = invite["default_role"] if invite["default_role"] in {"guest", "member"} else "guest"
        user_status = "pending" if int(invite["requires_approval"]) else "active"
        conn.execute(
            """
            INSERT INTO users (
              username, display_name, role, persona_id, avatar_color, avatar_emoji,
              status, password_hash, password_changed_at
            )
            VALUES (?, ?, ?, ?, '#94a3b8', '✉️', ?, ?, ?)
            """,
            (
                username,
                payload.display_name.strip(),
                role,
                username,
                user_status,
                hash_password(payload.password),
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.execute("UPDATE invites SET used_count = used_count + 1 WHERE id = ?", (invite["id"],))
        conn.commit()
    return RegisterResult(username=username, status=user_status)


@router.post("/admin/invites", response_model=InviteCreateResult, status_code=status.HTTP_201_CREATED)
def create_invite(payload: InviteCreate, actor: Actor = Depends(require_actor)) -> InviteCreateResult:
    if not actor.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required")
    code = payload.code or secrets.token_urlsafe(18)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO invites (
              code_hash, created_by_user_id, default_role, allowed_boards, digest_scope,
              requires_approval, max_uses, expires_at, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hash_token(code),
                actor.id,
                payload.default_role,
                json.dumps(payload.allowed_boards, ensure_ascii=False),
                payload.digest_scope,
                1 if payload.requires_approval else 0,
                payload.max_uses,
                payload.expires_at,
                payload.notes,
            ),
        )
        conn.commit()
    return InviteCreateResult(code=code, status="created")


def require_moderator(actor: Actor) -> None:
    if not actor.is_moderator:
        raise HTTPException(status_code=403, detail="Moderator role required")


def review_lane_roots() -> list[tuple[int, Path, Path]]:
    roots = []
    for index, review_root in enumerate(settings.review_roots):
        resolved_review_root = review_root.resolve()
        for relative in REVIEW_LANES.values():
            roots.append((index, resolved_review_root, (resolved_review_root / relative).resolve()))
    return roots


def review_roots() -> list[Path]:
    return [lane_root for _, _, lane_root in review_lane_roots()]


def encode_submission_id(path: Path) -> str:
    resolved = path.resolve()
    for index, review_root in enumerate(settings.review_roots):
        root = review_root.resolve()
        if resolved.is_relative_to(root):
            relative = resolved.relative_to(root).as_posix()
            payload = f"{index}:{relative}"
            return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    raise HTTPException(status_code=403, detail="Review path not allowed")


def decode_submission_path(submission_id: str) -> Path:
    try:
        padding = "=" * (-len(submission_id) % 4)
        relative = base64.urlsafe_b64decode((submission_id + padding).encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Submission not found") from exc

    root = settings.review_root.resolve()
    if re.match(r"^\d+:", relative):
        index_text, relative = relative.split(":", 1)
        try:
            root = settings.review_roots[int(index_text)].resolve()
        except (IndexError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Submission not found") from exc

    path = (root / relative).resolve()
    if path.suffix.lower() != ".md" or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Submission not found")
    if not any(path.is_relative_to(root) for root in review_roots()):
        raise HTTPException(status_code=403, detail="Review path not allowed")
    return path


def parse_review_markdown(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text.strip()

    lines = text.splitlines()
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        return {}, text.strip()

    data: dict[str, object] = {}
    current_key: str | None = None
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_key:
            value = data.setdefault(current_key, [])
            if isinstance(value, list):
                value.append(stripped[2:].strip())
            continue
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        current_key = key.strip()
        value = raw_value.strip()
        data[current_key] = [] if value == "" else value.strip("\"'")
    return data, "\n".join(lines[end + 1 :]).strip()


def first_markdown_heading(body: str) -> str:
    for line in body.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return ""


def strip_forum_marker(title: str) -> str:
    clean = re.sub(r"^\[forum[:\s]+[a-z_]+\]\s*", "", title.strip(), flags=re.IGNORECASE)
    clean = re.sub(
        r"^\[(?:forum-)?reply(?::#?\d+)?(?:\s+post:#?\d+)?\]\s*",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"^forum:?[a-z_]+\s*[-:：]?\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"^(论坛投稿|投稿到)\s+[a-z_]+\s*[-:：]?\s*", "", clean, flags=re.IGNORECASE)
    return clean.strip() or title.strip()


def review_title(frontmatter: dict[str, object], body: str, path: Path) -> str:
    for key in ("email_subject", "title"):
        value = str(frontmatter.get(key) or "").strip()
        if value:
            return strip_forum_marker(value)[:160]
    heading = first_markdown_heading(body)
    if heading:
        return strip_forum_marker(heading)[:160]
    value = str(frontmatter.get("source_doc_title") or "").strip()
    if value:
        return strip_forum_marker(value)[:160]
    return path.stem[:160]


def review_board(frontmatter: dict[str, object]) -> str:
    board = str(frontmatter.get("forum_board") or "").strip()
    return board or "guest_questions"


def review_int(frontmatter: dict[str, object], *keys: str) -> int | None:
    for key in keys:
        value = str(frontmatter.get(key) or "").strip()
        if not value:
            continue
        match = re.search(r"#?(\d+)", value)
        if match:
            return int(match.group(1))
    return None


def review_import_mode(frontmatter: dict[str, object]) -> str:
    mode = str(frontmatter.get("forum_import_mode") or "").strip().lower()
    if mode == "reply":
        return "reply"
    if review_int(frontmatter, "forum_reply_thread_id", "reply_thread_id", "thread_id") is not None:
        return "reply"
    return "thread"


def review_reply_thread_id(frontmatter: dict[str, object]) -> int | None:
    return review_int(frontmatter, "forum_reply_thread_id", "reply_thread_id")


def review_reply_parent_post_id(frontmatter: dict[str, object]) -> int | None:
    return review_int(frontmatter, "forum_reply_parent_post_id", "reply_parent_post_id", "parent_post_id")


def review_excerpt(body: str) -> str:
    return plain_excerpt(body.replace("#", " ").strip())


def review_source(path: Path, frontmatter: dict[str, object]) -> str:
    source = str(frontmatter.get("email_source") or frontmatter.get("source") or "").strip()
    if source:
        return source
    relative = path.as_posix()
    if "/email/" in relative:
        return "email"
    if "/docs/" in relative:
        return "docs"
    return "unknown"


def normalized_username(value: str, fallback: str = "guest") -> str:
    clean = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower())
    clean = re.sub(r"_+", "_", clean).strip("_")
    if not clean:
        clean = fallback
    if not clean[0].isalpha():
        clean = f"guest_{clean}"
    return clean[:80]


def body_author_hint(body: str) -> str | None:
    for line in body.splitlines()[:40]:
        match = re.match(r"^\s*(Author\s*/\s*display name|Author|From-Agent)\s*:\s*(.+?)\s*$", line, re.IGNORECASE)
        if not match:
            continue
        value = match.group(2).strip()
        if value:
            return value.split("/", 1)[0].strip()
    return None


def display_name_from_identity(username: str, frontmatter: dict[str, object] | None = None) -> str:
    frontmatter = frontmatter or {}
    for key in ("display_name", "from_display_name", "agent_display_name"):
        value = str(frontmatter.get(key) or "").strip()
        if value:
            return value[:120]
    return username.replace("_", " ").title()[:120]


def user_by_username(conn, username: str, statuses: tuple[str, ...] = ("active", "attribution_only")):
    placeholders = ",".join("?" for _ in statuses)
    return conn.execute(
        f"SELECT * FROM users WHERE username = ? AND status IN ({placeholders})",
        (username, *statuses),
    ).fetchone()


def suggested_author_username(frontmatter: dict[str, object], body: str = "") -> str | None:
    agent = normalized_username(str(frontmatter.get("agent") or "").strip())
    if agent and agent not in {"guest", "unknown", "unknown_guest"}:
        return agent
    hinted_author = body_author_hint(body)
    if hinted_author:
        return normalized_username(hinted_author, "guest")
    if agent == "guest":
        return "guest"
    sender = str(frontmatter.get("email_from") or frontmatter.get("from") or "").strip().lower()
    if sender and "@" in sender and sender != "forum@example.invalid":
        return normalized_username(sender.split("@", 1)[0], "guest")
    return None


def ensure_attribution_user(conn, username: str, frontmatter: dict[str, object]) -> int:
    username = normalized_username(username)
    existing = user_by_username(conn, username)
    if existing is not None:
        return int(existing["id"])

    display_name = display_name_from_identity(username, frontmatter)
    conn.execute(
        """
        INSERT INTO users (username, display_name, role, persona_id, avatar_color, avatar_emoji, status)
        VALUES (?, ?, 'guest', ?, '#94a3b8', '✉️', 'attribution_only')
        """,
        (username, display_name, username),
    )
    return int(conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"])


def resolve_review_author_id(conn, actor: Actor, frontmatter: dict[str, object], requested_username: str | None) -> int:
    raw_username = (requested_username or suggested_author_username(frontmatter) or "").strip()
    if not raw_username:
        return actor.id
    username = normalized_username(raw_username)

    existing = user_by_username(conn, username)
    if existing is not None:
        if existing["status"] == "active":
            if not actor.is_admin:
                return actor.id
            return int(existing["id"])
        return int(existing["id"])

    return ensure_attribution_user(conn, username, frontmatter)


def resolve_moderator_author_id(conn, username: str) -> int:
    normalized = normalized_username(username)
    row = user_by_username(conn, normalized)
    if row is None:
        raise HTTPException(status_code=404, detail="Author user not found")
    return int(row["id"])


def validate_parent_post(conn, thread_id: int, parent_post_id: int | None) -> str | None:
    if parent_post_id is None:
        return None
    parent = conn.execute(
        """
        SELECT id, body_markdown
        FROM posts
        WHERE id = ? AND thread_id = ? AND status = 'visible'
        """,
        (parent_post_id, thread_id),
    ).fetchone()
    if parent is None:
        raise HTTPException(status_code=400, detail="Parent post is not visible in this thread")
    return plain_excerpt(parent["body_markdown"], limit=180)


def review_source_message_id(frontmatter: dict[str, object]) -> str | None:
    for key in ("email_message_id", "email_thread_id", "source_doc_id", "id"):
        value = str(frontmatter.get(key) or "").strip()
        if value:
            return value[:200]
    return None


def review_relative_path(path: Path) -> str:
    resolved = path.resolve()
    for review_root in settings.review_roots:
        root = review_root.resolve()
        if resolved.is_relative_to(root):
            return resolved.relative_to(root).as_posix()
    return resolved.as_posix()


def review_identity_keys(frontmatter: dict[str, object]) -> set[str]:
    keys = set()
    for key in ("id", "email_message_id", "source_doc_id"):
        value = str(frontmatter.get(key) or "").strip()
        if value:
            keys.add(f"{key}:{value}")
    return keys


def imported_review_identity_keys() -> set[str]:
    keys = set()
    for _, memory_root, lane_root in review_lane_roots():
        imported_dir = memory_root / lane_root.relative_to(memory_root).parent / "imported"
        if not imported_dir.exists():
            continue
        for path in imported_dir.glob("*.md"):
            frontmatter, _ = parse_review_markdown(path)
            keys.update(review_identity_keys(frontmatter))
    return keys


def review_summary(
    path: Path,
    frontmatter: dict[str, object] | None = None,
    body: str | None = None,
) -> ReviewSubmissionSummary:
    if frontmatter is None or body is None:
        frontmatter, body = parse_review_markdown(path)
    suggested_username = suggested_author_username(frontmatter, body)
    return ReviewSubmissionSummary(
        id=encode_submission_id(path),
        source=review_source(path, frontmatter),
        relative_path=review_relative_path(path),
        title=review_title(frontmatter, body, path),
        board_slug=review_board(frontmatter),
        import_mode=review_import_mode(frontmatter),
        reply_thread_id=review_reply_thread_id(frontmatter),
        reply_parent_post_id=review_reply_parent_post_id(frontmatter),
        agent=str(frontmatter.get("agent") or "unknown"),
        suggested_author_username=suggested_username,
        suggested_author_display_name=display_name_from_identity(suggested_username, frontmatter)
        if suggested_username
        else None,
        created_at=str(frontmatter.get("created_at") or "") or None,
        excerpt=review_excerpt(body),
    )


def unique_import_path(source_path: Path) -> Path:
    imported_dir = source_path.parent.parent / "imported"
    imported_dir.mkdir(parents=True, exist_ok=True)
    desired = imported_dir / source_path.name
    if not desired.exists():
        return desired
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return desired.with_name(f"{desired.stem}-{stamp}{desired.suffix}")


def unique_rejected_path(source_path: Path) -> Path:
    rejected_dir = source_path.parent.parent / "rejected"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    desired = rejected_dir / source_path.name
    if not desired.exists():
        return desired
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return desired.with_name(f"{desired.stem}-{stamp}{desired.suffix}")


def import_body(body: str, source_path: Path) -> str:
    relative = review_relative_path(source_path)
    return body.rstrip() + "\n\n---\n\n_imported from review inbox: `" + relative + "`_\n"


def active_username_exists(username: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ? AND status = 'active'",
            (username,),
        ).fetchone()
    return row is not None


def review_acting_as(actor: Actor, requested_author: str | None) -> str | None:
    if not actor.is_admin or not requested_author:
        return None
    return requested_author if active_username_exists(requested_author) else None


@router.get("/review/authors", response_model=list[ReviewAuthor])
def list_review_authors(actor: Actor = Depends(require_actor)) -> list[ReviewAuthor]:
    require_moderator(actor)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT username, display_name, role, status
            FROM users
            WHERE status IN ('active', 'attribution_only')
            ORDER BY status ASC, display_name ASC
            """
        ).fetchall()
    authors = []
    for row in rows:
        status_value = row["status"]
        authors.append(
            ReviewAuthor(
                username=row["username"],
                display_name=row["display_name"],
                role=row["role"],
                status=status_value,
                source="attribution" if status_value == "attribution_only" else "active",
            )
        )
    return authors


@router.get("/review/submissions", response_model=list[ReviewSubmissionSummary])
def list_review_submissions(actor: Actor = Depends(require_actor)) -> list[ReviewSubmissionSummary]:
    require_moderator(actor)
    submissions: list[ReviewSubmissionSummary] = []
    seen_keys = imported_review_identity_keys()
    candidates: list[Path] = []
    for _, _, lane_root in review_lane_roots():
        if not lane_root.exists():
            continue
        candidates.extend(lane_root.glob("*.md"))

    for path in sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True):
        frontmatter, body = parse_review_markdown(path)
        keys = review_identity_keys(frontmatter)
        if keys and keys & seen_keys:
            continue
        seen_keys.update(keys)
        submissions.append(review_summary(path, frontmatter, body))
    return submissions


@router.get("/review/submissions/{submission_id}", response_model=ReviewSubmissionDetail)
def get_review_submission(submission_id: str, actor: Actor = Depends(require_actor)) -> ReviewSubmissionDetail:
    require_moderator(actor)
    path = decode_submission_path(submission_id)
    frontmatter, body = parse_review_markdown(path)
    return ReviewSubmissionDetail(**review_summary(path).model_dump(), body_markdown=body, frontmatter=frontmatter)


@router.post("/review/submissions/{submission_id}/import", response_model=ReviewImportResult)
def import_review_submission(
    submission_id: str,
    payload: ReviewImportRequest,
    actor: Actor = Depends(require_actor),
) -> ReviewImportResult:
    require_moderator(actor)
    path = decode_submission_path(submission_id)
    frontmatter, body = parse_review_markdown(path)
    title = (payload.title or review_title(frontmatter, body, path)).strip()
    board_slug = (payload.board_slug or review_board(frontmatter)).strip()
    if not title:
        raise HTTPException(status_code=400, detail="Submission title is empty")
    if not body:
        raise HTTPException(status_code=400, detail="Submission body is empty")

    import_mode = payload.import_mode or review_import_mode(frontmatter)
    reply_thread_id = payload.reply_thread_id or review_reply_thread_id(frontmatter)
    reply_parent_post_id = payload.reply_parent_post_id
    if reply_parent_post_id is None:
        reply_parent_post_id = review_reply_parent_post_id(frontmatter)
    imported_body = import_body(body, path)
    body_html = render_markdown(imported_body)
    now = datetime.now(UTC).isoformat()
    source = review_source(path, frontmatter)
    source_message_id = review_source_message_id(frontmatter)
    source_submission_id = str(frontmatter.get("id") or review_relative_path(path))[:300]

    with get_connection() as conn:
        board = None
        if import_mode == "thread":
            board = conn.execute("SELECT id FROM boards WHERE slug = ?", (board_slug,)).fetchone()
            if board is None:
                raise HTTPException(status_code=404, detail="Board not found")
        requested_author = payload.attribution_username or payload.acting_as
        acting_as = review_acting_as(actor, payload.acting_as)
        if payload.attribution_username:
            acting_user_id = resolve_review_author_id(conn, actor, frontmatter, payload.attribution_username)
        elif acting_as:
            acting_user_id = resolve_acting_user_id(actor, acting_as)
        else:
            acting_user_id = resolve_review_author_id(conn, actor, frontmatter, None)

        post_id: int | None = None
        if import_mode == "reply":
            if reply_thread_id is None:
                raise HTTPException(status_code=400, detail="Reply import requires reply_thread_id")
            thread = conn.execute(
                "SELECT id FROM threads WHERE id = ? AND status = 'open'",
                (reply_thread_id,),
            ).fetchone()
            if thread is None:
                raise HTTPException(status_code=404, detail="Reply target thread not found")
            quoted_excerpt = validate_parent_post(conn, reply_thread_id, reply_parent_post_id)
            cur = conn.execute(
                """
                INSERT INTO posts (
                  thread_id, parent_post_id, author_user_id, created_by_user_id,
                  quoted_excerpt, body_markdown, body_html, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reply_thread_id,
                    reply_parent_post_id,
                    acting_user_id,
                    actor.id,
                    quoted_excerpt,
                    imported_body,
                    body_html,
                    now,
                    now,
                ),
            )
            post_id = int(cur.lastrowid)
            conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, reply_thread_id))
            thread_id = reply_thread_id
        else:
            cur = conn.execute(
                """
                INSERT INTO threads (
                  board_id, title, author_user_id, created_by_user_id, submitter_identity_id,
                  source_channel, source_message_id, source_submission_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    board["id"],  # type: ignore[index]
                    title[:160],
                    acting_user_id,
                    actor.id,
                    acting_user_id,
                    source,
                    source_message_id,
                    source_submission_id,
                    now,
                    now,
                ),
            )
            thread_id = int(cur.lastrowid)
            cur = conn.execute(
                """
                INSERT INTO posts (thread_id, author_user_id, created_by_user_id, body_markdown, body_html, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (thread_id, acting_user_id, actor.id, imported_body, body_html, now, now),
            )
            post_id = int(cur.lastrowid)
        conn.commit()

    imported_path = unique_import_path(path)
    shutil.move(str(path), imported_path)
    append_audit(
        "review.import",
        {
            "performed_by": actor.username,
            "acting_as": requested_author or acting_as or actor.username,
            "source": "api",
            "import_mode": import_mode,
            "thread_id": thread_id,
            "post_id": post_id,
            "reply_parent_post_id": reply_parent_post_id,
            "board_slug": board_slug,
            "submission_path": str(path),
            "imported_path": str(imported_path),
        },
    )
    return ReviewImportResult(thread_id=thread_id, post_id=post_id, status="imported", imported_path=str(imported_path))


@router.delete("/review/submissions/{submission_id}", response_model=ReviewDeleteResult)
def reject_review_submission(
    submission_id: str,
    actor: Actor = Depends(require_actor),
) -> ReviewDeleteResult:
    require_moderator(actor)
    path = decode_submission_path(submission_id)
    rejected_path = unique_rejected_path(path)
    shutil.move(str(path), rejected_path)
    append_audit(
        "review.reject",
        {
            "performed_by": actor.username,
            "acting_as": actor.username,
            "source": "api",
            "submission_path": str(path),
            "rejected_path": str(rejected_path),
        },
    )
    return ReviewDeleteResult(submission_id=submission_id, status="rejected", rejected_path=str(rejected_path))


@router.get("/threads", response_model=list[ThreadSummary])
def list_threads(
    board: str | None = Query(default=None),
    sort: str = Query(default="latest", pattern="^(latest|hot)$"),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[ThreadSummary]:
    where = ["threads.status != 'deleted'"]
    params: list[object] = []
    if board:
        where.append("boards.slug = ?")
        params.append(board)
    order_by = "threads.is_pinned DESC, threads.updated_at DESC"
    if sort == "hot":
        order_by = "threads.is_pinned DESC, reply_count DESC, threads.updated_at DESC"
    sql = (
        thread_query()
        + " AND "
        + " AND ".join(where)
        + f"""
        GROUP BY threads.id
        ORDER BY {order_by}
        LIMIT ?
        """
    )
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [thread_summary_from_row(dict(row)) for row in rows]


@router.post("/threads", response_model=ThreadDetail, status_code=status.HTTP_201_CREATED)
def create_thread(payload: ThreadCreate, actor: Actor = Depends(require_actor)) -> ThreadDetail:
    acting_user_id = resolve_acting_user_id(actor, payload.acting_as)
    body_html = render_markdown(payload.body_markdown)
    now = datetime.now(UTC).isoformat()

    with get_connection() as conn:
        board = conn.execute("SELECT id FROM boards WHERE slug = ?", (payload.board_slug,)).fetchone()
        if board is None:
            raise HTTPException(status_code=404, detail="Board not found")
        cur = conn.execute(
            """
            INSERT INTO threads (board_id, title, author_user_id, created_by_user_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (board["id"], payload.title, acting_user_id, actor.id, now, now),
        )
        thread_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO posts (thread_id, author_user_id, created_by_user_id, body_markdown, body_html, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (thread_id, acting_user_id, actor.id, payload.body_markdown, body_html, now, now),
        )
        conn.commit()

    append_audit(
        "thread.create",
        {
            "performed_by": actor.username,
            "acting_as": payload.acting_as or actor.username,
            "source": "api",
            "thread_id": thread_id,
            "board_slug": payload.board_slug,
        },
    )
    return get_thread(thread_id)


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
def get_thread(thread_id: int) -> ThreadDetail:
    with get_connection() as conn:
        row = conn.execute(
            thread_query()
            + """
            AND threads.id = ? AND threads.status != 'deleted'
            GROUP BY threads.id
            """,
            (thread_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        post_rows = conn.execute(
            """
            SELECT
              posts.*,
              author.username AS author_username,
              author.display_name AS author_display_name,
              author.role AS author_role,
              author.persona_id AS author_persona_id,
              author.avatar_color AS author_avatar_color,
              author.avatar_emoji AS author_avatar_emoji,
              creator.username AS creator_username,
              creator.display_name AS creator_display_name,
              creator.role AS creator_role,
              creator.persona_id AS creator_persona_id,
              creator.avatar_color AS creator_avatar_color,
              creator.avatar_emoji AS creator_avatar_emoji
            FROM posts
            JOIN users author ON author.id = posts.author_user_id
            JOIN users creator ON creator.id = posts.created_by_user_id
            WHERE posts.thread_id = ? AND posts.status = 'visible'
            ORDER BY posts.created_at ASC, posts.id ASC
            """,
            (thread_id,),
        ).fetchall()

    summary = thread_summary_from_row(dict(row))
    posts = []
    for post_row in post_rows:
        data = dict(post_row)
        posts.append(
            {
                "id": data["id"],
                "thread_id": data["thread_id"],
                "parent_post_id": data["parent_post_id"],
                "quoted_excerpt": data["quoted_excerpt"],
                "author": agent_from_prefix(data, "author"),
                "created_by": agent_from_prefix(data, "creator"),
                "body_markdown": data["body_markdown"],
                "body_html": data["body_html"],
                "created_at": data["created_at"],
            }
        )
    return ThreadDetail(**summary.model_dump(), posts=posts)


@router.patch("/threads/{thread_id}", response_model=ThreadDetail)
def update_thread(
    thread_id: int,
    payload: ThreadUpdate,
    actor: Actor = Depends(require_actor),
) -> ThreadDetail:
    require_moderator(actor)
    now = datetime.now(UTC).isoformat()
    changes: dict[str, object] = {}
    with get_connection() as conn:
        thread = conn.execute(
            """
            SELECT id, title, board_id, author_user_id
            FROM threads
            WHERE id = ? AND status != 'deleted'
            """,
            (thread_id,),
        ).fetchone()
        if thread is None:
            raise HTTPException(status_code=404, detail="Thread not found")

        updates = ["updated_at = ?", "edited_at = ?", "edited_by_user_id = ?"]
        params: list[object] = [now, now, actor.id]

        if payload.title is not None:
            title = payload.title.strip()
            if not title:
                raise HTTPException(status_code=400, detail="Thread title is empty")
            updates.append("title = ?")
            params.append(title)
            changes["title"] = title

        if payload.board_slug is not None:
            board = conn.execute("SELECT id FROM boards WHERE slug = ?", (payload.board_slug.strip(),)).fetchone()
            if board is None:
                raise HTTPException(status_code=404, detail="Board not found")
            updates.append("board_id = ?")
            params.append(int(board["id"]))
            changes["board_slug"] = payload.board_slug.strip()

        if payload.author_username is not None:
            author_id = resolve_moderator_author_id(conn, payload.author_username)
            updates.append("author_user_id = ?")
            params.append(author_id)
            changes["author_username"] = normalized_username(payload.author_username)
            first_post = conn.execute(
                """
                SELECT id FROM posts
                WHERE thread_id = ? AND status = 'visible'
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                (thread_id,),
            ).fetchone()
            if first_post is not None:
                conn.execute(
                    """
                    UPDATE posts
                    SET author_user_id = ?, updated_at = ?, edited_at = ?, edited_by_user_id = ?
                    WHERE id = ?
                    """,
                    (author_id, now, now, actor.id, first_post["id"]),
                )

        if len(updates) == 3:
            raise HTTPException(status_code=400, detail="No thread changes provided")

        params.append(thread_id)
        conn.execute(f"UPDATE threads SET {', '.join(updates)} WHERE id = ?", tuple(params))
        conn.commit()

    append_audit(
        "thread.update",
        {
            "performed_by": actor.username,
            "acting_as": actor.username,
            "source": "api",
            "thread_id": thread_id,
            "changes": changes,
        },
    )
    return get_thread(thread_id)


@router.delete("/threads/{thread_id}", response_model=DeleteResult)
def delete_thread(thread_id: int, actor: Actor = Depends(require_actor)) -> DeleteResult:
    require_moderator(actor)
    now = datetime.now(UTC).isoformat()
    with get_connection() as conn:
        thread = conn.execute(
            "SELECT id FROM threads WHERE id = ? AND status != 'deleted'",
            (thread_id,),
        ).fetchone()
        if thread is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        conn.execute(
            "UPDATE threads SET status = 'deleted', updated_at = ? WHERE id = ?",
            (now, thread_id),
        )
        conn.execute(
            "UPDATE posts SET status = 'deleted', updated_at = ? WHERE thread_id = ? AND status != 'deleted'",
            (now, thread_id),
        )
        conn.commit()

    append_audit(
        "thread.delete",
        {
            "performed_by": actor.username,
            "acting_as": actor.username,
            "source": "api",
            "thread_id": thread_id,
        },
    )
    return DeleteResult(id=thread_id, status="deleted")


@router.delete("/posts/{post_id}", response_model=DeleteResult)
def delete_post(post_id: int, actor: Actor = Depends(require_actor)) -> DeleteResult:
    require_moderator(actor)
    now = datetime.now(UTC).isoformat()
    with get_connection() as conn:
        post = conn.execute(
            """
            SELECT posts.id, posts.thread_id
            FROM posts
            JOIN threads ON threads.id = posts.thread_id
            WHERE posts.id = ? AND posts.status = 'visible' AND threads.status != 'deleted'
            """,
            (post_id,),
        ).fetchone()
        if post is None:
            raise HTTPException(status_code=404, detail="Post not found")
        visible_count = conn.execute(
            "SELECT COUNT(*) AS count FROM posts WHERE thread_id = ? AND status = 'visible'",
            (post["thread_id"],),
        ).fetchone()["count"]
        if int(visible_count) <= 1:
            raise HTTPException(status_code=400, detail="Delete the thread instead of its last visible post")
        conn.execute(
            "UPDATE posts SET status = 'deleted', updated_at = ? WHERE id = ?",
            (now, post_id),
        )
        conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, post["thread_id"]))
        conn.commit()

    append_audit(
        "post.delete",
        {
            "performed_by": actor.username,
            "acting_as": actor.username,
            "source": "api",
            "thread_id": int(post["thread_id"]),
            "post_id": post_id,
        },
    )
    return DeleteResult(id=post_id, status="deleted")


@router.patch("/posts/{post_id}", response_model=ThreadDetail)
def update_post(
    post_id: int,
    payload: PostUpdate,
    actor: Actor = Depends(require_actor),
) -> ThreadDetail:
    require_moderator(actor)
    now = datetime.now(UTC).isoformat()
    changes: dict[str, object] = {}
    with get_connection() as conn:
        post = conn.execute(
            """
            SELECT posts.id, posts.thread_id, posts.body_markdown
            FROM posts
            JOIN threads ON threads.id = posts.thread_id
            WHERE posts.id = ? AND posts.status = 'visible' AND threads.status != 'deleted'
            """,
            (post_id,),
        ).fetchone()
        if post is None:
            raise HTTPException(status_code=404, detail="Post not found")

        updates = ["updated_at = ?", "edited_at = ?", "edited_by_user_id = ?"]
        params: list[object] = [now, now, actor.id]

        if payload.body_markdown is not None:
            body_markdown = payload.body_markdown.strip()
            if not body_markdown:
                raise HTTPException(status_code=400, detail="Post body is empty")
            updates.extend(["body_markdown = ?", "body_html = ?"])
            params.extend([body_markdown, render_markdown(body_markdown)])
            changes["body_markdown"] = "changed"
            conn.execute(
                """
                UPDATE posts
                SET quoted_excerpt = ?, updated_at = ?
                WHERE parent_post_id = ? AND status = 'visible'
                """,
                (plain_excerpt(body_markdown, limit=180), now, post_id),
            )

        if payload.author_username is not None:
            author_id = resolve_moderator_author_id(conn, payload.author_username)
            updates.append("author_user_id = ?")
            params.append(author_id)
            changes["author_username"] = normalized_username(payload.author_username)

        if len(updates) == 3:
            raise HTTPException(status_code=400, detail="No post changes provided")

        params.append(post_id)
        conn.execute(f"UPDATE posts SET {', '.join(updates)} WHERE id = ?", tuple(params))

        first_post = conn.execute(
            """
            SELECT id FROM posts
            WHERE thread_id = ? AND status = 'visible'
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """,
            (post["thread_id"],),
        ).fetchone()
        if first_post is not None and int(first_post["id"]) == post_id and payload.author_username is not None:
            conn.execute(
                "UPDATE threads SET author_user_id = ?, updated_at = ?, edited_at = ?, edited_by_user_id = ? WHERE id = ?",
                (author_id, now, now, actor.id, post["thread_id"]),
            )
        else:
            conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, post["thread_id"]))
        conn.commit()

    append_audit(
        "post.update",
        {
            "performed_by": actor.username,
            "acting_as": actor.username,
            "source": "api",
            "thread_id": int(post["thread_id"]),
            "post_id": post_id,
            "changes": changes,
        },
    )
    return get_thread(int(post["thread_id"]))


@router.post("/threads/{thread_id}/posts", response_model=ThreadDetail, status_code=status.HTTP_201_CREATED)
def reply_to_thread(
    thread_id: int,
    payload: ReplyCreate,
    actor: Actor = Depends(require_actor),
) -> ThreadDetail:
    acting_user_id = resolve_acting_user_id(actor, payload.acting_as)
    body_html = render_markdown(payload.body_markdown)
    now = datetime.now(UTC).isoformat()

    with get_connection() as conn:
        thread = conn.execute("SELECT id FROM threads WHERE id = ? AND status = 'open'", (thread_id,)).fetchone()
        if thread is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        quoted_excerpt = validate_parent_post(conn, thread_id, payload.parent_post_id)
        conn.execute(
            """
            INSERT INTO posts (
              thread_id, parent_post_id, author_user_id, created_by_user_id,
              quoted_excerpt, body_markdown, body_html, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                payload.parent_post_id,
                acting_user_id,
                actor.id,
                quoted_excerpt,
                payload.body_markdown,
                body_html,
                now,
                now,
            ),
        )
        conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id))
        conn.commit()

    append_audit(
        "post.create",
        {
            "performed_by": actor.username,
            "acting_as": payload.acting_as or actor.username,
            "source": "api",
            "thread_id": thread_id,
        },
    )
    return get_thread(thread_id)


@router.post("/export/thread/{thread_id}", response_model=ExportResult)
def export_thread(thread_id: int, actor: Actor = Depends(require_actor)) -> ExportResult:
    if not actor.is_moderator:
        raise HTTPException(status_code=403, detail="Export requires moderator role")
    detail = get_thread(thread_id)
    output_dir = settings.review_root / "exports" / "needs_review"
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in detail.title).strip("-")[:60] or "thread"
    output = output_dir / f"{datetime.now(UTC).strftime('%Y-%m-%d-%H%M')}-forum-export-{thread_id}-{slug}.md"
    body = render_export_markdown(detail, actor.username)
    if output.exists():
        output = output.with_name(output.stem + "-" + datetime.now(UTC).strftime("%S") + output.suffix)
    output.write_text(body, encoding="utf-8")
    append_audit(
        "thread.export.request",
        {
            "performed_by": actor.username,
            "acting_as": actor.username,
            "source": "api",
            "thread_id": thread_id,
            "output_path": str(output),
        },
    )
    return ExportResult(thread_id=thread_id, output_path=str(output), status="needs_review")


def render_export_markdown(detail: ThreadDetail, requested_by: str) -> str:
    created = datetime.now(UTC).isoformat()
    lines = [
        "---",
        f"id: forum-export-{detail.id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        f"created_at: {created}",
        "source: agent-forum-kit",
        f"exported_by: {requested_by}",
        "track: project",
        "memory_scope: project",
        "project: agent-forum-kit",
        "type: forum-export",
        "status: inbox",
        "priority: 2",
        "sensitivity: private",
        "publish: false",
        "visible_to:",
        "  - project:agent-forum-kit",
        "allowed_ops:",
        "  - read",
        "  - append",
        "tags:",
        "  - forum-export",
        f"forum_thread_id: {detail.id}",
        f"forum_board: {detail.board_slug}",
        f"requested_by: {requested_by}",
        "---",
        "",
        f"# {detail.title}",
        "",
        f"- Thread ID: {detail.id}",
        f"- Board: {detail.board_slug}",
        f"- Export requested by: {requested_by}",
        "",
    ]
    for post in detail.posts:
        lines.extend(
            [
                f"## {post.author.display_name} / {post.author.username}",
                "",
                f"_Created at: {post.created_at}; performed by: {post.created_by.username}_",
                "",
                post.body_markdown,
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
