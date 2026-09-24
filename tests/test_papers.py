from pathlib import Path

import pytest

from studylint import PROJECT_URL
from studylint.papers import (
    PaperLookupError,
    PaperVerification,
    _doaj_search,
    extract_doi,
    parse_queries,
    read_query_file,
    verify_paper,
)
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


@pytest.fixture(autouse=True)
def no_live_arxiv_requests(monkeypatch) -> None:
    monkeypatch.setattr(
        "studylint.papers._request_text",
        lambda url: '<feed xmlns="http://www.w3.org/2005/Atom"></feed>',
    )


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
    assert verification.verdict == "IDENTIFIER_FOUND"
    assert paper_status(verification)[0] == "DOI已登记"


def test_doi_metadata_mismatch_is_not_reported_as_verified(monkeypatch) -> None:
    monkeypatch.setattr(
        "studylint.papers._request_json",
        lambda url: {"message": SAMPLE_RECORD},
    )

    verification = verify_paper(
        "Kucsko et al. (2013). A fabricated paper title. doi:10.1038/nature12373"
    )
    status, explanation = paper_status(verification)

    assert verification.verdict == "METADATA_MISMATCH"
    assert verification.matches[0].similarity < 55
    assert status == "元数据冲突"
    assert "DOI真实存在" in explanation


def test_doi_with_matching_title_verifies_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        "studylint.papers._request_json",
        lambda url: {"message": SAMPLE_RECORD},
    )

    verification = verify_paper(
        "Kucsko et al. (2013). Nanometre-scale thermometry in a living cell. "
        "doi:10.1038/nature12373"
    )

    assert verification.verdict == "VERIFIED_METADATA"
    assert verification.matches[0].similarity >= 85


def test_doi_with_wrong_year_reports_metadata_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        "studylint.papers._request_json",
        lambda url: {"message": SAMPLE_RECORD},
    )

    verification = verify_paper(
        "Kucsko et al. (2025). Nanometre-scale thermometry in a living cell. "
        "doi:10.1038/nature12373"
    )

    assert verification.verdict == "METADATA_MISMATCH"
    assert "引用年份2025" in verification.warnings[0]


def test_title_search_prefers_matching_year_over_same_title_republication(
    monkeypatch,
) -> None:
    crossref_republication = {
        **SAMPLE_RECORD,
        "DOI": "10.9999/republication",
        "title": ["Attention Is All You Need"],
        "published-print": {"date-parts": [[2025, 1, 1]]},
    }
    openalex_original = {
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.48550/arXiv.1706.03762",
        "display_name": "Attention Is All You Need",
        "authorships": [],
        "publication_year": 2017,
        "primary_location": {
            "landing_page_url": "https://arxiv.org/abs/1706.03762",
            "source": {"display_name": "arXiv"},
        },
        "type": "preprint",
    }

    def fake_request(url: str) -> dict[str, object]:
        if "openalex.org" in url:
            return {"results": [openalex_original]}
        return {"message": {"items": [crossref_republication]}}

    monkeypatch.setattr("studylint.papers._request_json", fake_request)
    verification = verify_paper(
        "Vaswani et al. (2017). Attention Is All You Need."
    )

    assert verification.verdict == "VERIFIED_METADATA"
    assert verification.matches[0].year == "2017"
    assert verification.matches[0].source == "OpenAlex"


def test_title_is_extracted_after_year_not_from_long_author_list(monkeypatch) -> None:
    record = {
        **SAMPLE_RECORD,
        "title": ["Attention Is All You Need"],
        "published-print": {"date-parts": [[2017, 6, 1]]},
    }
    monkeypatch.setattr(
        "studylint.papers._request_json",
        lambda url: {"message": record},
    )

    verification = verify_paper(
        "Vaswani, Shazeer, Parmar, Uszkoreit, Jones, Gomez, Kaiser, Polosukhin "
        "(2017). Attention Is All You Need. doi:10.1038/nature12373"
    )

    assert verification.verdict == "VERIFIED_METADATA"
    assert verification.matches[0].similarity == 100


def test_title_search_with_wrong_year_reports_metadata_mismatch(monkeypatch) -> None:
    def fake_request(url: str) -> dict[str, object]:
        if "openalex.org" in url:
            return {"results": []}
        return {"message": {"items": [SAMPLE_RECORD]}}

    monkeypatch.setattr("studylint.papers._request_json", fake_request)
    verification = verify_paper(
        "Kucsko et al. (2025). Nanometre-scale thermometry in a living cell."
    )

    assert verification.verdict == "METADATA_MISMATCH"
    assert "引用年份2025" in verification.warnings[0]


def test_truncated_title_is_not_verified_by_subset_match(monkeypatch) -> None:
    record = {
        **SAMPLE_RECORD,
        "title": ["Large Language Models: An Applied Econometric Framework"],
    }
    monkeypatch.setattr(
        "studylint.papers._request_json",
        lambda url: {"message": {"items": [record]}},
    )

    verification = verify_paper("Large Language Models")

    assert verification.verdict == "PARTIAL_MATCH"
    assert 55 <= verification.matches[0].similarity < 85


def test_stopwords_do_not_create_a_title_match(monkeypatch) -> None:
    record = {
        **SAMPLE_RECORD,
        "title": ["On the Origin of Species by Means of Natural Selection"],
    }

    def fake_request(url: str) -> dict[str, object]:
        if "openalex.org" in url:
            return {"results": []}
        return {"message": {"items": [record]}}

    monkeypatch.setattr("studylint.papers._request_json", fake_request)

    verification = verify_paper("On the")

    assert verification.matches == ()
    assert verification.verdict == "NEEDS_MANUAL"


def test_verified_paper_is_hidden_from_report(monkeypatch) -> None:
    monkeypatch.setattr(
        "studylint.papers._request_json",
        lambda url: {"message": {"items": [SAMPLE_RECORD]}},
    )

    verification = verify_paper("Nanometre-scale thermometry in a living cell")
    report = render_paper_html(verification)

    assert verification.matches[0].similarity == 100
    assert "Nanometre-scale thermometry in a living cell" not in report
    assert "没有需要继续人工核查的论文" in report


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
        "best_oa_location": {
            "pdf_url": "https://example.org/openalex.pdf",
            "license": "cc-by",
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
    assert verification.matches[0].full_text_url.endswith("openalex.pdf")
    assert verification.matches[0].license == "cc-by"


def test_semantic_scholar_fallback(monkeypatch) -> None:
    semantic_record = {
        "paperId": "S2-123",
        "title": "一篇仅被第三数据库找到的论文",
        "authors": [{"name": "李四"}],
        "year": 2025,
        "venue": "测试会议",
        "externalIds": {"DOI": "10.1234/semantic"},
        "url": "https://www.semanticscholar.org/paper/S2-123",
        "publicationTypes": ["JournalArticle"],
        "openAccessPdf": {
            "url": "https://example.org/semantic.pdf",
            "license": "CCBY",
        },
    }

    def fake_request(url: str) -> dict[str, object]:
        if "semanticscholar.org" in url:
            return {"data": [semantic_record]}
        if "openalex.org" in url:
            return {"results": []}
        return {"message": {"items": []}}

    monkeypatch.setattr("studylint.papers._request_json", fake_request)
    verification = verify_paper("一篇仅被第三数据库找到的论文")

    assert verification.verdict == "VERIFIED_METADATA"
    assert verification.matches[0].source == "Semantic Scholar"
    assert verification.matches[0].doi == "10.1234/semantic"
    assert verification.matches[0].full_text_url.endswith("semantic.pdf")


def test_fulltext_mode_enriches_high_confidence_metadata_match(monkeypatch) -> None:
    crossref_record = {
        **SAMPLE_RECORD,
        "DOI": "10.1234/enriched",
        "title": ["A Verified Open Paper"],
    }
    semantic_record = {
        "paperId": "S2-open",
        "title": "A Verified Open Paper",
        "authors": [{"name": "Ada Example"}],
        "year": 2013,
        "venue": "Test Journal",
        "externalIds": {"DOI": "10.1234/enriched"},
        "url": "https://www.semanticscholar.org/paper/S2-open",
        "openAccessPdf": {
            "url": "https://example.org/enriched.pdf",
            "license": "CCBY",
        },
    }

    def fake_request(url: str) -> dict[str, object]:
        if "semanticscholar.org" in url:
            return {"data": [semantic_record]}
        if "openalex.org" in url:
            return {"results": []}
        if "dblp.org" in url:
            return {"result": {"hits": {"hit": []}}}
        if "europepmc" in url:
            return {"resultList": {"result": []}}
        return {"message": {"items": [crossref_record]}}

    monkeypatch.setattr("studylint.papers._request_json", fake_request)
    verification = verify_paper(
        "A Verified Open Paper", include_fulltext=True
    )

    assert verification.verdict == "VERIFIED_METADATA"
    assert verification.matches[0].source == "Crossref + Semantic Scholar"
    assert verification.matches[0].full_text_url.endswith("enriched.pdf")


def test_semantic_scholar_doi_fallback(monkeypatch) -> None:
    semantic_record = {
        "paperId": "S2-DOI",
        "title": "A DOI record found by the third database",
        "authors": [{"name": "Ada Example"}],
        "year": 2024,
        "venue": "Test Journal",
        "externalIds": {"DOI": "10.1234/semantic-doi"},
        "url": "https://www.semanticscholar.org/paper/S2-DOI",
    }

    def fake_request(url: str) -> dict[str, object]:
        if "semanticscholar.org" in url:
            return semantic_record
        if "openalex.org" in url:
            return {"results": []}
        return {}

    monkeypatch.setattr("studylint.papers._request_json", fake_request)
    verification = verify_paper("doi:10.1234/semantic-doi")

    assert verification.verdict == "IDENTIFIER_FOUND"
    assert verification.matches[0].source == "Semantic Scholar"
    assert verification.matches[0].similarity == 100


def test_arxiv_fallback(monkeypatch) -> None:
    feed = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>https://arxiv.org/abs/2401.12345</id>
        <title>Foreign Preprint Found on arXiv</title>
        <published>2024-01-20T00:00:00Z</published>
        <author><name>Ada Example</name></author>
        <arxiv:doi>10.1234/arxiv-example</arxiv:doi>
        <link href="http://arxiv.org/pdf/2401.12345" type="application/pdf"/>
      </entry>
    </feed>"""

    def fake_json(url: str) -> dict[str, object]:
        if "openalex.org" in url:
            return {"results": []}
        if "semanticscholar.org" in url:
            return {"data": []}
        if "dblp.org" in url:
            return {"result": {"hits": {"hit": []}}}
        if "europepmc" in url:
            return {"resultList": {"result": []}}
        return {"message": {"items": []}}

    monkeypatch.setattr("studylint.papers._request_json", fake_json)
    monkeypatch.setattr("studylint.papers._request_text", lambda url: feed)
    verification = verify_paper("Foreign Preprint Found on arXiv")

    assert verification.verdict == "VERIFIED_METADATA"
    assert verification.matches[0].source == "arXiv"
    assert verification.matches[0].url.endswith("2401.12345")
    assert verification.matches[0].full_text_url == "https://arxiv.org/pdf/2401.12345"


def test_dblp_fallback(monkeypatch) -> None:
    dblp_payload = {
        "result": {
            "hits": {
                "hit": [
                    {
                        "info": {
                            "title": "A Foreign Computer Science Conference Paper",
                            "authors": {"author": [{"text": "Ada Example"}]},
                            "year": "2025",
                            "venue": "TestConf",
                            "doi": "10.1234/dblp-example",
                            "url": "https://dblp.org/rec/conf/test/example",
                            "type": "Conference and Workshop Papers",
                        }
                    }
                ]
            }
        }
    }

    def fake_request(url: str) -> dict[str, object]:
        if "dblp.org" in url:
            return dblp_payload
        if "openalex.org" in url:
            return {"results": []}
        if "semanticscholar.org" in url:
            return {"data": []}
        if "europepmc" in url:
            return {"resultList": {"result": []}}
        return {"message": {"items": []}}

    monkeypatch.setattr("studylint.papers._request_json", fake_request)
    verification = verify_paper("A Foreign Computer Science Conference Paper")

    assert verification.verdict == "VERIFIED_METADATA"
    assert verification.matches[0].source == "DBLP"


def test_europe_pmc_fallback(monkeypatch) -> None:
    europe_pmc_payload = {
        "resultList": {
            "result": [
                {
                    "title": "An International Biomedical Study",
                    "authorString": "Ada Example, Bob Example",
                    "pubYear": "2023",
                    "journalTitle": "Test Medicine",
                    "doi": "10.1234/pmc-example",
                    "pmid": "12345678",
                    "pubType": "research article",
                    "isOpenAccess": "Y",
                    "license": "cc-by",
                    "fullTextUrlList": {
                        "fullTextUrl": [
                            {
                                "documentStyle": "pdf",
                                "url": "https://europepmc.org/articles/PMC123/pdf/test.pdf",
                            }
                        ]
                    },
                }
            ]
        }
    }

    def fake_request(url: str) -> dict[str, object]:
        if "europepmc" in url:
            return europe_pmc_payload
        if "openalex.org" in url:
            return {"results": []}
        if "semanticscholar.org" in url:
            return {"data": []}
        if "dblp.org" in url:
            return {"result": {"hits": {"hit": []}}}
        return {"message": {"items": []}}

    monkeypatch.setattr("studylint.papers._request_json", fake_request)
    verification = verify_paper("An International Biomedical Study")

    assert verification.verdict == "VERIFIED_METADATA"
    assert verification.matches[0].source == "Europe PMC"
    assert verification.matches[0].authors == ("Ada Example", "Bob Example")
    assert verification.matches[0].full_text_url.endswith("test.pdf")


def test_doaj_search_extracts_open_fulltext(monkeypatch) -> None:
    payload = {
        "results": [
            {
                "id": "doaj-record-id",
                "bibjson": {
                    "title": "An Open Journal Article",
                    "year": "2024",
                    "author": [{"name": "Ada Example"}],
                    "identifier": [
                        {"type": "doi", "id": "10.1234/doaj-example"}
                    ],
                    "journal": {
                        "title": "Open Journal",
                        "publisher": "Open Publisher",
                    },
                    "link": [
                        {
                            "type": "fulltext",
                            "content_type": "application/pdf",
                            "url": "http://europepmc.org/articles/PMC1?pdf=render",
                        }
                    ],
                    "license": [{"type": "CC BY"}],
                },
            }
        ]
    }
    monkeypatch.setattr("studylint.papers._request_json", lambda _url: payload)

    match = _doaj_search("An Open Journal Article")[0]

    assert match.source == "DOAJ"
    assert match.similarity == 100
    assert match.doi == "10.1234/doaj-example"
    assert match.authors == ("Ada Example",)
    assert match.full_text_url.startswith("https://europepmc.org/")
    assert match.license == "CC BY"


def test_doaj_is_used_as_fulltext_fallback(monkeypatch) -> None:
    crossref_record = {
        **SAMPLE_RECORD,
        "DOI": "10.1234/doaj-fallback",
        "title": ["A DOAJ Fulltext Fallback"],
    }
    doaj_payload = {
        "results": [
            {
                "id": "doaj-record-id",
                "bibjson": {
                    "title": "A DOAJ Fulltext Fallback",
                    "year": "2013",
                    "identifier": [
                        {"type": "doi", "id": "10.1234/doaj-fallback"}
                    ],
                    "link": [
                        {
                            "type": "fulltext",
                            "content_type": "application/pdf",
                            "url": "https://example.org/doaj.pdf",
                        }
                    ],
                },
            }
        ]
    }

    def fake_request(url: str) -> dict[str, object]:
        if "doaj.org" in url:
            return doaj_payload
        if "openalex.org" in url:
            return {"results": []}
        if "semanticscholar.org" in url:
            return {"data": []}
        if "dblp.org" in url:
            return {"result": {"hits": {"hit": []}}}
        if "europepmc" in url:
            return {"resultList": {"result": []}}
        return {"message": {"items": [crossref_record]}}

    monkeypatch.setattr("studylint.papers._request_json", fake_request)
    verification = verify_paper("A DOAJ Fulltext Fallback", include_fulltext=True)

    assert verification.verdict == "VERIFIED_METADATA"
    assert verification.matches[0].source == "Crossref + DOAJ"
    assert verification.matches[0].full_text_url.endswith("doaj.pdf")


def test_one_fallback_service_failure_does_not_abort_verification(monkeypatch) -> None:
    def fake_request(url: str) -> dict[str, object]:
        if "openalex.org" in url:
            return {"results": []}
        if "semanticscholar.org" in url:
            return {"data": []}
        if "europepmc" in url:
            return {"resultList": {"result": []}}
        return {"message": {"items": []}}

    monkeypatch.setattr("studylint.papers._request_json", fake_request)
    monkeypatch.setattr(
        "studylint.papers._dblp_search",
        lambda query: (_ for _ in ()).throw(PaperLookupError("DBLP暂时不可用。")),
    )

    verification = verify_paper("A paper that needs fallback services")

    assert verification.verdict == "NEEDS_MANUAL"
    assert "DBLP暂时不可用。" in verification.warnings


def test_retracted_openalex_record_has_priority(monkeypatch) -> None:
    openalex_record = {
        "id": "https://openalex.org/W999",
        "doi": "https://doi.org/10.1234/retracted",
        "display_name": "一篇后来被撤稿的论文",
        "authorships": [{"author": {"display_name": "王五"}}],
        "publication_year": 2020,
        "primary_location": {
            "landing_page_url": "https://doi.org/10.1234/retracted",
            "source": {"display_name": "测试期刊"},
        },
        "type": "article",
        "is_retracted": True,
    }

    def fake_request(url: str) -> dict[str, object]:
        if "openalex.org" in url:
            return {"results": [openalex_record]}
        if "semanticscholar.org" in url:
            return {"data": []}
        return {"message": {"items": []}}

    monkeypatch.setattr("studylint.papers._request_json", fake_request)
    verification = verify_paper("一篇后来被撤稿的论文")
    report = render_paper_html(verification)

    assert verification.verdict == "RETRACTED"
    assert verification.matches[0].is_retracted is True
    assert paper_status(verification)[0] == "撤稿警告"
    assert "请自行核查这篇论文" in report
    assert "已撤稿" not in report
    assert "RETRACTED" not in report


def test_crossref_and_openalex_duplicate_merges_retraction_flag(monkeypatch) -> None:
    openalex_record = {
        "id": "https://openalex.org/W999",
        "doi": "https://doi.org/10.1038/nature12373",
        "display_name": "Nanometre-scale thermometry in a living cell",
        "publication_year": 2013,
        "authorships": [],
        "primary_location": {},
        "type": "article",
        "is_retracted": True,
    }

    def fake_request(url: str) -> dict[str, object]:
        if "openalex.org" in url:
            return {"results": [openalex_record]}
        return {"message": SAMPLE_RECORD}

    monkeypatch.setattr("studylint.papers._request_json", fake_request)
    verification = verify_paper("doi:10.1038/nature12373")

    assert verification.verdict == "RETRACTED"
    assert verification.matches[0].source == "Crossref + OpenAlex"
    assert verification.matches[0].is_retracted is True


def test_batch_report_contains_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        "studylint.papers._request_json",
        lambda url: {"message": {"items": []}},
    )
    verifications = [verify_paper("第一篇"), verify_paper("第二篇")]
    report = render_paper_batch_html(verifications)

    assert "需要自行核查 <strong>2</strong> 篇" in report
    assert report.count("在知网搜索") == 2
    assert 'target="_blank"' in report
    assert "一键" not in report
    assert "openManualChecks" not in report
    assert ">⭐ Star</a>" in report
    assert PROJECT_URL in report


def test_batch_report_hides_passed_papers() -> None:
    verifications = [
        PaperVerification(
            query="已通过论文",
            query_type="bibliographic",
            matches=(),
            verdict="VERIFIED_METADATA",
        ),
        PaperVerification(
            query="待核查论文",
            query_type="bibliographic",
            matches=(),
            verdict="NEEDS_MANUAL",
        ),
    ]

    report = render_paper_batch_html(verifications)

    assert "已通过论文" not in report
    assert "待核查论文" in report
    assert "需要自行核查 <strong>1</strong> 篇" in report
