"""Minimal Yandex Search API Web Search client and SERP normalizer."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree import ElementTree

import requests


SEARCH_API_WEB_BASE = "https://searchapi.api.cloud.yandex.net/v2/web/"

DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
PHONE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.6422.112 Mobile Safari/537.36"
)
TABLET_USER_AGENT = (
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


class SearchApiError(RuntimeError):
    def __init__(self, message: str, *, response: requests.Response | None = None) -> None:
        super().__init__(message)
        self.provider = "search_api"
        self.response = response


def normalize_search_device(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    aliases = {
        "": "DEVICE_DESKTOP",
        "DESKTOP": "DEVICE_DESKTOP",
        "DEVICE_DESKTOP": "DEVICE_DESKTOP",
        "PHONE": "DEVICE_PHONE",
        "MOBILE": "DEVICE_PHONE",
        "MOBILE_PHONE": "DEVICE_PHONE",
        "DEVICE_PHONE": "DEVICE_PHONE",
        "TABLET": "DEVICE_TABLET",
        "DEVICE_TABLET": "DEVICE_TABLET",
    }
    out = aliases.get(normalized)
    if out is None:
        raise ValueError("device must be desktop, phone/mobile, tablet, or DEVICE_*")
    return out


def user_agent_for_device(device: str) -> str:
    if device == "DEVICE_PHONE":
        return PHONE_USER_AGENT
    if device == "DEVICE_TABLET":
        return TABLET_USER_AGENT
    return DESKTOP_USER_AGENT


def normalize_search_format(value: Any) -> str:
    normalized = str(value or "html").strip().upper()
    aliases = {
        "HTML": "FORMAT_HTML",
        "FORMAT_HTML": "FORMAT_HTML",
        "XML": "FORMAT_XML",
        "FORMAT_XML": "FORMAT_XML",
    }
    out = aliases.get(normalized)
    if out is None:
        raise ValueError("format must be html, xml, FORMAT_HTML, or FORMAT_XML")
    return out


def build_search_serp_payload(
    args: dict[str, Any],
    *,
    folder_id: str,
    default_region: int | str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    if len(query) > 400:
        raise ValueError("query must be at most 400 characters")

    mode = str(args.get("mode") or "sync").strip().lower()
    if mode != "sync":
        raise ValueError("search_serp currently supports mode=sync only")

    response_format = normalize_search_format(args.get("format") or "html")
    n_results = int(args.get("n_results") or 10)
    min_results = 5 if response_format == "FORMAT_HTML" else 1
    max_results = 50 if response_format == "FORMAT_HTML" else 100
    if n_results < min_results or n_results > max_results:
        raise ValueError(
            f"n_results must be between {min_results} and {max_results} for {response_format}"
        )

    page = int(args.get("page") or 0)
    if page < 0:
        raise ValueError("page must be >= 0")

    device = normalize_search_device(args.get("device") or "desktop")
    region = args.get("region")
    if region is None or str(region).strip() == "":
        region = default_region if default_region is not None else 213
    try:
        region_int = int(region)
    except Exception as exc:
        raise ValueError("region must be an integer region id") from exc

    search_type = str(args.get("search_type") or "SEARCH_TYPE_RU").strip().upper()
    if not search_type.startswith("SEARCH_TYPE_"):
        search_type = f"SEARCH_TYPE_{search_type}"

    user_agent = str(args.get("user_agent") or "").strip() or user_agent_for_device(device)
    payload: dict[str, Any] = {
        "folderId": folder_id,
        "query": {
            "searchType": search_type,
            "queryText": query,
            "page": str(page),
        },
        "groupSpec": {
            "groupsOnPage": str(n_results),
        },
        "region": str(region_int),
        "responseFormat": response_format,
        "userAgent": user_agent,
    }
    if response_format == "FORMAT_XML":
        payload["groupSpec"]["docsInGroup"] = str(int(args.get("docs_in_group") or 1))
        payload["maxPassages"] = str(int(args.get("max_passages") or 2))

    meta = {
        "query": query,
        "region": region_int,
        "device": device,
        "format": "html" if response_format == "FORMAT_HTML" else "xml",
        "mode": mode,
        "n_results": n_results,
        "page": page,
        "search_type": search_type,
    }
    return payload, meta


@dataclass(frozen=True)
class SearchApiClient:
    folder_id: str
    api_key: str | None = None
    iam_token: str | None = None
    base_url: str = SEARCH_API_WEB_BASE
    timeout_seconds: int = 60

    def _headers(self) -> dict[str, str]:
        if not self.folder_id:
            raise SearchApiError("Yandex Search API folderId is not configured.")
        if not (self.api_key or self.iam_token):
            raise SearchApiError("Yandex Search API API key or IAM token is not configured.")
        auth_value = f"Api-Key {self.api_key}" if self.api_key else f"Bearer {self.iam_token}"
        return {
            "Authorization": auth_value,
            "Content-Type": "application/json;charset=utf-8",
        }

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + "/search"
        try:
            resp = requests.post(url, headers=self._headers(), json=payload, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise SearchApiError(str(exc)) from exc
        if resp.status_code < 200 or resp.status_code >= 300:
            raise SearchApiError(f"Search API error (HTTP {resp.status_code})", response=resp)
        try:
            data: Any = resp.json()
        except Exception as exc:
            raise SearchApiError("Failed to decode Search API JSON response", response=resp) from exc
        if not isinstance(data, dict):
            raise SearchApiError("Unexpected Search API response type", response=resp)
        return data


def decode_raw_data(data: dict[str, Any]) -> str:
    raw = data.get("rawData")
    if not isinstance(raw, str) or not raw.strip():
        raise SearchApiError("Search API response does not contain rawData")
    try:
        return base64.b64decode(raw).decode("utf-8", errors="replace")
    except Exception as exc:
        raise SearchApiError("Failed to decode Search API rawData") from exc


def _clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path.split("/", 1)[0]
    return host.lower().removeprefix("www.")


_VISIBLE_DOMAIN_RE = re.compile(
    r"(?<![\w.-])(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+)",
    re.IGNORECASE,
)


def _is_yandex_ad_host(domain: str) -> bool:
    return domain in {"yabs.yandex.ru", "an.yandex.ru", "yandex.ru"}


def _domain_from_visible_text(text: str) -> str:
    for match in _VISIBLE_DOMAIN_RE.finditer(text):
        domain = match.group(1).lower().removeprefix("www.")
        suffix = domain.rsplit(".", 1)[-1]
        if not suffix.isdigit() and not _is_yandex_ad_host(domain):
            return domain
    return ""


def _landing_url_from_redirect(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    for key in ("url", "u", "target", "href", "redir"):
        for value in params.get(key, []):
            decoded = unquote(value)
            if decoded.startswith(("http://", "https://")):
                return decoded
    return ""


def _is_captcha(raw: str) -> bool:
    lowered = raw.lower()
    return "showcaptcha" in lowered or "captcha" in lowered or "are you not a robot" in lowered


def parse_search_xml(raw_xml: str) -> dict[str, Any]:
    organic: list[dict[str, Any]] = []
    reqid = None
    found_docs_human = None
    try:
        root = ElementTree.fromstring(raw_xml)
    except ElementTree.ParseError:
        return {
            "organic": organic,
            "ads": [],
            "ads_count_top": 0,
            "ads_count_bottom": 0,
            "captcha": _is_captcha(raw_xml),
        }

    def text_at(node: ElementTree.Element, path: str) -> str:
        found = node.find(path)
        return _clean_text("".join(found.itertext())) if found is not None else ""

    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1]
        if tag == "reqid" and reqid is None:
            reqid = _clean_text("".join(elem.itertext()))
        elif tag == "found-docs-human" and found_docs_human is None:
            found_docs_human = _clean_text("".join(elem.itertext()))

    for group in [el for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "group"]:
        doc = next((el for el in group.iter() if el.tag.rsplit("}", 1)[-1] == "doc"), None)
        if doc is None:
            continue
        url = text_at(doc, ".//url")
        title = text_at(doc, ".//title")
        domain = text_at(doc, ".//domain") or _domain_from_url(url)
        passages = [
            _clean_text("".join(p.itertext()))
            for p in doc.iter()
            if p.tag.rsplit("}", 1)[-1] == "passage"
        ]
        organic.append(
            {
                "domain": domain,
                "title": title,
                "url": url,
                "snippet": " ".join(x for x in passages if x).strip(),
                "position": len(organic) + 1,
            }
        )

    out: dict[str, Any] = {
        "organic": organic,
        "ads": [],
        "ads_count_top": 0,
        "ads_count_bottom": 0,
        "captcha": False,
    }
    if reqid:
        out["request_id"] = reqid
    if found_docs_human:
        out["found_docs_human"] = found_docs_human
    return out


@dataclass
class _SerpBlock:
    attrs_text: str
    text_parts: list[str]
    links: list[tuple[str, str]]
    heading: str = ""

    @property
    def text(self) -> str:
        return _clean_text(" ".join(self.text_parts))

    @property
    def href(self) -> str:
        return self.links[0][0] if self.links else ""

    @property
    def title(self) -> str:
        if self.heading:
            return self.heading
        for _href, text in self.links:
            clean = _clean_text(text)
            if clean:
                return clean
        text = self.text
        return text[:120]

    def is_ad(self) -> bool:
        haystack = f"{self.attrs_text} {self.text}".lower()
        markers = (
            "реклама",
            "advert",
            "adv",
            "direct",
            "premium",
            "commercial",
            "serp-adv",
            "yabs",
        )
        return any(marker in haystack for marker in markers)

    def ad_type(self) -> str:
        haystack = f"{self.attrs_text} {self.text} {' '.join(h for h, _t in self.links)}".lower()
        if "an.yandex.ru" in haystack or "может заинтересовать" in haystack:
            return "native"
        product_markers = (
            "популярные товары",
            "товарная галерея",
            "product-gallery",
            "product_gallery",
            "products-gallery",
            "carousel",
        )
        if any(marker in haystack for marker in product_markers):
            return "product_gallery"
        return "text"


class _YandexHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_SerpBlock] = []
        self._stack: list[tuple[str, dict[str, str]]] = []
        self._current: _SerpBlock | None = None
        self._current_depth = 0
        self._link_href: str | None = None
        self._link_text: list[str] = []
        self._heading_depth = 0
        self._heading_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k: v or "" for k, v in attrs}
        attrs_text = " ".join([tag, *[f"{k}={v}" for k, v in attrs_dict.items()]])
        self._stack.append((tag, attrs_dict))
        if self._is_block_start(tag, attrs_dict) and self._current is None:
            self._current = _SerpBlock(attrs_text=attrs_text, text_parts=[], links=[])
            self._current_depth = len(self._stack)
        elif self._current is not None:
            self._current.attrs_text += f" {attrs_text}"
        if tag == "a" and self._current is not None:
            href = attrs_dict.get("href", "")
            if href and not href.startswith(("#", "javascript:")):
                self._link_href = href
                self._link_text = []
        if tag in {"h1", "h2", "h3", "h4"} and self._current is not None:
            self._heading_depth = len(self._stack)
            self._heading_text = []

    def handle_endtag(self, tag: str) -> None:
        if self._current is not None and self._link_href is not None and tag == "a":
            self._current.links.append((self._link_href, _clean_text(" ".join(self._link_text))))
            self._link_href = None
            self._link_text = []
        if self._current is not None and self._heading_depth and len(self._stack) == self._heading_depth:
            heading = _clean_text(" ".join(self._heading_text))
            if heading and not self._current.heading:
                self._current.heading = heading
            self._heading_depth = 0
            self._heading_text = []
        if self._current is not None and len(self._stack) == self._current_depth:
            if self._current.href or self._current.text:
                self.blocks.append(self._current)
            self._current = None
            self._current_depth = 0
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        clean = _clean_text(data)
        if not clean:
            return
        self._current.text_parts.append(clean)
        if self._link_href is not None:
            self._link_text.append(clean)
        if self._heading_depth:
            self._heading_text.append(clean)

    @staticmethod
    def _is_block_start(tag: str, attrs: dict[str, str]) -> bool:
        if tag not in {"li", "article", "div", "section"}:
            return False
        attr_text = " ".join(attrs.values()).lower()
        keys = " ".join(attrs.keys()).lower()
        return (
            "serp-item" in attr_text
            or "organic" in attr_text
            or "serp-adv" in attr_text
            or "search-result" in attr_text
            or "data-cid" in keys
        )


def parse_search_html(raw_html: str) -> dict[str, Any]:
    if _is_captcha(raw_html):
        return {"organic": [], "ads": [], "ads_count_top": 0, "ads_count_bottom": 0, "captcha": True}

    parser = _YandexHtmlParser()
    parser.feed(raw_html)

    ads: list[dict[str, Any]] = []
    organic: list[dict[str, Any]] = []
    sequence: list[str] = []
    seen: set[tuple[str, str]] = set()
    for block in parser.blocks:
        href = block.href
        title = block.title
        if not href or not title:
            continue
        landing_url = _landing_url_from_redirect(href)
        visible_domain = _domain_from_visible_text(block.text)
        domain = visible_domain or _domain_from_url(landing_url) or _domain_from_url(href)
        if not domain:
            continue
        key = (domain, title)
        if key in seen:
            continue
        seen.add(key)
        item = {
            "domain": domain,
            "title": title,
            "url": landing_url or href,
            "snippet": block.text,
        }
        if block.is_ad():
            ad_type = block.ad_type()
            item["type"] = ad_type
            if href != item["url"] or _is_yandex_ad_host(_domain_from_url(href)):
                item["click_url"] = href
            item["block"] = "bottom" if "organic" in sequence else "top"
            item["position"] = len(ads) + 1
            ads.append(item)
            sequence.append("ad")
        else:
            item["position"] = len(organic) + 1
            organic.append(item)
            sequence.append("organic")

    ads_count_top = 0
    ads_count_bottom = 0
    for ad in ads:
        if ad.get("type") != "text":
            continue
        if ad.get("block") == "top":
            ads_count_top += 1
        elif ad.get("block") == "bottom":
            ads_count_bottom += 1

    return {
        "organic": organic,
        "ads": ads,
        "ads_count_top": ads_count_top,
        "ads_count_bottom": ads_count_bottom,
        "captcha": False,
    }


def normalize_search_serp(raw: str, *, response_format: str) -> dict[str, Any]:
    if response_format == "FORMAT_XML":
        return parse_search_xml(raw)
    return parse_search_html(raw)
