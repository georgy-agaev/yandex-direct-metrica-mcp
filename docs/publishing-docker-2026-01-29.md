# Публикация (Option B): GitHub + Docker registry (GHCR / Docker Hub)

## 1) GitHub репозиторий
1) Создайте репозиторий (например: `yandex-direct-metrica-mcp`).
2) Залейте текущие файлы проекта в `main`.
3) Проверьте, что секреты **не** попадают в git:
   - `.env` и любые токены не должны быть закоммичены.

В проект добавлены:
- CI: `.github/workflows/ci.yml` (pytest)
- Docker publish: `.github/workflows/docker-publish.yml` (linux/amd64 + linux/arm64)

## 1.1) Landing page (GitHub Pages)

В репозитории есть простая посадочная страница:
- `docs/index.html`

Чтобы включить GitHub Pages:
1) Repo Settings → Pages
2) Source: `Deploy from a branch`
3) Branch: `main` / Folder: `/docs`

После этого лендинг будет доступен по URL GitHub Pages для репозитория.

## 2) GHCR (GitHub Container Registry)
Ничего дополнительно настраивать не нужно:
- workflow логинится в GHCR через `GITHUB_TOKEN`
- public образ пушится в `ghcr.io/<repo-owner>/yandex-direct-metrica-mcp:<tag>` (read-only, `MCP_PUBLIC_READONLY=true`)
- pro образ пушится в `ghcr.io/<repo-owner>/yandex-direct-metrica-mcp-pro:<tag>` (write tools доступны при `MCP_WRITE_ENABLED=true`)

Пояснение:
- `MCP_PUBLIC_READONLY=true` — скрывает write tools из списка инструментов и блокирует любые попытки записи на уровне сервера.

Рекомендуемый релиз-флоу:
- Для релиза: создать git tag `vX.Y.Z` и пушнуть его — workflow соберёт и запушит Docker image.

## 2.1) Ручная публикация в GHCR (buildx + multi-arch)

Если нужно запушить образ вручную (без GitHub Actions):

1) Логин в GHCR (нужен GitHub PAT с правами на packages):
```bash
export GHCR_OWNER="<OWNER>"   # user or org
export GHCR_TOKEN="<TOKEN>"   # GitHub PAT
echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_OWNER" --password-stdin
```

2) Подготовить buildx (один раз):
```bash
docker buildx create --use --name ydm-builder || docker buildx use ydm-builder
docker buildx inspect --bootstrap
```

3) Собрать и запушить **public** (read-only):
```bash
export VERSION="0.1.0"
docker buildx build --platform linux/amd64,linux/arm64 \
  --build-arg MCP_PUBLIC_READONLY=true \
  -t "ghcr.io/$GHCR_OWNER/yandex-direct-metrica-mcp:$VERSION" \
  -t "ghcr.io/$GHCR_OWNER/yandex-direct-metrica-mcp:latest" \
  --push .
```

4) Собрать и запушить **pro** (full):
```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  --build-arg MCP_PUBLIC_READONLY=false \
  -t "ghcr.io/$GHCR_OWNER/yandex-direct-metrica-mcp-pro:$VERSION" \
  -t "ghcr.io/$GHCR_OWNER/yandex-direct-metrica-mcp-pro:latest" \
  --push .
```

## 3) Docker Hub (опционально)
Если хотите пушить также в Docker Hub, добавьте secrets в GitHub repo и расширьте workflow:
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

Примечание: текущий workflow пушит только в GHCR (для надёжности релиза v0.1.x). Docker Hub можно добавить отдельным шагом/джобой позже.

## 4) Как подключить образ к Claude Code

Пример (stdio транспорт):
```bash
claude mcp add yandex-direct-metrica-mcp --transport stdio -s local -- \
  docker run --rm -i \
    --env-file /Users/georgyagaev/mcp/state/yandex.ad/.env \
    -e MCP_ACCOUNTS_FILE=/data/accounts.json \
    -e MCP_ACCOUNTS_WRITE_ENABLED=true \
    -v /Users/georgyagaev/mcp/state/yandex.ad:/data \
    ghcr.io/<OWNER>/yandex-direct-metrica-mcp:<TAG>
```

Pro (если нужен create/update, Direct write tools):
```bash
claude mcp add yandex-direct-metrica-mcp-pro --transport stdio -s local -- \
  docker run --rm -i \
    --env-file /Users/georgyagaev/mcp/state/yandex.ad/.env \
    -e MCP_ACCOUNTS_FILE=/data/accounts.json \
    -e MCP_ACCOUNTS_WRITE_ENABLED=true \
    -e MCP_WRITE_ENABLED=true \
    -v /Users/georgyagaev/mcp/state/yandex.ad:/data \
    ghcr.io/<OWNER>/yandex-direct-metrica-mcp-pro:<TAG>
```

Примечания:
- Для read-only режима можно добавить `:ro` к volume mount.
- Если используете multi-account dashboard, убедитесь что `MCP_ACCOUNTS_FILE` указывает на корректный `accounts.json` внутри контейнера.
