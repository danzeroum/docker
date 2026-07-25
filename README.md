# docker-cockpit

Dashboard read-only de containers Docker, exposto via HTTPS com Basic Auth.

## Arquitetura

```
Internet → Nginx (80/443, TLS) → Basic Auth → FastAPI (GET only) → docker-socket-proxy (GET only) → /var/run/docker.sock (ro)
```

- **docker-socket-proxy** — filtra o socket, expõe só endpoints de leitura (GET)
- **app (FastAPI)** — serve o cockpit HTML + API `/api/*`
- **nginx** — termina TLS (Let's Encrypt), aplica Basic Auth, bloqueia métodos de escrita
- **certbot** — emissão/renovação de certificado (perfil `renew`)

## 3 passos para rodar na VPS

### 1. Configurar variáveis

```bash
cp .env.example .env
nano .env  # preencha DOMAIN, EMAIL, BASIC_AUTH_USER, BASIC_AUTH_PASS
```

### 2. Apontar DNS

Crie um registro A: `docker.danzeroum.com → <IP da VPS>`  
Aguarde a propagação antes de continuar.

### 3. Subir

```bash
chmod +x init.sh scripts/renew.sh
./init.sh
```

O script `init.sh`:
1. Gera `nginx/.htpasswd` automaticamente
2. Emite o certificado TLS via Certbot (webroot)
3. Sobe a stack completa com `docker compose up -d`

### Renovação automática

Adicione ao cron da VPS:

```cron
0 3 * * * /caminho/absoluto/scripts/renew.sh >> /var/log/certbot-renew.log 2>&1
```

### Testar

```bash
curl -u admin:sua_senha https://docker.danzeroum.com/health
curl -u admin:sua_senha https://docker.danzeroum.com/api/containers
```

## Adaptando o Cockpit HTML

1. Copie o conteúdo de `cockerPitZAI.html` para `app/static/index.html`
2. Substitua `fetch('inspect.json')` por `fetch('/api/containers')`  
   e `fetch(...)` de inspect individual por `fetch('/api/containers/${id}')`
3. Rebuild: `docker compose build app && docker compose up -d app`

## Estrutura

```
.
├── .env.example
├── docker-compose.yml
├── init.sh
├── scripts/
│   └── renew.sh
├── nginx/
│   └── nginx.conf
├── certbot/
│   ├── conf/   ← montado como bind mount (certificados)
│   └── www/    ← montado como bind mount (challenge ACME)
└── app/
    ├── Dockerfile
    ├── requirements.txt
    ├── app.py
    └── static/
        └── index.html  ← cockpit HTML aqui
```
