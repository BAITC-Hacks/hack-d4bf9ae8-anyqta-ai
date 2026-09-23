---
name: career-quest
description: "Implement or review Career Quest features involving trajectories, recommendations, HR analytics, data imports, demo workflows, or the local web cabinet. Use only in this repository, not for generic web applications."
---

# Career Quest

Use this skill when work changes the Career Quest product behavior or its
evaluation-ready demo. Keep the employee trajectory explainable and preserve
the distinction between deterministic facts and optional LLM selection.

Read [the data and workflow contract](references/data-contract.md) before
changing calculations, imports, recommendations, demo state or access control.

## Working rules

- Derive actual skill levels from the last review and completed activities after
  it. Apply the event's `gain` and `max_level`; never use an LLM for this.
- Filter event eligibility server-side before any model sees candidates. The LLM
  can choose only validated `event_id` values, and a failure must retain the
  labelled rules fallback.
- Keep employee access bound to the authenticated `employee_id`. HR actions
  require the `hr` role on the server.
- Preserve the atomic JSON/CSV import contract used by the jury. Do not silently
  overwrite an existing record with different source data.
- Keep `DEMO_MODE` behavior visible. Completion and reset are simulations, and
  reset must remove only app-created records for the current seeded demo user.

## Validation

Run the unit suite for behavior changes:

```bash
python3 -m unittest discover -s backend/tests -v
```

For a demo journey, bootstrap, authentication, HR or activity-lifecycle change,
also run:

```bash
python3 scripts/acceptance.py
```

Do not read or print `.env` values. Configure the optional LLM only through the
documented environment variables.
