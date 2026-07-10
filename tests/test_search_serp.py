from __future__ import annotations

import base64
from types import SimpleNamespace

from mcp_yandex_ad import server
from mcp_yandex_ad.ratelimit import RateLimiter
from mcp_yandex_ad.search_client import (
    build_search_serp_payload,
    normalize_search_serp,
    parse_search_xml,
)


def test_build_search_serp_payload_maps_region_device_and_html_limit() -> None:
    payload, meta = build_search_serp_payload(
        {
            "query": "гарнитура для колл центра купить",
            "region": 213,
            "device": "desktop",
            "format": "html",
            "mode": "sync",
            "n_results": 10,
        },
        folder_id="folder-1",
        default_region=225,
    )

    assert payload["folderId"] == "folder-1"
    assert payload["query"]["searchType"] == "SEARCH_TYPE_RU"
    assert payload["query"]["queryText"] == "гарнитура для колл центра купить"
    assert payload["groupSpec"]["groupsOnPage"] == "10"
    assert payload["region"] == "213"
    assert payload["responseFormat"] == "FORMAT_HTML"
    assert "Macintosh" in payload["userAgent"]
    assert meta["device"] == "DEVICE_DESKTOP"
    assert meta["region"] == 213


def test_normalize_search_html_extracts_top_ads_and_organic() -> None:
    raw_html = """
    <html><body>
      <li class="serp-item serp-adv" data-cid="ad-1">
        <span>Реклама</span>
        <a href="https://ads.example.ru/page"><h2>Ad title</h2></a>
        <div>Ad snippet text</div>
      </li>
      <li class="serp-item" data-cid="org-1">
        <a class="OrganicTitle-Link" href="https://organic.example.ru/a"><h2>Organic title</h2></a>
        <div>Organic snippet text</div>
      </li>
    </body></html>
    """

    out = normalize_search_serp(raw_html, response_format="FORMAT_HTML")

    assert out["captcha"] is False
    assert out["ads_count_top"] == 1
    assert out["ads_count_bottom"] == 0
    assert out["ads"] == [
        {
            "domain": "ads.example.ru",
            "title": "Ad title",
            "url": "https://ads.example.ru/page",
            "snippet": "Реклама Ad title Ad snippet text",
            "type": "text",
            "block": "top",
            "position": 1,
        }
    ]
    assert out["organic"][0]["domain"] == "organic.example.ru"
    assert out["organic"][0]["title"] == "Organic title"
    assert out["organic"][0]["position"] == 1


def test_parse_search_xml_extracts_organic_results() -> None:
    raw_xml = """
    <yandexsearch>
      <request><reqid>req-1</reqid></request>
      <response>
        <found-docs-human>Нашлось 10 млн результатов</found-docs-human>
        <results><grouping><group><doc>
          <url>https://organic.example.ru/a</url>
          <domain>organic.example.ru</domain>
          <title>Organic XML title</title>
          <passages><passage>XML snippet</passage></passages>
        </doc></group></grouping></results>
      </response>
    </yandexsearch>
    """

    out = parse_search_xml(raw_xml)

    assert out["request_id"] == "req-1"
    assert out["found_docs_human"] == "Нашлось 10 млн результатов"
    assert out["organic"] == [
        {
            "domain": "organic.example.ru",
            "title": "Organic XML title",
            "url": "https://organic.example.ru/a",
            "snippet": "XML snippet",
            "position": 1,
        }
    ]
    assert out["ads"] == []
    assert out["ads_count_bottom"] == 0


def test_normalize_search_html_prefers_visible_ad_domain_over_redirect() -> None:
    raw_html = """
    <html><body>
      <li class="serp-item serp-adv" data-cid="ad-1">
        <span>Реклама</span>
        <a href="https://yabs.yandex.ru/count/abc?url=https%3A%2F%2Fwww.PULT.ru%2Fcatalog">
          <h2>Купить гарнитуру</h2>
        </a>
        <span>www.PULT.ru/catalog</span>
        <div>Профессиональные гарнитуры</div>
      </li>
    </body></html>
    """

    out = normalize_search_serp(raw_html, response_format="FORMAT_HTML")

    assert out["ads_count_top"] == 1
    assert out["ads"][0]["domain"] == "pult.ru"
    assert out["ads"][0]["url"] == "https://www.PULT.ru/catalog"
    assert out["ads"][0]["click_url"].startswith("https://yabs.yandex.ru/")
    assert out["ads"][0]["type"] == "text"
    assert out["ads"][0]["block"] == "top"


def test_normalize_search_html_ignores_date_like_visible_text_before_domain() -> None:
    raw_html = """
    <html><body>
      <li class="serp-item serp-adv" data-cid="ad-1">
        <span>Реклама</span>
        <a href="https://yabs.yandex.ru/count/abc?url=https%3A%2F%2Fwww.PULT.ru%2Fcatalog">
          <h2>Купить гарнитуру</h2>
        </a>
        <div>Акция до 01.02.2026</div>
        <span>www.PULT.ru/catalog</span>
      </li>
    </body></html>
    """

    out = normalize_search_serp(raw_html, response_format="FORMAT_HTML")

    assert out["ads"][0]["domain"] == "pult.ru"


def test_normalize_search_html_classifies_ad_types_and_blocks() -> None:
    raw_html = """
    <html><body>
      <li class="serp-item serp-adv" data-cid="ad-1">
        <span>Реклама</span>
        <a href="https://direct.example.ru"><h2>Top text ad</h2></a>
        <span>direct.example.ru</span>
      </li>
      <li class="serp-item" data-cid="org-1">
        <a href="https://organic.example.ru"><h2>Organic title</h2></a>
        <div>Organic snippet</div>
      </li>
      <section class="serp-item serp-adv product-gallery" data-cid="gallery-1">
        <h2>Популярные товары</h2>
        <a href="https://market.example.ru/product"><span>market.example.ru</span></a>
      </section>
      <div class="serp-item serp-adv" data-cid="native-1">
        <span>Может заинтересовать</span>
        <a href="https://an.yandex.ru/map?url=https%3A%2F%2Fnative.example.ru">
          <h2>Native recommendation</h2>
        </a>
        <span>native.example.ru</span>
      </div>
      <li class="serp-item serp-adv" data-cid="ad-2">
        <span>Реклама</span>
        <a href="https://bottom.example.ru"><h2>Bottom text ad</h2></a>
        <span>bottom.example.ru</span>
      </li>
    </body></html>
    """

    out = normalize_search_serp(raw_html, response_format="FORMAT_HTML")

    assert [ad["type"] for ad in out["ads"]] == ["text", "product_gallery", "native", "text"]
    assert [ad["block"] for ad in out["ads"]] == ["top", "bottom", "bottom", "bottom"]
    assert out["ads_count_top"] == 1
    assert out["ads_count_bottom"] == 1
    assert out["ads"][2]["domain"] == "native.example.ru"


def test_search_serp_server_helper_omits_raw_by_default(monkeypatch) -> None:
    raw_html = """
    <li class="serp-item serp-adv" data-cid="ad-1">
      <span>Реклама</span>
      <a href="https://top.example.ru"><h2>Top Ad</h2></a>
      <span>top.example.ru</span>
    </li>
    <li class="serp-item" data-cid="org-1">
      <a href="https://example.ru"><h2>Title</h2></a>
      <div>Snippet</div>
    </li>
    <li class="serp-item serp-adv" data-cid="ad-2">
      <span>Реклама</span>
      <a href="https://bottom.example.ru"><h2>Bottom Ad</h2></a>
      <span>bottom.example.ru</span>
    </li>
    """
    encoded = base64.b64encode(raw_html.encode("utf-8")).decode("ascii")
    captured: dict[str, object] = {}

    class FakeSearchApiClient:
        def __init__(self, **kwargs) -> None:
            captured["client_kwargs"] = kwargs

        def search(self, payload):
            captured["payload"] = payload
            return {"rawData": encoded}

    monkeypatch.setattr(server, "SearchApiClient", FakeSearchApiClient)
    ctx = SimpleNamespace(
        config=SimpleNamespace(
            search_api_enabled=True,
            wordstat_search_api_folder_id="folder-1",
            wordstat_search_api_api_key="key-1",
            wordstat_search_api_iam_token=None,
            search_api_default_region=213,
            search_api_web_base_url=None,
            retry_max_attempts=1,
            retry_base_delay_seconds=0,
            retry_max_delay_seconds=0,
        ),
        wordstat_rate_limiter=RateLimiter(0),
    )

    out = server._search_serp(ctx, {"query": "x", "n_results": 5})

    assert out["query"] == "x"
    assert out["region"] == 213
    assert out["device"] == "DEVICE_DESKTOP"
    assert out["ads_count_top"] == 1
    assert out["ads_count_bottom"] == 1
    assert out["organic"][0]["domain"] == "example.ru"
    assert "raw_html" not in out
    assert captured["payload"]["responseFormat"] == "FORMAT_HTML"
