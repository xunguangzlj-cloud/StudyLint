from pathlib import Path

from studylint.papers import extract_doi, parse_queries, read_query_file, verify_paper
from studylint.reporters import paper_status, render_paper_batch_html, render_paper_html


SAMPLE_RECORD = {
    "DOI": "10.1038/nature12373",
    "title": ["Nanometre-scale thermometry in a living cell"],
    "author": [
        {"given": "G.", "family": "Kucsko"},
        {"given": "P. C.", "family": "Maurer"},
    ],
    "published-print": {"date-parts": [[2013, 8, 1]]},
    "container-title": ["Nature"],
    "publisher": "Springer Science and Business Media LLC",
    "type": "journal-article",
    "URL": "https://doi.org/10.1038/nature12373",
}


def test_extract_doi_from_url() -> None:
    assert extract_doi("https://doi.org/10.1038/NATURE12373.") == "10.1038/nature12373"
    assert extract_doi("（doi:10.1038/nature12373）。") == "10.1038/nature12373"


def test_verify_exact_doi(monkeypatch) -> None:
    monkeypatch.setattr(
        "studylint.papers._request_json",
        lambda url: {"message": SAMPLE_RECORD},
    )

    verification = verify_paper("doi: 10.1038/nature12373")

    assert verification.query_type == "doi"
    assert verification.matches[0].title == "Nanometre-scale thermometry in a living cell"
    assert verification.matches[0].similarity == 100
    assert paper_status(verification)[0] == "DOI已匹配"


def test_verify_title_and_render_link(monkeypatch) -> None:
    monkeypatch.setattr(
        "studylint.papers._request_json",
        lambda url: {"message": {"items": [SAMPLE_RECORD]}},
    )

    verification = verify_paper("Nanometre-scale thermometry in a living cell")
    report = render_paper_html(verification)

    assert verification.matches[0].similarity == 100
    assert "https://doi.org/10.1038/nature12373" in report
    assert "查看论文页面" in report


def test_empty_result_does_not_claim_nonexistence(monkeypatch) -> None:
    monkeypatch.setattr(
        "studylint.papers._request_json",
        lambda url: {"message": {"items": []}},
    )

    verification = verify_paper("一篇不存在于数据库的虚构论文")
    status, explanation = paper_status(verification)

    assert status == "开放数据库未匹配"
    assert "不能证明论文不存在" in explanation


def test_parse_batch_queries_and_gb18030_file(tmp_path: Path) -> None:
    content = "1. 第一篇论文\n- 第二篇论文\n第一篇论文\n10.1038/nature12373\n"
    path = tmp_path / "papers.txt"
    path.write_text(content, encoding="gb18030")

    expected = ["第一篇论文", "第二篇论文", "10.1038/nature12373"]
    assert parse_queries(content) == expected
    assert read_query_file(path) == expected


def test_chinese_title_filters_irrelevant_results_and_links_cnki(monkeypatch) -> None:
    query = "高黏度与低黏度骨水泥二次注射椎体成形术"
    irrelevant = {
        **SAMPLE_RECORD,
        "DOI": "10.37155/example",
        "title": ["降低高强混凝土黏度的减水剂制备与机理研究"],
    }

    def fake_request(url: str) -> dict[str, object]:
        if "openalex.org" in url:
            return {"results": []}
        return {"message": {"items": [irrelevant]}}

    monkeypatch.setattr("studylint.papers._request_json", fake_request)
    verification = verify_paper(query)
    report = render_paper_html(verification)

    assert verification.matches == ()
    assert "在知网搜索" in report
    assert "降低高强混凝土黏度" not in report


def test_openalex_fallback(monkeypatch) -> None:
    openalex_record = {
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.1234/openalex",
        "display_name": "一篇中文医学论文",
        "authorships": [{"author": {"display_name": "张三"}}],
        "publication_year": 2024,
        "primary_location": {
            "landing_page_url": "https://doi.org/10.1234/openalex",
            "source": {"display_name": "测试期刊"},
        },
        "type": "article",
    }

    def fake_request(url: str) -> dict[str, object]:
        if "openalex.org" in url:
            return {"results": [openalex_record]}
        return {"message": {"items": []}}

    monkeypatch.setattr("studylint.papers._request_json", fake_request)
    verification = verify_paper("一篇中文医学论文")

    assert verification.matches[0].source == "OpenAlex"
    assert verification.matches[0].similarity == 100


def test_batch_report_contains_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        "studylint.papers._request_json",
        lambda url: {"message": {"items": []}},
    )
    verifications = [verify_paper("第一篇"), verify_paper("第二篇")]
    report = render_paper_batch_html(verifications)

    assert "共 <strong>2</strong> 篇" in report
    assert report.count("在知网搜索") == 2
