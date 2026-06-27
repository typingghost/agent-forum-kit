from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth import Actor, require_actor


router = APIRouter(prefix="/api/meeting-room", tags=["meeting-room"])

_session_counter = itertools.count(1)
_event_counter = itertools.count(1)
_sessions: dict[str, dict[str, Any]] = {}
_events: dict[str, list[dict[str, Any]]] = {}


class MeetingAdapterInfo(BaseModel):
    id: str
    label: str
    status: str
    capabilities: list[str]
    limitations: list[str]
    allowed_agent_ids: list[str]


class MeetingSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(default="agent_alpha", min_length=1, max_length=80)
    adapter: str = Field(default="mock", min_length=1, max_length=80)
    title: str | None = Field(default=None, max_length=160)
    opening_prompt: str | None = Field(default=None, max_length=4000)


class MeetingMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body_markdown: str = Field(min_length=1, max_length=20000)


class MeetingEventOut(BaseModel):
    id: int
    event_type: str
    actor: str
    body_markdown: str
    created_at: str


class MeetingSessionOut(BaseModel):
    id: str
    title: str
    agent_id: str
    adapter: str
    status: str
    created_by: str
    created_at: str
    updated_at: str


class MeetingSessionDetail(MeetingSessionOut):
    events: list[MeetingEventOut]


SUPPORTED_ADAPTERS = [
    MeetingAdapterInfo(
        id="mock",
        label="Mock Adapter",
        status="available",
        capabilities=["local session scaffold", "echo replies", "frontend integration testing"],
        limitations=["does not call real models", "does not execute shell commands", "not for production automation"],
        allowed_agent_ids=["agent_alpha", "agent_beta", "admin", "moderator"],
    )
]


@router.get("/adapters", response_model=list[MeetingAdapterInfo])
def list_meeting_adapters(actor: Actor = Depends(require_actor)) -> list[MeetingAdapterInfo]:
    return SUPPORTED_ADAPTERS


@router.get("/sessions", response_model=list[MeetingSessionOut])
def list_meeting_sessions(actor: Actor = Depends(require_actor)) -> list[MeetingSessionOut]:
    return [MeetingSessionOut(**session) for session in sorted(_sessions.values(), key=lambda item: item["updated_at"], reverse=True)]


@router.post("/sessions", response_model=MeetingSessionOut, status_code=status.HTTP_201_CREATED)
def create_meeting_session(payload: MeetingSessionCreate, actor: Actor = Depends(require_actor)) -> MeetingSessionOut:
    if payload.adapter != "mock":
        raise HTTPException(status_code=400, detail="The public kit only ships with the mock adapter")
    adapter = SUPPORTED_ADAPTERS[0]
    if payload.agent_id not in adapter.allowed_agent_ids:
        raise HTTPException(status_code=400, detail="agent_id is not allowed for the mock adapter")

    now = datetime.now(UTC).isoformat()
    session_id = f"mock-{next(_session_counter)}"
    session = {
        "id": session_id,
        "title": payload.title or f"Mock session with {payload.agent_id}",
        "agent_id": payload.agent_id,
        "adapter": payload.adapter,
        "status": "open",
        "created_by": actor.username,
        "created_at": now,
        "updated_at": now,
    }
    _sessions[session_id] = session
    _events[session_id] = []
    if payload.opening_prompt:
        append_event(session_id, "user.message", actor.username, payload.opening_prompt)
        append_event(session_id, "adapter.output", payload.agent_id, mock_reply(payload.opening_prompt, payload.agent_id))
    return MeetingSessionOut(**session)


@router.get("/sessions/{session_id}", response_model=MeetingSessionDetail)
def get_meeting_session(session_id: str, actor: Actor = Depends(require_actor)) -> MeetingSessionDetail:
    session = require_session(session_id)
    return MeetingSessionDetail(**session, events=[MeetingEventOut(**event) for event in _events.get(session_id, [])])


@router.post("/sessions/{session_id}/messages", response_model=MeetingSessionDetail)
def add_meeting_message(
    session_id: str,
    payload: MeetingMessageCreate,
    actor: Actor = Depends(require_actor),
) -> MeetingSessionDetail:
    session = require_session(session_id)
    if session["status"] != "open":
        raise HTTPException(status_code=400, detail="Session is not open")
    append_event(session_id, "user.message", actor.username, payload.body_markdown)
    append_event(session_id, "adapter.output", session["agent_id"], mock_reply(payload.body_markdown, session["agent_id"]))
    session["updated_at"] = datetime.now(UTC).isoformat()
    return MeetingSessionDetail(**session, events=[MeetingEventOut(**event) for event in _events.get(session_id, [])])


@router.post("/sessions/{session_id}/close", response_model=MeetingSessionOut)
def close_meeting_session(session_id: str, actor: Actor = Depends(require_actor)) -> MeetingSessionOut:
    session = require_session(session_id)
    session["status"] = "closed"
    session["updated_at"] = datetime.now(UTC).isoformat()
    append_event(session_id, "system.status", "system", f"Closed by {actor.username}.")
    return MeetingSessionOut(**session)


def require_session(session_id: str) -> dict[str, Any]:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Meeting session not found")
    return session


def append_event(session_id: str, event_type: str, actor: str, body_markdown: str) -> None:
    _events.setdefault(session_id, []).append(
        {
            "id": next(_event_counter),
            "event_type": event_type,
            "actor": actor,
            "body_markdown": body_markdown,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )


def mock_reply(message: str, agent_id: str) -> str:
    excerpt = " ".join(message.split())[:220]
    return f"Mock reply from `{agent_id}`. Received: {excerpt}"
