from __future__ import annotations

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

CROSSREF_API = "https://api.crossref.org"
OPENALEX_API = "https://api.openalex.org"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
ARXIV_API = "https://export.arxiv.org/api/query"
DBLP_API = "https://dblp.org/search/publ/api"
EUROPE_PMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
DOAJ_API = "https://doaj.org/api/search/articles"
MINIMUM_SIMILARITY = 55
TITLE_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but",
    "by", "for", "from", "in", "into", "is", "it", "of", "on", "or",
    "over", "that", "the", "these", "this", "those", "to", "under", "was",
    "were", "with",
}
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
    is_retracted: bool = False
    full_text_url: str = ""
    license: str = ""


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
    verdict: str = ""

    def __post_init__(self) -> None:
        if self.verdict:
            return
        if not self.matches:
            inferred = "NEEDS_MANUAL"
        elif self.query_type == "doi":
            inferred = "IDENTIFIER_FOUND"
        elif self.matches[0].similarity >= 85:
            inferred = "VERIFIED_METADATA"
        else:
            inferred = "PARTIAL_MATCH"
        object.__setattr__(self, "verdict", inferred)


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
    if "openalex.org" in url:
        service = "OpenAlex"
    elif "semanticscholar.org" in url:
        service = "Semantic Scholar"
    elif "dblp.org" in url:
        service = "DBLP"
    elif "europepmc" in url:
        service = "Europe PMC"
    elif "doaj.org" in url:
        service = "DOAJ"
    else:
        service = "Crossref"
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except json.JSONDecodeError as error:
        raise PaperLookupError(f"{service}返回了无法解析的数据。") from error
    except HTTPError as error:
        if error.code == 404:
            return {}
        raise PaperLookupError(f"{service}返回HTTP {error.code}。") from error
    except (URLError, TimeoutError, OSError) as error:
        raise PaperLookupError(f"无法连接{service}。") from error


def _request_text(url: str, timeout: int = 12) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/atom+xml, application/xml, text/xml",
            "User-Agent": "StudyLint/0.6.0 (https://github.com/xunguangzlj-cloud/StudyLint)",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        if error.code == 404:
            return ""
        raise PaperLookupError(f"arXiv返回HTTP {error.code}。") from error
    except (URLError, TimeoutError, OSError) as error:
        raise PaperLookupError("无法连接arXiv。") from error


def _normalized_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold().replace("黏", "粘"))
    value = "".join(character for character in value if not unicodedata.combining(character))
    return "".join(character for character in value if character.isalnum())


def _title_features(value: str) -> Counter[str]:
    value = unicodedata.normalize("NFKD", value.casefold().replace("黏", "粘"))
    value = "".join(character for character in value if not unicodedata.combining(character))
    features: list[str] = []
    for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", value):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            features.extend(
                token[index : index + 2]
                for index in range(max(1, len(token) - 1))
            )
        elif token not in TITLE_STOPWORDS:
            features.append(token)
    return Counter(features)


def _similarity(query: str, title: str) -> int:
    normalized_query = _normalized_title(query)
    normalized_title = _normalized_title(title)
    if not normalized_query or not normalized_title:
        return 0
    if normalized_query == normalized_title:
        return 100
    query_features = _title_features(query)
    title_features = _title_features(title)
    if not query_features or not title_features:
        return 0
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", query))
    if not has_cjk and sum(query_features.values()) < 3:
        return 0
    overlap = sum((query_features & title_features).values())
    precision = overlap / sum(query_features.values())
    recall = overlap / sum(title_features.values())
    if not precision or not recall:
        return 0
    return round(200 * precision * recall / (precision + recall))


def _claimed_title_fragment(query: str) -> str:
    context = DOI_PATTERN.sub("", query)
    context = re.sub(r"\bdoi\b\s*: ?", "", context, flags=re.IGNORECASE)
    year = re.search(
        r"[（(\[]\s*(?:19|20)\d{2}[a-z]?\s*[）)\]]",
        context,
        re.IGNORECASE,
    )
    if year:
        after_year = context[year.end() :].lstrip(" \t\r\n.,，;；:：")
        first_sentence = re.split(r"[。！？]|[.!?]\s+", after_year, maxsplit=1)[0]
        if len(_normalized_title(first_sentence)) >= 8:
            return first_sentence.strip(" \t\r\n,，;；:：()（）[]【】")
    fragments = [
        fragment.strip(" \t\r\n,，;；:：()（）[]【】")
        for fragment in re.split(r"[。！？]|[.!?]\s+", context)
    ]
    candidates = [fragment for fragment in fragments if len(_normalized_title(fragment)) >= 8]
    return max(candidates, key=lambda item: len(_normalized_title(item)), default="")


def _claimed_year(query: str) -> str:
    match = re.search(r"[（(\[]\s*((?:19|20)\d{2})[a-z]?\s*[）)\]]", query, re.IGNORECASE)
    return match.group(1) if match else ""


def _year_mismatch_warning(query: str, match: PaperMatch) -> str:
    claimed = _claimed_year(query)
    if not claimed or not match.year:
        return ""
    try:
        if abs(int(claimed) - int(match.year)) <= 1:
            return ""
    except ValueError:
        return ""
    return f"引用年份{claimed}与数据库年份{match.year}不一致。"


def _doi_match_verdict(query: str, match: PaperMatch) -> tuple[PaperMatch, str]:
    claimed_title = _claimed_title_fragment(query)
    if not claimed_title:
        return replace(match, similarity=100), "IDENTIFIER_FOUND"
    similarity = _similarity(claimed_title, match.title)
    updated = replace(match, similarity=similarity)
    if similarity >= 85:
        return updated, "VERIFIED_METADATA"
    if similarity >= MINIMUM_SIMILARITY:
        return updated, "PARTIAL_MATCH"
    return updated, "METADATA_MISMATCH"


def _search_verdict(matches: tuple[PaperMatch, ...]) -> str:
    if not matches:
        return "NEEDS_MANUAL"
    if matches[0].is_retracted:
        return "RETRACTED"
    return "VERIFIED_METADATA" if matches[0].similarity >= 85 else "PARTIAL_MATCH"


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
        similarity=(
            100
            if exact_doi
            else _similarity(_claimed_title_fragment(query) or query, title)
        ),
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
    full_text_url = ""
    license_name = ""
    if isinstance(location, dict):
        landing_page = str(location.get("landing_page_url") or "")
        full_text_url = str(location.get("pdf_url") or "")
        license_name = str(location.get("license") or "")
        source = location.get("source")
        if isinstance(source, dict):
            source_name = str(source.get("display_name") or "")
    best_oa = record.get("best_oa_location")
    if isinstance(best_oa, dict):
        full_text_url = str(best_oa.get("pdf_url") or full_text_url)
        license_name = str(best_oa.get("license") or license_name)
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
        similarity=(
            100
            if exact_doi
            else _similarity(_claimed_title_fragment(query) or query, title)
        ),
        source="OpenAlex",
        is_retracted=bool(record.get("is_retracted")),
        full_text_url=full_text_url,
        license=license_name,
    )


def _semantic_scholar_match(
    record: dict[str, object], query: str, exact_doi: bool = False
) -> PaperMatch:
    title = str(record.get("title") or "（未提供标题）")
    external_ids = record.get("externalIds")
    doi = ""
    if isinstance(external_ids, dict):
        doi = str(external_ids.get("DOI") or "")
    authors: list[str] = []
    value = record.get("authors")
    if isinstance(value, list):
        for author in value[:8]:
            if isinstance(author, dict) and author.get("name"):
                authors.append(str(author["name"]))
    paper_id = str(record.get("paperId") or "")
    url = str(record.get("url") or "")
    if not url and paper_id:
        url = f"https://www.semanticscholar.org/paper/{quote(paper_id, safe='')}"
    open_access = record.get("openAccessPdf")
    full_text_url = ""
    license_name = ""
    if isinstance(open_access, dict):
        full_text_url = str(open_access.get("url") or "")
        license_name = str(open_access.get("license") or "")
    publication_types = record.get("publicationTypes")
    work_type = (
        ", ".join(str(value) for value in publication_types)
        if isinstance(publication_types, list)
        else ""
    )
    return PaperMatch(
        title=title,
        doi=doi,
        authors=tuple(authors),
        year=str(record.get("year") or ""),
        venue=str(record.get("venue") or ""),
        publisher="",
        work_type=work_type,
        url=url,
        similarity=(
            100
            if exact_doi
            else _similarity(_claimed_title_fragment(query) or query, title)
        ),
        source="Semantic Scholar",
        full_text_url=full_text_url,
        license=license_name,
    )


def _deduplicate_matches(
    matches: list[PaperMatch], query: str = ""
) -> tuple[PaperMatch, ...]:
    selected: dict[str, PaperMatch] = {}
    for match in sorted(matches, key=lambda item: item.similarity, reverse=True):
        if match.similarity < MINIMUM_SIMILARITY:
            continue
        key = match.doi.casefold() if match.doi else _normalized_title(match.title)
        if not key:
            continue
        existing = selected.get(key)
        if existing is None:
            selected[key] = match
            continue
        sources = existing.source.split(" + ")
        if match.source not in sources:
            sources.append(match.source)
        selected[key] = replace(
            existing,
            source=" + ".join(sources),
            is_retracted=existing.is_retracted or match.is_retracted,
            full_text_url=existing.full_text_url or match.full_text_url,
            license=existing.license or match.license,
        )
    claimed_year = _claimed_year(query)

    def rank(match: PaperMatch) -> tuple[int, int, int, int]:
        year_bonus = 15 if claimed_year and match.year == claimed_year else 0
        year_known = int(bool(match.year))
        return (
            match.similarity + year_bonus,
            match.similarity,
            int(bool(match.doi)),
            year_known,
        )

    return tuple(sorted(selected.values(), key=rank, reverse=True)[:5])


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
    search_query = _claimed_title_fragment(query) or query
    parameters = (
        {"filter": f"doi:https://doi.org/{doi}", "per-page": "1"}
        if doi
        else {"search": search_query, "per-page": "5"}
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


def _semantic_scholar_search(query: str) -> list[PaperMatch]:
    search_query = (_claimed_title_fragment(query) or query).replace("-", " ")
    parameters = {
        "query": search_query,
        "limit": "5",
        "fields": (
            "paperId,title,authors,year,venue,externalIds,url,"
            "publicationTypes,isOpenAccess,openAccessPdf"
        ),
    }
    payload = _request_json(
        f"{SEMANTIC_SCHOLAR_API}/paper/search?{urlencode(parameters)}"
    )
    items = payload.get("data", [])
    if not isinstance(items, list):
        return []
    return [
        _semantic_scholar_match(item, query)
        for item in items
        if isinstance(item, dict)
    ]


def _semantic_scholar_doi_search(query: str, doi: str) -> list[PaperMatch]:
    fields = (
        "paperId,title,authors,year,venue,externalIds,url,"
        "publicationTypes,isOpenAccess,openAccessPdf"
    )
    encoded_doi = quote(doi, safe="")
    payload = _request_json(
        f"{SEMANTIC_SCHOLAR_API}/paper/DOI:{encoded_doi}?{urlencode({'fields': fields})}"
    )
    if not payload or not payload.get("title"):
        return []
    return [_semantic_scholar_match(payload, query, exact_doi=True)]


def _arxiv_search(query: str) -> list[PaperMatch]:
    search_query = _claimed_title_fragment(query) or query
    parameters = {
        "search_query": f'all:"{search_query}"',
        "start": "0",
        "max_results": "5",
    }
    body = _request_text(f"{ARXIV_API}?{urlencode(parameters)}")
    if not body:
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise PaperLookupError("arXiv返回了无法解析的数据。") from error
    atom = "{http://www.w3.org/2005/Atom}"
    arxiv = "{http://arxiv.org/schemas/atom}"
    matches: list[PaperMatch] = []
    for entry in root.findall(f"{atom}entry"):
        title = " ".join((entry.findtext(f"{atom}title") or "").split())
        if not title:
            continue
        entry_url = (entry.findtext(f"{atom}id") or "").strip()
        published = (entry.findtext(f"{atom}published") or "").strip()
        authors = tuple(
            name.text.strip()
            for author in entry.findall(f"{atom}author")
            if (name := author.find(f"{atom}name")) is not None and name.text
        )
        pdf_url = next(
            (
                link.get("href", "")
                for link in entry.findall(f"{atom}link")
                if link.get("type") == "application/pdf"
            ),
            "",
        )
        if pdf_url.startswith("http://") and "arxiv.org/" in pdf_url:
            pdf_url = "https://" + pdf_url.removeprefix("http://")
        matches.append(
            PaperMatch(
                title=title,
                doi=(entry.findtext(f"{arxiv}doi") or "").strip(),
                authors=authors[:8],
                year=published[:4],
                venue=(entry.findtext(f"{arxiv}journal_ref") or "arXiv").strip(),
                publisher="",
                work_type="preprint",
                url=entry_url,
                similarity=_similarity(search_query, title),
                source="arXiv",
                full_text_url=pdf_url,
            )
        )
    return matches


def _dblp_search(query: str) -> list[PaperMatch]:
    search_query = _claimed_title_fragment(query) or query
    payload = _request_json(
        f"{DBLP_API}?{urlencode({'q': search_query, 'format': 'json', 'h': '5'})}"
    )
    result = payload.get("result")
    hits_container = result.get("hits") if isinstance(result, dict) else None
    hits = hits_container.get("hit", []) if isinstance(hits_container, dict) else []
    if isinstance(hits, dict):
        hits = [hits]
    if not isinstance(hits, list):
        return []
    matches: list[PaperMatch] = []
    for hit in hits:
        info = hit.get("info") if isinstance(hit, dict) else None
        if not isinstance(info, dict):
            continue
        title = str(info.get("title") or "").strip().rstrip(".")
        if not title:
            continue
        author_container = info.get("authors")
        raw_authors = (
            author_container.get("author", [])
            if isinstance(author_container, dict)
            else []
        )
        if isinstance(raw_authors, (str, dict)):
            raw_authors = [raw_authors]
        authors = tuple(
            str(author.get("text") if isinstance(author, dict) else author).strip()
            for author in raw_authors[:8]
        )
        doi = str(info.get("doi") or "").strip()
        matches.append(
            PaperMatch(
                title=title,
                doi=doi,
                authors=authors,
                year=str(info.get("year") or ""),
                venue=str(info.get("venue") or ""),
                publisher="",
                work_type=str(info.get("type") or "publication"),
                url=str(info.get("url") or (f"https://doi.org/{doi}" if doi else "")),
                similarity=_similarity(search_query, title),
                source="DBLP",
            )
        )
    return matches


def _europe_pmc_search(query: str, doi: str = "") -> list[PaperMatch]:
    search_query = _claimed_title_fragment(query) or query
    pmc_query = f'DOI:"{doi}"' if doi else f'TITLE:"{search_query}"'
    parameters = {
        "query": pmc_query,
        "format": "json",
        "pageSize": "5",
        "resultType": "core",
    }
    payload = _request_json(f"{EUROPE_PMC_API}?{urlencode(parameters)}")
    result_list = payload.get("resultList")
    items = result_list.get("result", []) if isinstance(result_list, dict) else []
    if not isinstance(items, list):
        return []
    matches: list[PaperMatch] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        item_doi = str(item.get("doi") or "").strip()
        pmcid = str(item.get("pmcid") or "").strip()
        pmid = str(item.get("pmid") or "").strip()
        full_text_url = ""
        full_text_list = item.get("fullTextUrlList")
        full_text_items = (
            full_text_list.get("fullTextUrl", [])
            if isinstance(full_text_list, dict)
            else []
        )
        if isinstance(full_text_items, dict):
            full_text_items = [full_text_items]
        if str(item.get("isOpenAccess") or "").upper() == "Y":
            full_text_url = next(
                (
                    str(link.get("url") or "")
                    for link in full_text_items
                    if isinstance(link, dict)
                    and str(link.get("documentStyle") or "").lower() == "pdf"
                ),
                "",
            )
        url = (
            f"https://doi.org/{item_doi}"
            if item_doi
            else f"https://europepmc.org/article/PMC/{pmcid}"
            if pmcid
            else f"https://europepmc.org/article/MED/{pmid}"
            if pmid
            else ""
        )
        author_string = str(item.get("authorString") or "").strip(" .")
        authors = tuple(
            author.strip()
            for author in re.split(r"[,;]", author_string)
            if author.strip()
        )[:8]
        matches.append(
            PaperMatch(
                title=title,
                doi=item_doi,
                authors=authors,
                year=str(item.get("pubYear") or ""),
                venue=str(item.get("journalTitle") or ""),
                publisher="",
                work_type=str(item.get("pubType") or "article"),
                url=url,
                similarity=100 if doi else _similarity(search_query, title),
                source="Europe PMC",
                full_text_url=full_text_url,
                license=str(item.get("license") or ""),
            )
        )
    return matches


def _doaj_match(
    record: dict[str, object], query: str, exact_doi: bool = False
) -> PaperMatch:
    bibjson = record.get("bibjson")
    if not isinstance(bibjson, dict):
        bibjson = {}
    title = str(bibjson.get("title") or "（未提供标题）").strip()
    identifiers = bibjson.get("identifier")
    doi = ""
    if isinstance(identifiers, list):
        doi = next(
            (
                str(identifier.get("id") or "").strip()
                for identifier in identifiers
                if isinstance(identifier, dict)
                and str(identifier.get("type") or "").casefold() == "doi"
            ),
            "",
        )
    authors_value = bibjson.get("author")
    authors = tuple(
        str(author.get("name") or "").strip()
        for author in authors_value[:8]
        if isinstance(author, dict) and str(author.get("name") or "").strip()
    ) if isinstance(authors_value, list) else ()
    journal = bibjson.get("journal")
    venue = str(journal.get("title") or "").strip() if isinstance(journal, dict) else ""
    publisher = (
        str(journal.get("publisher") or "").strip()
        if isinstance(journal, dict)
        else ""
    )
    links = bibjson.get("link")
    full_text_candidates: list[tuple[bool, str]] = []
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict) or str(link.get("type") or "").casefold() != "fulltext":
                continue
            link_url = str(link.get("url") or "").strip()
            if not link_url:
                continue
            if link_url.startswith("http://") and any(
                host in link_url.casefold()
                for host in ("europepmc.org/", "ncbi.nlm.nih.gov/", "doaj.org/")
            ):
                link_url = "https://" + link_url.removeprefix("http://")
            content_type = str(link.get("content_type") or "").casefold()
            full_text_candidates.append(("pdf" in content_type, link_url))
    full_text_candidates.sort(key=lambda item: item[0], reverse=True)
    full_text_url = full_text_candidates[0][1] if full_text_candidates else ""
    licenses = bibjson.get("license")
    license_name = ""
    if isinstance(licenses, list):
        license_name = next(
            (
                str(item.get("type") or "").strip()
                for item in licenses
                if isinstance(item, dict) and item.get("type")
            ),
            "",
        )
    record_id = str(record.get("id") or "").strip()
    return PaperMatch(
        title=title,
        doi=doi,
        authors=authors,
        year=str(bibjson.get("year") or ""),
        venue=venue,
        publisher=publisher,
        work_type="journal-article",
        url=(
            f"https://doi.org/{quote(doi, safe='/:()')}"
            if doi
            else f"https://doaj.org/article/{quote(record_id, safe='')}"
            if record_id
            else ""
        ),
        similarity=(
            100
            if exact_doi
            else _similarity(_claimed_title_fragment(query) or query, title)
        ),
        source="DOAJ",
        full_text_url=full_text_url,
        license=license_name,
    )


def _doaj_search(query: str, doi: str = "") -> list[PaperMatch]:
    search_query = _claimed_title_fragment(query) or query
    expression = (
        f"bibjson.identifier.id:{doi}"
        if doi
        else f'bibjson.title:"{search_query}"'
    )
    payload = _request_json(
        f"{DOAJ_API}/{quote(expression, safe=':.')}?{urlencode({'pageSize': '5'})}"
    )
    items = payload.get("results", [])
    if not isinstance(items, list):
        return []
    return [
        _doaj_match(item, query, exact_doi=bool(doi))
        for item in items
        if isinstance(item, dict)
    ]


def verify_paper(
    query: str, email: str = "", include_fulltext: bool = False
) -> PaperVerification:
    cleaned = query.strip()
    if not cleaned:
        raise ValueError("请输入论文标题、完整参考文献或DOI。")

    links = external_search_links(cleaned)
    warnings: list[str] = []
    doi = extract_doi(cleaned)
    if doi:
        matches: list[PaperMatch] = []

        def crossref_doi_search() -> list[PaperMatch]:
            payload = _request_json(f"{CROSSREF_API}/works/{quote(doi, safe='')}")
            message = payload.get("message")
            if not isinstance(message, dict):
                return []
            return [_crossref_match(message, cleaned, exact_doi=True)]

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(crossref_doi_search),
                executor.submit(_openalex_search, cleaned, doi),
            )
            for future in futures:
                try:
                    matches.extend(future.result())
                except PaperLookupError as error:
                    warnings.append(str(error))

        selected = _deduplicate_matches(matches, cleaned)
        if not selected or (
            include_fulltext
            and not any(match.full_text_url for match in selected)
        ):
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = (
                    executor.submit(_semantic_scholar_doi_search, cleaned, doi),
                    executor.submit(_europe_pmc_search, cleaned, doi),
                    executor.submit(_doaj_search, cleaned, doi),
                )
                for future in futures:
                    try:
                        matches.extend(future.result())
                    except PaperLookupError as error:
                        warnings.append(str(error))
            selected = _deduplicate_matches(matches, cleaned)
        verdict = "NEEDS_MANUAL"
        if selected:
            match, verdict = _doi_match_verdict(cleaned, selected[0])
            year_warning = _year_mismatch_warning(cleaned, match)
            if year_warning:
                warnings.append(year_warning)
                verdict = "METADATA_MISMATCH"
            if match.is_retracted:
                warnings.append("OpenAlex将该论文标记为已撤稿，请勿直接引用。")
                verdict = "RETRACTED"
            selected = (match,)
        return PaperVerification(
            cleaned, "doi", selected, links, tuple(warnings), verdict
        )

    matches: list[PaperMatch] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(_crossref_title_search, cleaned, email),
            executor.submit(_openalex_search, cleaned),
        )
        for future in futures:
            try:
                matches.extend(future.result())
            except PaperLookupError as error:
                warnings.append(str(error))
    selected = _deduplicate_matches(matches, cleaned)
    claimed_year = _claimed_year(cleaned)
    year_conflict = bool(
        selected
        and claimed_year
        and selected[0].year
        and selected[0].year != claimed_year
    )
    if (
        not selected
        or selected[0].similarity < 85
        or year_conflict
        or (
            include_fulltext
            and not any(match.full_text_url for match in selected)
        )
    ):
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = (
                executor.submit(_semantic_scholar_search, cleaned),
                executor.submit(_arxiv_search, cleaned),
                executor.submit(_dblp_search, cleaned),
                executor.submit(_europe_pmc_search, cleaned),
                executor.submit(_doaj_search, cleaned),
            )
            for future in futures:
                try:
                    matches.extend(future.result())
                except PaperLookupError as error:
                    warnings.append(str(error))
        selected = _deduplicate_matches(matches, cleaned)
    verdict = _search_verdict(selected)
    if selected:
        year_warning = _year_mismatch_warning(cleaned, selected[0])
        if year_warning:
            warnings.append(year_warning)
            if verdict != "RETRACTED":
                verdict = "METADATA_MISMATCH"
    if verdict == "RETRACTED":
        warnings.append("OpenAlex将该论文标记为已撤稿，请勿直接引用。")
    return PaperVerification(
        cleaned,
        "bibliographic",
        selected,
        links,
        tuple(warnings),
        verdict,
    )


def verify_papers(
    queries: list[str],
    email: str = "",
    include_fulltext: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> list[PaperVerification]:
    if not queries:
        raise ValueError("请至少输入一篇论文。")
    if len(queries) == 1:
        result = verify_paper(queries[0], email=email, include_fulltext=include_fulltext)
        if progress:
            progress(1, 1)
        return [result]
    workers = min(4, len(queries))
    results: list[PaperVerification | None] = [None] * len(queries)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                verify_paper,
                query,
                email,
                include_fulltext,
            ): index
            for index, query in enumerate(queries)
        }
        completed = 0
        for future in as_completed(futures):
            results[futures[future]] = future.result()
            completed += 1
            if progress:
                progress(completed, len(queries))
    return [result for result in results if result is not None]
