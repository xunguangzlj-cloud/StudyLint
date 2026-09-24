from __future__ import annotations

import hashlib
import ipaddress
import os
import socket
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from studylint.papers import (
    PaperLookupError,
    PaperMatch,
    PaperVerification,
    verify_papers,
)


DEFAULT_TIMEOUT = 15.0
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_HTML_BYTES = 2 * 1024 * 1024
DEFAULT_MIN_SIMILARITY = 85
DOWNLOAD_CHUNK_SIZE = 64 * 1024
PDF_MAGIC = b"%PDF-"


class FullTextError(RuntimeError):
    """开放全文获取失败。"""


class UnsafeFullTextURLError(FullTextError):
    """全文URL不满足安全边界。"""


class InvalidPDFError(FullTextError):
    """内容不是可接受的PDF文件。"""


class FullTextStatus(str, Enum):
    LOCAL_FILE = "LOCAL_FILE"
    CACHED_FILE = "CACHED_FILE"
    DOWNLOADED = "DOWNLOADED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    UNAVAILABLE = "UNAVAILABLE"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"


@dataclass(frozen=True)
class FullTextResult:
    status: FullTextStatus
    path: Path | None = None
    source_url: str = ""
    license: str = ""
    message: str = ""
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status in {
            FullTextStatus.LOCAL_FILE,
            FullTextStatus.CACHED_FILE,
            FullTextStatus.DOWNLOADED,
        }


@dataclass(frozen=True)
class ReferenceResolution:
    number: int
    reference: str
    verification_verdict: str
    verification_message: str
    url: str
    work_type: str
    is_retracted: bool
    full_text_url: str
    license: str
    path: Path | None
    source_status: str
    source_message: str
    warnings: tuple[str, ...] = ()


def _not_nonexistent(detail: str) -> str:
    return f"{detail.rstrip('。')}；这不代表论文不存在。"


def _public_ip_addresses(host: str, port: int) -> tuple[ipaddress._BaseAddress, ...]:
    try:
        return (ipaddress.ip_address(host),)
    except ValueError:
        pass
    try:
        records = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError as error:
        raise UnsafeFullTextURLError(f"无法安全解析全文主机：{host}") from error
    addresses: list[ipaddress._BaseAddress] = []
    for record in records:
        address = record[4][0].split("%", 1)[0]
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as error:
            raise UnsafeFullTextURLError("全文主机返回了无效地址。") from error
        if parsed not in addresses:
            addresses.append(parsed)
    if not addresses:
        raise UnsafeFullTextURLError(f"全文主机没有可验证的地址：{host}")
    return tuple(addresses)


def _validate_https_public_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port or 443
    except ValueError as error:
        raise UnsafeFullTextURLError("全文URL格式无效。") from error
    if parsed.scheme.casefold() != "https":
        raise UnsafeFullTextURLError("自动获取全文仅允许HTTPS链接。")
    if not parsed.hostname:
        raise UnsafeFullTextURLError("全文URL缺少主机名。")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeFullTextURLError("全文URL不能包含登录凭据。")
    host = parsed.hostname.rstrip(".").casefold()
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise UnsafeFullTextURLError("全文URL不能指向本地主机。")
    addresses = _public_ip_addresses(host, port)
    if any(not address.is_global for address in addresses):
        raise UnsafeFullTextURLError("全文URL不能指向本地、私网或保留地址。")
    return url


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> Request | None:
        _validate_https_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_URL_OPENER = build_opener(_SafeRedirectHandler())


def _open_url(request: Request, timeout: float):
    return _URL_OPENER.open(request, timeout=timeout)


def _validate_pdf_file(path: Path, *, max_bytes: int | None = None) -> None:
    if not path.is_file():
        raise InvalidPDFError(f"找不到PDF文件：{path}")
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise InvalidPDFError(f"PDF超过大小限制（{max_bytes}字节）。")
    with path.open("rb") as file:
        if file.read(len(PDF_MAGIC)) != PDF_MAGIC:
            raise InvalidPDFError("文件缺少PDF魔数，可能是网页或损坏文件。")


def _validate_epub_file(path: Path) -> None:
    if not path.is_file():
        raise InvalidPDFError(f"找不到EPUB文件：{path}")
    try:
        with zipfile.ZipFile(path) as archive:
            mimetype = archive.read("mimetype")
    except (KeyError, OSError, zipfile.BadZipFile) as error:
        raise InvalidPDFError("EPUB容器无效或缺少mimetype标识。") from error
    if mimetype != b"application/epub+zip":
        raise InvalidPDFError("文件不是有效的EPUB电子书。")


def _validate_local_file(path: Path) -> str:
    if path.suffix.casefold() == ".epub":
        _validate_epub_file(path)
        return "EPUB"
    _validate_pdf_file(path)
    return "PDF"


def _download_pdf(
    url: str,
    destination: Path,
    *,
    timeout: float,
    max_bytes: int,
) -> str:
    _validate_https_public_url(url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(
        url,
        headers={
            "Accept": "application/pdf,application/octet-stream;q=0.8",
            "User-Agent": "StudyLint/0.6.0 (+https://github.com/xunguangzlj-cloud/StudyLint)",
        },
    )
    temporary_path: Path | None = None
    try:
        with _open_url(request, timeout) as response:
            final_url = str(response.geturl())
            _validate_https_public_url(final_url)
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    declared_size = int(content_length)
                except (TypeError, ValueError):
                    declared_size = -1
                if declared_size > max_bytes:
                    raise FullTextError(
                        f"开放全文超过大小限制（{max_bytes}字节）。"
                    )
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                total = 0
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise FullTextError(
                            f"开放全文超过大小限制（{max_bytes}字节）。"
                        )
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
        _validate_pdf_file(temporary_path, max_bytes=max_bytes)
        os.replace(temporary_path, destination)
        temporary_path = None
        return final_url
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


class _PDFLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.candidates: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {key.casefold(): (value or "").strip() for key, value in attrs}
        if tag.casefold() == "meta":
            name = values.get("name", "").casefold()
            if name in {"citation_pdf_url", "eprints.document_url"}:
                candidate = values.get("content", "")
                if candidate:
                    self.candidates.append(candidate)
        elif tag.casefold() == "link" and "application/pdf" in values.get("type", "").casefold():
            candidate = values.get("href", "")
            if candidate:
                self.candidates.append(candidate)


def _discover_pdf_url(
    landing_url: str,
    *,
    timeout: float,
    max_bytes: int = DEFAULT_MAX_HTML_BYTES,
) -> str:
    """从论文落地页的标准元数据中发现公开PDF，不猜测站点路径。"""
    _validate_https_public_url(landing_url)
    request = Request(
        landing_url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.8",
            "User-Agent": "StudyLint/0.6.0 (+https://github.com/xunguangzlj-cloud/StudyLint)",
        },
    )
    with _open_url(request, timeout) as response:
        final_url = str(response.geturl())
        _validate_https_public_url(final_url)
        content_type = str(response.headers.get("Content-Type") or "").casefold()
        if "application/pdf" in content_type:
            return final_url
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise FullTextError(f"论文页面超过解析限制（{max_bytes}字节）。")
    parser = _PDFLinkParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    if not parser.candidates:
        return ""
    candidate = urljoin(final_url, parser.candidates[0])
    _validate_https_public_url(candidate)
    return candidate


def acquire_fulltext(
    match: PaperMatch | None,
    destination: Path,
    *,
    local_path: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    min_similarity: int = DEFAULT_MIN_SIMILARITY,
) -> FullTextResult:
    """优先使用本地PDF/EPUB，否则仅为高置信候选获取开放PDF。"""
    if timeout <= 0:
        raise ValueError("全文下载超时必须大于0。")
    if max_bytes <= 0:
        raise ValueError("全文大小限制必须大于0。")
    local_warnings: list[str] = []
    if local_path is not None:
        try:
            local_format = _validate_local_file(local_path)
        except (InvalidPDFError, OSError) as error:
            local_warnings.append(f"本地文献不可用：{error}")
        else:
            return FullTextResult(
                FullTextStatus.LOCAL_FILE,
                path=local_path,
                message=f"已优先使用用户导入的本地{local_format}。",
            )

    if destination.is_file():
        try:
            _validate_pdf_file(destination, max_bytes=max_bytes)
        except (InvalidPDFError, OSError) as error:
            return FullTextResult(
                FullTextStatus.DOWNLOAD_FAILED,
                message=_not_nonexistent(f"现有缓存不可用：{error}"),
                warnings=tuple(local_warnings),
            )
        return FullTextResult(
            FullTextStatus.CACHED_FILE,
            path=destination,
            source_url=match.full_text_url if match is not None else "",
            license=match.license if match is not None else "",
            message="已使用经过校验的全文缓存。",
            warnings=tuple(local_warnings),
        )

    if match is None:
        return FullTextResult(
            FullTextStatus.UNAVAILABLE,
            message=_not_nonexistent("当前元数据源未提供可安全获取的开放全文"),
            warnings=tuple(local_warnings),
        )
    if match.similarity < min_similarity:
        return FullTextResult(
            FullTextStatus.LOW_CONFIDENCE,
            source_url=match.full_text_url,
            license=match.license,
            message=_not_nonexistent(
                f"候选匹配度为{match.similarity}%，为避免下载错文献已跳过"
            ),
            warnings=tuple(local_warnings),
        )
    full_text_url = match.full_text_url
    if not full_text_url and match.url:
        try:
            full_text_url = _discover_pdf_url(match.url, timeout=timeout)
        except (
            FullTextError,
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
        ) as error:
            local_warnings.append(f"论文页面未能解析开放PDF：{error}")
    if not full_text_url:
        return FullTextResult(
            FullTextStatus.UNAVAILABLE,
            license=match.license,
            message=_not_nonexistent("元数据已匹配，但未发现可安全获取的开放全文链接"),
            warnings=tuple(local_warnings),
        )

    try:
        final_url = _download_pdf(
            full_text_url,
            destination,
            timeout=timeout,
            max_bytes=max_bytes,
        )
    except (
        FullTextError,
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
    ) as error:
        return FullTextResult(
            FullTextStatus.DOWNLOAD_FAILED,
            source_url=full_text_url,
            license=match.license,
            message=_not_nonexistent(f"开放全文获取失败：{error}"),
            warnings=tuple(local_warnings),
        )
    return FullTextResult(
        FullTextStatus.DOWNLOADED,
        path=destination,
        source_url=final_url,
        license=match.license,
        message="已从开放来源获取并校验PDF。",
        warnings=tuple(local_warnings),
    )


_VERIFICATION_MESSAGES = {
    "IDENTIFIER_FOUND": "标识符对应的论文元数据已匹配。",
    "VERIFIED_METADATA": "题名与论文元数据高置信匹配。",
    "RETRACTED": "元数据记录存在，但来源将该论文标记为已撤稿。",
    "METADATA_MISMATCH": "检索到候选记录，但参考文献与元数据存在不一致。",
    "PARTIAL_MATCH": _not_nonexistent("仅找到低置信候选，需要人工核查"),
    "NEEDS_MANUAL": _not_nonexistent("自动元数据源尚未确认该参考文献"),
    "LOOKUP_FAILED": _not_nonexistent("元数据服务暂时不可用，无法完成确认"),
}


def _verification_message(verification: PaperVerification) -> str:
    return _VERIFICATION_MESSAGES.get(
        verification.verdict,
        _not_nonexistent("当前元数据结果需要人工核查"),
    )


def _cache_path(cache_dir: Path, number: int, reference: str) -> Path:
    digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()[:12]
    return cache_dir / f"reference-{number}-{digest}.pdf"


def resolve_reference_sources(
    references: dict[int, str],
    local_matches: dict[int, Path],
    cache_dir: Path,
) -> dict[int, ReferenceResolution]:
    """批量核验参考文献元数据，并独立解析本地或开放全文来源。"""
    if not references:
        return {}
    numbers = list(references)
    queries = [references[number] for number in numbers]
    try:
        verifications = verify_papers(queries, include_fulltext=True)
    except PaperLookupError as error:
        verifications = [
            PaperVerification(
                query,
                "bibliographic",
                (),
                warnings=(str(error),),
                verdict="LOOKUP_FAILED",
            )
            for query in queries
        ]

    if len(verifications) != len(numbers):
        raise RuntimeError("批量元数据核验返回数量与参考文献数量不一致。")

    def resolve_one(
        item: tuple[int, str, PaperVerification],
    ) -> tuple[int, ReferenceResolution]:
        number, reference, verification = item
        match = verification.matches[0] if verification.matches else None
        downloadable_match = (
            match
            if verification.verdict in {"VERIFIED_METADATA", "IDENTIFIER_FOUND"}
            else None
        )
        local_path = local_matches.get(number)
        if downloadable_match is None and local_path is None and match is not None:
            fulltext = FullTextResult(
                FullTextStatus.LOW_CONFIDENCE,
                source_url=match.full_text_url,
                license=match.license,
                message=_not_nonexistent(
                    "文献元数据尚未高置信通过，为避免取错原文已跳过自动下载"
                ),
            )
        else:
            fulltext = acquire_fulltext(
                downloadable_match,
                _cache_path(cache_dir, number, reference),
                local_path=local_path,
            )
        return number, ReferenceResolution(
            number=number,
            reference=reference,
            verification_verdict=verification.verdict,
            verification_message=_verification_message(verification),
            url=match.url if match is not None else "",
            work_type=match.work_type if match is not None else "",
            is_retracted=match.is_retracted if match is not None else False,
            full_text_url=(fulltext.source_url or match.full_text_url) if match is not None else "",
            license=match.license if match is not None else "",
            path=fulltext.path,
            source_status=fulltext.status.value,
            source_message=fulltext.message,
            warnings=tuple(verification.warnings) + fulltext.warnings,
        )

    items = list(zip(numbers, queries, verifications, strict=True))
    workers = min(4, len(items))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return dict(executor.map(resolve_one, items))
