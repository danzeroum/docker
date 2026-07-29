# app/config

`servicos.json` — mapa `domínio → nome de negócio`, consumido pelo Resumo executivo.

Não vem versionado de propósito: o conteúdo é específico da instalação e preenchê-lo é
trabalho de quem conhece o negócio. Copie o exemplo e edite:

```bash
cp app/config/servicos.example.json app/config/servicos.json
```

Sem o arquivo a tela **não quebra e não inventa nome** — ela avisa qual arquivo falta e
renderiza o resto. Domínio sem entrada aparece como "não mapeado".

Caminho configurável por `SERVICOS_CONFIG`.
