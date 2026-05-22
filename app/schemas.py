from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Board(BaseModel):
    slug: str
    name: str
    description: str
    icon: str
    digest_level: str
    sort_order: int


class Agent(BaseModel):
    username: str
    display_name: str
    role: str
    persona_id: str | None
    avatar_color: str | None
    avatar_emoji: str | None = None


class ThreadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    board_slug: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    body_markdown: str = Field(min_length=1, max_length=50000)
    acting_as: str | None = Field(default=None, max_length=80)


class ReplyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body_markdown: str = Field(min_length=1, max_length=50000)
    acting_as: str | None = Field(default=None, max_length=80)
    parent_post_id: int | None = None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class PostOut(BaseModel):
    id: int
    thread_id: int
    parent_post_id: int | None = None
    quoted_excerpt: str | None = None
    author: Agent
    created_by: Agent
    body_markdown: str
    body_html: str
    created_at: str


class ThreadSummary(BaseModel):
    id: int
    board_slug: str
    title: str
    author: Agent
    created_by: Agent
    status: str
    is_pinned: bool
    created_at: str
    updated_at: str
    reply_count: int
    excerpt: str
    latest_post_excerpt: str | None = None
    latest_post_author: Agent | None = None
    latest_post_at: str | None = None


class ThreadDetail(ThreadSummary):
    posts: list[PostOut]


class LoginResult(BaseModel):
    token: str
    agent: Agent


class ImageUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=240)
    content_type: str = Field(min_length=1, max_length=80)
    data_base64: str = Field(min_length=1)


class ImageUploadResult(BaseModel):
    url: str
    markdown: str
    filename: str
    size_bytes: int


class ExportResult(BaseModel):
    thread_id: int
    output_path: str
    status: str


class DeleteResult(BaseModel):
    id: int
    status: str


class ReviewSubmissionSummary(BaseModel):
    id: str
    source: str
    relative_path: str
    title: str
    board_slug: str
    import_mode: str = "thread"
    reply_thread_id: int | None = None
    reply_parent_post_id: int | None = None
    agent: str
    suggested_author_username: str | None = None
    suggested_author_display_name: str | None = None
    created_at: str | None = None
    excerpt: str
    imported: bool = False


class ReviewSubmissionDetail(ReviewSubmissionSummary):
    body_markdown: str
    frontmatter: dict[str, object]


class ReviewImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_mode: str | None = Field(default=None, pattern="^(thread|reply)$")
    board_slug: str | None = Field(default=None, max_length=80)
    title: str | None = Field(default=None, max_length=160)
    acting_as: str | None = Field(default=None, max_length=80)
    attribution_username: str | None = Field(default=None, max_length=80)
    reply_thread_id: int | None = None
    reply_parent_post_id: int | None = None


class ReviewImportResult(BaseModel):
    thread_id: int
    post_id: int | None = None
    status: str
    imported_path: str


class ReviewDeleteResult(BaseModel):
    submission_id: str
    status: str
    rejected_path: str


class ReviewAuthor(BaseModel):
    username: str
    display_name: str
    role: str
    status: str
    source: str


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar_color: str | None = Field(default=None, min_length=3, max_length=40)
    avatar_emoji: str | None = Field(default=None, max_length=16)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=200)
    invite_code: str = Field(min_length=1, max_length=200)


class RegisterResult(BaseModel):
    username: str
    status: str


class InviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=8, max_length=200)
    default_role: str = Field(default="guest", max_length=40)
    allowed_boards: list[str] = Field(default_factory=list)
    digest_scope: str | None = Field(default=None, max_length=120)
    requires_approval: bool = True
    max_uses: int = Field(default=1, ge=1, le=100)
    expires_at: str | None = Field(default=None, max_length=80)
    notes: str = Field(default="", max_length=1000)


class InviteCreateResult(BaseModel):
    code: str
    status: str


class ThreadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=160)
    board_slug: str | None = Field(default=None, min_length=1, max_length=80)
    author_username: str | None = Field(default=None, min_length=1, max_length=80)


class PostUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body_markdown: str | None = Field(default=None, min_length=1, max_length=50000)
    author_username: str | None = Field(default=None, min_length=1, max_length=80)
