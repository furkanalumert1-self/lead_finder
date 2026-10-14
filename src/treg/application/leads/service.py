"""Lead Radar use cases behind the HTTP routes. Every function takes the caller's `org_id` and every
query filters on it; a row of another team reads as not found."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_
from sqlmodel import select

from ...domain.leads import rules
from ...infra.db import session_maker
from ...models import (Lead, LeadCache, LeadCampaign, LeadEvidence, LeadIcp, LeadRun, LeadSettings,
                       LeadSpend, LeadSuppression, Secret, _now)
from . import budget, runs
from .providers import ProviderError, Registry, registry_token


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


ICP_LISTS = ("sectors", "geographies", "sizes", "roles", "problems", "competitors", "exclusions")
PILOT_RESULT_LIMIT, PILOT_ENRICH_LIMIT = 20, 5
MAX_RESULT_LIMIT, MAX_ENRICH_LIMIT = 100, 50


def _iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat(timespec="seconds") if value else None


def _clean_list(value) -> list[str]:
    if isinstance(value, str):
        value = value.replace("\n", ",").split(",")
    if not isinstance(value, list):
        return []
    return [str(v).strip()[:120] for v in value if str(v).strip()][:50]


async def _owned(db, model, row_id: int, org_id: int):
    row = await db.get(model, row_id)
    if row is None or row.org_id != org_id:
        raise NotFound(model.__name__)
    return row


# ---- ICP ---------------------------------------------------------------------------------------

def icp_view(i: LeadIcp) -> dict:
    return {"id": i.id, "name": i.name, "product": i.product, "website": i.website,
            **{k: getattr(i, k) for k in ICP_LISTS}, "updated_at": _iso(i.updated_at)}


async def list_icps(org_id: int) -> list[dict]:
    async with session_maker() as db:
        return [icp_view(i) for i in (await db.execute(
            select(LeadIcp).where(LeadIcp.org_id == org_id).order_by(LeadIcp.id))).scalars()]


async def save_icp(org_id: int, body: dict, icp_id: int | None = None) -> dict:
    name = str(body.get("name") or "").strip()[:120]
    if not name:
        raise Invalid("ICP adı gerekli")
    async with session_maker() as db:
        icp = await _owned(db, LeadIcp, icp_id, org_id) if icp_id else LeadIcp(org_id=org_id, name=name)
        icp.name = name
        icp.product = str(body.get("product") or "").strip()[:500]
        icp.website = str(body.get("website") or "").strip()[:300]
        for k in ICP_LISTS:
            setattr(icp, k, _clean_list(body.get(k)))
        icp.updated_at = _now()
        db.add(icp)
        await db.commit()
        return icp_view(icp)


# ---- campaigns ---------------------------------------------------------------------------------

def campaign_view(c: LeadCampaign, last_run: LeadRun | None = None) -> dict:
    return {"id": c.id, "name": c.name, "icp_id": c.icp_id, "provider": c.provider,
            "enrich_provider": c.enrich_provider, "signal_type": c.signal_type, "queries": c.queries,
            "date_range_days": c.date_range_days, "result_limit": c.result_limit,
            "enrich_limit": c.enrich_limit, "budget_run_micro": c.budget_run_micro, "status": c.status,
            "schedule_daily": c.schedule_daily, "schedule_hour": c.schedule_hour,
            "created_at": _iso(c.created_at), "last_run": run_view(last_run) if last_run else None}


def run_view(r: LeadRun) -> dict:
    return {"id": r.id, "campaign_id": r.campaign_id, "trigger": r.trigger, "slot": r.slot,
            "status": r.status, "provider": r.provider, "demo": r.demo, "candidates": r.candidates,
            "qualified": r.qualified, "new_leads": r.new_leads, "enriched": r.enriched,
            "api_cost_micro": r.api_cost_micro, "llm_cost_micro": r.llm_cost_micro, "issues": r.issues,
            "created_at": _iso(r.created_at), "started_at": _iso(r.started_at),
            "finished_at": _iso(r.finished_at)}


def _int(body: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(body.get(key, default))
    except (TypeError, ValueError):
        raise Invalid(f"{key} sayı olmalı") from None
    return max(lo, min(hi, value))


async def list_campaigns(org_id: int) -> list[dict]:
    async with session_maker() as db:
        out = []
        for c in (await db.execute(select(LeadCampaign).where(
                LeadCampaign.org_id == org_id).order_by(LeadCampaign.id.desc()))).scalars():
            last = (await db.execute(select(LeadRun).where(LeadRun.campaign_id == c.id)
                                     .order_by(LeadRun.id.desc()).limit(1))).scalar_one_or_none()
            out.append(campaign_view(c, last))
        return out


async def save_campaign(org_id: int, body: dict, registry: Registry, campaign_id: int | None = None) -> dict:
    name = str(body.get("name") or "").strip()[:120]
    if not name:
        raise Invalid("Kampanya adı gerekli")
    provider = str(body.get("provider") or "demo")
    if provider not in registry.discovery:
        raise Invalid(f"Bilinmeyen kaynak: {provider}")
    enrich = str(body.get("enrich_provider") or "")
    if enrich and enrich not in registry.enrichers:
        raise Invalid(f"Bilinmeyen e-posta sağlayıcısı: {enrich}")
    queries = _clean_list(body.get("queries"))[:10]
    if not queries:
        raise Invalid("En az bir sorgu gerekli")
    async with session_maker() as db:
        icp_id = body.get("icp_id")
        if icp_id:
            await _owned(db, LeadIcp, int(icp_id), org_id)
        c = await _owned(db, LeadCampaign, campaign_id, org_id) if campaign_id else LeadCampaign(org_id=org_id, name=name)
        c.name, c.icp_id, c.provider, c.enrich_provider = name, int(icp_id) if icp_id else None, provider, enrich
        c.signal_type = "hiring" if body.get("signal_type") == "hiring" else "content"
        c.queries = queries
        c.date_range_days = _int(body, "date_range_days", 30, 1, 365)
        c.result_limit = _int(body, "result_limit", PILOT_RESULT_LIMIT, 1, MAX_RESULT_LIMIT)
        c.enrich_limit = _int(body, "enrich_limit", PILOT_ENRICH_LIMIT, 0, MAX_ENRICH_LIMIT)
        c.budget_run_micro = _int(body, "budget_run_micro", 0, 0, 1_000 * 1_000_000)
        c.status = body.get("status") if body.get("status") in ("draft", "active", "paused") else c.status
        c.schedule_daily = bool(body.get("schedule_daily", c.schedule_daily))
        c.schedule_hour = _int(body, "schedule_hour", c.schedule_hour, 0, 23)
        c.updated_at = _now()
        db.add(c)
        await db.commit()
        return campaign_view(c)


async def delete_campaign(org_id: int, campaign_id: int) -> None:
    """Removes the campaign and its runs. Its leads stay (with their notes), detached."""
    async with session_maker() as db:
        c = await _owned(db, LeadCampaign, campaign_id, org_id)
        busy = (await db.execute(select(LeadRun.id).where(
            LeadRun.campaign_id == c.id, LeadRun.status.in_(("queued", "running"))))).first()
        if busy:
            raise Invalid("Koşu sürerken kampanya silinemez; önce durdurun")
        for lead in (await db.execute(select(Lead).where(Lead.campaign_id == c.id))).scalars():
            lead.campaign_id = None
        run_ids = list((await db.execute(select(LeadRun.id).where(LeadRun.campaign_id == c.id))).scalars())
        if run_ids:
            for model in (LeadEvidence, LeadSpend):
                for row in (await db.execute(select(model).where(model.run_id.in_(run_ids)))).scalars():
                    row.run_id = None
            await db.execute(delete(LeadRun).where(LeadRun.id.in_(run_ids)))
        await db.delete(c)
        await db.commit()


async def start_run(org_id: int, campaign_id: int, registry: Registry, *, inline: bool = False) -> dict:
    """Start a run. `inline` (serverless) finishes it inside this request, because a function may be
    frozen the moment it answers; otherwise it runs as a task in this long-lived process."""
    if inline:
        await runs.recover_interrupted(runs.STALE_AFTER)   # a killed function's run must not block
    async with session_maker() as db:
        c = await _owned(db, LeadCampaign, campaign_id, org_id)
        busy = (await db.execute(select(LeadRun.id).where(
            LeadRun.campaign_id == c.id, LeadRun.status.in_(("queued", "running"))))).first()
        if busy:
            raise Invalid("Bu kampanyanın bir koşusu zaten sürüyor")
        if c.status == "draft":
            c.status = "active"
        run = LeadRun(org_id=org_id, campaign_id=c.id, provider=c.provider,
                      demo=registry.discovery[c.provider].demo if c.provider in registry.discovery else False)
        db.add(run)
        await db.commit()
        view = run_view(run)
    if not inline:
        runs.spawn(view["id"], registry)
        return view
    await runs.execute(view["id"], registry)
    async with session_maker() as db:
        return run_view(await db.get(LeadRun, view["id"]))


async def stop_run(org_id: int, run_id: int) -> dict:
    async with session_maker() as db:
        run = await _owned(db, LeadRun, run_id, org_id)
        if run.status in ("queued", "running"):
            run.stop_requested = True
        await db.commit()
        return run_view(run)


async def list_runs(org_id: int, campaign_id: int | None = None, limit: int = 30) -> list[dict]:
    async with session_maker() as db:
        q = select(LeadRun).where(LeadRun.org_id == org_id)
        if campaign_id:
            q = q.where(LeadRun.campaign_id == campaign_id)
        return [run_view(r) for r in (await db.execute(q.order_by(LeadRun.id.desc()).limit(limit))).scalars()]


# ---- leads -------------------------------------------------------------------------------------

def lead_view(l: Lead, evidence: list[LeadEvidence] | None = None) -> dict:
    out = {"id": l.id, "campaign_id": l.campaign_id, "company": l.company, "domain": l.domain,
           "person_name": l.person_name, "person_role": l.person_role, "person_url": l.person_url,
           "location": l.location, "signal_type": l.signal_type, "signal_date": l.signal_date,
           "summary": l.summary, "fit_reason": l.fit_reason, "score": l.score,
           "score_fit": l.score_fit, "score_signal": l.score_signal, "score_recency": l.score_recency,
           "score_notes": l.score_notes, "qualified": l.qualified, "email": l.email,
           "email_status": l.email_status, "provider": l.provider, "demo": l.demo,
           "last_enriched_at": _iso(l.last_enriched_at), "status": l.status, "note": l.note,
           "discovered_at": _iso(l.discovered_at), "updated_at": _iso(l.updated_at)}
    if evidence is not None:
        out["evidence"] = [{"id": e.id, "url": e.url, "title": e.title, "snippet": e.snippet,
                            "signal_date": e.signal_date, "provider": e.provider,
                            "found_at": _iso(e.found_at)} for e in evidence]
    return out


SORTS = {"score": Lead.score.desc(), "recent": Lead.discovered_at.desc(),
         "signal": Lead.signal_date.desc(), "company": Lead.company.asc()}


def _lead_query(org_id: int, f: dict):
    q = select(Lead).where(Lead.org_id == org_id)
    if f.get("status") in rules.STATUSES:
        q = q.where(Lead.status == f["status"])
    if f.get("qualified") in ("1", "true", True):
        q = q.where(Lead.qualified.is_(True))
    if f.get("campaign_id"):
        q = q.where(Lead.campaign_id == int(f["campaign_id"]))
    if f.get("min_score"):
        q = q.where(Lead.score >= int(f["min_score"]))
    if f.get("demo") in ("0", "false"):
        q = q.where(Lead.demo.is_(False))
    if f.get("email") == "1":
        q = q.where(Lead.email != "")
    if text := str(f.get("q") or "").strip():
        like = f"%{text[:80]}%"
        q = q.where(or_(Lead.company.ilike(like), Lead.domain.ilike(like), Lead.person_name.ilike(like),
                        Lead.summary.ilike(like), Lead.note.ilike(like), Lead.email.ilike(like)))
    return q.order_by(SORTS.get(f.get("sort") or "score", Lead.score.desc()), Lead.id.desc())


async def list_leads(org_id: int, f: dict, limit: int = 500) -> dict:
    async with session_maker() as db:
        q = _lead_query(org_id, f)
        total = (await db.execute(select(func.count()).select_from(q.order_by(None).subquery()))).scalar_one()
        rows = list((await db.execute(q.limit(limit))).scalars())
        return {"total": total, "leads": [lead_view(l) for l in rows]}


async def get_lead(org_id: int, lead_id: int) -> dict:
    async with session_maker() as db:
        lead = await _owned(db, Lead, lead_id, org_id)
        evidence = list((await db.execute(select(LeadEvidence).where(
            LeadEvidence.lead_id == lead.id).order_by(LeadEvidence.signal_date.desc()))).scalars())
        return lead_view(lead, evidence)


EDITABLE = ("company", "domain", "person_name", "person_role", "person_url", "location", "email", "note")


async def update_lead(org_id: int, lead_id: int, body: dict) -> dict:
    async with session_maker() as db:
        lead = await _owned(db, Lead, lead_id, org_id)
        if "status" in body:
            if body["status"] not in rules.STATUSES:
                raise Invalid("Geçersiz durum")
            lead.status = body["status"]
        for k in EDITABLE:
            if k in body:
                value = str(body[k] or "").strip()[: 4000 if k == "note" else 300]
                if k == "domain":
                    value = rules.normalize_domain(value)
                if k == "person_url":
                    value = rules.normalize_url(value)
                if k == "email" and value != lead.email:
                    lead.email_status = "found" if value else ""
                setattr(lead, k, value)
        lead.updated_at = _now()
        await db.commit()
    return await get_lead(org_id, lead_id)


async def delete_lead(org_id: int, lead_id: int) -> None:
    async with session_maker() as db:
        lead = await _owned(db, Lead, lead_id, org_id)
        await db.execute(delete(LeadEvidence).where(LeadEvidence.lead_id == lead.id))
        await db.delete(lead)
        await db.commit()


async def _icp_for(db, org_id: int, campaign_id: int | None) -> rules.Icp:
    row = None
    if campaign_id:
        c = await db.get(LeadCampaign, campaign_id)
        if c and c.org_id == org_id and c.icp_id:
            row = await db.get(LeadIcp, c.icp_id)
    if row is None:
        row = (await db.execute(select(LeadIcp).where(LeadIcp.org_id == org_id)
                                .order_by(LeadIcp.id).limit(1))).scalar_one_or_none()
    return runs._icp(row)


async def add_leads(org_id: int, rows: list[dict], *, provider: str) -> dict:
    """Manual entry and CSV import. A row merges into an existing lead with the same key; its
    status and note are kept. Rows without a company, domain, person URL or source URL are skipped."""
    created = merged = skipped = 0
    suppression_hits = 0
    today = runs._today()
    async with session_maker() as db:
        suppression = [(s.kind, s.value) for s in (await db.execute(
            select(LeadSuppression).where(LeadSuppression.org_id == org_id))).scalars()]
        icp = await _icp_for(db, org_id, None)
        for raw in rows[:5000]:
            r = {k: str(v or "").strip() for k, v in raw.items()}
            domain = rules.normalize_domain(r.get("domain") or r.get("email", ""))
            person_url = rules.normalize_url(r.get("person_url", ""))
            source = rules.normalize_url(r.get("url", ""))
            key = rules.dedup_key(domain=domain, person_url=person_url, source_url=source)
            if not key and r.get("company"):
                key = "c:" + rules.fold(r["company"])[:120]
            if not key:
                skipped += 1
                continue
            lead = (await db.execute(select(Lead).where(Lead.org_id == org_id, Lead.dedup_key == key))).scalar_one_or_none()
            if lead is None:
                lead = Lead(org_id=org_id, dedup_key=key, provider=provider, status="new")
                db.add(lead)
                created += 1
            else:
                merged += 1
            for k in ("company", "person_name", "person_role", "location", "email"):
                if r.get(k) and not getattr(lead, k):
                    setattr(lead, k, r[k][:300])
            lead.domain = lead.domain or domain
            lead.person_url = lead.person_url or person_url
            if r.get("email") and not lead.email_status:
                lead.email_status = "found"
            if r.get("note") and not lead.note:
                lead.note = r["note"][:4000]
            if r.get("status") in rules.STATUSES and lead.status == "new":
                lead.status = r["status"]
            lead.signal_date = lead.signal_date or (r.get("signal_date", "")[:10] if rules.parse_day(r.get("signal_date", "")) else "")
            lead.summary = lead.summary or r.get("summary", "")[:300]
            await db.flush()
            if source:
                exists = (await db.execute(select(LeadEvidence.id).where(
                    LeadEvidence.lead_id == lead.id, LeadEvidence.url == source))).first()
                if not exists:
                    db.add(LeadEvidence(org_id=org_id, lead_id=lead.id, url=source,
                                        title=r.get("summary", "")[:300], signal_date=lead.signal_date,
                                        provider=provider))
            await db.flush()
            count = (await db.execute(select(func.count()).select_from(LeadEvidence).where(
                LeadEvidence.lead_id == lead.id))).scalar_one()
            s = rules.score(icp, rules.Candidate(
                text=f"{lead.summary} {r.get('note', '')}", company=lead.company, domain=lead.domain,
                person_role=lead.person_role, location=lead.location, signal_type=lead.signal_type or "content",
                signal_date=lead.signal_date, evidence_count=count), today)
            if count == 0:
                s.qualified = False
                s.notes = ["Kanıt URL'si yok: uygun lead sayılmaz"] + s.notes
            if rules.suppressed(suppression, email=lead.email, domain=lead.domain, person_url=lead.person_url):
                s.qualified = False
                suppression_hits += 1
                s.notes = ["İletişim hariç tutma listesinde"] + s.notes
            lead.score, lead.score_fit, lead.score_signal, lead.score_recency = s.total, s.fit, s.signal, s.recency
            lead.score_notes, lead.qualified, lead.fit_reason = s.notes, s.qualified, s.fit_reason
            lead.updated_at = _now()
        await db.commit()
    return {"created": created, "merged": merged, "skipped": skipped, "suppressed": suppression_hits}


CSV_COLUMNS = [
    ("company", "Şirket"), ("domain", "Domain"), ("person_name", "Kişi"), ("person_role", "Rol"),
    ("person_url", "Profil URL"), ("location", "Konum"), ("signal_type", "Sinyal türü"),
    ("signal_date", "Sinyal tarihi"), ("discovered_at", "Keşif tarihi"), ("summary", "Kanıt özeti"),
    ("fit_reason", "Uygunluk gerekçesi"), ("score", "Skor"), ("score_fit", "ICP uyumu"),
    ("score_signal", "Sinyal gücü"), ("score_recency", "Güncellik"), ("email", "E-posta"),
    ("email_status", "E-posta durumu"), ("provider", "Kaynak"), ("evidence", "Kanıt URL'leri"),
    ("status", "Durum"), ("note", "Not"), ("demo", "Demo"),
]
_IMPORT_ALIASES = {label.casefold(): key for key, label in CSV_COLUMNS}
_IMPORT_ALIASES.update({"url": "url", "kanıt url": "url", "kaynak url": "url", "website": "domain",
                        "name": "person_name", "title": "person_role", "role": "person_role"})


async def export_csv(org_id: int, f: dict) -> str:
    async with session_maker() as db:
        leads = list((await db.execute(_lead_query(org_id, f).limit(10_000))).scalars())
        ev: dict[int, list[str]] = {}
        if leads:
            for e in (await db.execute(select(LeadEvidence).where(
                    LeadEvidence.org_id == org_id, LeadEvidence.lead_id.in_([l.id for l in leads])))).scalars():
                ev.setdefault(e.lead_id, []).append(e.url)
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
    writer.writerow([label for _k, label in CSV_COLUMNS])
    for l in leads:
        view = lead_view(l)
        view["evidence"] = " ".join(ev.get(l.id, []))
        view["status"] = rules.STATUS_LABELS.get(l.status, l.status)
        view["demo"] = "evet" if l.demo else ""
        writer.writerow([rules.csv_cell(view.get(k, "")) for k, _label in CSV_COLUMNS])
    return "﻿" + buf.getvalue()   # BOM so Excel reads UTF-8 Turkish characters


def parse_csv(text: str) -> list[dict]:
    text = text.lstrip("﻿")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, None)
    if not header:
        raise Invalid("CSV boş")
    keys = [_IMPORT_ALIASES.get(h.strip().casefold(), h.strip().casefold()) for h in header]
    rows = []
    for values in reader:
        row = {}
        for k, v in zip(keys, values):
            v = v.strip()
            if v.startswith("'") and v[1:2] in ("=", "+", "-", "@"):
                v = v[1:]   # undo our own export's formula guard
            row[k] = v
        if "evidence" in row and not row.get("url"):
            row["url"] = row["evidence"].split()[0] if row["evidence"].split() else ""
        if row.get("status"):
            back = {label.casefold(): key for key, label in rules.STATUS_LABELS.items()}
            row["status"] = back.get(row["status"].casefold(), row["status"])
        rows.append(row)
    return rows


async def enrich_lead(org_id: int, lead_id: int, provider: str, registry: Registry) -> dict:
    """The drawer's single enrichment, on the team's day and month limits."""
    enricher = registry.enrichers.get(provider)
    if enricher is None:
        raise Invalid("Bilinmeyen e-posta sağlayıcısı")
    async with session_maker() as db:
        lead = await _owned(db, Lead, lead_id, org_id)
        settings = await budget.ensure_settings(db, org_id)
        prices = dict(settings.prices_micro or {})
        suppression = [(s.kind, s.value) for s in (await db.execute(
            select(LeadSuppression).where(LeadSuppression.org_id == org_id))).scalars()]
        name, domain = lead.person_name, lead.domain
        if rules.suppressed(suppression, email=lead.email, domain=domain, person_url=lead.person_url):
            raise Invalid("Bu kişi iletişim hariç tutma listesinde; enrichment yapılmaz")
        if not lead.qualified:
            raise Invalid("Yalnızca uygun (kanıtlı) leadler zenginleştirilebilir")
    if not name or not domain:
        raise Invalid("E-posta aramak için kişi adı ve şirket domaini gerekli")
    price = enricher.price(prices)
    if price is None:
        raise Invalid(f"{enricher.label}: ücret doğrulanamadı, çağrı engellendi")
    try:
        result, _cost = await runs._paid_call(
            org_id=org_id, run_id=None, provider_key=enricher.key, ceiling=price.ceiling_micro,
            run_limit=0, call=lambda: enricher.find_email(name, domain), cost_of=lambda r: r.cost_micro)
    except budget.BudgetExceeded as exc:
        raise Invalid(str(exc)) from None
    except ProviderError as exc:
        raise Invalid(f"{exc.kind}: {exc}") from None
    email, status = result.email, result.status
    if email and rules.suppressed(suppression, email=email):
        email, status = "", "skipped"
    await runs._set_email(lead_id, email, status)
    return await get_lead(org_id, lead_id)


def draft_message(lead: dict, icp: dict | None) -> str:
    """A short first-message draft from the lead's own evidence. Template only: no model, nothing
    is sent."""
    name = (lead.get("person_name") or "").split(" ")[0] or "Merhaba"
    greet = f"Merhaba {name}," if lead.get("person_name") else "Merhaba,"
    product = (icp or {}).get("product") or "çözümümüz"
    why = lead.get("summary") or "paylaşımınızı"
    return (f"{greet}\n\n\"{why[:140]}\" başlıklı paylaşımınızı gördüm. {product} tam olarak bu konuda "
            f"yardımcı oluyor. Uygunsanız 15 dakikalık kısa bir görüşmede nasıl çalıştığını "
            f"göstermek isterim.\n\nİyi çalışmalar")


# ---- suppression, settings, retention ------------------------------------------------------------

async def list_suppressions(org_id: int) -> list[dict]:
    async with session_maker() as db:
        return [{"id": s.id, "kind": s.kind, "value": s.value, "reason": s.reason,
                 "created_at": _iso(s.created_at)} for s in (await db.execute(
                     select(LeadSuppression).where(LeadSuppression.org_id == org_id)
                     .order_by(LeadSuppression.id.desc()))).scalars()]


async def add_suppression(org_id: int, kind: str, value: str, reason: str = "") -> dict:
    if kind not in rules.SUPPRESSION_KINDS:
        raise Invalid("Tür email, domain veya person_url olmalı")
    value = (value.strip().lower() if kind == "email" else
             rules.normalize_domain(value) if kind == "domain" else rules.normalize_url(value))
    if not value:
        raise Invalid("Geçerli bir değer girin")
    async with session_maker() as db:
        existing = (await db.execute(select(LeadSuppression).where(
            LeadSuppression.org_id == org_id, LeadSuppression.kind == kind,
            LeadSuppression.value == value))).scalar_one_or_none()
        if existing is None:
            existing = LeadSuppression(org_id=org_id, kind=kind, value=value, reason=reason[:200])
            db.add(existing)
        # Leads it covers stop counting as qualified right away.
        rule = [(kind, value)]
        for lead in (await db.execute(select(Lead).where(Lead.org_id == org_id))).scalars():
            if rules.suppressed(rule, email=lead.email, domain=lead.domain, person_url=lead.person_url):
                lead.qualified = False
                if "İletişim hariç tutma listesinde" not in lead.score_notes:
                    lead.score_notes = ["İletişim hariç tutma listesinde", *lead.score_notes]
        await db.commit()
        return {"id": existing.id, "kind": kind, "value": value}


async def delete_suppression(org_id: int, suppression_id: int) -> None:
    async with session_maker() as db:
        row = await _owned(db, LeadSuppression, suppression_id, org_id)
        await db.delete(row)
        await db.commit()


def settings_view(s: LeadSettings) -> dict:
    return {"run_limit_micro": s.run_limit_micro, "day_limit_micro": s.day_limit_micro,
            "month_limit_micro": s.month_limit_micro, "retention_days": s.retention_days,
            "cache_ttl_hours": {**runs.DEFAULT_TTL_HOURS, **(s.cache_ttl_hours or {})},
            "prices_micro": s.prices_micro or {}}


async def get_settings_view(org_id: int) -> dict:
    async with session_maker() as db:
        return settings_view(await budget.ensure_settings(db, org_id))


async def save_settings(org_id: int, body: dict) -> dict:
    async with session_maker() as db:
        s = await budget.ensure_settings(db, org_id)
        for k in ("day_limit_micro", "month_limit_micro", "run_limit_micro"):
            if k in body:
                s.__setattr__(k, _int(body, k, 0, 0, 100_000 * 1_000_000))
        if "retention_days" in body:
            s.retention_days = _int(body, "retention_days", 365, 7, 3650)
        if isinstance(body.get("cache_ttl_hours"), dict):
            s.cache_ttl_hours = {k: max(0, min(24 * 365, int(v))) for k, v in body["cache_ttl_hours"].items()
                                 if k in runs.DEFAULT_TTL_HOURS and str(v).lstrip("-").isdigit()}
        if isinstance(body.get("prices_micro"), dict):
            s.prices_micro = {k: int(v) for k, v in body["prices_micro"].items()
                              if isinstance(k, str) and str(v).isdigit() and int(v) > 0}
        s.updated_at = _now()
        await db.commit()
        return settings_view(s)


async def purge_expired(org_id: int) -> dict:
    """Retention: drop leads not touched within `retention_days`, their evidence, expired cache."""
    async with session_maker() as db:
        s = await budget.ensure_settings(db, org_id)
        cutoff = _now() - timedelta(days=s.retention_days)
        old = list((await db.execute(select(Lead.id).where(
            Lead.org_id == org_id, Lead.updated_at < cutoff))).scalars())
        if old:
            await db.execute(delete(LeadEvidence).where(LeadEvidence.lead_id.in_(old)))
            await db.execute(delete(Lead).where(Lead.id.in_(old)))
        cache = await db.execute(delete(LeadCache).where(LeadCache.org_id == org_id, LeadCache.expires_at < _now()))
        await db.commit()
        return {"leads_deleted": len(old), "cache_deleted": cache.rowcount or 0}


async def delete_demo(org_id: int) -> dict:
    async with session_maker() as db:
        ids = list((await db.execute(select(Lead.id).where(Lead.org_id == org_id, Lead.demo.is_(True)))).scalars())
        if ids:
            await db.execute(delete(LeadEvidence).where(LeadEvidence.lead_id.in_(ids)))
            await db.execute(delete(Lead).where(Lead.id.in_(ids)))
        await db.commit()
        return {"deleted": len(ids)}


# ---- sources and overview ----------------------------------------------------------------------

async def sources(org_id: int, registry: Registry) -> dict:
    async with session_maker() as db:
        settings = await budget.ensure_settings(db, org_id)
        prices = dict(settings.prices_micro or {})
        secrets = {s.provider: s for s in (await db.execute(select(Secret).where(
            Secret.org_id == org_id, Secret.provider != ""))).scalars()}
    has_token = bool(registry_token())

    def row(adapter, kind: str) -> dict:
        price = adapter.price(prices)
        secret = secrets.get(adapter.service) if adapter.service else None
        missing = []
        if not adapter.demo:
            if secret is None:
                missing.append(f"{adapter.service} anahtarı bağlı değil")
            if not has_token:
                missing.append("registry token yok (TREG_SINGLE_USER=1 veya TREG_LEADS_TOKEN)")
            if price is None:
                missing.append("doğrulanmış ücret yok")
        state = ("demo" if adapter.demo else "error" if secret is not None and secret.health_status == "invalid"
                 else "connected" if not missing else "missing")
        return {"key": adapter.key, "kind": kind, "label": adapter.label, "demo": adapter.demo,
                "service": adapter.service, "data_note": adapter.data_note, "state": state,
                "missing": missing,
                "health": (secret.health_status if secret else None),
                "last_checked": _iso(secret.health_checked_at) if secret else None,
                "price": ({"ceiling_micro": price.ceiling_micro, "unit_micro": price.unit_micro,
                           "source": price.source, "checked": price.checked} if price else None)}

    return {"discovery": [row(a, "discovery") for a in registry.discovery.values()],
            "enrichment": [row(a, "enrichment") for a in registry.enrichers.values()],
            "registry_token": has_token}


async def overview(org_id: int) -> dict:
    day_start, month_start = budget.local_bounds()
    async with session_maker() as db:
        settings = await budget.ensure_settings(db, org_id)

        async def count(*where) -> int:
            return (await db.execute(select(func.count()).select_from(Lead).where(
                Lead.org_id == org_id, *where))).scalar_one()

        real = Lead.demo.is_(False)
        week_ago = _now() - timedelta(days=7)
        new_fit = await count(real, Lead.qualified.is_(True), Lead.discovered_at >= week_ago)
        review = await count(real, Lead.status == "review")
        demo_leads = await count(Lead.demo.is_(True))
        real_leads = await count(real)
        month_cost = await budget.committed(db, org_id, since=month_start)
        day_cost = await budget.committed(db, org_id, since=day_start)
        month_fit = await count(real, Lead.qualified.is_(True), Lead.discovered_at >= month_start)
        last = (await db.execute(select(LeadRun).where(LeadRun.org_id == org_id)
                                 .order_by(LeadRun.id.desc()).limit(1))).scalar_one_or_none()
        trend = []
        for i in range(6, -1, -1):
            start = day_start - timedelta(days=i)
            end = start + timedelta(days=1)
            leads = (await db.execute(select(func.count()).select_from(Lead).where(
                Lead.org_id == org_id, real, Lead.discovered_at >= start, Lead.discovered_at < end))).scalar_one()
            fit = (await db.execute(select(func.count()).select_from(Lead).where(
                Lead.org_id == org_id, real, Lead.qualified.is_(True),
                Lead.discovered_at >= start, Lead.discovered_at < end))).scalar_one()
            cost = (await db.execute(select(func.coalesce(func.sum(LeadSpend.actual_micro), 0)).where(
                LeadSpend.org_id == org_id, LeadSpend.state == "settled",
                LeadSpend.created_at >= start, LeadSpend.created_at < end))).scalar_one()
            trend.append({"day": (start + timedelta(hours=3)).date().isoformat(),
                          "leads": leads, "qualified": fit, "cost_micro": int(cost)})
        uncertain = (await db.execute(select(func.coalesce(func.sum(LeadSpend.reserved_micro), 0)).where(
            LeadSpend.org_id == org_id, LeadSpend.state == "uncertain",
            LeadSpend.created_at >= month_start))).scalar_one()
    return {
        "new_fit_7d": new_fit, "pending_review": review, "real_leads": real_leads, "demo_leads": demo_leads,
        "month_api_cost_micro": month_cost, "month_llm_cost_micro": 0, "day_api_cost_micro": day_cost,
        "month_uncertain_micro": int(uncertain),
        "cost_per_fit_micro": (month_cost // month_fit) if month_fit else None,
        "limits": settings_view(settings), "last_run": run_view(last) if last else None, "trend": trend,
    }
