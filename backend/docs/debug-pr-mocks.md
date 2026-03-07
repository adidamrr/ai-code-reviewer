# Export 3 PRs to Mock Files

Скрипт скачивает **ровно 3 PR** из GitHub и сохраняет их в JSON-файлы для debug/mocks.

## Где скрипт
- `backend/scripts/export_pr_mocks.py`

## Что генерируется
- `frontend/src/debug/mocks/*.json` — по одному файлу на PR
- `frontend/src/debug/mocks/manifest.json` — индекс с путями
- (опционально) `frontend/src/debug/presets.ts` — если передать `--write-presets`

## Форматы входа для `--pr`
- URL: `https://github.com/owner/repo/pull/123`
- Короткий: `owner/repo#123`

## Пример запуска
```bash
cd backend
source .venv/bin/activate

GITHUB_TOKEN=ghp_xxx \
python scripts/export_pr_mocks.py \
  --pr https://github.com/owner1/repo1/pull/10 \
  --pr owner2/repo2#25 \
  --pr owner3/repo3#44 \
  --write-presets
```

## Полезные флаги
- `--out-dir frontend/src/debug/mocks`
- `--scope security bugs style`
- `--max-comments 40`
- `--max-files 500`
- `--presets-path frontend/src/debug/presets.ts`

## Что дальше
- Для live debug-suite в UI нужен GitHub токен в `Connect`.
- Если используете `--write-presets`, кнопка `Запустить debug` начнет гонять именно эти 3 PR.
