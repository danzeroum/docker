# ---------------------------------------------------------------------------
# Estágio de assets: empacota o JavaScript.
# ---------------------------------------------------------------------------
# O painel serve 49 módulos ES em cascata — cada `import` é uma ida ao servidor, e o
# navegador só descobre o próximo depois de baixar o anterior. Empacotado, 49
# requisições viram 1 e 384 KB viram 132 KB (40 KB com gzip).
#
# O REPOSITÓRIO continua sem build. `static/index.html` aponta para `main.js`, e rodar
# a app a partir do código-fonte funciona sem passar por aqui — útil para depurar, e é
# o que os testes de estrutura leem. É só a IMAGEM que recebe o bundle e tem o
# `<script src>` reescrito: quem lê o repositório lê módulos legíveis, quem roda em
# produção recebe um arquivo só.
#
# O `test -s` e o `grep` no fim são a trava: se o esbuild falhar em silêncio ou o
# caminho do `sed` mudar, a imagem NÃO é construída. Uma app servindo um <script> que
# aponta para arquivo inexistente sobe em branco, sem erro no servidor.
FROM node:22-alpine AS assets
WORKDIR /assets
COPY static/ ./static/
RUN npm install --no-save --no-fund --no-audit esbuild@0.28.1 \
 && ./node_modules/.bin/esbuild static/js/main.js \
      --bundle --format=esm --minify \
      --outfile=static/js/main.bundle.js \
 && sed -i 's|/static/js/main\.js|/static/js/main.bundle.js|' static/index.html \
 && test -s static/js/main.bundle.js \
 && grep -q 'main\.bundle\.js' static/index.html

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y docker-ce-cli docker-compose-plugin \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Os módulos continuam na imagem: o service worker os lista, e mantê-los deixa o
# bundle ser uma otimização de entrega, não uma amputação do que dá para inspecionar.
COPY --from=assets /assets/static/js/main.bundle.js ./static/js/main.bundle.js
COPY --from=assets /assets/static/index.html ./static/index.html

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
