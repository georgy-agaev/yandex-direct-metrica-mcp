# Yandex Search API Web Search note - 2026-06-18

Short operator note for testing and integrating Yandex Web Search through
Yandex Search API.

## Credentials

Use the same Yandex Search API credential family as Wordstat:

- `YANDEX_SEARCH_API_FOLDER_ID`
- `YANDEX_SEARCH_API_API_KEY` or `YANDEX_SEARCH_API_IAM_TOKEN`

The service account needs `search-api.webSearch.user`; API keys must include the
`yc.search-api.execute` scope.

## Async request flow

Web Search uses an asynchronous operation:

1. `POST https://searchapi.api.cloud.yandex.net/v2/web/searchAsync`
2. Save the returned operation `id`.
3. Poll `GET https://operation.api.cloud.yandex.net/operations/<operation-id>`.
4. When `done=true`, decode `response.rawData` from Base64.
5. Parse the decoded XML or HTML response.

Minimal XML request:

```bash
curl -sS -X POST \
  -H "Authorization: Api-Key $YANDEX_SEARCH_API_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "folderId": "'"$YANDEX_SEARCH_API_FOLDER_ID"'",
    "query": {
      "searchType": "SEARCH_TYPE_RU",
      "queryText": "профессиональные гарнитуры для контакт-центра",
      "page": "0"
    },
    "groupSpec": {
      "groupsOnPage": "10",
      "docsInGroup": "1"
    },
    "maxPassages": "1",
    "responseFormat": "FORMAT_XML"
  }' \
  "https://searchapi.api.cloud.yandex.net/v2/web/searchAsync"
```

Expected initial response:

```json
{
  "done": false,
  "id": "spr...",
  "description": "WEB search async"
}
```

Poll and decode on macOS:

```bash
curl -sS -X GET \
  -H "Authorization: Api-Key $YANDEX_SEARCH_API_API_KEY" \
  "https://operation.api.cloud.yandex.net/operations/<operation-id>" \
  | jq -r '.response.rawData' \
  | base64 -D > result.xml
```

## Request fields that matter

- `query.searchType`: `SEARCH_TYPE_RU`, `SEARCH_TYPE_COM`, etc.
- `query.queryText`: search phrase.
- `query.page`: zero-based result page number.
- `groupSpec.groupsOnPage`: number of result groups on the page.
- `groupSpec.docsInGroup`: documents per group.
- `maxPassages`: snippet passages per document.
- `responseFormat`: `FORMAT_XML` or `FORMAT_HTML`.

Do not use `"page": { "size": 10 }`; this is not part of the Web Search API
request contract. Page size is controlled by `groupSpec.groupsOnPage`.

## Useful XML fields

For downstream parsing, extract:

- `//group/doc/url`
- `//group/doc/domain`
- `//group/doc/title`
- `//group/doc/passages/passage`
- `//found-docs-human`
- `//reqid` for support/debug correlation

## MCP tool: `search_serp`

`search_serp` is the bounded MCP surface for Web Search SERP use cases. It uses
the synchronous REST endpoint (`/v2/web/search`), decodes `rawData`, and returns
normalized result buckets so agents do not parse raw SERP HTML in prompt space.

Request:

```json
{
  "query": "гарнитура для колл центра купить",
  "region": 213,
  "device": "desktop",
  "format": "html",
  "mode": "sync",
  "n_results": 10
}
```

Response shape:

```json
{
  "query": "гарнитура для колл центра купить",
  "region": 213,
  "device": "DEVICE_DESKTOP",
  "format": "html",
  "mode": "sync",
  "n_results": 10,
  "page": 0,
  "search_type": "SEARCH_TYPE_RU",
  "ads": [
    {
      "domain": "example.ru",
      "title": "Ad title",
      "snippet": "Ad snippet",
      "url": "https://example.ru",
      "click_url": "https://yabs.yandex.ru/count/...",
      "type": "text",
      "block": "top",
      "position": 1
    }
  ],
  "ads_count_top": 1,
  "ads_count_bottom": 0,
  "organic": [
    {"domain": "example.org", "title": "Organic title", "snippet": "Organic snippet", "url": "https://example.org", "position": 1}
  ],
  "captcha": false
}
```

Notes:

- `format=html` is the default and is required for ad extraction.
- For ads, `domain` is the normalized advertiser domain. `click_url` contains
  the Yandex redirect URL when the parser retains one.
- Use `ads[].type` to filter normal text ads from `product_gallery` and `native`
  blocks. `ads_count_top` and `ads_count_bottom` count only `type=text`.
- Use `ads[].block` for top/bottom slot analysis when placement is inferred.
- `format=xml` is useful for organic result debugging, but ad extraction is not
  expected from XML.
- `device` is implemented via the documented `userAgent` request field; the
  response returns the normalized device enum.
- `region` defaults to `YANDEX_SEARCH_API_DEFAULT_REGION` (`213` by default).
- `search_type` defaults to `SEARCH_TYPE_RU`.
- raw HTML/XML is omitted unless `include_raw=true`.
