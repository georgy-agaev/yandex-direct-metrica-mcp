"""Tool contract metadata for prioritized MCP tools."""

from __future__ import annotations

from typing import Any

from mcp.types import Tool, ToolAnnotations


def _string_array_schema() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _meta_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["envelope_version", "request_id", "timestamp"],
        "properties": {
            "envelope_version": {"type": "string"},
            "tool_version": {"type": "string"},
            "request_id": {"type": "string"},
            "timestamp": {"type": "string"},
        },
    }


def _error_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["code", "type", "retryable"],
        "properties": {
            "code": {"type": "string"},
            "type": {"type": "string"},
            "retryable": {"type": "boolean"},
            "details": {"type": "object"},
        },
    }


def _choice_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["id", "label", "type", "context"],
        "properties": {
            "id": {"type": "string"},
            "label": {"type": "string"},
            "type": {"type": "string"},
            "context": {"type": "object"},
        },
    }


def _warning_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["code", "message", "details"],
        "properties": {
            "code": {"type": "string"},
            "message": {"type": "string"},
            "field": {"type": "string"},
            "details": {"type": "object"},
        },
    }


def _hf_envelope_schema(*, result_schema: dict[str, Any] | None = None, preview_schema: dict[str, Any] | None = None) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "tool": {"type": "string"},
        "status": {"type": "string"},
        "message": {"type": "string"},
        "meta": _meta_schema(),
        "error": _error_schema(),
        "choices": {"type": "array", "items": _choice_schema()},
        "warnings": {"type": "array", "items": _warning_schema()},
    }
    if result_schema is not None:
        properties["result"] = result_schema
    else:
        properties["result"] = {"type": "object"}
    if preview_schema is not None:
        properties["preview"] = preview_schema
    else:
        properties["preview"] = {"type": "object"}
    return {
        "type": "object",
        "required": ["tool", "status", "meta"],
        "properties": properties,
    }


def _campaign_counts_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["campaign_id", "counts"],
        "properties": {
            "campaign_id": {"type": "integer"},
            "counts": {
                "type": "object",
                "properties": {
                    "adgroups": {"type": "integer"},
                    "ads": {"type": "integer"},
                    "keywords": {"type": "integer"},
                },
            },
        },
    }


def _bids_summary_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["campaign_id", "count"],
        "properties": {
            "campaign_id": {"type": "integer"},
            "count": {"type": "integer"},
            "min": {"type": "number"},
            "avg": {"type": "number"},
            "max": {"type": "number"},
        },
    }


def _direct_report_result_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "raw": {"type": "string"},
            "columns": _string_array_schema(),
        },
    }


def _metrica_report_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["counter_id", "raw"],
        "properties": {
            "counter_id": {"type": "string"},
            "raw": {"type": "object"},
        },
    }


def _time_series_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["counter_id", "metric", "granularity", "data", "raw"],
        "properties": {
            "counter_id": {"type": "string"},
            "metric": {"type": "string"},
            "granularity": {"type": "string"},
            "data": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "period": {"type": "string"},
                        "metrics": {"type": "array", "items": {"type": "number"}},
                    },
                },
            },
            "raw": {"type": "object"},
        },
    }


def _join_utm_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["utm_campaign", "campaign_id", "counter_id", "joined_by_date", "totals", "raw"],
        "properties": {
            "utm_campaign": {"type": "string"},
            "campaign_id": {"type": "integer"},
            "counter_id": {"type": "string"},
            "joined_by_date": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string"},
                        "impressions": {"type": "number"},
                        "clicks": {"type": "number"},
                        "cost": {"type": "number"},
                        "visits": {"type": "number"},
                    },
                },
            },
            "totals": {"type": "object"},
            "raw": {"type": "object"},
        },
    }


def _accounts_list_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["result"],
        "properties": {
            "result": {
                "type": "object",
                "required": ["path", "count", "accounts"],
                "properties": {
                    "path": {"type": ["string", "null"]},
                    "count": {"type": "integer"},
                    "accounts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id"],
                            "properties": {
                                "id": {"type": "string"},
                                "name": {"type": "string"},
                                "direct_client_login": {"type": "string"},
                                "metrica_counter_ids": _string_array_schema(),
                            },
                        },
                    },
                },
            },
        },
    }


def _dashboard_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["result"],
        "properties": {
            "result": {
                "type": "object",
                "properties": {
                    "data": {"type": "object"},
                    "summary": {"type": "object"},
                    "meta": {"type": "object"},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                    "coverage": {"type": "object"},
                    "accounts": {"type": "array", "items": {"type": "object"}},
                    "html": {"type": "string"},
                    "files": {
                        "type": "object",
                        "properties": {
                            "html_path": {"type": ["string", "null"]},
                            "json_path": {"type": ["string", "null"]},
                        },
                    },
                },
            },
        },
    }


def _search_serp_schema() -> dict[str, Any]:
    result_item = {
        "type": "object",
        "required": ["domain", "title", "position"],
        "properties": {
            "domain": {"type": "string"},
            "title": {"type": "string"},
            "snippet": {"type": "string"},
            "url": {"type": "string"},
            "click_url": {"type": "string"},
            "type": {"type": "string", "enum": ["text", "product_gallery", "native"]},
            "block": {"type": "string", "enum": ["top", "bottom"]},
            "position": {"type": "integer"},
        },
    }
    return {
        "type": "object",
        "required": [
            "query",
            "region",
            "device",
            "ads",
            "ads_count_top",
            "ads_count_bottom",
            "organic",
            "captcha",
        ],
        "properties": {
            "query": {"type": "string"},
            "region": {"type": "integer"},
            "device": {"type": "string"},
            "format": {"type": "string"},
            "mode": {"type": "string"},
            "n_results": {"type": "integer"},
            "page": {"type": "integer"},
            "search_type": {"type": "string"},
            "ads": {"type": "array", "items": result_item},
            "ads_count_top": {"type": "integer"},
            "ads_count_bottom": {"type": "integer"},
            "organic": {"type": "array", "items": result_item},
            "captcha": {"type": "boolean"},
            "request_id": {"type": "string"},
            "found_docs_human": {"type": "string"},
            "raw_html": {"type": "string"},
            "raw_xml": {"type": "string"},
        },
    }


def _default_read_annotations() -> ToolAnnotations:
    return ToolAnnotations(readOnlyHint=True, idempotentHint=True)


def _artifact_write_annotations() -> ToolAnnotations:
    return ToolAnnotations(readOnlyHint=False, idempotentHint=True)


def prioritized_contract_tools() -> set[str]:
    return set(tool_contracts().keys())


def tool_contracts() -> dict[str, dict[str, Any]]:
    entity_list_schemas = {
        "direct.hf.find_campaigns": {"type": "object", "required": ["campaigns"], "properties": {"campaigns": {"type": "array", "items": {"type": "object"}}}},
        "direct.hf.find_adgroups": {"type": "object", "required": ["adgroups"], "properties": {"adgroups": {"type": "array", "items": {"type": "object"}}}},
        "direct.hf.find_ads": {"type": "object", "required": ["ads"], "properties": {"ads": {"type": "array", "items": {"type": "object"}}}},
        "direct.hf.find_keywords": {"type": "object", "required": ["keywords"], "properties": {"keywords": {"type": "array", "items": {"type": "object"}}}},
    }

    contracts: dict[str, dict[str, Any]] = {
        "accounts.list": {
            "outputSchema": _accounts_list_schema(),
            "annotations": _default_read_annotations(),
        },
        "dashboard.generate_option1": {
            "outputSchema": _dashboard_schema(),
            "annotations": _artifact_write_annotations(),
        },
        "search_serp": {
            "outputSchema": _search_serp_schema(),
            "annotations": _default_read_annotations(),
        },
        "direct.hf.get_campaign_summary": {
            "outputSchema": _hf_envelope_schema(result_schema=_campaign_counts_schema()),
            "annotations": _default_read_annotations(),
        },
        "direct.hf.get_bids_summary": {
            "outputSchema": _hf_envelope_schema(result_schema=_bids_summary_schema()),
            "annotations": _default_read_annotations(),
        },
        "direct.hf.pressure_report": {
            "outputSchema": _hf_envelope_schema(
                result_schema={
                    "type": "object",
                    "required": ["date_from", "date_to", "grain", "placement", "by_cluster", "coverage_notes", "raw_refs"],
                    "properties": {
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"},
                        "grain": {"type": "string"},
                        "placement": {"type": "string"},
                        "by_cluster": {"type": "array", "items": {"type": "object"}},
                        "by_cluster_region_device": {"type": ["array", "null"], "items": {"type": "object"}},
                        "coverage_notes": {"type": "object"},
                        "raw_refs": {"type": "array", "items": {"type": "object"}},
                    },
                }
            ),
            "annotations": _default_read_annotations(),
        },
        "direct.hf.report_performance": {
            "outputSchema": _hf_envelope_schema(result_schema=_direct_report_result_schema()),
            "annotations": _default_read_annotations(),
        },
        "direct.hf.report_keywords": {
            "outputSchema": _hf_envelope_schema(result_schema=_direct_report_result_schema()),
            "annotations": _default_read_annotations(),
        },
        "direct.hf.report_ads": {
            "outputSchema": _hf_envelope_schema(result_schema=_direct_report_result_schema()),
            "annotations": _default_read_annotations(),
        },
        "direct.hf.report_adgroups": {
            "outputSchema": _hf_envelope_schema(result_schema=_direct_report_result_schema()),
            "annotations": _default_read_annotations(),
        },
        "direct.hf.report_search_phrases": {
            "outputSchema": _hf_envelope_schema(result_schema=_direct_report_result_schema()),
            "annotations": _default_read_annotations(),
        },
        "metrica.hf.list_accessible_counters": {
            "outputSchema": _hf_envelope_schema(result_schema={"type": "object", "required": ["counters"], "properties": {"counters": {"type": "array", "items": {"type": "object"}}}}),
            "annotations": _default_read_annotations(),
        },
        "metrica.hf.counter_summary": {
            "outputSchema": _hf_envelope_schema(result_schema={"type": "object", "required": ["counter"], "properties": {"counter": {"type": "object"}, "goals": {"type": ["object", "array", "null"]}}}),
            "annotations": _default_read_annotations(),
        },
        "metrica.hf.report_time_series": {
            "outputSchema": _hf_envelope_schema(result_schema=_time_series_schema()),
            "annotations": _default_read_annotations(),
        },
        "metrica.hf.report_landing_pages": {
            "outputSchema": _hf_envelope_schema(result_schema=_metrica_report_schema()),
            "annotations": _default_read_annotations(),
        },
        "metrica.hf.report_utm_campaigns": {
            "outputSchema": _hf_envelope_schema(result_schema=_metrica_report_schema()),
            "annotations": _default_read_annotations(),
        },
        "metrica.hf.report_geo": {
            "outputSchema": _hf_envelope_schema(result_schema=_metrica_report_schema()),
            "annotations": _default_read_annotations(),
        },
        "metrica.hf.report_devices": {
            "outputSchema": _hf_envelope_schema(result_schema=_metrica_report_schema()),
            "annotations": _default_read_annotations(),
        },
        "join.hf.direct_vs_metrica_by_utm": {
            "outputSchema": _hf_envelope_schema(result_schema=_join_utm_schema()),
            "annotations": _default_read_annotations(),
        },
    }
    for tool_name, result_schema in entity_list_schemas.items():
        contracts[tool_name] = {
            "outputSchema": _hf_envelope_schema(result_schema=result_schema),
            "annotations": _default_read_annotations(),
        }
    return contracts


def decorate_tool(tool: Tool) -> Tool:
    contract = tool_contracts().get(tool.name)
    if contract is None:
        return tool

    annotations = contract.get("annotations")
    existing_annotations = tool.annotations
    if existing_annotations is not None and annotations is not None:
        annotations = existing_annotations.model_copy(
            update={k: v for k, v in annotations.model_dump(exclude_none=True).items() if getattr(existing_annotations, k, None) is None}
        )
    elif existing_annotations is not None:
        annotations = existing_annotations

    return tool.model_copy(
        update={
            "outputSchema": contract.get("outputSchema") or tool.outputSchema,
            "annotations": annotations,
        }
    )
