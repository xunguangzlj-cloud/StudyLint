import io
import json

from studylint.ai_audit import (
    AI_ISSUE_TYPES,
    AI_PROVIDER_PRESETS,
    AIConfig,
    _extract_json,
    _request_completion,
    _system_prompt,
    deep_verify_audits,
)
from studylint.claims import ClaimEvidence
from studylint.manuscripts import CitationAudit
from studylint.reporters import render_manuscript_html


def make_audit(verdict: str = "PARTIAL_SUPPORT") -> CitationAudit:
    return CitationAudit(
        claim="The treatment reduced complications.",
        paragraph=2,
        citation_number=1,
        reference_text="Example clinical study.",
        source_path="paper.pdf",
        verdict=verdict,
        explanation="规则判断。",
        evidences=(
            ClaimEvidence("paper.pdf", 3, "The treatment may reduce complications.", 80),
        ),
    )


def make_config(mode: str = "fast") -> AIConfig:
    return AIConfig(
        endpoint="http://localhost:8000/v1/chat/completions",
        model="test-model",
        api_key="test-key",
        mode=mode,
        skill="biomedical",
    )


def test_provider_presets_use_complete_https_endpoints() -> None:
    assert {"DeepSeek", "OpenAI", "Gemini", "通义千问（阿里云百炼）"} <= set(
        AI_PROVIDER_PRESETS
    )
    for endpoint, model in AI_PROVIDER_PRESETS.values():
        assert endpoint.startswith("https://")
        assert endpoint.endswith("/chat/completions")
        assert model

    assert AI_PROVIDER_PRESETS["DeepSeek"] == (
        "https://api.deepseek.com/chat/completions",
        "deepseek-flash",
    )


def test_extracts_json_from_code_fence() -> None:
    payload = _extract_json(
        '```json\n{"verdict":"SUPPORTED","confidence":91,'
        '"explanation":"supported","evidence_pages":[3]}\n```'
    )

    assert payload["verdict"] == "SUPPORTED"


def test_issue_types_are_a_closed_hallucination_taxonomy() -> None:
    assert AI_ISSUE_TYPES == {
        "CITATION_SOURCE": "引用/来源",
        "FACT_BACKGROUND": "事实背景",
        "DATA_RESULT": "数据结果",
        "METHOD_PROCESS": "方法过程",
        "LOGIC_REASONING": "逻辑推理",
        "MATH_FORMULA": "数学公式",
        "CONCEPT_TERMINOLOGY": "概念术语",
        "ATTRIBUTION_SOURCE": "归因来源",
        "ETHICS_COMPLIANCE": "伦理合规",
        "FORMAT_INTERNAL_CONSISTENCY": "格式/内部一致性",
        "TIME_VERSION": "时间/版本",
    }


def test_system_prompt_requires_evidence_and_limits_authenticity_claims() -> None:
    prompt = _system_prompt(make_config("strict"))

    assert '"issue_types"' in prompt
    assert all(code in prompt for code in AI_ISSUE_TYPES)
    assert "只能依据" in prompt
    assert "无法证明实验是否真实实施" in prompt
    assert "INSUFFICIENT" in prompt
    assert "不得断言造假、伪造、违规或未实施" in prompt


def test_openai_compatible_request_uses_bearer_key_and_structured_prompt(
    monkeypatch,
) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "verdict": "SUPPORTED",
                                "confidence": 95,
                                "explanation": "原文支持。",
                                "evidence_pages": [3],
                            }
                        )
                    }
                }
            ]
        }
        return io.BytesIO(json.dumps(response).encode("utf-8"))

    monkeypatch.setattr("studylint.ai_audit.urlopen", fake_urlopen)
    result = _request_completion(make_config(), make_audit())

    assert captured["authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "test-model"
    assert "candidate_evidence" in captured["body"]["messages"][1]["content"]
    assert "rule_verdict" not in captured["body"]["messages"][1]["content"]
    assert result["verdict"] == "SUPPORTED"


def test_fast_mode_skips_rule_direct_and_reviews_ambiguous(monkeypatch) -> None:
    calls: list[str] = []

    def fake_request(config, audit):
        calls.append(audit.verdict)
        return {
            "verdict": "PARTIAL",
            "confidence": 84,
            "explanation": "原文语气更谨慎。",
            "evidence_pages": [3],
        }

    monkeypatch.setattr("studylint.ai_audit._request_completion", fake_request)
    results = deep_verify_audits(
        [make_audit("DIRECT_SUPPORT"), make_audit("PARTIAL_SUPPORT")],
        make_config("fast"),
    )

    assert calls == ["PARTIAL_SUPPORT"]
    assert results[0].ai_verdict == "NOT_RUN_RULE_DIRECT"
    assert results[1].ai_verdict == "PARTIAL"
    assert results[1].ai_confidence == 84
    assert results[1].ai_evidence_pages == (3,)


def test_strict_mode_reviews_direct_support_and_renders_separate_result(monkeypatch) -> None:
    monkeypatch.setattr(
        "studylint.ai_audit._request_completion",
        lambda config, audit: {
            "verdict": "OVERSTATED",
            "confidence": 92,
            "explanation": "正文只说可能降低，论述删除了限定语。",
            "evidence_pages": [3],
        },
    )

    result = deep_verify_audits(
        [make_audit("DIRECT_SUPPORT")], make_config("strict")
    )[0]
    report = render_manuscript_html("draft.md", [result])

    assert result.verdict == "DIRECT_SUPPORT"
    assert result.ai_verdict == "OVERSTATED"
    assert "规则结果与AI结果分开显示" in report
    assert "AI判断：论述夸大" in report
    assert "test-key" not in report


def test_controlled_issue_types_are_deduplicated_and_added_to_explanation(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "studylint.ai_audit._request_completion",
        lambda config, audit: {
            "verdict": "OVERSTATED",
            "confidence": 90,
            "explanation": "相关关系被写成因果关系。",
            "evidence_pages": [3],
            "issue_types": [
                "LOGIC_REASONING",
                "DATA_RESULT",
                "LOGIC_REASONING",
            ],
        },
    )

    result = deep_verify_audits(
        [make_audit("PARTIAL_SUPPORT")], make_config("strict")
    )[0]

    assert result.ai_verdict == "OVERSTATED"
    assert result.ai_issue_types == ("LOGIC_REASONING", "DATA_RESULT")
    assert "问题类型：逻辑推理、数据结果" in result.ai_explanation


def test_unknown_issue_type_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "studylint.ai_audit._request_completion",
        lambda config, audit: {
            "verdict": "CONTRADICTED",
            "confidence": 90,
            "explanation": "存在问题。",
            "evidence_pages": [3],
            "issue_types": ["MADE_UP_CATEGORY"],
        },
    )

    result = deep_verify_audits(
        [make_audit("PARTIAL_SUPPORT")], make_config("strict")
    )[0]

    assert result.ai_verdict == "ERROR"
    assert "issue_types" in result.ai_explanation


def test_remote_http_endpoint_is_rejected() -> None:
    config = AIConfig(
        endpoint="http://example.com/v1/chat/completions",
        model="model",
        api_key="key",
    )

    try:
        config.validate()
    except ValueError as error:
        assert "HTTPS" in str(error)
    else:
        raise AssertionError("远程HTTP接口应被拒绝")
