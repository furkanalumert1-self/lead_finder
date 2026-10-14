"""The team's provider-spend guard: reserve before a call, settle after it, on the server.

A reservation first UPDATEs the team's `leadsettings` row, which takes a write lock (a row lock on
Postgres, the database write lock on SQLite), then sums what the run, the local day and the local
month have already committed and refuses a call that would pass any limit. Two concurrent runs
therefore cannot both fit into the last dollar. Each reservation is closed exactly once:
`settle` (what it cost), `release` (it cost nothing) or `uncertain` (a timeout: the reserve stays
counted, because the provider may have billed it).

A limit of 0 means "not set" and blocks every paid call; free (demo) calls never reserve.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ...models import LeadSettings, LeadSpend, _now

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Istanbul")
except Exception:  # noqa: BLE001 - no tz database (bare Windows): Istanbul is fixed UTC+3
    TZ = timezone(timedelta(hours=3))


class BudgetExceeded(Exception):
    def __init__(self, window: str, limit: int, committed: int, amount: int):
        labels = {"run": "koşu", "day": "günlük", "month": "aylık"}
        super().__init__(
            f"{labels.get(window, window)} bütçe sınırı: ${committed / 1e6:.4f} harcandı/ayrıldı, "
            f"bu çağrı ${amount / 1e6:.4f}, sınır ${limit / 1e6:.4f}"
            if limit else f"{labels.get(window, window)} bütçe sınırı tanımlı değil: ücretli çağrı engellendi")
        self.window = window


def local_bounds(now_utc: datetime | None = None) -> tuple[datetime, datetime]:
    """Naive-UTC starts of the current Europe/Istanbul day and month."""
    now = (now_utc or datetime.now(timezone.utc)).astimezone(TZ)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    to_utc = lambda d: d.astimezone(timezone.utc).replace(tzinfo=None)  # noqa: E731
    return to_utc(day), to_utc(month)


_COMMITTED = func.coalesce(func.sum(case(
    (LeadSpend.state.in_(("reserved", "uncertain")), LeadSpend.reserved_micro),
    (LeadSpend.state == "settled", LeadSpend.actual_micro),
    else_=0,
)), 0)


async def ensure_settings(db: AsyncSession, org_id: int) -> LeadSettings:
    row = await db.get(LeadSettings, org_id)
    if row is None:
        db.add(LeadSettings(org_id=org_id))
        try:
            await db.commit()
        except IntegrityError:   # a concurrent first reservation created it
            await db.rollback()
        row = await db.get(LeadSettings, org_id)
    return row


async def committed(db: AsyncSession, org_id: int, *, run_id: int | None = None,
                    since: datetime | None = None) -> int:
    q = select(_COMMITTED).where(LeadSpend.org_id == org_id)
    if run_id is not None:
        q = q.where(LeadSpend.run_id == run_id)
    if since is not None:
        q = q.where(LeadSpend.created_at >= since)
    return int((await db.execute(q)).scalar_one())


async def reserve(db: AsyncSession, *, org_id: int, run_id: int | None, provider: str, amount: int,
                  run_limit: int, kind: str = "api") -> int:
    """Hold `amount` micro-USD for one call, or raise BudgetExceeded. Commits. Returns the id."""
    await ensure_settings(db, org_id)
    await db.commit()
    # The UPDATE is the transaction's first statement, so it takes the write lock before any read:
    # on SQLite a read first would hold a shared lock two writers could deadlock on.
    await db.execute(update(LeadSettings).where(LeadSettings.org_id == org_id)
                     .values(lock_version=LeadSettings.lock_version + 1))
    settings = (await db.execute(select(LeadSettings).where(LeadSettings.org_id == org_id)
                                 .execution_options(populate_existing=True))).scalar_one()
    day_start, month_start = local_bounds()
    checks = [("month", settings.month_limit_micro, await committed(db, org_id, since=month_start)),
              ("day", settings.day_limit_micro, await committed(db, org_id, since=day_start))]
    if run_id is not None:
        checks.append(("run", run_limit, await committed(db, org_id, run_id=run_id)))
    for window, limit, used in checks:
        if limit <= 0 or used + amount > limit:
            await db.rollback()
            raise BudgetExceeded(window, limit, used, amount)
    spend = LeadSpend(org_id=org_id, run_id=run_id, provider=provider, kind=kind,
                      reserved_micro=amount)
    db.add(spend)
    await db.commit()
    return spend.id


async def close(db: AsyncSession, spend_id: int, state: str, actual: int = 0) -> None:
    """Close one reservation: settled | released | uncertain. A second close is ignored."""
    spend = await db.get(LeadSpend, spend_id)
    if spend is None or spend.state != "reserved":
        return
    spend.state = state
    spend.actual_micro = max(actual, 0) if state == "settled" else 0
    spend.settled_at = _now()
    await db.commit()
