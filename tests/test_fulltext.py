from __future__ import annotations

import io
import socket
import zipfile
from pathlib import Path
from urllib.request import Request

import pytest

from studylint import fulltext
from studylint.fulltext import (
    FullTextStatus,
    UnsafeFullTextURLError,
    acquire_fulltext,
    resolve_reference_sources,
)
from studylint.papers import PaperLookupError, PaperMatch, PaperVerification


def _match(
    *,
    similarity: int = 100,
    full_text_url: str = "https://8.8.8.8/paper.pdf",
) -> PaperMatch:
    return PaperMatch(
        title="A verified paper",
        doi="10.1234/example",
        authors=("A. Author",),
        year="2025",
        venue="Journal",
        publisher="Publisher",
        work_type="journal-article",
        url="https://doi.org/10.1234/example",
        similarity=similarity,
        source="OpenAlex",
        full_text_url=full_text_url,
        license="cc-by",
    )


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        url: str = "https://8.8.8.8/paper.pdf",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = io.BytesIO(body)
        self._url = url
        self.headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_local_pdf_has_priority_over_confidence_and_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "uploaded.pdf"
    local.write_bytes(b"%PDF-1.7\nlocal")

    def fail_open(_request: Request, _timeout: float) -> _Response:
        raise AssertionError("本地文件可用时不应访问网络")

    monkeypatch.setattr(fulltext, "_open_url", fail_open)
    result = acquire_fulltext(
        _match(similarity=10, full_text_url="http://127.0.0.1/private.pdf"),
        tmp_path / "cache.pdf",
        local_path=local,
    )

    assert result.status is FullTextStatus.LOCAL_FILE
    assert result.path == local
    assert result.ok is True


def test_local_epub_is_validated_and_has_priority(tmp_path: Path) -> None:
    local = tmp_path / "uploaded.epub"
    with zipfile.ZipFile(local, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", "<container />")

    result = acquire_fulltext(None, tmp_path / "cache.pdf", local_path=local)

    assert result.status is FullTextStatus.LOCAL_FILE
    assert result.path == local
    assert "EPUB" in result.message


def test_invalid_local_epub_is_not_accepted(tmp_path: Path) -> None:
    local = tmp_path / "broken.epub"
    local.write_bytes(b"not a zip")

    result = acquire_fulltext(None, tmp_path / "cache.pdf", local_path=local)

    assert result.status is FullTextStatus.UNAVAILABLE
    assert result.path is None
    assert result.warnings and "EPUB" in result.warnings[0]


def test_low_confidence_match_is_never_downloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_open(_request: Request, _timeout: float) -> _Response:
        raise AssertionError("低置信匹配不应下载")

    monkeypatch.setattr(fulltext, "_open_url", fail_open)
    result = acquire_fulltext(_match(similarity=84), tmp_path / "paper.pdf")

    assert result.status is FullTextStatus.LOW_CONFIDENCE
    assert result.path is None
    assert "不代表论文不存在" in result.message


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/paper.pdf",
        "https://127.0.0.1/paper.pdf",
        "https://10.0.0.8/paper.pdf",
        "https://[::1]/paper.pdf",
    ],
)
def test_download_rejects_non_https_and_private_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    def fail_open(_request: Request, _timeout: float) -> _Response:
        raise AssertionError("不安全URL不应发起请求")

    monkeypatch.setattr(fulltext, "_open_url", fail_open)
    result = acquire_fulltext(
        _match(full_text_url=url), tmp_path / "paper.pdf"
    )

    assert result.status is FullTextStatus.DOWNLOAD_FAILED
    assert result.path is None
    assert "不代表论文不存在" in result.message


def test_hostname_resolving_to_private_address_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.2", 443))
        ],
    )

    with pytest.raises(UnsafeFullTextURLError):
        fulltext._validate_https_public_url("https://example.com/paper.pdf")


def test_redirect_handler_revalidates_target_url() -> None:
    handler = fulltext._SafeRedirectHandler()
    request = Request("https://8.8.8.8/paper.pdf")

    with pytest.raises(UnsafeFullTextURLError):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "http://127.0.0.1/redirected.pdf",
        )


def test_download_uses_timeout_checks_pdf_and_lands_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"%PDF-1.7\nvalid"
    observed: dict[str, object] = {}

    def fake_open(request: Request, timeout: float) -> _Response:
        observed["url"] = request.full_url
        observed["timeout"] = timeout
        return _Response(body, headers={"Content-Length": str(len(body))})

    monkeypatch.setattr(fulltext, "_open_url", fake_open)
    destination = tmp_path / "cached.pdf"
    result = acquire_fulltext(
        _match(), destination, timeout=3.5, max_bytes=1024
    )

    assert result.status is FullTextStatus.DOWNLOADED
    assert result.path == destination
    assert destination.read_bytes() == body
    assert observed == {
        "url": "https://8.8.8.8/paper.pdf",
        "timeout": 3.5,
    }
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize(
    ("body", "headers", "max_bytes"),
    [
        (b"<html>not a pdf</html>", {}, 1024),
        (b"%PDF-1.7\ntoo large", {"Content-Length": "9999"}, 32),
        (b"%PDF-1.7\n" + b"x" * 64, {}, 32),
    ],
)
def test_invalid_or_oversized_download_leaves_no_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    headers: dict[str, str],
    max_bytes: int,
) -> None:
    monkeypatch.setattr(
        fulltext,
        "_open_url",
        lambda _request, _timeout: _Response(body, headers=headers),
    )
    destination = tmp_path / "paper.pdf"

    result = acquire_fulltext(
        _match(), destination, max_bytes=max_bytes
    )

    assert result.status is FullTextStatus.DOWNLOAD_FAILED
    assert result.path is None
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []
    assert "不代表论文不存在" in result.message


def test_network_timeout_is_fulltext_failure_not_nonexistent_paper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def time_out(_request: Request, _timeout: float) -> _Response:
        raise TimeoutError("timed out")

    monkeypatch.setattr(fulltext, "_open_url", time_out)
    result = acquire_fulltext(_match(), tmp_path / "paper.pdf")

    assert result.status is FullTextStatus.DOWNLOAD_FAILED
    assert "不代表论文不存在" in result.message


def test_discovers_pdf_from_publisher_landing_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = b'''<html><head>
    <meta name="citation_pdf_url" content="/article/open.pdf">
    </head></html>'''
    pdf = b"%PDF-1.7\nopen"
    requested: list[str] = []

    def fake_open(request: Request, _timeout: float) -> _Response:
        requested.append(request.full_url)
        if request.full_url == "https://8.8.8.8/article":
            return _Response(
                html,
                url="https://8.8.8.8/article",
                headers={"Content-Type": "text/html; charset=utf-8"},
            )
        return _Response(
            pdf,
            url="https://8.8.8.8/article/open.pdf",
            headers={"Content-Type": "application/pdf"},
        )

    monkeypatch.setattr(fulltext, "_open_url", fake_open)
    match = _match(full_text_url="")
    match = PaperMatch(**{**match.__dict__, "url": "https://8.8.8.8/article"})
    result = acquire_fulltext(match, tmp_path / "paper.pdf")

    assert result.status is FullTextStatus.DOWNLOADED
    assert result.source_url == "https://8.8.8.8/article/open.pdf"
    assert requested == [
        "https://8.8.8.8/article",
        "https://8.8.8.8/article/open.pdf",
    ]


def test_unsafe_pdf_link_on_landing_page_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = b'''<meta name="citation_pdf_url" content="http://127.0.0.1/private.pdf">'''
    monkeypatch.setattr(
        fulltext,
        "_open_url",
        lambda _request, _timeout: _Response(
            html,
            url="https://8.8.8.8/article",
            headers={"Content-Type": "text/html"},
        ),
    )
    match = _match(full_text_url="")
    match = PaperMatch(**{**match.__dict__, "url": "https://8.8.8.8/article"})
    result = acquire_fulltext(match, tmp_path / "paper.pdf")

    assert result.status is FullTextStatus.UNAVAILABLE
    assert result.path is None
    assert result.warnings and "HTTPS" in result.warnings[0]


def test_resolve_reference_sources_keeps_metadata_and_fulltext_states_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "local.pdf"
    local.write_bytes(b"%PDF-1.7\nlocal")
    verifications = [
        PaperVerification("one", "bibliographic", (_match(),), verdict="VERIFIED_METADATA"),
        PaperVerification(
            "two",
            "bibliographic",
            (_match(similarity=70),),
            verdict="PARTIAL_MATCH",
        ),
        PaperVerification("three", "bibliographic", (), verdict="NEEDS_MANUAL"),
    ]
    monkeypatch.setattr(
        fulltext, "verify_papers", lambda _queries, **_kwargs: verifications
    )

    def fail_open(_request: Request, _timeout: float) -> _Response:
        raise AssertionError("这些状态都不应下载")

    monkeypatch.setattr(fulltext, "_open_url", fail_open)
    results = resolve_reference_sources(
        {1: "one", 2: "two", 3: "three"},
        {1: local},
        tmp_path / "cache",
    )

    assert results[1].verification_verdict == "VERIFIED_METADATA"
    assert results[1].source_status == "LOCAL_FILE"
    assert results[1].path == local
    assert results[2].verification_verdict == "PARTIAL_MATCH"
    assert results[2].source_status == "LOW_CONFIDENCE"
    assert results[2].path is None
    assert results[3].verification_verdict == "NEEDS_MANUAL"
    assert results[3].source_status == "UNAVAILABLE"
    assert "不代表论文不存在" in results[3].verification_message


def test_metadata_service_failure_does_not_hide_valid_local_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "local.pdf"
    local.write_bytes(b"%PDF-1.7\nlocal")

    def fail_lookup(
        _queries: list[str], **_kwargs
    ) -> list[PaperVerification]:
        raise PaperLookupError("元数据服务超时")

    monkeypatch.setattr(fulltext, "verify_papers", fail_lookup)
    results = resolve_reference_sources(
        {1: "one"}, {1: local}, tmp_path / "cache"
    )

    assert results[1].verification_verdict == "LOOKUP_FAILED"
    assert "不代表论文不存在" in results[1].verification_message
    assert results[1].source_status == "LOCAL_FILE"
    assert results[1].path == local


def test_metadata_mismatch_never_downloads_even_with_exact_title_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verification = PaperVerification(
        "claimed 2017 reference",
        "bibliographic",
        (_match(similarity=100),),
        verdict="METADATA_MISMATCH",
    )
    monkeypatch.setattr(
        fulltext, "verify_papers", lambda _queries, **_kwargs: [verification]
    )
    monkeypatch.setattr(
        fulltext,
        "_open_url",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("元数据冲突时不得下载候选全文")
        ),
    )

    result = resolve_reference_sources(
        {1: "claimed 2017 reference"}, {}, tmp_path / "cache"
    )[1]

    assert result.verification_verdict == "METADATA_MISMATCH"
    assert result.path is None
    assert result.source_status == "LOW_CONFIDENCE"
