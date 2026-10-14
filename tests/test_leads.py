"""Lead Radar: dedup, scoring, team isolation, suppression, the concurrent budget limit,
timeouts and partial failures, CSV safety, the demo flow end to end, and the daily schedule."""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import date, datetime, timezone

import pytest
from sqlmodel import select

from conftest import verified_signup

from treg.application.leads import budget, runs, scheduler, service
from treg.application.leads.providers import (DemoDiscovery, DemoEnricher, EmailResult, Hit, Price,
                                              ProviderError, Registry, SearchRequest, SearchResult)
from treg.domain.leads import rules
from treg.infra.db import session_maker
from treg.models import Lead, LeadRun, LeadSettings, LeadSpend, Membership, User


# ---- pure rules --------------------------------------------------------------------------------

def test_normalization_and_dedup_keys():
    assert rules.normalize_domain("https://www.Acme.com.tr/about") == "acme.com.tr"
    assert rules.normalize_domain("ali@Acme.io") == "acme.io"
    assert rules.normalize_url("http://www.x.com/a/?utm_source=t&id=3#frag") == "https://x.com/a?id=3"
    # person beats company beats source page; the same person via two spellings is one key
    assert rules.dedup_key(domain="acme.io", person_url="https://www.linkedin.com/in/ali/") == \
        rules.dedup_key(person_url="linkedin.com/in/ali?utm_medium=x")
    assert rules.dedup_key(domain="https://acme.io", source_url="https://a.com/p") == "d:acme.io"
    assert rules.dedup_key(source_url="https://reddit.com/r/x/1") == "u:https://reddit.com/r/x/1"
    assert rules.dedup_key() == ""


def test_score_is_explained_and_unknown_is_not_fit():
    today = date(2026, 10, 14)
    icp = rules.Icp(problems=["stok takibi"], sectors=["lojistik"], roles=[], geographies=["İstanbul"],
                    competitors=["Logo"], exclusions=["ajans"])
    hit = rules.Candidate(text="Stok takibi için çözüm arıyoruz, Logo'dan memnun değiliz",
                          company="Anadolu Lojistik", location="istanbul", signal_date="2026-10-10")
    s = rules.score(icp, hit, today)
    assert (s.fit, s.signal, s.recency) == (40, 25, 20) and s.total == 85 and s.qualified
    assert any("Rol tanımlı değil" in n for n in s.notes)          # unknown, not assumed
    # exclusions apply first and zero everything
    ex = rules.score(icp, rules.Candidate(text="dijital ajans stok takibi"), today)
    assert ex.excluded and ex.total == 0 and not ex.qualified
    # no evidence -> never qualified; no date -> no recency points
    none = rules.score(icp, rules.Candidate(text="stok takibi lojistik", evidence_count=0), today)
    assert not none.qualified and none.recency == 0
    # an empty ICP gives no fit at all
    assert rules.score(rules.Icp(), hit, today).fit == 0


def test_suppression_and_csv_cells():
    rules_ = [("domain", "acme.io"), ("email", "x@y.com"), ("person_url", "https://linkedin.com/in/ali")]
    assert rules.suppressed(rules_, email="someone@acme.io")
    assert rules.suppressed(rules_, email="X@Y.com")
    assert rules.suppressed(rules_, person_url="http://www.linkedin.com/in/ali/")
    assert not rules.suppressed(rules_, email="a@b.com", domain="b.com")
    for bad in ("=HYPERLINK(1)", "+1", "-2", "@SUM(A1)", "\tx"):
        assert rules.csv_cell(bad).startswith("'")
    assert rules.csv_cell("Acme") == "Acme"


# ---- helpers -----------------------------------------------------------------------------------

async def _org_id(email: str) -> int:
    async with session_maker() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        return (await db.execute(select(Membership.org_id).where(Membership.user_id == user.id))).scalars().first()


async def _wait_runs():
    while runs._tasks:
        await asyncio.gather(*list(runs._tasks))


async def _limits(org_id: int, run=0, day=0, month=0):
    async with session_maker() as db:
        s = await budget.ensure_settings(db, org_id)
        s.run_limit_micro, s.day_limit_micro, s.month_limit_micro = run, day, month
        await db.commit()


class _PaidDiscovery:
    key, label, demo, service, data_note, cache_kind = "paid", "Test kaynak", False, "paid", "", "search"

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = 0

    def price(self, prices):
        return Price(10_000, 5_000, "test")

    def cache_key(self, req):
        return f"paid:{req.query}"

    async def search(self, req):
        self.calls += 1
        return await self.behaviour(req, self.calls)


# ---- the demo flow through HTTP ----------------------------------------------------------------

async def test_demo_flow_end_to_end_keeps_notes_and_exports_safely(clients):
    c = clients
    icp = (await c.post("/leads/api/icps", json={
        "name": "Lojistik", "problems": "stok takibi, rota planlama", "sectors": ["lojistik"],
        "geographies": ["İstanbul", "İzmir"], "roles": ["Operasyon"], "exclusions": ["ajans"]})).json()
    camp = await c.post("/leads/api/campaigns", json={
        "name": "Pilot", "icp_id": icp["id"], "provider": "demo", "enrich_provider": "demo",
        "queries": ["stok takibi"], "result_limit": 20, "enrich_limit": 5})
    assert camp.status_code == 200, camp.text
    cid = camp.json()["id"]
    run = await c.post(f"/leads/api/campaigns/{cid}/run")
    assert run.status_code == 200, run.text
    await _wait_runs()
    runs_ = (await c.get("/leads/api/runs")).json()
    assert runs_[0]["status"] == "succeeded" and runs_[0]["demo"] and runs_[0]["api_cost_micro"] == 0
    leads = (await c.get("/leads/api/leads")).json()["leads"]
    assert leads and all(l["demo"] for l in leads)
    assert sum(1 for l in leads if l["email"]) <= 5
    top = leads[0]
    detail = (await c.get(f"/leads/api/leads/{top['id']}")).json()
    assert detail["evidence"] and detail["score_notes"]

    await c.patch(f"/leads/api/leads/{top['id']}", json={"status": "contacted", "note": "Pazartesi aradım"})
    await c.post(f"/leads/api/campaigns/{cid}/run")
    await _wait_runs()
    again = (await c.get(f"/leads/api/leads/{top['id']}")).json()
    assert (again["status"], again["note"]) == ("contacted", "Pazartesi aradım")
    assert (await c.get("/leads/api/leads")).json()["total"] == len(leads)    # merged, not duplicated

    # demo leads do not count as real success on the overview
    ov = (await c.get("/leads/api/overview")).json()
    assert ov["real_leads"] == 0 and ov["demo_leads"] == len(leads) and ov["cost_per_fit_micro"] is None

    await c.patch(f"/leads/api/leads/{top['id']}", json={"note": "=HYPERLINK(\"http://evil\")"})
    exported = (await c.get("/leads/api/leads.csv")).text
    rows = list(csv.reader(io.StringIO(exported.lstrip("﻿"))))
    assert rows[0][0] == "Şirket"
    assert all(not cell.startswith(("=", "+", "@")) for row in rows for cell in row)
    # the exporter's guard is undone on import, and the row merges into the existing lead
    imported = (await c.post("/leads/api/leads/import", json={"csv": exported})).json()
    assert imported["created"] == 0 and imported["merged"] == len(leads)


async def test_teams_cannot_see_each_others_leads(clients):
    c = clients
    camp = (await c.post("/leads/api/campaigns", json={"name": "A", "queries": ["x"]})).json()
    lead = await c.post("/leads/api/leads", json={"company": "Acme", "domain": "acme.io", "url": "https://acme.io/blog"})
    assert lead.status_code == 200
    mine = (await c.get("/leads/api/leads")).json()["leads"][0]

    other = await verified_signup(c, json={"email": "rakip@example.org"})
    h = {"X-Treg-Token": other.json()["token"]}
    assert (await c.get("/leads/api/leads", headers=h)).json() == {"total": 0, "leads": []}
    assert (await c.get(f"/leads/api/leads/{mine['id']}", headers=h)).status_code == 404
    assert (await c.patch(f"/leads/api/leads/{mine['id']}", json={"note": "x"}, headers=h)).status_code == 404
    assert (await c.delete(f"/leads/api/leads/{mine['id']}", headers=h)).status_code == 404
    assert (await c.post(f"/leads/api/campaigns/{camp['id']}/run", headers=h)).status_code == 404
    assert (await c.get("/leads/api/campaigns", headers=h)).json() == []


async def test_suppressed_people_are_never_enriched(clients):
    c = clients
    org = await _org_id("tim@superdesign.dev")
    icp = (await c.post("/leads/api/icps", json={"name": "I", "problems": ["stok takibi"]})).json()
    blocked = (await DemoDiscovery().search(SearchRequest("stok takibi", 30, 20))).hits[0].domain
    await c.post("/leads/api/suppressions", json={"kind": "domain", "value": f"https://www.{blocked}"})
    enricher = DemoEnricher()
    asked: list[str] = []

    async def find_email(name, domain):
        asked.append(domain)
        return EmailResult(email=f"x@{domain}", status="found", cost_micro=0)
    enricher.find_email = find_email
    registry = Registry(discovery={"demo": DemoDiscovery()}, enrichers={"demo": enricher})
    camp = await service.save_campaign(org, {"name": "S", "queries": ["stok takibi"], "enrich_provider": "demo",
                                             "icp_id": icp["id"],
                                             "enrich_limit": 50}, registry)
    await service.start_run(org, camp["id"], registry)
    await _wait_runs()
    assert asked and blocked not in asked
    async with session_maker() as db:
        sup = (await db.execute(select(Lead).where(Lead.domain == blocked))).scalars().all()
    assert sup and all(not l.qualified and not l.email for l in sup)


# ---- money -------------------------------------------------------------------------------------

async def test_concurrent_reservations_never_pass_the_limit(clients):
    org = await _org_id("tim@superdesign.dev")
    await _limits(org, day=50_000, month=1_000_000)

    async def one():
        async with session_maker() as db:
            try:
                return await budget.reserve(db, org_id=org, run_id=None, provider="p", amount=10_000, run_limit=0)
            except budget.BudgetExceeded:
                return None
    got = await asyncio.gather(*[one() for _ in range(12)])
    assert sum(1 for g in got if g) == 5
    async with session_maker() as db:
        assert await budget.committed(db, org) == 50_000


async def test_unset_limits_block_paid_calls_but_not_demo(clients):
    org = await _org_id("tim@superdesign.dev")
    paid = _PaidDiscovery(lambda req, n: _ok(req))
    registry = Registry(discovery={"paid": paid, "demo": DemoDiscovery()})
    camp = await service.save_campaign(org, {"name": "P", "provider": "paid", "queries": ["a"]}, registry)
    await service.start_run(org, camp["id"], registry)
    await _wait_runs()
    run = (await service.list_runs(org))[0]
    assert paid.calls == 0 and run["issues"][0]["kind"] == "budget"


async def _ok(req):
    return SearchResult(hits=[Hit(url=f"https://{req.query}.example/p", title="stok takibi", domain=f"{req.query}.example")],
                        cost_micro=5_000)


async def test_timeout_keeps_the_reserve_and_partial_failures_are_reported(clients):
    org = await _org_id("tim@superdesign.dev")
    await _limits(org, run=100_000, day=100_000, month=100_000)

    async def behaviour(req, n):
        if req.query == "yavas":
            raise ProviderError("timeout", "zaman aşımı", charged=True)
        if req.query == "limit":
            raise ProviderError("rate_limit", "429", retryable=True)
        return await _ok(req)
    paid = _PaidDiscovery(behaviour)
    registry = Registry(discovery={"paid": paid})
    camp = await service.save_campaign(org, {"name": "P", "provider": "paid", "budget_run_micro": 100_000,
                                             "queries": ["iyi", "yavas", "limit"]}, registry)
    orig = asyncio.sleep
    runs.asyncio.sleep = lambda s: orig(0)      # no real backoff in tests
    try:
        await service.start_run(org, camp["id"], registry)
        await _wait_runs()
    finally:
        runs.asyncio.sleep = orig
    run = (await service.list_runs(org))[0]
    kinds = [i["kind"] for i in run["issues"]]
    assert run["status"] == "partial" and "timeout" in kinds and "rate_limit" in kinds
    assert paid.calls == 1 + 1 + 3                 # the timeout is not retried; 429 twice more
    async with session_maker() as db:
        states = sorted(s.state for s in (await db.execute(select(LeadSpend))).scalars())
        assert states == ["released", "released", "released", "settled", "uncertain"]
        # the uncertain timeout stays counted at its reserve
        assert await budget.committed(db, org) == 5_000 + 10_000
    assert run["api_cost_micro"] == 5_000


# ---- schedule ----------------------------------------------------------------------------------

async def test_schedule_runs_once_per_day_and_survives_restart(clients):
    org = await _org_id("tim@superdesign.dev")
    registry = Registry(discovery={"demo": DemoDiscovery()})
    camp = await service.save_campaign(org, {"name": "D", "queries": ["stok"], "status": "active",
                                             "schedule_daily": True, "schedule_hour": 9}, registry)
    early = datetime(2026, 10, 14, 5, 0, tzinfo=timezone.utc)      # 08:00 Istanbul
    late = datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc)       # 10:00 Istanbul
    assert await scheduler.tick(registry, early) == []
    first = await scheduler.tick(registry, late)
    assert len(first) == 1
    assert await scheduler.tick(registry, late) == []              # same slot: never twice
    # a run a crash left behind is closed, not resumed
    async with session_maker() as db:
        db.add(LeadRun(org_id=org, campaign_id=camp["id"], status="running"))
        await db.commit()
    assert await runs.recover_interrupted() == 1
    async with session_maker() as db:
        slots = [r.slot for r in (await db.execute(select(LeadRun).where(LeadRun.trigger == "scheduled"))).scalars()]
    assert slots == ["2026-10-14"]


async def test_settings_and_sources_show_missing_keys(clients):
    c = clients
    src = (await c.get("/leads/api/sources")).json()
    tavily = next(s for s in src["discovery"] if s["key"] == "tavily")
    assert tavily["state"] == "missing" and any("anahtar" in m for m in tavily["missing"])
    assert tavily["price"]["ceiling_micro"] > 0 and "katalog" in tavily["price"]["source"]
    saved = (await c.put("/leads/api/settings", json={"day_limit_micro": 500_000, "month_limit_micro": 5_000_000,
                                                      "cache_ttl_hours": {"search": 6}})).json()
    assert saved["cache_ttl_hours"]["search"] == 6 and saved["day_limit_micro"] == 500_000
