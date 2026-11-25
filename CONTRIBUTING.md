# Contributing to Clarivo

Thank you for contributing to **Clarivo**. Please follow these standards to keep the codebase clean, secure, and production-ready.

## Local Development Setup

1. **Clone & Configure Environment**
   ```bash
   git clone https://github.com/Anmol8729/AI-Calling-Agent.git
   cd AI-Calling-Agent
   cp .env.example .env
   ```
   Fill in your development keys in `.env` (never commit `.env`).

2. **Install Dependencies**
   ```bash
   # Backend & Voice Agent
   pip install -r backend/requirements.txt -r agent/requirements.txt

   # Frontend Dashboard
   npm --prefix frontend ci
   ```

3. **Run Services**
   - Using `make`:
     ```bash
     make dev-backend
     make dev-agent
     make dev-frontend
     ```
   - Or on Windows via helper scripts in `scripts/dev/`:
     ```powershell
     .\scripts\dev\run_all.ps1
     ```

## Code Quality & Testing

Before opening a Pull Request, ensure all checks pass locally:

```bash
# Backend security & unit tests
pytest backend/tests -v

# Python linter
ruff check backend agent

# Frontend production build check
npm --prefix frontend run build
```

## Commit & Pull Request Conventions

We follow **Conventional Commits**:
- `feat(scope): ...` — New feature
- `fix(scope): ...` — Bug fix
- `perf(scope): ...` — Latency or performance improvement
- `refactor(scope): ...` — Code restructuring without behavior change
- `docs(scope): ...` — Documentation updates
- `chore(scope): ...` — Tooling, CI, or dependency maintenance

### Security Rules
- **Never** commit `.env`, API keys, JWT secrets, or database passwords.
- **Never** bypass `clinic_id` tenant scoping in backend routes or database queries.
- All database schema changes must include an Alembic migration under `backend/migrations/versions/`.
