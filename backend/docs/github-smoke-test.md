# GitHub Smoke Test (Real Account)

Проверяет, что backend-методы реально работают на данных из вашего GitHub PR.

## Что делает
1. Проверяет `GITHUB_TOKEN` через `GET /user`.
2. Показывает несколько репозиториев аккаунта (`/user/repos`).
3. Читает PR и changed files из GitHub API.
4. Прогоняет локальный backend flow:
   - `POST /integrations/github/install`
   - `POST /repos/{repoId}/prs/{prNumber}/sync`
   - `POST /prs/{prId}/analysis-jobs`
   - `GET /analysis-jobs/{jobId}/results`
   - `POST /prs/{prId}/publish` (по умолчанию `dryRun=true`)

## Требования
- Запущенный backend на `http://localhost:4000`
- Python 3.10+
- Personal Access Token GitHub с доступом к нужному repo/PR

## Переменные окружения
Обязательные:
- `GITHUB_TOKEN`
- `GH_OWNER`
- `GH_REPO`
- `GH_PR_NUMBER`

Опциональные:
- `BACKEND_BASE_URL` (default: `http://localhost:4000`)
- `API_SERVICE_TOKEN` (если включили токен-аутентификацию в backend)
- `GITHUB_INSTALLATION_ID` (default: `999001`)
- `GITHUB_ACCOUNT_LOGIN` (default: `GH_OWNER`)
- `PUBLISH_DRY_RUN` (default: `true`)

## Запуск
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

В другом терминале:
```bash
cd backend
source .venv/bin/activate
GITHUB_TOKEN=ghp_xxx \
GH_OWNER=your-org \
GH_REPO=your-repo \
GH_PR_NUMBER=123 \
python scripts/github_smoke.py
```

## Безопасность
- Не передавайте токен в чат и не коммитьте его в репозиторий.
- Используйте только env-переменные локально.
