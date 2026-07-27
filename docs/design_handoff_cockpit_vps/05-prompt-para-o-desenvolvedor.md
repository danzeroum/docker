# 05 · Prompt para o desenvolvedor

Cole o texto abaixo no Claude Code (ou entregue ao desenvolvedor), com esta pasta disponível
no repositório e o `nginx.conf` real acessível.

---

```
Você vai implementar o redesenho do Docker Cockpit no repositório danzeroum/docker.

CONTEXTO
O painel hoje é um dashboard somente-leitura de containers: FastAPI em app/app.py falando com
tecnativa/docker-socket-proxy, e um frontend em HTML/CSS/JS puro em app/static/ (sem bundler).
Ele cobre containers. Precisa passar a cobrir a VPS inteira: 15 containers, 12 stacks e 13
domínios servidos por um único gateway nginx (/opt/btv/ingress).

MATERIAL
Na pasta design_handoff_cockpit_vps/:
- README.md ................. visão geral, as 11 telas, os 27 design tokens, tipografia
- 01-contrato-de-dados.md ... campo por campo da UI e a origem real de cada um  ← comece aqui
- 02-backend.md ............. endpoints e módulos novos, com esquemas JSON
- 03-frontend.md ............ arquitetura, estado, camada de dados, temas, acessibilidade
- 04-plano-de-entrega.md .... 6 fases com critério de aceite
- Cockpit Docker.dc.html .... o protótipo navegável

O .dc.html é REFERÊNCIA DE DESIGN, não código para copiar. Todos os dados dentro dele são
simulados. Abra no navegador e navegue: 5 perfis, 3 temas, 3 cenários, 11 telas.

REGRAS INEGOCIÁVEIS

1. Sem framework novo. Mantenha HTML/CSS/JS puro servido por app/static/. Sem React, sem
   build step.

2. Zero dado fixo no frontend. Nenhum nome de container, domínio, métrica ou texto de
   diagnóstico escrito à mão. A seção "Símbolos a eliminar" do 01-contrato-de-dados.md lista
   cada variável do protótipo e a chamada que a substitui. Critério: grep no JS final não
   pode achar "criptotrade", "giva", "buildtovalue" nem número de métrica.

3. A camada Dado → Informação → Conhecimento é o produto. Cada achado devolve
   {evidence, interpretation, recommendation} (mais as variantes _plain para leigos) e o
   frontend só escolhe qual campo mostrar conforme a profundidade ativa. Se você escrever
   essas frases no JS, o produto perde a razão de existir. Motor no backend:
   services/findings.py, uma função pura por regra, testável.

4. Fidelidade visual alta. Cores, tipos e espaçamentos do protótipo são finais. Copie o bloco
   [data-tema] do <style> para app/static/css/themes.css — são 3 temas × 27 tokens. Cores de
   estado (#22c55e, #f59e0b, #ef4444, #64748b) NÃO entram no tema, de propósito.

5. Desempenho: /api/containers/{id}/stats leva ~1,2s por container. Nunca chame em série para
   os 15. Faça GET /api/overview com asyncio.gather e cache de 5s no servidor.

6. Segurança, antes de qualquer tela nova:
   - Config.Env hoje volta com segredos em texto claro para qualquer sessão. Mascare no
     servidor (chaves casando pass|secret|token|key|dsn|url|auth|credential e a parte de
     credencial de qualquer URI).
   - POST/DELETE do socket-proxy estão habilitados. Toda mutação passa a exigir
     X-Cockpit-Unlock (POST /api/session/unlock, TTL 30 min) e vai para tabela de auditoria.
   - Não ligue o terminal web.

7. Onde não houver fonte real, o campo sai da tela. Não invente latência por salto nem
   disponibilidade de 30 dias antes de ter 30 dias de coleta. Enquanto coleta, a UI diz desde
   quando está coletando.

8. Para ler o nginx.conf use crossplane (parser oficial da Nginx), alimentado com a saída de
   `nginx -T` do container btv-nginx-prod, com fallback para o arquivo montado :ro. Nada de
   regex. O parser dá arquivo, linha e trecho — use nas evidências dos achados.

ACHADOS QUE O SISTEMA PRECISA DETECTAR SOZINHO
(o protótipo já os mostra; use o nginx.conf atual como fixture de teste)
- executagent e familia-web: bloco :80 com proxy_pass em vez de return 301 (crítico)
- criptotrade: /docs e /openapi.json públicos, sem auth (alto)
- docker.danzeroum.com: proxy_read_timeout 60s e sem proxy_buffering off, o que corta o
  próprio SSE de logs e o WebSocket de stats do cockpit (alto)
- default_server 443 usando o certificado do prompte (alto)
- location ~* (...|env) sem escape em 10 blocos; só giva usa \.env (médio)
- Connection "upgrade" no nível http sem map $http_upgrade (médio)
- client_max_body_size só definido no giva; os outros 12 travam em 1 MB (médio)
- nenhum host com http2, nenhum com gzip (médio/baixo)
- /opt/portfolio e /opt/btv/educacional montados no gateway sem nenhum server block que os
  sirva (baixo)
- healthcheck do gateway só passa por causa do bloco server_name ... localhost (baixo)
Mais as regras de container: OOMKilled, restart loop, unhealthy, sem healthcheck, sem limite
de memória, log json-file sem rotação, exit ≠ 0, pressão de disco/memória, projeção de disco,
certificado vencendo, ausência de serviço de backup.

COMO TRABALHAR
Siga as fases de 04-plano-de-entrega.md, na ordem. Não pule para as telas bonitas antes da
F0/F1 — elas dependem de /api/overview e da limpeza de segurança. Ao terminar cada fase,
rode a suíte (pytest tests/ -v) e valide o critério de aceite escrito na fase. Abra PR por
fase, não um PR só.

COMECE POR
1. Ler 01-contrato-de-dados.md inteiro.
2. Abrir o .dc.html no navegador e navegar as 11 telas nos 3 cenários.
3. Rodar `docker exec btv-nginx-prod nginx -T` e conferir se o parse cobre os 13 hosts.
4. Propor o diff da F0 antes de escrever a F1.

Se algum item do contrato de dados não tiver fonte real possível no ambiente, diga qual e
proponha remover o campo — não preencha com estimativa.
```

---

## Como usar em outro assistente

O prompt acima é autossuficiente desde que os cinco `.md` e o `.dc.html` estejam junto. Se o
desenvolvedor for humano e não usar IA, a ordem de leitura é: `README.md` →
`01-contrato-de-dados.md` → `04-plano-de-entrega.md`, consultando `02` e `03` durante a
implementação.
