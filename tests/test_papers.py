from studylint.papers import extract_doi, verify_paper
from studylint.reporters import paper_status, render_paper_html


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

    assert status == "未检索到"
    assert "不能证明论文不存在" in explanation
