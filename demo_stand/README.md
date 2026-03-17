# Demo Stand

Тестовый стенд с GitLab, Nexus и вебхук-сервисом для автоматического управления зависимостями Python-модулей.

## Запуск сервисов

```bash
docker compose up -d
docker compose down
```

## Сервисы

- GitLab: http://localhost:8080 
- Nexus: http://localhost:8081 
- Webhook App: http://localhost:8000

## Настройка окружения

После запуска контейнеров выполните:

```bash
python setup_dev_env.py
```

Скрипт:
- Получает пароли из контейнеров GitLab и Nexus
- Создаёт Personal Access Token в GitLab
- Регистрирует GitLab Runner
- Создает nexus репозиторий и настраивает в нем webhooks
- Импортирует шаблонный проект из папки test_stand
- Устанавливает переменные CI/CD в шаблонный проект 
- Создаёт файл .env со всеми необходимыми переменными


## Создание модулей

```bash
cd gitlab-scripts
## Создание модулей:

```bash
cd gitlab-scripts
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m src.project_setup_script
```

Для конфигурации иерархии модулей используется файл `gitlab-scripts/config.yaml`:

```yaml
template_id: 1  # ID шаблонного проекта
modules:
  - name: module-a
    dependencies: []
  - name: module-b
    dependencies: ["module-a"]
  - name: module-c
    dependencies: ["module-a", "module-b"]
```

## Переменные окружения

Файл `.env` создаётся автоматически скриптом `setup_dev_env.py`:

```
GITLAB_ACCESS_TOKEN=<token>
GITLAB_BASE_URL=http://gitlab
GITLAB_ROOT_PASSWORD=<password>
NEXUS_URL=http://nexus:8081
NEXUS_USERNAME=admin
NEXUS_PASSWORD=<password>
```



