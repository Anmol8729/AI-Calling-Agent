## Summary
<!-- Describe what this PR changes and why. -->

## Type of Change
- [ ] Feature (`feat`)
- [ ] Bug fix (`fix`)
- [ ] Performance / latency optimization (`perf`)
- [ ] Security hardening (`security`)
- [ ] Refactor / chore / docs

## Verification Checklist
- [ ] `pytest backend/tests -v` passes locally
- [ ] `npm --prefix frontend run build` succeeds without errors
- [ ] No secrets, `.env` values, or API keys are committed
- [ ] Multi-tenant isolation (`clinic_id` scoping) is preserved for all modified queries/endpoints
- [ ] Database schema changes include an Alembic migration (if applicable)
