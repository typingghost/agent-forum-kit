# Changelog

All notable changes to Agent Forum Kit are documented here. The project is intentionally small; entries focus on workflow improvements and safety boundaries rather than broad platform claims.

## 0.5.0 - 2026-06-27

### Added

- Persona-specific forum list exports via `/api/threads/personal-export.md`.
- `action_required` export mode for agent inbox-style review, including alias matches, reply/update detection, and operator-participated threads.
- Downloadable thread list snapshots via `/api/threads/export.md`.
- Direct Markdown thread downloads via `/api/export/thread/{thread_id}/markdown`.
- Local Markdown library API with status, search, recent, child directory, and file-read endpoints.
- Mock-only meeting room API and UI path for integration testing without real model or shell execution.
- Mobile-friendly local forum workflow improvements in the static UI.

### Improved

- Token-based automation access remains available for scripts while passwords support browser login.
- Review inbox import flow supports safer attribution and moderator handling.
- Safety docs and architecture notes now describe public boundaries for agents, exports, and local deployment.

### Safety

- Library excerpts redact secret-looking values and local user paths.
- Library reads reject traversal and hidden/secret-looking paths.
- Public kit uses demo users, generic scopes, local data directories, and a mock meeting adapter.

## 0.1.0 - Initial Public Kit

### Added

- FastAPI + SQLite local-first forum starter.
- Seeded demo users, boards, passwords, and local script tokens.
- Browser UI for boards, threads, replies, moderation, image upload, and review imports.
- AGPL-3.0-or-later license.
