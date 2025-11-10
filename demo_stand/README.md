# Demo Stand

Demo stand with GitLab, Nexus, and a webhook service.

## Launching services

docker-compose up -d

docker-compose down

## Services

- GitLab: http://localhost:80
- Nexus: http://localhost:8081
- Webhook App: http://localhost:8000

## Webhook App

Endpoint: POST http://localhost:8000/webhook/nexus

## Creating a project in GitLab

cd gitlab-script && uv run python project_setup_script.py

With environment variables:
GITLAB_TEMPLATE_ID, PROJECT_NAME

## Environment variables
Create .env file:
```
GITLAB_ACCESS_TOKEN=
GITLAB_BASE_URL=http://gitlab
GITLAB_TEMPLATE_ID=
PROJECT_NAME=
NEXUS_USERNAME=
NEXUS_PASSWORD= 
```
