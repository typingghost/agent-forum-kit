from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.auth import Actor
from app.services.markdown import plain_excerpt, render_markdown


MARKDOWN_SUFFIXES = {".md", ".markdown"}
MAX_SEARCH_BYTES = 1_200_000
MAX_READ_BYTES = 2_000_000

SCOPE_PREFIXES: dict[str, tuple[str, ...]] = {
    "all": (),
    "inbox": ("inbox",),
    "projects": ("projects",),
    "notes": ("notes",),
    "handoffs": ("handoffs",),
    "reports": ("reports",),
    "forum": ("forum",),
    "archive": ("archive",),
}

SCOPE_LABELS = {
    "all": "All",
    "inbox": "Inbox",
    "projects": "Projects",
    "notes": "Notes",
    "handoffs": "Handoffs",
    "reports": "Reports",
    "forum": "Forum Archive",
    "archive": "Archive",
}

SEARCH_SORTS = {"relevance", "newest", "oldest"}

HIDDEN_DIRS = {".git", ".obsidian", "__pycache__", ".pytest_cache"}
DENIED_PARTS = {"99_LOCKS", ".git", ".obsidian"}
DENIED_PATH_FRAGMENTS = {
    ".env",
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "apikey",
    "api_key",
    "auth.local",
}


class LibraryError(Exception):
    status_code = 400


class LibraryNotFoundError(LibraryError):
    status_code = 404


class LibraryForbiddenError(LibraryError):
    status_code = 403


@dataclass(frozen=True)
class ParsedMarkdown:
    frontmatter: dict[str, Any]
    body: str


def scope_options(root: Path | None = None, actor: Actor | None = None) -> list[dict[str, Any]]:
    return [
        {
            "slug": slug,
            "label": SCOPE_LABELS[slug],
            "prefix": "/".join(prefix),
            "children": scope_children(root, slug, "", actor) if root and actor and slug != "all" else [],
        }
        for slug, prefix in SCOPE_PREFIXES.items()
    ]


def root_status(root: Path, actor: Actor) -> dict[str, Any]:
    root = root.expanduser()
    exists = root.exists() and root.is_dir()
    return {
        "root": str(root),
        "exists": exists,
        "scopes": scope_options(root, actor) if exists else scope_options(),
    }


def search_library(
    root: Path,
    query: str,
    scope: str,
    limit: int,
    offset: int,
    sort: str,
    subpath: str,
    actor: Actor,
) -> dict[str, Any]:
    root = resolve_root(root)
    validate_scope(scope)
    validate_sort(sort)
    subpath = normalize_subpath(subpath)
    terms = normalize_terms(query)
    if not terms:
        return empty_search_response(query, scope, limit, offset, sort, subpath)

    results: list[dict[str, Any]] = []
    for relative_path, parsed, stat in iter_visible_documents(root, scope, actor, subpath):
        scored = score_document(relative_path, parsed, terms, stat.st_size, stat.st_mtime)
        if scored is not None:
            results.append(scored)

    sort_results(results, sort)
    return paginated_response(
        {"query": query, "scope": scope, "subpath": subpath, "sort": sort},
        results,
        limit,
        offset,
    )


def recent_library(
    root: Path,
    scope: str,
    hours: int,
    limit: int,
    offset: int,
    subpath: str,
    actor: Actor,
) -> dict[str, Any]:
    root = resolve_root(root)
    validate_scope(scope)
    subpath = normalize_subpath(subpath)
    window_start = datetime.now(UTC) - timedelta(hours=hours)
    results = [
        document_result(relative_path, parsed, stat.st_size, stat.st_mtime)
        for relative_path, parsed, stat in iter_visible_documents(root, scope, actor, subpath)
        if datetime.fromtimestamp(stat.st_mtime, UTC) >= window_start
    ]
    sort_results(results, "newest")
    return paginated_response(
        {"scope": scope, "subpath": subpath, "hours": hours, "sort": "newest"},
        results,
        limit,
        offset,
    )


def list_library_children(root: Path, scope: str, subpath: str, actor: Actor) -> dict[str, Any]:
    root = resolve_root(root)
    validate_scope(scope)
    subpath = normalize_subpath(subpath)
    resolve_scope_dir(root, scope, subpath, require_exists=True)
    return {
        "scope": scope,
        "subpath": subpath,
        "children": scope_children(root, scope, subpath, actor),
    }


def empty_search_response(query: str, scope: str, limit: int, offset: int, sort: str, subpath: str) -> dict[str, Any]:
    return {
        "query": query,
        "scope": scope,
        "subpath": subpath,
        "sort": sort,
        "limit": limit,
        "offset": offset,
        "total": 0,
        "has_more": False,
        "results": [],
    }


def paginated_response(base: dict[str, Any], results: list[dict[str, Any]], limit: int, offset: int) -> dict[str, Any]:
    total = len(results)
    page = [public_result(result) for result in results[offset : offset + limit]]
    return {
        **base,
        "limit": limit,
        "offset": offset,
        "total": total,
        "has_more": offset + limit < total,
        "results": page,
    }


def read_library_file(root: Path, relative_path_text: str, actor: Actor) -> dict[str, Any]:
    root = resolve_root(root)
    path = resolve_relative_path(root, relative_path_text)
    if not path.exists() or not path.is_file() or path.suffix.lower() not in MARKDOWN_SUFFIXES:
        raise LibraryNotFoundError("Library file not found")
    if is_denied_path(path.relative_to(root)):
        raise LibraryForbiddenError("Library file is not exposed")
    stat = path.stat()
    if stat.st_size > MAX_READ_BYTES:
        raise LibraryError("Library file is too large to display")

    parsed = read_markdown_file(path, stat.st_size)
    relative_path = path.relative_to(root)
    if not actor_can_read(actor, relative_path, parsed.frontmatter):
        raise LibraryForbiddenError("Library file is not visible to this actor")

    title = document_title(relative_path, parsed)
    return {
        "path": relative_path.as_posix(),
        "title": title,
        "frontmatter": public_frontmatter(parsed.frontmatter),
        "body_markdown": parsed.body,
        "body_html": render_markdown(parsed.body),
        "updated_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        "size_bytes": stat.st_size,
    }


def resolve_root(root: Path) -> Path:
    root = root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise LibraryNotFoundError("Agent library root is not available")
    return root


def resolve_relative_path(root: Path, relative_path_text: str) -> Path:
    relative = Path(relative_path_text)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise LibraryError("Library path must be relative to the configured library root")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise LibraryError("Library path escapes the configured library root") from exc
    return candidate


def resolve_scope_dir(root: Path, scope: str, subpath: str, require_exists: bool = False) -> Path:
    validate_scope(scope)
    subpath = normalize_subpath(subpath)
    base = root.joinpath(*SCOPE_PREFIXES[scope]).resolve()
    if subpath:
        relative = Path(subpath)
        candidate = (base / relative).resolve()
    else:
        candidate = base
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise LibraryError("Library subpath escapes the selected scope") from exc
    if require_exists and (not candidate.exists() or not candidate.is_dir()):
        raise LibraryNotFoundError("Library subpath not found")
    return candidate


def normalize_subpath(subpath: str | None) -> str:
    if not subpath:
        return ""
    relative = Path(subpath)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise LibraryError("Library subpath must be relative to the selected scope")
    if should_skip_path(relative):
        raise LibraryForbiddenError("Library subpath is not exposed")
    return relative.as_posix()


def validate_scope(scope: str) -> None:
    if scope not in SCOPE_PREFIXES:
        raise LibraryError(f"Unknown library scope: {scope}")


def validate_sort(sort: str) -> None:
    if sort not in SEARCH_SORTS:
        raise LibraryError(f"Unknown library sort: {sort}")


def iter_visible_documents(root: Path, scope: str, actor: Actor, subpath: str = ""):
    for path in iter_markdown_files(root, scope, subpath):
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size > MAX_SEARCH_BYTES:
            continue
        relative_path = path.relative_to(root)
        try:
            parsed = read_markdown_file(path, stat.st_size)
        except LibraryError:
            continue
        if not actor_can_read(actor, relative_path, parsed.frontmatter):
            continue
        yield relative_path, parsed, stat


def iter_markdown_files(root: Path, scope: str, subpath: str = ""):
    start = resolve_scope_dir(root, scope, subpath)
    if not start.exists():
        return
    for path in start.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in MARKDOWN_SUFFIXES:
            continue
        relative_path = path.relative_to(root)
        if should_skip_path(relative_path):
            continue
        yield path


def scope_children(root: Path, scope: str, subpath: str, actor: Actor) -> list[dict[str, Any]]:
    try:
        start = resolve_scope_dir(root.expanduser().resolve(), scope, subpath, require_exists=True)
    except LibraryError:
        return []
    children: list[dict[str, Any]] = []
    for child in sorted((item for item in start.iterdir() if item.is_dir()), key=lambda item: item.name.lower()):
        relative_path = child.relative_to(root.expanduser().resolve())
        if should_skip_path(relative_path):
            continue
        child_subpath = child.relative_to(resolve_scope_dir(root.expanduser().resolve(), scope, "")).as_posix()
        document_count = visible_document_count(root.expanduser().resolve(), scope, child_subpath, actor)
        child_children = safe_child_dir_count(root.expanduser().resolve(), scope, child_subpath)
        if document_count == 0:
            continue
        children.append(
            {
                "slug": child.name,
                "label": child.name.replace("_", " ").replace("-", " "),
                "path": child_subpath,
                "prefix": relative_path.as_posix(),
                "document_count": document_count,
                "has_children": child_children > 0,
            }
        )
    return children


def visible_document_count(root: Path, scope: str, subpath: str, actor: Actor) -> int:
    count = 0
    for _relative_path, _parsed, _stat in iter_visible_documents(root, scope, actor, subpath):
        count += 1
    return count


def safe_child_dir_count(root: Path, scope: str, subpath: str) -> int:
    try:
        start = resolve_scope_dir(root, scope, subpath, require_exists=True)
    except LibraryError:
        return 0
    count = 0
    for child in start.iterdir():
        if child.is_dir() and not should_skip_path(child.relative_to(root)):
            count += 1
    return count


def should_skip_path(relative_path: Path) -> bool:
    if any(part.startswith(".") or part in HIDDEN_DIRS for part in relative_path.parts):
        return True
    if relative_path.name.endswith(".meta.yaml"):
        return True
    return is_denied_path(relative_path)


def is_denied_path(relative_path: Path) -> bool:
    normalized = relative_path.as_posix().lower()
    if any(part in DENIED_PARTS for part in relative_path.parts):
        return True
    return any(fragment in normalized for fragment in DENIED_PATH_FRAGMENTS)


def read_markdown_file(path: Path, size: int | None = None) -> ParsedMarkdown:
    if size is None:
        size = path.stat().st_size
    if size > MAX_READ_BYTES:
        raise LibraryError("Library file is too large to display")
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_frontmatter(text)


def parse_frontmatter(text: str) -> ParsedMarkdown:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ParsedMarkdown(frontmatter={}, body=text)

    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return ParsedMarkdown(frontmatter={}, body=text)

    metadata: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in lines[1:end_index]:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith((" ", "\t")) and current_key and raw_line.strip().startswith("- "):
            value = raw_line.strip()[2:].strip()
            existing = metadata.setdefault(current_key, [])
            if not isinstance(existing, list):
                metadata[current_key] = [existing]
                existing = metadata[current_key]
            existing.append(clean_frontmatter_scalar(value))
            continue
        if ":" not in raw_line:
            current_key = None
            continue
        key, value = raw_line.split(":", 1)
        current_key = key.strip()
        value = value.strip()
        if value in {"", "[]"}:
            metadata[current_key] = []
        elif value.startswith("[") and value.endswith("]"):
            metadata[current_key] = [
                clean_frontmatter_scalar(part.strip())
                for part in value[1:-1].split(",")
                if part.strip()
            ]
        else:
            metadata[current_key] = clean_frontmatter_scalar(value)

    body = "\n".join(lines[end_index + 1 :]).lstrip("\n")
    return ParsedMarkdown(frontmatter=metadata, body=body)


def clean_frontmatter_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def normalize_terms(query: str) -> list[str]:
    query = query.strip().lower()
    if not query:
        return []
    terms = [term for term in re.split(r"\s+", query) if term]
    return terms[:8]


def score_document(
    relative_path: Path,
    parsed: ParsedMarkdown,
    terms: list[str],
    size_bytes: int,
    updated_mtime: float,
) -> dict[str, Any] | None:
    path_text = relative_path.as_posix()
    title = document_title(relative_path, parsed)
    title_text = title.lower()
    path_lower = path_text.lower()
    frontmatter_text = " ".join(str(value) for value in parsed.frontmatter.values()).lower()
    body_lower = parsed.body.lower()

    score = 0
    matched_fields: set[str] = set()
    for term in terms:
        if term in title_text:
            score += 10
            matched_fields.add("title")
        if term in path_lower:
            score += 5
            matched_fields.add("path")
        if term in frontmatter_text:
            score += 4
            matched_fields.add("frontmatter")
        body_hits = body_lower.count(term)
        if body_hits:
            score += min(12, body_hits)
            matched_fields.add("body")
    if score == 0:
        return None

    result = document_result(relative_path, parsed, size_bytes, updated_mtime)
    result.update(
        {
            "excerpt": best_excerpt(parsed.body, terms),
            "score": score,
            "matches": sorted(matched_fields),
        }
    )
    return result


def document_result(
    relative_path: Path,
    parsed: ParsedMarkdown,
    size_bytes: int,
    updated_mtime: float,
) -> dict[str, Any]:
    path_text = relative_path.as_posix()
    return {
        "path": path_text,
        "title": document_title(relative_path, parsed),
        "excerpt": best_excerpt(parsed.body, []),
        "score": 0,
        "matches": [],
        "frontmatter": public_frontmatter(parsed.frontmatter),
        "updated_at": datetime.fromtimestamp(updated_mtime, UTC).isoformat(),
        "_mtime": updated_mtime,
        "size_bytes": size_bytes,
    }


def public_result(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if not key.startswith("_")}


def sort_results(results: list[dict[str, Any]], sort: str) -> None:
    if sort == "newest":
        results.sort(key=lambda item: item["_mtime"], reverse=True)
        return
    if sort == "oldest":
        results.sort(key=lambda item: item["_mtime"])
        return
    results.sort(key=lambda item: (item["score"], item["_mtime"]), reverse=True)


def document_title(relative_path: Path, parsed: ParsedMarkdown) -> str:
    metadata_title = parsed.frontmatter.get("title")
    if isinstance(metadata_title, str) and metadata_title.strip():
        return metadata_title.strip()
    for line in parsed.body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or relative_path.stem
    return relative_path.stem.replace("_", " ").replace("-", " ")


def best_excerpt(body: str, terms: list[str], limit: int = 220) -> str:
    body_for_search = body.lower()
    first_index = min((body_for_search.find(term) for term in terms if term in body_for_search), default=-1)
    if first_index < 0:
        return redact_excerpt(plain_excerpt(body, limit=limit))
    start = max(0, first_index - 70)
    end = min(len(body), first_index + limit - 30)
    snippet = body[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(body):
        snippet = snippet + "..."
    return redact_excerpt(" ".join(snippet.split()))


def redact_excerpt(text: str) -> str:
    text = re.sub(r"/Users/[^\s)]+", "/Users/[redacted]", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}", r"\1[redacted]", text)
    text = re.sub(r"[A-Za-z0-9_-]{32,}", "[redacted]", text)
    return text


def public_frontmatter(metadata: dict[str, Any]) -> dict[str, Any]:
    blocked_keys = {"token", "secret", "password", "credential", "api_key", "apikey"}
    public: dict[str, Any] = {}
    for key, value in metadata.items():
        if key.lower() in blocked_keys:
            continue
        public[key] = value
    return public


def actor_can_read(actor: Actor, relative_path: Path, metadata: dict[str, Any]) -> bool:
    if actor.is_admin:
        return True
    if is_denied_path(relative_path):
        return False

    visible_to = metadata_values(metadata.get("visible_to"))
    if not visible_to:
        visible_to = metadata_values(metadata.get("audience"))
    actor_tokens = {
        "all_agents",
        "internal",
        actor.username.lower(),
        f"user:{actor.username.lower()}",
        f"persona:{actor.username.lower()}",
    }
    if actor.persona_id:
        persona_id = actor.persona_id.lower()
        actor_tokens.add(persona_id)
        actor_tokens.add(f"persona:{persona_id}")

    parts = relative_path.parts
    if len(parts) >= 3 and parts[0] in {"private", "notes"} and parts[1] == "private":
        owner = parts[2].lower()
        owner_tokens = {actor.username.lower()}
        if actor.persona_id:
            owner_tokens.add(actor.persona_id.lower())
        return owner.lower() in owner_tokens or bool(visible_to & actor_tokens)

    if visible_to and visible_to & actor_tokens:
        return True
    if any(value.startswith("project:") for value in visible_to):
        return True
    return not visible_to


def metadata_values(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, list):
        values = value
    else:
        values = [value]
    return {str(item).strip().lower() for item in values if str(item).strip()}
