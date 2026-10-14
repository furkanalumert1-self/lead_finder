---
title: Lead Radar — a team's lead panel on its own registry (`/leads`)
status: built; daily schedule behind `leads_scheduler` (TREG_LEADS_SCHEDULER), campaigns opt in
sources:
  - src/treg/domain/leads/rules.py
  - src/treg/application/leads/providers.py
  - src/treg/application/leads/budget.py
  - src/treg/application/leads/runs.py
  - src/treg/application/leads/scheduler.py
  - src/treg/application/leads/service.py
  - src/treg/routers/leads.py
  - src/treg/models.py
  - src/treg/alembic/versions/0073_lead_radar.py
  - src/treg/bootstrap.py
  - frontend/src/leads/
  - scripts/lead-radar.sh
  - tests/test_leads.py
related:
  - architecture/proxy-model.md
  - architecture/multi-tenancy.md
  - architecture/import-boundaries.md
---

# Lead Radar

A campaign turns a team's ICP into a few search queries against one discovery source, scores what
comes back with fixed rules, merges it into leads, and optionally finds work emails for the best few.
It is the `lead-signals` skill made persistent: the same detect → qualify → contact order, with the
results, notes and spend kept in the registry's own database.

## Shape

- **Tables** (`lead*`, revision 0073) all carry `org_id`; `application/leads` is their only writer and
  every query filters by the caller's team (`require_member`). Another team's row reads as 404.
- **Rules** (`domain/leads/rules.py`) are pure: a lead is keyed by person URL, else company domain,
  else source URL; the score is ICP fit 50 + signal strength 30 + recency 20, exclusions first, an
  empty ICP field scores as unknown (0), and a lead with no evidence is never qualified. No model.
- **Adapters** (`providers.py`) never hold a key. A real adapter calls this registry's own
  `/call/<endpoint id>` with a team token (`TREG_LEADS_TOKEN`, else the single-user token file), so
  the team's connected key is injected server-side like any other call. Prices come from the catalog
  row × the provider's credit rate in `fx.yaml`, or from a per-call price the team entered; with
  neither, the call is blocked. Demo adapters produce `.example` companies and are marked demo
  everywhere; demo leads never count in the overview.

## Money

`budget.py` guards the team's **provider** spend, not treg balance (own keys are never metered,
non-negotiable 1). A reservation's first statement UPDATEs the team's `leadsettings` row, which
serializes concurrent reservations for one team; then it checks the run, local-day and local-month
totals (Europe/Istanbul) and refuses a call that would pass any limit. A limit of 0 blocks paid calls.
Each reservation closes exactly once: `settled` at the reported cost (or the ceiling when the answer
reports none), `released` when nothing can have been billed, `uncertain` on a timeout, which keeps
its reserve counted. Retries: at most two, only for 429 and refused connections.

## Runs and schedule

No session is open while a provider call is in flight. A re-run adds evidence and refreshes the
score but never changes `status` or `note`. The scheduler runs in the server process
(`ROLE_BACKGROUND_TASKS`): it claims `(campaign_id, slot=local date)` before spending, so a restart
or a second worker cannot start the same day twice, and at startup it marks runs a restart
interrupted as failed and their open reservations as uncertain.
