from pathlib import Path

from studylint.parsers import extract_citations, load_source, parse_time


def test_parse_time() -> None:
    assert parse_time("00:01:30") == 90
    assert parse_time("01:02:03,400") == 3723
    assert parse_time("00:70:00") is None


def test_extract_citations() -> None:
    citations = extract_citations(
        "内容 [slides.pdf#page=12] [lecture.srt#time=00:31:42]"
    )
    assert [(item.source_name, item.locator_type, item.locator_value) for item in citations] == [
        ("slides.pdf", "page", 12),
        ("lecture.srt", "time", 1902),
    ]


def test_markdown_page_markers(tmp_path: Path) -> None:
    source = tmp_path / "slides.md"
    source.write_text("第一页\n<!-- page: 3 -->\n第三页", encoding="utf-8")
    document = load_source(source)
    assert [(span.locator_value, span.text) for span in document.spans] == [
        (1, "第一页"),
        (3, "第三页"),
    ]


def test_srt_segments(tmp_path: Path) -> None:
    source = tmp_path / "lecture.srt"
    source.write_text(
        "1\n00:00:01,000 --> 00:00:04,000\n第一句话\n\n"
        "2\n00:00:05,000 --> 00:00:08,000\n第二句话\n",
        encoding="utf-8",
    )
    document = load_source(source)
    assert len(document.spans) == 2
    assert document.spans[1].locator_value == 5
    assert document.spans[1].end_value == 8


def test_pdf_pages(tmp_path: Path) -> None:
    import fitz

    source = tmp_path / "slides.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Page one evidence")
    document.save(source)
    document.close()

    parsed = load_source(source)
    assert len(parsed.spans) == 1
    assert parsed.spans[0].locator_value == 1
    assert "Page one evidence" in parsed.spans[0].text


def test_pptx_slides(tmp_path: Path) -> None:
    from pptx import Presentation

    source = tmp_path / "slides.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Slide evidence"
    presentation.save(source)

    parsed = load_source(source)
    assert len(parsed.spans) == 1
    assert parsed.spans[0].locator_value == 1
    assert "Slide evidence" in parsed.spans[0].text
