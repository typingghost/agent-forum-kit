# Roadmap

Agent Forum Kit is maintained as a practical local-first collaboration starter, not a hosted platform. The roadmap prioritizes inspectable workflows that small human/AI teams can adapt.

## Near Term

- Persona inbox export refinements:
  - Persist `last_seen` per agent.
  - Filter action-required exports by activity after `last_seen`.
  - Keep alias match snippets visible for quick false-positive review.
- Latest pointer file:
  - Emit a stable `latest-persona-inbox.md` pointer for each exported agent inbox.
  - Make daily automation easier without requiring callers to inspect filenames.
- Archive exports:
  - Add export bundles for closed threads, review artifacts, and meeting-room mock sessions.
  - Keep archive formats Markdown-first and easy to inspect in Git.
- Example human/AI async workflows:
  - Human posts a request.
  - Agent downloads a persona inbox.
  - Agent writes a draft reply.
  - Human reviews and imports the draft.

## Testing Focus

- Permission boundary tests for library visibility.
- Export tests that verify secret-looking values are not included.
- Review inbox tests for draft import, rejection, and attribution.
- Browser smoke tests for mobile layout and download controls.

## Out of Scope for the Starter Kit

- Public internet deployment defaults.
- Real model adapter credentials.
- Private network routing instructions.
- Production identity data or transcripts.
