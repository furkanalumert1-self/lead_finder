"""Daily campaign runs, Europe/Istanbul time, in the server process.

One run per campaign per local day: the run row's unique (campaign_id, slot) is claimed before
anything is spent, so a restart, a second worker or an overlapping tick can never start the same
day twice. Scheduled runs execute one after another, never in parallel. No model, no agent: a
scheduled run is the same deterministic pipeline as the Run button.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from ...infra.db import background_session_maker as session_maker
from ...models import LeadCampaign, LeadRun
from . import runs
from .budget import TZ
from .providers import default_registry

log = logging.getLogger("treg.leads")
TICK_SECONDS = 60


async def tick(registry, now_utc: datetime | None = None) -> list[int]:
    """Claim and run every campaign due today. Returns the run ids it started."""
    local = (now_utc or datetime.now(timezone.utc)).astimezone(TZ)
    slot = local.date().isoformat()
    claimed: list[int] = []
    async with session_maker() as db:
        due = [c.id for c in (await db.execute(select(LeadCampaign).where(
            LeadCampaign.status == "active", LeadCampaign.schedule_daily.is_(True)))).scalars()
            if local.hour >= c.schedule_hour]
    for campaign_id in due:
        async with session_maker() as db:
            campaign = await db.get(LeadCampaign, campaign_id)
            busy = (await db.execute(select(LeadRun.id).where(
                LeadRun.campaign_id == campaign_id, LeadRun.status.in_(("queued", "running"))))).first()
            if campaign is None or busy is not None:
                continue
            run = LeadRun(org_id=campaign.org_id, campaign_id=campaign_id, trigger="scheduled", slot=slot)
            db.add(run)
            try:
                await db.commit()
            except IntegrityError:      # this day's slot is already taken
                await db.rollback()
                continue
            claimed.append(run.id)
    for run_id in claimed:
        await runs.execute(run_id, registry)
    return claimed


async def cron(registry, now_utc: datetime | None = None) -> dict:
    """One external tick (Vercel Cron): close runs a killed function left open, then start what is
    due. The slot claim keeps a retried or doubled cron delivery from running a day twice."""
    recovered = await runs.recover_interrupted(runs.STALE_AFTER)
    started = await tick(registry, now_utc)
    return {"recovered": recovered, "started": started}


async def worker(client_factory, *, enabled: bool, serverless: bool = False) -> None:
    """Recover runs a restart interrupted, then tick every minute while `enabled`. Serverless
    instances do neither: many run at once and none lives long; the cron route does both."""
    if serverless:
        return
    try:
        recovered = await runs.recover_interrupted()
        if recovered:
            log.warning("event=lead_runs_recovered count=%s", recovered)
    except Exception:  # noqa: BLE001 - a missing table before `upgrade` must not kill startup
        log.exception("lead run recovery failed")
    if not enabled:
        return
    registry = default_registry(client_factory)
    while True:
        try:
            await tick(registry)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - one bad pass never kills the loop
            log.exception("lead scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)
