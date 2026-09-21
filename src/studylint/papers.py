from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from rapidfuzz import fuzz


CROSSREF_API = "https://api.crossref.org"
DOI_PATTERN = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)",
    re.IGNORECASE,
)


class PaperLookupError(RuntimeError):
    """论文元数据服务暂时无法使用。"""


@dataclass(frozen=True)
class PaperMatch:
    title: str
    doi: str
    authors: tuple[str, ...]
    year: str
    venue: str
    publisher: str
    work_type: str
    url: str
    similarity: int


@dataclass(frozen=True)
class PaperVerification:
    query: str
    query_type: str
    matches: tuple[PaperMatch, ...]


def extract_doi(value: str) -> str | None:
    match = DOI_PATTERN.search(value.strip())
    if not match:
        return None
    doi = match.group(1).rstrip(".,;。；").lower()
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1]
    return doi


def _request_json(url: str, timeout: int = 12) -> dict[str, object]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "StudyLint/0.3 (https://github.com/xunguangzlj-cloud/StudyLint)",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return {}
        raise PaperLookupError(f"Crossref返回HTTP {error.code}，请稍后重试。") from error
    except (URLError, TimeoutError, OSError) as error:
        raise PaperLookupError("无法连接Crossref，请检查网络后重试。") from error


def _first_text(record: dict[str, object], key: str) -> str:
    value = record.get(key)
    if isinstance(value, list) and value:
        return str(value[0]).strip()
    return ""


def _publication_year(record: dict[str, object]) -> str:
    for key in ("published-print", "published-online", "issued"):
        value = record.get(key)
        if not isinstance(value, dict):
            continue
        parts = value.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            return str(parts[0][0])
    return ""


def _authors(record: dict[str, object]) -> tuple[str, ...]:
    result: list[str] = []
    value = record.get("author")
    if not isinstance(value, list):
        return ()
    for author in value[:8]:
        if not isinstance(author, dict):
            continue
        parts = (
            str(author.get("given", "")).strip(),
            str(author.get("family", "")).strip(),
        )
        name = " ".join(part for part in parts if part)
        if name:
            result.append(name)
    return tuple(result)


def _to_match(record: dict[str, object], query: str, exact_doi: bool) -> PaperMatch:
    title = _first_text(record, "title") or "（未提供标题）"
    doi = str(record.get("DOI", "")).strip()
    url = f"https://doi.org/{quote(doi, safe='/:()')}" if doi else str(record.get("URL", "")).strip()
    similarity = 100 if exact_doi else round(fuzz.token_set_ratio(query, title))
    return PaperMatch(
        title=title,
        doi=doi,
        authors=_authors(record),
        year=_publication_year(record),
        venue=_first_text(record, "container-title"),
        publisher=str(record.get("publisher", "")).strip(),
        work_type=str(record.get("type", "")).strip(),
        url=url,
        similarity=similarity,
    )


def verify_paper(query: str, email: str = "") -> PaperVerification:
    cleaned = query.strip()
    if not cleaned:
        raise ValueError("请输入论文标题、完整参考文献或DOI。")

    doi = extract_doi(cleaned)
    if doi:
        url = f"{CROSSREF_API}/works/{quote(doi, safe='')}"
        payload = _request_json(url)
        message = payload.get("message")
        matches = (
            (_to_match(message, cleaned, exact_doi=True),)
            if isinstance(message, dict)
            else ()
        )
        return PaperVerification(cleaned, "doi", matches)

    parameters = {
        "query.bibliographic": cleaned,
        "rows": "5",
        "select": "DOI,title,author,published-print,published-online,issued,container-title,publisher,type,URL",
    }
    if email.strip():
        parameters["mailto"] = email.strip()
    payload = _request_json(f"{CROSSREF_API}/works?{urlencode(parameters)}")
    message = payload.get("message")
    items = message.get("items", []) if isinstance(message, dict) else []
    matches = tuple(
        _to_match(item, cleaned, exact_doi=False)
        for item in items
        if isinstance(item, dict)
    )
    return PaperVerification(cleaned, "bibliographic", matches)
