"""HTTP routes for Lead Radar: the page at `/leads` and its JSON API under `/leads/api/`.

Every API route resolves the caller's team through `require_member`, and the use cases filter
every query by that team. Reads need membership; writes need `member` or above.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..application.leads import service
from ..application.leads.providers import default_registry
from ..domain.identity import session as sess
from ..domain.identity.access import Caller, _require_can_register, _user_from_session, require_member
from ..infra.db import get_session
from .auth_helpers import _is_https
from .web import _WEB_DIR, _local_owner

app = APIRouter()
_PAGE = _WEB_DIR / "dashboard" / "leads.html"


def _registry(request: Request):
    return default_registry(lambda: request.app.state.http)


def _errors(exc: Exception) -> HTTPException:
    if isinstance(exc, service.NotFound):
        return HTTPException(404, "bulunamadı")
    return HTTPException(400, str(exc))


async def _do(coro):
    try:
        return await coro
    except (service.NotFound, service.Invalid) as exc:
        raise _errors(exc) from None


def _writer(caller: Caller) -> Caller:
    _require_can_register(caller)
    return caller


@app.get("/leads", include_in_schema=False)
async def leads_page(request: Request, treg_session: str = Cookie(default=""),
                     db: AsyncSession = Depends(get_session)):
    """The Lead Radar app. On a single-user local box it opens signed in, exactly like /app."""
    if not _PAGE.exists():
        raise HTTPException(503, "Lead Radar not built: run scripts/build-dashboard.sh")
    signed_in = await _user_from_session(treg_session, db)
    owner = await _local_owner(db) if not signed_in else None
    resp = HTMLResponse(_PAGE.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "private, no-store", "Vary": "Cookie"})
    if owner is not None:
        resp.set_cookie(sess.COOKIE, sess.make_session(owner.id, token_version=owner.token_version),
                        httponly=True, samesite="lax", secure=_is_https(request), max_age=sess.TTL_SECONDS)
    return resp


@app.get("/leads/api/overview")
async def overview(caller: Caller = Depends(require_member)) -> dict:
    return await service.overview(caller.org_id)


@app.get("/leads/api/sources")
async def sources(request: Request, caller: Caller = Depends(require_member)) -> dict:
    return await service.sources(caller.org_id, _registry(request))


# ---- ICP & campaigns ---------------------------------------------------------------------------

@app.get("/leads/api/icps")
async def list_icps(caller: Caller = Depends(require_member)) -> list[dict]:
    return await service.list_icps(caller.org_id)


@app.post("/leads/api/icps")
async def create_icp(body: dict = Body(...), caller: Caller = Depends(require_member)) -> dict:
    return await _do(service.save_icp(_writer(caller).org_id, body))


@app.put("/leads/api/icps/{icp_id}")
async def update_icp(icp_id: int, body: dict = Body(...), caller: Caller = Depends(require_member)) -> dict:
    return await _do(service.save_icp(_writer(caller).org_id, body, icp_id))


@app.get("/leads/api/campaigns")
async def list_campaigns(caller: Caller = Depends(require_member)) -> list[dict]:
    return await service.list_campaigns(caller.org_id)


@app.post("/leads/api/campaigns")
async def create_campaign(request: Request, body: dict = Body(...),
                          caller: Caller = Depends(require_member)) -> dict:
    return await _do(service.save_campaign(_writer(caller).org_id, body, _registry(request)))


@app.put("/leads/api/campaigns/{campaign_id}")
async def update_campaign(campaign_id: int, request: Request, body: dict = Body(...),
                          caller: Caller = Depends(require_member)) -> dict:
    return await _do(service.save_campaign(_writer(caller).org_id, body, _registry(request), campaign_id))


@app.delete("/leads/api/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int, caller: Caller = Depends(require_member)) -> dict:
    await _do(service.delete_campaign(_writer(caller).org_id, campaign_id))
    return {"ok": True}


@app.post("/leads/api/campaigns/{campaign_id}/run")
async def run_campaign(campaign_id: int, request: Request, caller: Caller = Depends(require_member)) -> dict:
    return await _do(service.start_run(_writer(caller).org_id, campaign_id, _registry(request)))


@app.get("/leads/api/runs")
async def list_runs(campaign_id: int | None = None, caller: Caller = Depends(require_member)) -> list[dict]:
    return await service.list_runs(caller.org_id, campaign_id)


@app.post("/leads/api/runs/{run_id}/stop")
async def stop_run(run_id: int, caller: Caller = Depends(require_member)) -> dict:
    return await _do(service.stop_run(_writer(caller).org_id, run_id))


# ---- leads -------------------------------------------------------------------------------------

def _filters(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in
            ("q", "status", "qualified", "campaign_id", "min_score", "sort", "demo", "email")}


@app.get("/leads/api/leads")
async def list_leads(request: Request, caller: Caller = Depends(require_member)) -> dict:
    try:
        return await service.list_leads(caller.org_id, _filters(request))
    except ValueError:
        raise HTTPException(400, "geçersiz filtre") from None


@app.get("/leads/api/leads.csv")
async def export_csv(request: Request, caller: Caller = Depends(require_member)):
    try:
        text = await service.export_csv(caller.org_id, _filters(request))
    except ValueError:
        raise HTTPException(400, "geçersiz filtre") from None
    return PlainTextResponse(text, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="leadler.csv"'})


@app.post("/leads/api/leads")
async def add_lead(body: dict = Body(...), caller: Caller = Depends(require_member)) -> dict:
    return await _do(service.add_leads(_writer(caller).org_id, [body], provider="manuel"))


@app.post("/leads/api/leads/import")
async def import_csv(body: dict = Body(...), caller: Caller = Depends(require_member)) -> dict:
    text = str(body.get("csv") or "")
    if len(text) > 5_000_000:
        raise HTTPException(413, "CSV çok büyük (en fazla 5 MB)")
    try:
        rows = service.parse_csv(text)
    except service.Invalid as exc:
        raise _errors(exc) from None
    return await _do(service.add_leads(_writer(caller).org_id, rows, provider="csv"))


@app.post("/leads/api/leads/delete-demo")
async def delete_demo(caller: Caller = Depends(require_member)) -> dict:
    return await service.delete_demo(_writer(caller).org_id)


@app.get("/leads/api/leads/{lead_id}")
async def get_lead(lead_id: int, caller: Caller = Depends(require_member)) -> dict:
    return await _do(service.get_lead(caller.org_id, lead_id))


@app.patch("/leads/api/leads/{lead_id}")
async def update_lead(lead_id: int, body: dict = Body(...), caller: Caller = Depends(require_member)) -> dict:
    return await _do(service.update_lead(_writer(caller).org_id, lead_id, body))


@app.delete("/leads/api/leads/{lead_id}")
async def delete_lead(lead_id: int, caller: Caller = Depends(require_member)) -> dict:
    await _do(service.delete_lead(_writer(caller).org_id, lead_id))
    return {"ok": True}


@app.post("/leads/api/leads/{lead_id}/enrich")
async def enrich_lead(lead_id: int, request: Request, body: dict = Body(default={}),
                      caller: Caller = Depends(require_member)) -> dict:
    return await _do(service.enrich_lead(_writer(caller).org_id, lead_id,
                                         str(body.get("provider") or ""), _registry(request)))


@app.post("/leads/api/leads/{lead_id}/draft")
async def draft(lead_id: int, caller: Caller = Depends(require_member)) -> dict:
    lead = await _do(service.get_lead(caller.org_id, lead_id))
    icps = await service.list_icps(caller.org_id)
    return {"draft": service.draft_message(lead, icps[0] if icps else None), "sent": False}


# ---- suppression, settings, retention ------------------------------------------------------------

@app.get("/leads/api/suppressions")
async def list_suppressions(caller: Caller = Depends(require_member)) -> list[dict]:
    return await service.list_suppressions(caller.org_id)


@app.post("/leads/api/suppressions")
async def add_suppression(body: dict = Body(...), caller: Caller = Depends(require_member)) -> dict:
    return await _do(service.add_suppression(_writer(caller).org_id, str(body.get("kind") or ""),
                                             str(body.get("value") or ""), str(body.get("reason") or "")))


@app.delete("/leads/api/suppressions/{suppression_id}")
async def delete_suppression(suppression_id: int, caller: Caller = Depends(require_member)) -> dict:
    await _do(service.delete_suppression(_writer(caller).org_id, suppression_id))
    return {"ok": True}


@app.get("/leads/api/settings")
async def get_settings(caller: Caller = Depends(require_member)) -> dict:
    return await service.get_settings_view(caller.org_id)


@app.put("/leads/api/settings")
async def save_settings(body: dict = Body(...), caller: Caller = Depends(require_member)) -> dict:
    return await _do(service.save_settings(_writer(caller).org_id, body))


@app.post("/leads/api/retention/purge")
async def purge(caller: Caller = Depends(require_member)) -> dict:
    return await service.purge_expired(_writer(caller).org_id)


router = app
