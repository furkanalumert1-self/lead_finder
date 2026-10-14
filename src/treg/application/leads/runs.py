"""One campaign run: discover -> qualify -> merge -> (optionally) enrich the best few.

No database session is open while a provider call is in flight: every step reads what it needs,
closes the session, calls, then opens a new one to write. Each paid call is reserved before it
leaves and closed exactly once after (budget.py). Retries: at most two, and only for answers that
cannot have been billed (429, a refused connection); a timeout is never retried blind.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from sqlmodel import select

from ...domain.leads import rules
from ...infra.db import background_session_maker as session_maker
from ...models import (Lead, LeadCache, LeadCampaign, LeadEvidence, LeadIcp, LeadRun, LeadSettings,
                       LeadSuppression, _now)
from . import budget
from .providers import Hit, ProviderError, Registry, SearchRequest

log = logging.getLogger("treg.leads")

MAX_RETRIES = 2
DEFAULT_TTL_HOURS = {"search": 24, "email": 24 * 30}
_tasks: set[asyncio.Task] = set()


def _issue(kind: str, message: str, **extra) -> dict:
    return {"kind": kind, "message": message[:300], "at": _now().isoformat(timespec="seconds"), **extra}


async def _cached(org_id: int, key: str) -> dict | None:
    async with session_maker() as db:
        row = (await db.execute(select(LeadCache).where(
            LeadCache.org_id == org_id, LeadCache.key == key))).scalar_one_or_none()
        if row is None or row.expires_at <= _now():
            return None
        return row.payload


async def _store_cache(org_id: int, key: str, provider: str, payload: dict, ttl_hours: int) -> None:
    if ttl_hours <= 0:
        return
    async with session_maker() as db:
        row = (await db.execute(select(LeadCache).where(
            LeadCache.org_id == org_id, LeadCache.key == key))).scalar_one_or_none()
        expires = _now() + timedelta(hours=ttl_hours)
        if row is None:
            db.add(LeadCache(org_id=org_id, key=key, provider=provider, payload=payload, expires_at=expires))
        else:
            row.payload, row.created_at, row.expires_at = payload, _now(), expires
        await db.commit()


async def _paid_call(*, org_id: int, run_id: int, provider_key: str, ceiling: int, run_limit: int,
                     call, cost_of) -> tuple[object, int]:
    """Reserve, call (bounded retries), close. Returns (result, micro-USD charged)."""
    attempt = 0
    while True:
        spend_id = None
        if ceiling > 0:
            async with session_maker() as db:
                spend_id = await budget.reserve(db, org_id=org_id, run_id=run_id, provider=provider_key,
                                                amount=ceiling, run_limit=run_limit)
        try:
            result = await call()
        except ProviderError as exc:
            if spend_id is not None:
                async with session_maker() as db:
                    await budget.close(db, spend_id, "uncertain" if exc.charged else "released")
            if exc.retryable and attempt < MAX_RETRIES:
                attempt += 1
                await asyncio.sleep(1.5 * attempt)
                continue
            raise
        except BaseException:
            # Cancellation or a bug after the request left: the provider may have billed it.
            if spend_id is not None:
                async with session_maker() as db:
                    await budget.close(db, spend_id, "uncertain")
            raise
        cost = cost_of(result)
        cost = ceiling if cost < 0 else cost      # unknown actual: settle at the reserved ceiling
        if spend_id is not None:
            async with session_maker() as db:
                await budget.close(db, spend_id, "settled" if cost > 0 else "released", cost)
        return result, cost


async def _update_run(run_id: int, **fields) -> LeadRun | None:
    async with session_maker() as db:
        run = await db.get(LeadRun, run_id)
        if run is None:
            return None
        for k, v in fields.items():
            setattr(run, k, v)
        await db.commit()
        return run


async def _stop_requested(run_id: int) -> bool:
    async with session_maker() as db:
        run = await db.get(LeadRun, run_id)
        return run is None or run.stop_requested


def _icp(row: LeadIcp | None) -> rules.Icp:
    if row is None:
        return rules.Icp()
    return rules.Icp(product=row.product, sectors=row.sectors, geographies=row.geographies,
                     sizes=row.sizes, roles=row.roles, problems=row.problems,
                     competitors=row.competitors, exclusions=row.exclusions)


def _today() -> date:
    return datetime.now(timezone.utc).astimezone(budget.TZ).date()


async def execute(run_id: int, registry: Registry) -> None:
    """Run to a terminal status. Never raises: every failure ends up on the run's issues."""
    issues: list[dict] = []
    try:
        await _execute(run_id, registry, issues)
    except Exception as exc:  # noqa: BLE001 - the run records it; the server keeps going
        log.exception("lead run %s failed", run_id)
        issues.append(_issue("internal", f"Beklenmeyen hata: {type(exc).__name__}"))
        await _update_run(run_id, status="failed", issues=issues, finished_at=_now())


async def _execute(run_id: int, registry: Registry, issues: list[dict]) -> None:
    async with session_maker() as db:
        run = await db.get(LeadRun, run_id)
        if run is None or run.status not in ("queued",):
            return
        campaign = await db.get(LeadCampaign, run.campaign_id)
        if campaign is None or campaign.org_id != run.org_id:
            return
        icp_row = await db.get(LeadIcp, campaign.icp_id) if campaign.icp_id else None
        if icp_row is not None and icp_row.org_id != run.org_id:
            icp_row = None
        settings = await budget.ensure_settings(db, run.org_id)
        prices, ttl = dict(settings.prices_micro or {}), {**DEFAULT_TTL_HOURS, **(settings.cache_ttl_hours or {})}
        suppression = [(s.kind, s.value) for s in (await db.execute(
            select(LeadSuppression).where(LeadSuppression.org_id == run.org_id))).scalars()]
        org_id, c = run.org_id, campaign
        run.status, run.started_at = "running", _now()
        await db.commit()

    discovery = registry.discovery.get(c.provider)
    if discovery is None:
        issues.append(_issue("missing_credential", f"Bilinmeyen kaynak: {c.provider}"))
        await _update_run(run_id, status="failed", issues=issues, finished_at=_now())
        return
    await _update_run(run_id, provider=discovery.key, demo=discovery.demo)
    price = discovery.price(prices)
    if price is None:
        issues.append(_issue("unknown_price", f"{discovery.label}: ücret doğrulanamadı, çağrı engellendi"))
        await _update_run(run_id, status="failed", issues=issues, finished_at=_now())
        return

    hits: list[tuple[Hit, str]] = []
    api_cost = 0
    stopped = False
    calls_ok = calls_failed = 0
    for query in [q for q in c.queries if q.strip()]:
        if len(hits) >= c.result_limit:
            break
        if await _stop_requested(run_id):
            stopped = True
            break
        req = SearchRequest(query=query.strip(), days=c.date_range_days,
                            limit=c.result_limit - len(hits), signal_type=c.signal_type)
        key = discovery.cache_key(req)
        cached = await _cached(org_id, key)
        if cached is not None:
            batch = [Hit(**h) for h in cached.get("hits", [])]
        else:
            try:
                result, cost = await _paid_call(
                    org_id=org_id, run_id=run_id, provider_key=discovery.key, ceiling=price.ceiling_micro,
                    run_limit=c.budget_run_micro, call=lambda r=req: discovery.search(r),
                    cost_of=lambda r: r.cost_micro)
            except budget.BudgetExceeded as exc:
                issues.append(_issue("budget", str(exc), query=query))
                break
            except ProviderError as exc:
                calls_failed += 1
                issues.append(_issue(exc.kind, str(exc), query=query))
                if exc.kind in ("missing_credential", "unknown_price"):
                    break
                continue
            api_cost += cost
            calls_ok += 1
            batch = result.hits
            await _store_cache(org_id, key, discovery.key, {"hits": [asdict(h) for h in batch]},
                               int(ttl.get(discovery.cache_kind, 24)))
        if not batch:
            issues.append(_issue("empty", "Sorgu sonuç döndürmedi", query=query))
        hits.extend((h, query) for h in batch[: c.result_limit - len(hits)])
        await _update_run(run_id, candidates=len(hits), api_cost_micro=api_cost, issues=list(issues))

    new, qualified_ids = await _merge(org_id, run_id, c, _icp(icp_row), hits, discovery, suppression)
    qualified = len(qualified_ids)

    enriched = 0
    if c.enrich_provider and c.enrich_limit > 0 and not stopped and qualified_ids:
        enriched, cost = await _enrich(org_id, run_id, c, registry, prices, ttl, suppression, qualified_ids, issues)
        api_cost += cost

    if await _stop_requested(run_id):
        stopped = True
    status = ("stopped" if stopped else
              "failed" if calls_ok == 0 and calls_failed > 0 and not hits else
              "partial" if any(i["kind"] not in ("empty",) for i in issues) else "succeeded")
    await _update_run(run_id, status=status, candidates=len(hits), qualified=qualified, new_leads=new,
                      enriched=enriched, api_cost_micro=api_cost, issues=issues, finished_at=_now())


async def _merge(org_id: int, run_id: int, c: LeadCampaign, icp: rules.Icp, hits: list[tuple[Hit, str]],
                 discovery, suppression) -> tuple[int, list[int]]:
    """Fold this run's hits into leads. Existing leads gain evidence and a fresh score; their
    status and note are never touched."""
    today = _today()
    groups: dict[str, list[Hit]] = {}
    for hit, _query in hits:
        key = rules.dedup_key(domain=hit.domain, person_url=hit.person_url, source_url=hit.url)
        if key:
            groups.setdefault(key, []).append(hit)
    new = 0
    qualified_ids: list[int] = []
    async with session_maker() as db:
        for key, group in groups.items():
            lead = (await db.execute(select(Lead).where(Lead.org_id == org_id, Lead.dedup_key == key))).scalar_one_or_none()
            first = group[0]
            if lead is None:
                lead = Lead(org_id=org_id, campaign_id=c.id, dedup_key=key, company=first.company,
                            domain=rules.normalize_domain(first.domain), person_name=first.person_name,
                            person_role=first.person_role, person_url=rules.normalize_url(first.person_url),
                            location=first.location, provider=discovery.key, demo=discovery.demo,
                            status="new")
                db.add(lead)
                await db.flush()
                new += 1
            known = {e.url for e in (await db.execute(select(LeadEvidence).where(
                LeadEvidence.lead_id == lead.id))).scalars()}
            for h in group:
                url = rules.normalize_url(h.url)
                if url and url not in known:
                    db.add(LeadEvidence(org_id=org_id, lead_id=lead.id, run_id=run_id, url=url,
                                        title=h.title, snippet=h.snippet, signal_date=h.published,
                                        provider=discovery.key))
                    known.add(url)
            await db.flush()
            evidence = list((await db.execute(select(LeadEvidence).where(
                LeadEvidence.lead_id == lead.id))).scalars())
            newest = max(evidence, key=lambda e: e.signal_date or "", default=None)
            text = " ".join(f"{e.title} {e.snippet}" for e in evidence)
            s = rules.score(icp, rules.Candidate(
                text=text, company=lead.company, domain=lead.domain, person_role=lead.person_role,
                location=lead.location, signal_type=c.signal_type,
                signal_date=newest.signal_date if newest else "", evidence_count=len(evidence)), today)
            if rules.suppressed(suppression, email=lead.email, domain=lead.domain, person_url=lead.person_url):
                s.qualified = False
                s.notes = ["İletişim hariç tutma listesinde"] + s.notes
            lead.signal_type = c.signal_type
            lead.signal_date = newest.signal_date if newest else ""
            lead.summary = (newest.title or newest.snippet[:160]) if newest else ""
            lead.score, lead.score_fit, lead.score_signal, lead.score_recency = s.total, s.fit, s.signal, s.recency
            lead.score_notes, lead.qualified, lead.fit_reason = s.notes, s.qualified, s.fit_reason
            if s.excluded and lead.status == "new":
                lead.status = "dropped"
            elif s.qualified and lead.status == "new":
                lead.status = "review"
            lead.updated_at = _now()
            if s.qualified and lead.status != "dropped":
                qualified_ids.append(lead.id)
        await db.commit()
    return new, qualified_ids


async def _enrich(org_id, run_id, c, registry, prices, ttl, suppression, lead_ids, issues) -> tuple[int, int]:
    enricher = registry.enrichers.get(c.enrich_provider)
    if enricher is None:
        issues.append(_issue("missing_credential", f"Bilinmeyen e-posta sağlayıcısı: {c.enrich_provider}"))
        return 0, 0
    price = enricher.price(prices)
    if price is None:
        issues.append(_issue("unknown_price", f"{enricher.label}: ücret doğrulanamadı, enrichment engellendi"))
        return 0, 0
    async with session_maker() as db:
        leads = list((await db.execute(select(Lead).where(
            Lead.org_id == org_id, Lead.id.in_(lead_ids)).order_by(Lead.score.desc()))).scalars())
    targets = [(l.id, l.person_name, l.domain) for l in leads
               if not l.email and l.email_status not in ("not_found",)][: c.enrich_limit]
    done = cost_total = 0
    for lead_id, name, domain in targets:
        if not name or not domain:
            await _set_email(lead_id, "", "skipped")
            continue
        if await _stop_requested(run_id):
            break
        key = enricher.cache_key(name, domain)
        cached = await _cached(org_id, key)
        if cached is not None:
            email, status = cached.get("email", ""), cached.get("status", "not_found")
        else:
            try:
                result, cost = await _paid_call(
                    org_id=org_id, run_id=run_id, provider_key=enricher.key, ceiling=price.ceiling_micro,
                    run_limit=c.budget_run_micro, call=lambda n=name, d=domain: enricher.find_email(n, d),
                    cost_of=lambda r: r.cost_micro)
            except budget.BudgetExceeded as exc:
                issues.append(_issue("budget", str(exc)))
                break
            except ProviderError as exc:
                issues.append(_issue(exc.kind, f"E-posta: {exc}"))
                if exc.kind == "missing_credential":
                    break
                continue
            cost_total += cost
            email, status = result.email, result.status
            await _store_cache(org_id, key, enricher.key, {"email": email, "status": status},
                               int(ttl.get(enricher.cache_kind, 720)))
        # Re-check suppression with the address we now know before keeping it.
        if email and rules.suppressed(suppression, email=email):
            email, status = "", "skipped"
        await _set_email(lead_id, email, status)
        done += 1
    return done, cost_total


async def _set_email(lead_id: int, email: str, status: str) -> None:
    async with session_maker() as db:
        lead = await db.get(Lead, lead_id)
        if lead is None:
            return
        lead.email, lead.email_status = email, status
        lead.last_enriched_at = lead.updated_at = _now()
        await db.commit()


def spawn(run_id: int, registry: Registry) -> None:
    """Start a run in this process, keeping a reference so it is not garbage-collected."""
    task = asyncio.create_task(execute(run_id, registry))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def recover_interrupted() -> int:
    """Runs left `running`/`queued` by a crash or restart end as failed, never resumed twice.
    Their open reservations become uncertain: the call may have been billed."""
    from ...models import LeadSpend
    async with session_maker() as db:
        stale = list((await db.execute(select(LeadRun).where(LeadRun.status.in_(("running", "queued"))))).scalars())
        for run in stale:
            run.status, run.finished_at = "failed", _now()
            run.issues = [*run.issues, _issue("interrupted", "Sunucu yeniden başladı; koşu yarıda kaldı")]
        for spend in (await db.execute(select(LeadSpend).where(LeadSpend.state == "reserved"))).scalars():
            spend.state, spend.settled_at = "uncertain", _now()
        await db.commit()
        return len(stale)
