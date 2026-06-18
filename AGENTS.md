# AGENTS.md

This repository is the public, synthetic-data MVP of Quip RAG.

## Product Goal

Help project managers turn years of semi-structured issue logs into a traceable
decision system: normalize changing schemas, surface recurring patterns, review
AI classifications, and answer questions with evidence.

## Public Demo Rules

- Only synthetic data may be committed.
- Never commit Quip exports, company names, customer names, internal URLs, tokens,
  API keys, local databases, vector indexes, or copied production identifiers.
- The hosted demo must work without login or private credentials.
- Demo-only behavior must be labeled clearly in the UI and documentation.
- Use fictional organizations, projects, vendors, people, and issue descriptions.

## Architecture

- `frontend/`: React + TypeScript + Vite product demo.
- `backend/`: FastAPI reference implementation for the production architecture.
- `demo/`: deterministic synthetic fixtures and generation notes.
- `docs/`: product case study and deployment material.

The browser-ready MVP defaults to a frontend demo adapter backed by deterministic
fixtures. The backend remains available for local architecture exploration.

## Engineering Rules

- Keep API types centralized in `frontend/src/api/client.ts`.
- Demo responses must satisfy the same TypeScript contracts as live responses.
- Do not add speculative features. Every visible feature must support the core
  project-manager workflow: understand, investigate, review, or follow up.
- Preserve accessible focus states, keyboard navigation, loading, empty, and error
  states.
- Use one dark neutral theme with emerald as the only accent.

## Required Checks

Before publishing:

```bash
npm run check
npm run scan:public
```

`scan:public` must fail when likely secrets or forbidden source-data paths are
present. A successful build without a successful public scan is not releasable.
