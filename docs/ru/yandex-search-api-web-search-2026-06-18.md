# Yandex Search API Web Search - заметка 2026-06-18

Короткая операторская заметка для тестирования и интеграции поисковой выдачи
Yandex Web Search через Yandex Search API.

## Доступ

Используется та же группа credentials, что и для Wordstat через Search API:

- `YANDEX_SEARCH_API_FOLDER_ID`
- `YANDEX_SEARCH_API_API_KEY` или `YANDEX_SEARCH_API_IAM_TOKEN`

У сервисного аккаунта должна быть роль `search-api.webSearch.user`; для
API-ключа нужна область `yc.search-api.execute`.

## Асинхронный сценарий

Web Search работает через асинхронную операцию:

1. `POST https://searchapi.api.cloud.yandex.net/v2/web/searchAsync`
2. Сохранить `id` операции из ответа.
3. Проверять `GET https://operation.api.cloud.yandex.net/operations/<operation-id>`.
4. Когда `done=true`, декодировать `response.rawData` из Base64.
5. Парсить XML или HTML.

Минимальный XML-запрос:

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

Ожидаемый первый ответ:

```json
{
  "done": false,
  "id": "spr...",
  "description": "WEB search async"
}
```

Проверка и декодирование на macOS:

```bash
curl -sS -X GET \
  -H "Authorization: Api-Key $YANDEX_SEARCH_API_API_KEY" \
  "https://operation.api.cloud.yandex.net/operations/<operation-id>" \
  | jq -r '.response.rawData' \
  | base64 -D > result.xml
```

## Важные поля запроса

- `query.searchType`: `SEARCH_TYPE_RU`, `SEARCH_TYPE_COM` и т.д.
- `query.queryText`: поисковая фраза.
- `query.page`: номер страницы, начиная с нуля.
- `groupSpec.groupsOnPage`: количество групп результатов на странице.
- `groupSpec.docsInGroup`: документов в группе.
- `maxPassages`: количество пассажей в сниппете.
- `responseFormat`: `FORMAT_XML` или `FORMAT_HTML`.

Не использовать `"page": { "size": 10 }`: такого поля нет в контракте Web
Search API. Размер страницы задается через `groupSpec.groupsOnPage`.

## Полезные XML-поля

Для дальнейшего парсинга нужны:

- `//group/doc/url`
- `//group/doc/domain`
- `//group/doc/title`
- `//group/doc/passages/passage`
- `//found-docs-human`
- `//reqid` для поддержки и отладки

## MCP tool: `search_serp`

`search_serp` - ограниченная MCP-поверхность для SERP-сценариев Web Search.
Инструмент использует синхронный REST endpoint (`/v2/web/search`), декодирует
`rawData` и возвращает нормализованные блоки, чтобы агенты не парсили сырой HTML
в prompt space.

Запрос:

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

Форма ответа:

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

Примечания:

- `format=html` используется по умолчанию и нужен для извлечения рекламы.
- Для рекламы `domain` - нормализованный домен рекламодателя. `click_url`
  содержит Yandex redirect URL, если parser его сохраняет.
- Используйте `ads[].type`, чтобы отделять обычные текстовые объявления от
  `product_gallery` и `native`. `ads_count_top` и `ads_count_bottom` считают
  только `type=text`.
- Используйте `ads[].block` для анализа верхнего и нижнего рекламного блока,
  когда placement удалось определить.
- `format=xml` полезен для отладки organic-результатов, но реклама из XML не
  ожидается.
- `device` реализован через документированное поле `userAgent`; ответ возвращает
  нормализованный enum устройства.
- `region` по умолчанию берется из `YANDEX_SEARCH_API_DEFAULT_REGION` (`213` по
  умолчанию).
- `search_type` по умолчанию равен `SEARCH_TYPE_RU`.
- сырой HTML/XML возвращается только при `include_raw=true`.
