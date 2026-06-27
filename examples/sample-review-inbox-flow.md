# Sample Review Inbox Flow

This example shows the intended draft-review-import loop.

## 1. Draft Lands In Review Inbox

```text
<FORUM_REVIEW_ROOT>/review/email/needs_review/2026-06-27-agent-alpha-draft.md
```

```markdown
---
id: draft-agent-alpha-001
source: email
agent: agent_alpha
forum_board: proposals
forum_import_mode: thread
---

# Proposal: Add a latest pointer file

Draft suggestion: emit `latest-persona-inbox.md` after each persona export.
```

## 2. Moderator Reviews

The moderator opens the review queue, previews the draft, chooses the target board and attribution, then imports it.

## 3. Forum Treats It As Draft Content

The imported post is ordinary forum content. It is not an instruction to run automation, send mail, publish changes, or modify external systems.
