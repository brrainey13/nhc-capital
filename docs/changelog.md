---
title: Changelog
summary: 'Release history and migration notes.'
read_when:
  - Checking what changed in the repo
  - Understanding migration history
---

# Changelog

## 2026-03-05 — GitHub Migration

- Migrated from GitLab to GitHub as primary remote
- Squashed git history (clean slate, no secrets)
- Ported Code Factory CI from `.gitlab-ci.yml` to GitHub Actions
- Updated all scripts (`mr-review`, `committer`, `remediate`) for GitHub
- Added CODEOWNERS (`@brrainey13` auto-requested on all PRs)
- Branch protection: PRs required, 1 approval, gate + review + lint + docs checks
- Replaced ngrok with Cloudflare Tunnel + Access
- Scrubbed all PII (emails, IPs, hardcoded paths) from tracked files
- Updated review model chain: GPT-OSS-120B → Qwen3-Next-80B → Kimi K2 → Qwen3.5-122B → DeepSeek V3.1
- Added auto-fix workflow (ruff + docs-guard failures trigger automated fixes)
