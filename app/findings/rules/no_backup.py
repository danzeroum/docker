"""Nenhuma solucao de backup detectada na VPS.

O achado mais grave em aberto: 15 containers, 12 stacks, e nada que copie os
volumes para fora da maquina. Diferente das outras regras, esta nao observa algo
quebrado — observa uma AUSENCIA. Duas consequencias no desenho:

1. Ausencia de dado nao e evidencia de ausencia. Se `ctx.containers` vier vazio
   (socket-proxy reiniciando, por exemplo), a regra se cala. Afirmar "nao ha
   backup" porque nao conseguimos listar container nenhum seria inventar um
   critico a partir de uma falha de leitura.
2. Um container de backup PARADO nao dispara esta regra. A afirmacao aqui e
   "nao existe solucao configurada"; stack parada e outro problema, e ja tem
   dono (`upstream_missing`, `unhealthy`, a tela Projetos). Regra que reivindica
   mais do que observa manda o operador para o lugar errado com ar de certeza.
"""

SEVERITY = "high"
SCOPE = "host"
MIN_INTERVAL = 60
# Duas amostras antes de abrir: evita achado no meio de um restart do daemon.
DEBOUNCE = {"samples": 2}
# Exige trabalho humano (escolher destino, criar a stack, testar restauracao) e
# nao se conserta sozinho — cartao no board.
AUTO_TASK = True

ALVO = "vps"

# Imagens de ferramentas de backup conhecidas. Casamento por substring no nome da
# imagem, entao "offen/docker-volume-backup:v2" casa com "docker-volume-backup".
IMAGENS_DE_BACKUP = (
    "docker-volume-backup",
    "restic",
    "borgbackup",
    "borgmatic",
    "duplicati",
    "duplicity",
    "kopia",
    "pgbackrest",
    "barman",
    "wal-g",
    "velero",
    "bivac",
    "rclone",
)


def _texto_de_rotulos(container):
    rotulos = container.get("Config", {}).get("Labels") or {}
    if not isinstance(rotulos, dict):
        return ""
    partes = []
    for chave, valor in rotulos.items():
        partes.append(str(chave))
        partes.append(str(valor))
    return " ".join(partes).lower()


def _e_solucao_de_backup(container):
    """Um container conta como backup por imagem, rotulo ou nome."""
    imagem = (container.get("Config", {}).get("Image") or "").lower()
    for conhecida in IMAGENS_DE_BACKUP:
        if conhecida in imagem:
            return True

    rotulos = _texto_de_rotulos(container)
    if "backup" in rotulos:
        return True

    nome = (container.get("Name") or "").lstrip("/").lower()
    if "backup" in nome:
        return True

    return False


def evaluate(ctx):
    containers = [c for c in (ctx.containers or []) if isinstance(c, dict)]
    if not containers:
        # Sem leitura do daemon nao ha o que afirmar. Ver o docstring.
        return None

    encontrados = [
        (c.get("Name") or "").lstrip("/")
        for c in containers
        if _e_solucao_de_backup(c)
    ]
    if encontrados:
        return None

    total = len(containers)
    return {
        "target": ALVO,
        "title": f"Nenhuma solução de backup detectada ({total} containers)",
        "title_plain": "Os dados do servidor não estão sendo copiados",
        "interpretation": (
            f"Nenhum dos {total} containers usa imagem, rótulo ou nome de "
            "ferramenta de backup"
        ),
        "interpretation_plain": (
            "Se este servidor falhar agora, não existe cópia dos dados "
            "para restaurar"
        ),
        "recommendation": (
            "Subir uma stack de backup com destino FORA da VPS e agendar "
            "restauração de teste — cópia que nunca foi restaurada "
            "não e backup"
        ),
        "recommendation_plain": (
            "Contratar um destino de cópia externo e programar a cópia "
            "automática dos dados"
        ),
        "evidence": f"{total} containers inspecionados, 0 com sinal de backup",
        # Vai para "precisa de decisao" no Resumo executivo: escolher destino de
        # copia custa dinheiro, e isso nao e decisao de quem opera.
        "requires_approval": True,
        "impact": "Perda total e definitiva dos dados em falha de disco ou do provedor",
        "impact_plain": "Uma falha do servidor apaga tudo, sem volta",
        "facts": [
            {"key": "Containers", "value": str(total), "tone": "neutral"},
            {"key": "Com backup", "value": "0", "tone": "bad"},
        ],
        "actions": [
            {
                "title": "Listar os volumes que precisam de cópia",
                "detail": "Inventario antes de escolher a ferramenta",
                "command": "docker volume ls",
                "risk": "nenhum",
                "applies_via": "manual",
            },
            {
                "title": "Subir uma stack de backup de volumes",
                "detail": (
                    "offen/docker-volume-backup e o caminho mais curto para "
                    "volumes Docker; destino tem de ser fora desta VPS"
                ),
                "command": "docker compose -f /opt/btv/backup/docker-compose.yml up -d",
                "risk": "nenhum",
                "applies_via": "manual",
            },
            {
                "title": "Testar a restauração",
                "detail": "Restaurar um volume num diretorio temporario e conferir o conteudo",
                "command": "",
                "risk": "nenhum",
                "applies_via": "manual",
            },
        ],
    }
