import json

from mcp.types import TextContent

from mcp_yandex_ad.server import _error_response, _unwrap_confirmed_output


def test_confirm_output_success_pair_passes_structured():
    structured = {"result": {"UpdateResults": [{"Id": 1, "Errors": []}]}}
    out = ([TextContent(type="text", text=json.dumps(structured))], structured)
    assert _unwrap_confirmed_output(out) == (structured, False)


def test_confirm_output_error_list_is_flagged_and_serializable():
    out = _error_response(
        "direct.update_ads",
        ValueError("Элемент массива Ads.ResponsiveAd.Titles должен содержать строку"),
    )
    parsed, is_error = _unwrap_confirmed_output(out)
    assert is_error is True
    assert "должен содержать строку" in json.dumps(parsed, ensure_ascii=False)


def test_confirm_output_text_without_pair_is_parsed_not_raw():
    payload = {"tool": "direct.hf.pause_ads", "status": "ok", "result": {"paused": 2}}
    out = [TextContent(type="text", text=json.dumps(payload))]
    parsed, is_error = _unwrap_confirmed_output(out)
    assert is_error is False
    assert parsed == payload
    json.dumps(parsed)


def test_confirm_output_hf_error_status_is_flagged():
    out = [TextContent(type="text", text=json.dumps({"status": "error", "message": "nope"}))]
    assert _unwrap_confirmed_output(out)[1] is True
