"""The rules a lead is judged by. Deterministic and explainable: every point a score carries has a
sentence in `notes`, and a missing ICP field scores as unknown, never as a fit."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

STATUSES = ("new", "review", "fit", "contacted", "replied", "won", "dropped")
STATUS_LABELS = {
    "new": "Yeni", "review": "İncelenecek", "fit": "Uygun", "contacted": "İletişime geçildi",
    "replied": "Yanıtlandı", "won": "Kazanıldı", "dropped": "Elendi",
}
SUPPRESSION_KINDS = ("email", "domain", "person_url")

FIT_MAX, SIGNAL_MAX, RECENCY_MAX = 50, 30, 20
# A lead needs real evidence and at least this much fit to count as qualified.
QUALIFY_MIN_FIT = 20

_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|mc_[a-z]+|ref|ref_src|igshid|si)$", re.IGNORECASE)
_PROFILE_HOSTS = ("linkedin.com", "x.com", "twitter.com", "github.com", "reddit.com")

# First-person need or pain, Turkish and English. Matched on whole words after folding.
PAIN_PHRASES = (
    "arıyoruz", "arıyorum", "öneri", "önerisi", "tavsiye", "sorun", "sorunu", "sıkıntı",
    "zorlanıyoruz", "ihtiyacımız", "çözüm arıyoruz", "alternatif",
    "looking for", "recommend", "recommendation", "struggling", "need a", "we need",
    "alternative to", "switching from", "frustrated", "pain", "any suggestions",
)
HIRING_PHRASES = (
    "işe alım", "ilanı", "kariyer", "pozisyon", "aranıyor", "alıyoruz",
    "hiring", "we're hiring", "job", "career", "position", "vacancy", "opening",
)


def fold(text: str) -> str:
    """Case- and dot-insensitive form for matching Turkish and English alike."""
    return (text or "").replace("İ", "i").replace("I", "i").replace("ı", "i").casefold()


def _contains(haystack: str, needle: str) -> bool:
    needle = fold(needle).strip()
    if not needle:
        return False
    return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack) is not None


def normalize_domain(value: str) -> str:
    """`https://www.Acme.com.tr/x` -> `acme.com.tr`; an email's domain; "" when there is none."""
    value = (value or "").strip().lower()
    if not value:
        return ""
    if "@" in value and "/" not in value:
        value = value.rsplit("@", 1)[1]
    if "://" not in value:
        value = "//" + value
    host = (urlsplit(value).hostname or "").strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host if "." in host else ""


def normalize_url(value: str) -> str:
    """https, lower-case host without www, no fragment, no tracking parameters, no trailing slash."""
    value = (value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    host = parts.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not _TRACKING.match(k)])
    path = parts.path.rstrip("/")
    return urlunsplit(("https", host, path, query, ""))


def is_profile_url(url: str) -> bool:
    host = normalize_domain(url)
    return any(host == h or host.endswith("." + h) for h in _PROFILE_HOSTS)


def dedup_key(*, domain: str = "", person_url: str = "", source_url: str = "") -> str:
    """One lead per person when we know the person, else per company, else per source page."""
    person = normalize_url(person_url)
    if person:
        return "p:" + person
    dom = normalize_domain(domain)
    if dom:
        return "d:" + dom
    src = normalize_url(source_url)
    return "u:" + src if src else ""


def parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


@dataclass
class Icp:
    product: str = ""
    sectors: list[str] = field(default_factory=list)
    geographies: list[str] = field(default_factory=list)
    sizes: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    competitors: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)


@dataclass
class Candidate:
    """What a source said about one lead, before it is scored."""
    text: str = ""                # title + snippet + any page text the source returned
    company: str = ""
    domain: str = ""
    person_role: str = ""
    location: str = ""
    signal_type: str = "content"
    signal_date: str = ""
    evidence_count: int = 1


@dataclass
class Score:
    total: int
    fit: int
    signal: int
    recency: int
    notes: list[str]
    excluded: bool
    qualified: bool
    fit_reason: str


def _matches(haystack: str, terms: list[str]) -> list[str]:
    return [t for t in terms if _contains(haystack, t)]


def score(icp: Icp, c: Candidate, today: date) -> Score:
    """0-100: ICP fit 50, signal strength 30, recency 20. Hard exclusions apply first."""
    hay = fold(" ".join([c.text, c.company, c.domain, c.person_role, c.location]))
    notes: list[str] = []

    excluded = _matches(hay, icp.exclusions)
    if excluded:
        reason = "Dışlama ölçütü: " + ", ".join(excluded)
        return Score(0, 0, 0, 0, [reason], True, False, reason)

    fit = 0
    reasons: list[str] = []
    if not icp.problems:
        notes.append("Problem ifadesi tanımlı değil: problem uyumu bilinmiyor (0/20)")
    elif hits := _matches(hay, icp.problems):
        fit += 20
        notes.append(f"Problem ifadesi geçiyor: {', '.join(hits[:3])} (+20)")
        reasons.append("hedef problemden söz ediyor")
    else:
        notes.append("Problem ifadesi geçmiyor (0/20)")
    for label, terms, points, why in (
        ("Sektör", icp.sectors, 10, "sektör uyuyor"),
        ("Coğrafya", icp.geographies, 10, "bölge uyuyor"),
        ("Rol", icp.roles, 10, "rol uyuyor"),
    ):
        if not terms:
            notes.append(f"{label} tanımlı değil: bilinmiyor (0/{points})")
        elif hits := _matches(hay, terms):
            fit += points
            notes.append(f"{label} eşleşti: {', '.join(hits[:2])} (+{points})")
            reasons.append(why)
        else:
            notes.append(f"{label} bilinmiyor veya eşleşmedi (0/{points})")
    fit = min(fit, FIT_MAX)

    signal = 0
    phrases = HIRING_PHRASES if c.signal_type == "hiring" else PAIN_PHRASES
    if hits := _matches(hay, list(phrases)):
        signal += 15
        kind = "işe alım ifadesi" if c.signal_type == "hiring" else "ihtiyaç/şikâyet ifadesi"
        notes.append(f"Açık {kind}: {hits[0]} (+15)")
    if hits := _matches(hay, icp.competitors):
        signal += 10
        notes.append(f"Rakipten söz ediyor: {hits[0]} (+10)")
        reasons.append("rakip kullanıyor/arıyor olabilir")
    if c.evidence_count > 1:
        extra = min(5 * (c.evidence_count - 1), 10)
        signal += extra
        notes.append(f"{c.evidence_count} bağımsız kanıt (+{extra})")
    signal = min(signal, SIGNAL_MAX)

    recency = 0
    day = parse_day(c.signal_date)
    if day is None:
        notes.append("Sinyal tarihi bilinmiyor (0/20)")
    else:
        age = (today - day).days
        recency = 20 if age <= 7 else 14 if age <= 30 else 7 if age <= 90 else 0
        notes.append(f"Sinyal {max(age, 0)} gün önce (+{recency})")

    total = fit + signal + recency
    qualified = c.evidence_count > 0 and fit >= QUALIFY_MIN_FIT
    fit_reason = ("; ".join(reasons) if reasons else "ICP ile eşleşme bulunamadı").capitalize()
    return Score(total, fit, signal, recency, notes, False, qualified, fit_reason)


def suppressed(rules: list[tuple[str, str]], *, email: str = "", domain: str = "",
               person_url: str = "") -> bool:
    """True when any (kind, value) rule covers this person. Values are compared normalized."""
    email = (email or "").strip().lower()
    doms = {normalize_domain(domain), normalize_domain(email)} - {""}
    person = normalize_url(person_url)
    for kind, value in rules:
        if kind == "email" and email and value.strip().lower() == email:
            return True
        if kind == "domain" and normalize_domain(value) in doms:
            return True
        if kind == "person_url" and person and normalize_url(value) == person:
            return True
    return False


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\n")


def csv_cell(value: object) -> str:
    """A cell a spreadsheet will show as text: a leading formula character is neutralized."""
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_START):
        return "'" + text
    return text
