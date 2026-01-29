# Shortlist + оценка оберток (Direct/Metrica)

## Рекомендованный вариант (минимальные ресурсы, быстрый старт)

### 1) Python: pavelmaksimov/tapi-yandex-direct
- Статус: активная библиотека.
- Покрытие: 28 ресурсов (campaigns, adgroups, ads, keywords, reports и др.).
- Механика: единый клиент, передача метода `get/add/update/...` + словарь параметров.
- Зависимости: requests, orjson, tapi-wrapper2.
- Сложность обертки MCP: средняя.
  - Плюсы: единая форма запроса, легкая докеризация, минимум памяти.
  - Минусы: слабая типизация, нужно вручную контролировать структуру запросов и валидацию.

### 1b) Python: pavelmaksimov/tapi-yandex-metrika (read-only)
- Для метрик: визиты/время на сайте/landing pages.
- Типично read-only по природе Metrica.
- Плюсы: единый автор/стиль с Direct‑библиотекой, проще интеграция в MCP.

## Альтернатива (PHP, более “классический” SDK)

### 2) PHP: gladyshev/yandex-direct-client
- Покрытие: 27 сервисов, включая Campaigns/AdGroups/Ads/Keywords/Reports.
- Зависимости: относительно легкие (psr/http-client, guzzlehttp/psr7).
- Сложность обертки MCP: средняя-низкая.
  - Плюсы: меньше зависимостей, простая структура сервисов.
  - Минусы: PHP‑стек тяжелее в Docker на M1, чем Python‑slim.

### Почему не biplane/yandex-direct как основной
- Библиотека сильная и полная, но тяжелее по зависимостям (SOAP + symfony), выше оверхед в Docker.

---

## Сравнение покрытия Direct (методы/сервисы)

### biplane/yandex-direct (PHP)
- Сервисы: 27
- Есть add/update: Campaigns/AdGroups/Ads/Keywords (проверено в V5 класcах)
- Reports: есть
- Сложность: выше среднего (SOAP + symfony stack)

### sitkoru/yandex-direct-api (PHP)
- Сервисы: 19
- Есть add/update: Campaigns/AdGroups/Ads/Keywords
- Reports: есть
- Сложность: средняя (guzzle + validator + mapper)

### gladyshev/yandex-direct-client (PHP)
- Сервисы: 27
- Есть add/update: Campaigns/AdGroups/Ads/Keywords
- Reports: есть
- Сложность: средняя-низкая

### perf2k2/direct (PHP)
- Сервисы: 24
- Есть add/update: Campaigns/AdGroups/Ads/Keywords (README + tests)
- Reports: есть
- Риск: старый PHP (7.*), устаревшие зависимости

### pavelmaksimov/tapi-yandex-direct (Python)
- Ресурсы: 28
- add/update доступен через универсальный метод
- Reports: есть
- Сложность: средняя (динамическая обертка)

---

## Ранее найденные read-only библиотеки (полезны для справки/быстрого старта)

### Yandex Metrica (read-only, аналитика)
- pavelmaksimov/tapi-yandex-metrika (Python, самый живой)
- pikhovkin/yametrikapy (Python)
- AlariCode/yandex-metrika-api (TypeScript)
- tamert/python_yandex_metrica_api (Python, минималистично)
- ustsl/yandex-metrica-api (Python, скрипт)

### Yandex Direct (read-only/минимальные обертки)
- LPgenerator/django-yandex-direct (Python, старее/узко)
- boshqa проекты из поиска без явного add/update в README — требуют ручной проверки
