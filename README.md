# Docker Cockpit

Dashboard somente-leitura para monitoramento de containers Docker, servido via HTTPS com autenticacao basica.

## Arquitetura

```
Browser
  HTTPS (443)
bdv-nginx-prod  (global-ingress /opt/btv/ingress)
  proxy_pass -> docker-cockpit:8000  (btv-prod-net)
FastAPI (app:8000)
  httpx -> docker-cockpit-proxy:2375  (rede internal)
docker-socket-proxy
  /var/run/docker.sock:ro
Docker Daemon
```

## Pre-requisitos

- Servidor com `global-ingress` rodando (`btv-nginx-prod` nas portas 80/443)
- Rede Docker `btv-prod-net` existente
- DNS do dominio apontando para o IP do servidor

## Deploy

```bash
git clone https://github.com/danzeroum/docker /opt/btv/docker
cd /opt/btv/docker

# 1. Configurar variaveis de ambiente
cp .env.example .env
# editar .env se necessario

# 2. Descobrir o CIDR da rede do ingress e setar no .env
docker network inspect btv-prod-net --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'
# Exemplo de saida: 172.19.0.0/16
# Coloque no .env: TRUSTED_GATEWAY_CIDR=172.19.0.0/16
# Sem essa env o unlock retorna 403 (fail-closed).

# 3. Subir app + socket-proxy
docker compose up -d

# 3. Emitir certificado e registrar no global-ingress
# (rodar APOS DNS estar propagado)
bash scripts/setup-ingress.sh docker.danzeroum.com
```

## Desenvolvimento / CI

```bash
# Testes (sem Docker)
pip install -r tests/requirements-test.txt
pytest tests/ -v
```

CI verde em cada push na `main` via GitHub Actions (`.github/workflows/ci.yml`).

## Endpoints da API

| Endpoint | Descricao |
|---|---|
| `GET /health` | Health check |
| `GET /api/containers` | Lista todos os containers |
| `GET /api/containers/{id}` | Inspect completo |
| `GET /api/containers/{id}/logs` | Logs (tail=500) |
| `GET /api/containers/{id}/stats` | CPU/mem/rede snapshot |
| `GET /api/images` | Lista imagens |
| `GET /api/info` | Info do daemon Docker |
