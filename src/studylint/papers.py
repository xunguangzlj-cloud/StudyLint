from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from rapidfuzz import fuzz


CROSSREF_API = "https://api.crossref.org"
OPENALEX_API = "https://api.openalex.org"
MINIMUM_SIMILARITY = 55
DOI_PATTERN = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)",
    re.IGNORECASE,
)
LIST_PREFIX = re.compile(r"^\s*(?:(?:[-*•]\s+)|(?:\d+[.、)]\s+))")


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
    source: str = "Crossref"


@dataclass(frozen=True)
class PaperSearchLink:
    name: str
    url: str


@dataclass(frozen=True)
class PaperVerification:
    query: str
    query_type: str
    matches: tuple[PaperMatch, ...]
    search_links: tuple[PaperSearchLink, ...] = ()
    warnings: tuple[str, ...] = ()


def parse_queries(text: str) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        query = LIST_PREFIX.sub("", line).strip()
        key = query.casefold()
        if query and key not in seen:
            seen.add(key)
            queries.append(query)
    return queries


def read_query_file(path: Path) -> list[str]:
    if not path.is_file():
        raise ValueError(f"找不到论文清单：{path}")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return parse_queries(path.read_text(encoding=encoding))
        except UnicodeDecodeError:
            continue
    raise ValueError("论文清单需要使用UTF-8或GB18030编码。")


def extract_doi(value: str) -> str | None:
    match = DOI_PATTERN.search(value.strip())
    if not match:
        return None
    doi = match.group(1).rstrip(".,;。；").lower()
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1]
    return doi


def external_search_links(query: str) -> tuple[PaperSearchLink, ...]:
    encoded = quote(query)
    return (
        PaperSearchLink(
            "在知网搜索",
            f"https://kns.cnki.net/kns8s/defaultresult/index?kw={encoded}&korder=SU",
        ),
        PaperSearchLink(
            "在Google Scholar搜索",
            f"https://scholar.google.com/scholar?q={encoded}",
        ),
        PaperSearchLink(
            "在百度学术搜索",
            f"https://xueshu.baidu.com/s?wd={encoded}",
        ),
    )


def _request_json(url: str, timeout: int = 12) -> dict[str, object]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "StudyLint/0.4 (https://github.com/xunguangzlj-cloud/StudyLint)",
        },
    )
    service = "OpenAlex" if "openalex.org" in url else "Crossref"
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return {}
        raise PaperLookupError(f"{service}返回HTTP {error.code}。") from error
    except (URLError, TimeoutError, OSError) as error:
        raise PaperLookupError(f"无法连接{service}。") from error


def _normalized_title(value: str) -> str:
    value = value.casefold().replace("黏", "粘")
    return "".join(character for character in value if character.isalnum())


def _similarity(query: str, title: str) -> int:
    normalized_query = _normalized_title(query)
    normalized_title = _normalized_title(title)
    if not normalized_query or not normalized_title:
        return 0
    return round(
        max(
            fuzz.ratio(normalized_query, normalized_title),
            fuzz.partial_ratio(normalized_query, normalized_title),
        )
    )


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


def _crossref_authors(record: dict[str, object]) -> tuple[str, ...]:
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


def _crossref_match(
    record: dict[str, object], query: str, exact_doi: bool
) -> PaperMatch:
    title = _first_text(record, "title") or "（未提供标题）"
    doi = str(record.get("DOI", "")).strip()
    url = (
        f"https://doi.org/{quote(doi, safe='/:()')}"
        if doi
        else str(record.get("URL", "")).strip()
    )
    return PaperMatch(
        title=title,
        doi=doi,
        authors=_crossref_authors(record),
        year=_publication_year(record),
        venue=_first_text(record, "container-title"),
        publisher=str(record.get("publisher", "")).strip(),
        work_type=str(record.get("type", "")).strip(),
        url=url,
        similarity=100 if exact_doi else _similarity(query, title),
        source="Crossref",
    )


def _openalex_match(
    record: dict[str, object], query: str, exact_doi: bool
) -> PaperMatch:
    title = str(record.get("display_name") or record.get("title") or "（未提供标题）")
    doi = str(record.get("doi") or "").removeprefix("https://doi.org/")
    authors: list[str] = []
    authorships = record.get("authorships")
    if isinstance(authorships, list):
        for authorship in authorships[:8]:
            if not isinstance(authorship, dict):
                continue
            author = authorship.get("author")
            if isinstance(author, dict) and author.get("display_name"):
                authors.append(str(author["display_name"]))
    location = record.get("primary_location")
    source_name = ""
    landing_page = ""
    if isinstance(location, dict):
        landing_page = str(location.get("landing_page_url") or "")
        source = location.get("source")
        if isinstance(source, dict):
            source_name = str(source.get("display_name") or "")
    url = (
        f"https://doi.org/{quote(doi, safe='/:()')}"
        if doi
        else landing_page or str(record.get("id") or "")
    )
    return PaperMatch(
        title=title,
        doi=doi,
        authors=tuple(authors),
        year=str(record.get("publication_year") or ""),
        venue=source_name,
        publisher="",
        work_type=str(record.get("type") or ""),
        url=url,
        similarity=100 if exact_doi else _similarity(query, title),
        source="OpenAlex",
    )


def _deduplicate_matches(matches: list[PaperMatch]) -> tuple[PaperMatch, ...]:
    selected: dict[str, PaperMatch] = {}
    for match in sorted(matches, key=lambda item: item.similarity, reverse=True):
        if match.similarity < MINIMUM_SIMILARITY:
            continue
        key = match.doi.casefold() if match.doi else _normalized_title(match.title)
        if key and key not in selected:
            selected[key] = match
    return tuple(list(selected.values())[:5])


def _crossref_title_search(query: str, email: str) -> list[PaperMatch]:
    parameters = {
        "query.bibliographic": query,
        "rows": "5",
        "select": "DOI,title,author,published-print,published-online,issued,container-title,publisher,type,URL",
    }
    if email.strip():
        parameters["mailto"] = email.strip()
    payload = _request_json(f"{CROSSREF_API}/works?{urlencode(parameters)}")
    message = payload.get("message")
    items = message.get("items", []) if isinstance(message, dict) else []
    return [
        _crossref_match(item, query, exact_doi=False)
        for item in items
        if isinstance(item, dict)
    ]


def _openalex_search(query: str, doi: str = "") -> list[PaperMatch]:
    parameters = (
        {"filter": f"doi:https://doi.org/{doi}", "per-page": "1"}
        if doi
        else {"search": query, "per-page": "5"}
    )
    payload = _request_json(f"{OPENALEX_API}/works?{urlencode(parameters)}")
    items = payload.get("results", [])
    if not isinstance(items, list):
        return []
    return [
        _openalex_match(item, query, exact_doi=bool(doi))
        for item in items
        if isinstance(item, dict)
    ]


def verify_paper(query: str, email: str = "") -> PaperVerification:
    cleaned = query.strip()
    if not cleaned:
        raise ValueError("请输入论文标题、完整参考文献或DOI。")

    links = external_search_links(cleaned)
    warnings: list[str] = []
    doi = extract_doi(cleaned)
    if doi:
        try:
            payload = _request_json(f"{CROSSREF_API}/works/{quote(doi, safe='')}")
            message = payload.get("message")
            if isinstance(message, dict):
                match = _crossref_match(message, cleaned, exact_doi=True)
                return PaperVerification(cleaned, "doi", (match,), links)
        except PaperLookupError as error:
            warnings.append(str(error))
        try:
            matches = _openalex_search(cleaned, doi=doi)
        except PaperLookupError as error:
            warnings.append(str(error))
            matches = []
        return PaperVerification(cleaned, "doi", tuple(matches[:1]), links, tuple(warnings))

    matches: list[PaperMatch] = []
    try:
        matches.extend(_crossref_title_search(cleaned, email))
    except PaperLookupError as error:
        warnings.append(str(error))
    if not matches or max(match.similarity for match in matches) < 85:
        try:
            matches.extend(_openalex_search(cleaned))
        except PaperLookupError as error:
            warnings.append(str(error))
    return PaperVerification(
        cleaned,
        "bibliographic",
        _deduplicate_matches(matches),
        links,
        tuple(warnings),
    )


def verify_papers(queries: list[str], email: str = "") -> list[PaperVerification]:
    if not queries:
        raise ValueError("请至少输入一篇论文。")
    if len(queries) == 1:
        return [verify_paper(queries[0], email=email)]
    workers = min(4, len(queries))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(lambda query: verify_paper(query, email=email), queries))
