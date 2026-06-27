from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import Actor, require_actor
from app.config import settings
from app.services.library import (
    LibraryError,
    list_library_children,
    recent_library,
    read_library_file,
    root_status,
    search_library,
)


router = APIRouter(prefix="/api/library", tags=["library"])


class LibraryScopeChildOut(BaseModel):
    slug: str
    label: str
    path: str
    prefix: str
    document_count: int
    has_children: bool


class LibraryScopeOut(BaseModel):
    slug: str
    label: str
    prefix: str
    children: list[LibraryScopeChildOut]


class LibraryStatusOut(BaseModel):
    root: str
    exists: bool
    scopes: list[LibraryScopeOut]


class LibrarySearchResultOut(BaseModel):
    path: str
    title: str
    excerpt: str
    score: int
    matches: list[str]
    frontmatter: dict[str, Any]
    updated_at: str
    size_bytes: int


class LibrarySearchResponseOut(BaseModel):
    query: str
    scope: str
    subpath: str
    sort: str
    limit: int
    offset: int
    total: int
    has_more: bool
    results: list[LibrarySearchResultOut]


class LibraryRecentResponseOut(BaseModel):
    scope: str
    subpath: str
    hours: int
    sort: str
    limit: int
    offset: int
    total: int
    has_more: bool
    results: list[LibrarySearchResultOut]


class LibraryChildrenResponseOut(BaseModel):
    scope: str
    subpath: str
    children: list[LibraryScopeChildOut]


class LibraryFileOut(BaseModel):
    path: str
    title: str
    frontmatter: dict[str, Any]
    body_markdown: str
    body_html: str
    updated_at: str
    size_bytes: int


@router.get("/status", response_model=LibraryStatusOut)
def library_status(actor: Actor = Depends(require_actor)) -> dict[str, Any]:
    return root_status(settings.library_root, actor)


@router.get("/children", response_model=LibraryChildrenResponseOut)
def library_children(
    scope: str = Query(..., min_length=1, max_length=40),
    subpath: str = Query("", max_length=300),
    actor: Actor = Depends(require_actor),
) -> dict[str, Any]:
    try:
        return list_library_children(settings.library_root, scope, subpath, actor)
    except LibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/search", response_model=LibrarySearchResponseOut)
def library_search(
    q: str = Query(..., min_length=1, max_length=120),
    scope: str = Query("all", min_length=1, max_length=40),
    subpath: str = Query("", max_length=300),
    sort: str = Query("relevance", min_length=1, max_length=20),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    actor: Actor = Depends(require_actor),
) -> dict[str, Any]:
    try:
        return search_library(settings.library_root, q, scope, limit, offset, sort, subpath, actor)
    except LibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/recent", response_model=LibraryRecentResponseOut)
def library_recent(
    hours: int = Query(24, ge=1, le=168),
    scope: str = Query("all", min_length=1, max_length=40),
    subpath: str = Query("", max_length=300),
    limit: int = Query(30, ge=1, le=50),
    offset: int = Query(0, ge=0),
    actor: Actor = Depends(require_actor),
) -> dict[str, Any]:
    try:
        return recent_library(settings.library_root, scope, hours, limit, offset, subpath, actor)
    except LibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/file", response_model=LibraryFileOut)
def library_file(
    path: str = Query(..., min_length=1, max_length=500),
    actor: Actor = Depends(require_actor),
) -> dict[str, Any]:
    try:
        return read_library_file(settings.library_root, path, actor)
    except LibraryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
