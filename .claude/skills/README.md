# Project skills

Claude Code loads the skills in this folder automatically when working in this repo.

## Vendored from ECC

These six skills are copied from [affaan-m/ECC](https://github.com/affaan-m/ECC) at commit `d2ef268` (2026-11-06), under the MIT license (see `ECC-LICENSE`). Only the `SKILL.md` files were copied; no ECC hooks, installer, agents or commands.

| Skill | Use for |
|---|---|
| `python-testing` | pytest fixtures, mocking, parametrization |
| `python-patterns` | idiomatic Python, typing, error handling |
| `docker-patterns` | Dockerfile and Compose structure, container security |
| `deployment-patterns` | health checks, rollback, production readiness |
| `llm-trading-agent-security` | spend limits, circuit breakers, prompt injection, key handling for agents with trade authority |
| `prediction-market-risk-review` | review gates before a workflow touches venue auth, portfolio data or execution |

Local changes:
- `docker-patterns`: removed the "Hardened CLI Installer Harnesses" section, which documents ECC's own plugin-setup test harness (files that don't exist here, a global `npm install` and a Codex login flow).

Things to know:
- `python-testing` and `python-patterns` are generic. They push TDD and 80%+ coverage, and mention tools this repo doesn't use (`pytest-cov`, `black`, `mypy`, `bandit`). The repo's own conventions win where they differ.
- `deployment-patterns` examples lean towards Node, Kubernetes and Vercel; the checklists are the useful part.
- `prediction-market-risk-review` refers to ECC's "Itô" data products (`ITO_API_KEY`); ignore those lines.
