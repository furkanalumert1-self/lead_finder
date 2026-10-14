"""Provider adapters: the only code that knows a source's request and answer shape.

Real adapters do not hold keys. They call this registry's own `/call/<endpoint id>` with a team
token, so the team's connected key is injected server-side, masked in errors and never reaches
this module, the browser or a log. Prices come from the shipped catalog (cost row x the provider's
credit rate in fx.yaml) or from a price the team typed in; with neither, the call is blocked.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

import httpx

from ...domain.leads.rules import is_profile_url, normalize_domain

MICRO = 1_000_000


@dataclass
class SearchRequest:
    query: str
    days: int
    limit: int
    signal_type: str = "content"


@dataclass
class Hit:
    url: str
    title: str = ""
    snippet: str = ""
    published: str = ""            # YYYY-MM-DD or ""
    company: str = ""
    domain: str = ""
    person_name: str = ""
    person_role: str = ""
    person_url: str = ""
    location: str = ""


@dataclass
class SearchResult:
    hits: list[Hit]
    cost_micro: int


@dataclass
class EmailResult:
    email: str
    status: str                    # found | verified | not_found
    cost_micro: int


class ProviderError(Exception):
    """A failed call, by kind. `charged` says whether money may have moved: True only when we
    cannot know (a timeout after the request left), so the reserve is kept, never zeroed."""

    KINDS = ("timeout", "rate_limit", "missing_credential", "upstream", "bad_response", "unknown_price")

    def __init__(self, kind: str, message: str, *, charged: bool = False, retryable: bool = False):
        super().__init__(message)
        self.kind = kind
        self.charged = charged
        self.retryable = retryable


@dataclass
class Price:
    ceiling_micro: int             # the most one call can cost; what is reserved
    unit_micro: int                # one provider credit (or one call) in micro-USD
    source: str                    # where the figure comes from, shown in the UI
    checked: str = ""


class Discovery(Protocol):
    key: str
    label: str
    demo: bool
    service: str                   # the treg provider whose key it uses ("" for demo)
    data_note: str
    cache_kind: str

    def price(self, prices: dict) -> Price | None: ...
    def cache_key(self, req: SearchRequest) -> str: ...
    async def search(self, req: SearchRequest) -> SearchResult: ...


class Enricher(Protocol):
    key: str
    label: str
    demo: bool
    service: str
    data_note: str
    cache_kind: str

    def price(self, prices: dict) -> Price | None: ...
    def cache_key(self, full_name: str, domain: str) -> str: ...
    async def find_email(self, full_name: str, domain: str) -> EmailResult: ...


def _hash(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ---- the registry transport ---------------------------------------------------------------------

def registry_token() -> str:
    """A team token for this registry's own /call/: `TREG_LEADS_TOKEN`, else the single-user token
    file the server writes on a local box. Never logged, never sent anywhere but `registry_url`."""
    token = os.environ.get("TREG_LEADS_TOKEN", "").strip()
    if token:
        return token
    from ...config import get_settings
    path = Path(get_settings().single_user_token_file).expanduser()
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def registry_url() -> str:
    from ...config import get_settings
    return os.environ.get("TREG_LEADS_REGISTRY_URL", "").strip() or get_settings().public_url.rstrip("/")


class RegistryCaller:
    """POST/GET `<registry>/call/<endpoint id>` with a team token; maps failures to kinds."""

    def __init__(self, client_factory, *, base_url: str | None = None, token: str | None = None,
                 timeout: float = 30.0):
        self._client_factory = client_factory
        self._base = base_url
        self._token = token
        self._timeout = timeout

    async def call(self, endpoint_id: str, *, method: str = "GET", params: dict | None = None,
                   body: dict | None = None) -> dict:
        token = self._token if self._token is not None else registry_token()
        if not token:
            raise ProviderError("missing_credential",
                                "Registry token yok: TREG_SINGLE_USER=1 ile başlatın veya TREG_LEADS_TOKEN verin")
        url = f"{(self._base or registry_url()).rstrip('/')}/call/{endpoint_id}"
        try:
            resp = await self._client_factory().request(
                method, url, params=params, json=body,
                headers={"X-Treg-Token": token}, timeout=self._timeout)
        except httpx.TimeoutException:
            # The request may have reached the provider and been billed: keep the reserve.
            raise ProviderError("timeout", "Sağlayıcı zaman aşımına uğradı", charged=True) from None
        except httpx.TransportError as exc:
            raise ProviderError("upstream", f"Bağlantı kurulamadı: {type(exc).__name__}",
                                retryable=isinstance(exc, httpx.ConnectError)) from None
        if resp.status_code == 429:
            raise ProviderError("rate_limit", "Sağlayıcı hız sınırına takıldı (429)", retryable=True)
        detail = _detail(resp)
        low = detail.lower()
        if resp.status_code in (401, 402, 403) or (
                resp.status_code >= 400 and ("credential" in low or "not connected" in low or "no key" in low)):
            raise ProviderError("missing_credential", f"Anahtar eksik veya reddedildi ({resp.status_code}): {detail[:160]}")
        if resp.status_code >= 500:
            raise ProviderError("upstream", f"Sağlayıcı hatası ({resp.status_code}): {detail[:160]}")
        if resp.status_code >= 400:
            raise ProviderError("bad_response", f"İstek reddedildi ({resp.status_code}): {detail[:160]}")
        try:
            data = resp.json()
        except ValueError:
            raise ProviderError("bad_response", "Sağlayıcı JSON döndürmedi") from None
        if not isinstance(data, dict):
            raise ProviderError("bad_response", "Beklenmeyen yanıt biçimi")
        return data


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(body, dict):
        d = body.get("detail") or body.get("error") or body.get("message") or ""
        if isinstance(d, dict):
            d = d.get("message") or d.get("error") or json.dumps(d)[:200]
        return str(d)
    return ""


# ---- catalog prices ----------------------------------------------------------------------------

def catalog_price(endpoint_id: str, service: str) -> Price | None:
    """The catalog's documented ceiling for one call, in micro-USD, or None when it has none."""
    from ...domain.catalog import store
    cat = store.load()
    ep = cat.by_id.get(endpoint_id)
    rate = cat.credit_rates.get(service)
    cost = (ep or {}).get("cost") or {}
    if not ep or not rate or cost.get("currency") != "credit":
        return None
    values = [cost.get("value"), (cost.get("fallback") or {}).get("value")]
    values += [row.get("value") for row in cost.get("table") or []]
    credits = max((float(v) for v in values if v is not None), default=None)
    if credits is None:
        return None
    unit = int(round(rate * MICRO))
    return Price(ceiling_micro=int(round(credits * rate * MICRO)), unit_micro=unit,
                 source=f"katalog: {cost.get('source_url') or 'fx.yaml'}", checked=str(cost.get("checked") or ""))


def _override(prices: dict, key: str) -> Price | None:
    """A per-call price the team entered after checking its own plan (micro-USD)."""
    value = prices.get(key)
    if isinstance(value, int) and value > 0:
        return Price(ceiling_micro=value, unit_micro=value, source="ayarlarda girilen fiyat")
    return None


# ---- Demo -------------------------------------------------------------------------------------

_DEMO_COMPANIES = [
    ("Anadolu Lojistik", "anadolu-lojistik.example", "İstanbul", "Operasyon Müdürü", "Elif Kaya"),
    ("Ege Gıda Dağıtım", "ege-gida.example", "İzmir", "Satın Alma Müdürü", "Mert Demir"),
    ("Kuzey Yazılım", "kuzey-yazilim.example", "Ankara", "CTO", "Zeynep Arslan"),
    ("Marmara Tekstil", "marmara-tekstil.example", "Bursa", "Genel Müdür", "Can Yıldız"),
    ("Toros Enerji", "toros-enerji.example", "Adana", "IT Direktörü", "Ayşe Çelik"),
    ("Başkent Sağlık", "baskent-saglik.example", "Ankara", "Operasyon Direktörü", "Emre Şahin"),
    ("Akdeniz Turizm", "akdeniz-turizm.example", "Antalya", "Pazarlama Müdürü", "Deniz Aydın"),
    ("Karadeniz Lojistik", "karadeniz-lojistik.example", "Samsun", "Lojistik Müdürü", "Burak Koç"),
]


class DemoDiscovery:
    """Made-up companies on `.example` domains so the whole flow can be tried with no key and no
    money. Every row it produces is marked demo and never counts as real success."""
    key = "demo"
    label = "Demo veri"
    demo = True
    service = ""
    data_note = "Hiçbir dış sağlayıcıya veri gitmez; sonuçlar uydurmadır."
    cache_kind = "search"

    def __init__(self, today: date | None = None):
        self._today = today

    def price(self, prices: dict) -> Price | None:
        return Price(0, 0, "demo (ücretsiz)")

    def cache_key(self, req: SearchRequest) -> str:
        return _hash("demo", req.query, req.days, req.limit, req.signal_type)

    async def search(self, req: SearchRequest) -> SearchResult:
        today = self._today or date.today()
        seed = int(hashlib.sha256(req.query.encode()).hexdigest(), 16)
        hits = []
        for i in range(min(req.limit, 6)):
            company, domain, city, role, person = _DEMO_COMPANIES[(seed + i) % len(_DEMO_COMPANIES)]
            age = (seed >> i) % max(req.days, 1)
            topic = req.query.replace('"', "").strip()
            if req.signal_type == "hiring":
                title = f"{company}: {role} işe alım ilanı"
                text = f"{company} {city} ekibine {role} arıyor. İlanda şu konu geçiyor: {topic}."
            else:
                title = f"{person} ({company}) paylaştı: {topic}"
                text = (f"{company} olarak bu konuda sorun yaşıyoruz, tavsiye arıyoruz: {topic}. "
                        f"{city} merkezli ekip, {role} karar veriyor.")
            hits.append(Hit(
                url=f"https://{domain}/demo/{seed % 9973}-{i}", title=title, snippet=text,
                published=(today - timedelta(days=int(age))).isoformat(), company=company,
                domain=domain, person_name=person, person_role=role,
                person_url=f"https://{domain}/ekip/{person.split()[0].lower()}", location=city))
        return SearchResult(hits=hits, cost_micro=0)


class DemoEnricher:
    key = "demo"
    label = "Demo e-posta"
    demo = True
    service = ""
    data_note = "Hiçbir dış sağlayıcıya veri gitmez; e-postalar uydurmadır."
    cache_kind = "email"

    def price(self, prices: dict) -> Price | None:
        return Price(0, 0, "demo (ücretsiz)")

    def cache_key(self, full_name: str, domain: str) -> str:
        return _hash("demo-email", full_name, domain)

    async def find_email(self, full_name: str, domain: str) -> EmailResult:
        first = (full_name.split() or ["info"])[0].lower()
        first = first.translate(str.maketrans("çğıöşü", "cgiosu"))
        return EmailResult(email=f"{first}@{domain}", status="found", cost_micro=0)


# ---- Tavily: public web content ------------------------------------------------------------------

class TavilyDiscovery:
    """`tavily.web.search` at basic depth: public pages about the problem, or job posts."""
    key = "tavily"
    label = "Tavily web araması"
    demo = False
    service = "tavily"
    endpoint = "tavily.web.search"
    data_note = "Arama sorguları Tavily'ye (tavily.com) gider; kendi anahtarınızdan kredi düşer."
    cache_kind = "search"

    def __init__(self, caller: RegistryCaller):
        self._caller = caller
        self._unit = 0

    def price(self, prices: dict) -> Price | None:
        price = _override(prices, self.key) or catalog_price(self.endpoint, self.service)
        self._unit = price.unit_micro if price else 0
        return price

    def _body(self, req: SearchRequest) -> dict:
        query = req.query
        if req.signal_type == "hiring" and "hiring" not in query.lower() and "ilan" not in query.lower():
            query = f"{query} (hiring OR \"iş ilanı\" OR kariyer)"
        start = (date.today() - timedelta(days=max(req.days, 1))).isoformat()
        return {"query": query, "search_depth": "basic", "max_results": max(1, min(req.limit, 20)),
                "start_date": start, "include_usage": True}

    def cache_key(self, req: SearchRequest) -> str:
        return _hash(self.key, self._body(req))

    async def search(self, req: SearchRequest) -> SearchResult:
        data = await self._caller.call(self.endpoint, method="POST", body=self._body(req))
        results = data.get("results")
        if not isinstance(results, list):
            raise ProviderError("bad_response", "Tavily yanıtında results yok")
        hits = []
        for r in results:
            if not isinstance(r, dict) or not r.get("url"):
                continue
            url = str(r["url"])
            domain = "" if is_profile_url(url) else normalize_domain(url)
            hits.append(Hit(url=url, title=str(r.get("title") or "")[:300],
                            snippet=str(r.get("content") or "")[:1200],
                            published=str(r.get("published_date") or "")[:10], domain=domain,
                            company=domain.split(".")[0].replace("-", " ").title() if domain else ""))
        # The answer reports its own credits; without them the run settles at the reserved ceiling.
        credits = (data.get("usage") or {}).get("credits") if isinstance(data.get("usage"), dict) else None
        cost = int(round(float(credits) * self._unit)) if isinstance(credits, (int, float)) else -1
        return SearchResult(hits=hits, cost_micro=cost)


# ---- Hunter: work email by name + domain ----------------------------------------------------------

class HunterEnricher:
    """`hunter.people.email.find`: one search credit when an email is found; a miss is free."""
    key = "hunter"
    label = "Hunter e-posta bulucu"
    demo = False
    service = "hunter"
    endpoint = "hunter.people.email.find"
    data_note = "Kişi adı ve şirket domaini Hunter'a (hunter.io) gider; bulunan her e-posta kredi düşer."
    cache_kind = "email"

    def __init__(self, caller: RegistryCaller):
        self._caller = caller
        self._unit = 0

    def price(self, prices: dict) -> Price | None:
        price = _override(prices, self.key) or catalog_price(self.endpoint, self.service)
        self._unit = price.unit_micro if price else 0
        return price

    def cache_key(self, full_name: str, domain: str) -> str:
        return _hash(self.key, full_name.strip().lower(), domain)

    async def find_email(self, full_name: str, domain: str) -> EmailResult:
        data = await self._caller.call(self.endpoint, params={"domain": domain, "full_name": full_name})
        found = (data.get("data") or {}) if isinstance(data.get("data"), dict) else {}
        email = str(found.get("email") or "")
        if not email:
            return EmailResult(email="", status="not_found", cost_micro=0)
        verification = (found.get("verification") or {}).get("status") if isinstance(found.get("verification"), dict) else ""
        return EmailResult(email=email, status="verified" if verification == "valid" else "found",
                           cost_micro=self._unit)


@dataclass
class Registry:
    discovery: dict[str, Discovery] = field(default_factory=dict)
    enrichers: dict[str, Enricher] = field(default_factory=dict)


def default_registry(client_factory) -> Registry:
    caller = RegistryCaller(client_factory)
    return Registry(
        discovery={"demo": DemoDiscovery(), "tavily": TavilyDiscovery(caller)},
        enrichers={"demo": DemoEnricher(), "hunter": HunterEnricher(caller)},
    )
