"""Verificação de imagem desatualizada via Docker Hub (B6).

Compara o **digest** local com o digest da mesma tag no Hub. Por digest e nunca
por nome de tag: `nginx:1.25` local e `nginx:1.25` remoto têm o mesmo nome
sempre, inclusive depois de a tag ser republicada — que é justamente o caso que
esta verificação existe para pegar. `latest` então é o exemplo extremo: o nome
nunca muda e o conteúdo muda toda semana.

Três estados, e nenhum deles é erro:

- `atualizada` — os digests batem;
- `desatualizada` — divergem, e há data da tag remota para o operador julgar;
- `desconhecido` — registry privado, imagem construída localmente, ou o Hub não
  respondeu. Não é falha do cockpit e não vira alarme.

`pendente` é o quarto, e existe só para o 429: uma VPS com 20 imagens estoura o
rate limit anônimo do Hub com facilidade, e a resposta certa é tentar de novo
amanhã — não marcar tudo como desconhecido e perder o resultado bom que já
estava no banco.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import httpx

HUB = os.getenv("DOCKER_HUB_API", "https://hub.docker.com/v2")

# Uma vez por dia. O Hub não muda de minuto a minuto e o rate limit anônimo é
# apertado; verificar de hora em hora só gastaria a cota.
INTERVALO_S = float(os.getenv("UPDATES_INTERVAL", str(24 * 3600)) or 24 * 3600)

# Idade a partir da qual vale reconsultar uma imagem. Mais curto que o intervalo
# do job de propósito: um restart do cockpit não deve refazer as 20 consultas.
CACHE_H = float(os.getenv("UPDATES_CACHE_HOURS", "24") or 24)

_SEM = asyncio.Semaphore(2)


def _agora():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_repo_tag(repo_tag: str):
    """`nginx:1.25` -> ('library', 'nginx', '1.25'). None se não for do Hub.

    Devolve None para qualquer coisa com registry próprio (`ghcr.io/x/y`,
    `registry.local:5000/z`) e para imagem sem tag utilizável. O sinal de
    registry é ponto ou dois-pontos na primeira parte do caminho — `localhost`
    também conta, porque não é o Hub.
    """
    if not repo_tag or repo_tag == "<none>:<none>":
        return None
    nome, _, tag = repo_tag.rpartition(":")
    if not nome or "/" in tag:
        return None
    if tag in ("", "<none>"):
        return None

    partes = nome.split("/")
    if len(partes) > 1 and ("." in partes[0] or ":" in partes[0] or partes[0] == "localhost"):
        # registry explícito e diferente do Hub
        return None
    if len(partes) == 1:
        return "library", partes[0], tag
    if len(partes) == 2:
        return partes[0], partes[1], tag
    return None


def digest_local(imagem: dict, repo_tag: str) -> str:
    """RepoDigest correspondente ao repo da tag.

    Uma imagem pode ter vários RepoDigests (mesma camada publicada em repos
    diferentes); pegar o primeiro compararia o digest de um repo com a tag de
    outro. Imagem construída localmente não tem RepoDigest nenhum — e é assim
    que ela se identifica.
    """
    alvo = parse_repo_tag(repo_tag)
    if not alvo:
        return ""
    ns, repo, _tag = alvo
    caminho = repo if ns == "library" else f"{ns}/{repo}"
    for d in imagem.get("RepoDigests") or []:
        if str(d).split("@")[0] in (caminho, f"docker.io/{caminho}"):
            return str(d).split("@", 1)[1] if "@" in str(d) else ""
    return ""


async def consulta_hub(ns: str, repo: str, tag: str) -> dict:
    """Consulta a tag no Hub. Nunca levanta: devolve status no dicionário."""
    url = f"{HUB}/repositories/{ns}/{repo}/tags/{tag}"
    try:
        async with _SEM:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                r = await client.get(url)
    except (httpx.HTTPError, OSError) as exc:
        return {"status": "desconhecido", "erro": f"rede: {type(exc).__name__}"}

    if r.status_code == 429:
        # Rate limit: `pendente` preserva o resultado anterior no banco em vez
        # de sobrescrevê-lo com "desconhecido". Amanhã tenta de novo.
        return {"status": "pendente", "erro": "429 do Hub — rate limit"}
    if r.status_code == 404:
        return {"status": "desconhecido", "erro": "tag nao encontrada no Hub"}
    if r.status_code >= 400:
        return {"status": "desconhecido", "erro": f"HTTP {r.status_code}"}

    try:
        corpo = r.json()
    except ValueError:
        return {"status": "desconhecido", "erro": "resposta ilegivel"}

    return {
        "status": "ok",
        "digest": str(corpo.get("digest") or ""),
        "remoto_em": str(corpo.get("last_updated") or ""),
    }


async def _uma(imagem: dict) -> dict | None:
    """Avalia uma imagem. None quando ela não é candidata (local, privada…)."""
    from db import get_image_update, upsert_image_update

    tags = imagem.get("RepoTags") or []
    repo_tag = next((t for t in tags if t and t != "<none>:<none>"), "")
    alvo = parse_repo_tag(repo_tag)
    if not alvo:
        # Construída localmente ou registry privado: fica FORA da listagem, não
        # entra como "desconhecido" — o operador não tem o que fazer com ela.
        return None
    ns, repo, tag = alvo

    anterior = await get_image_update(repo_tag)
    if anterior and anterior.get("consultado_em"):
        quando = anterior["consultado_em"]
        try:
            visto = datetime.fromisoformat(quando.replace("Z", "+00:00"))
            if _agora() - visto < timedelta(hours=CACHE_H):
                return anterior
        except (ValueError, TypeError):
            pass

    local = digest_local(imagem, repo_tag)
    resposta = await consulta_hub(ns, repo, tag)

    if resposta["status"] == "pendente":
        # Não sobrescreve o digest remoto conhecido; só anota a tentativa.
        await upsert_image_update(
            repo_tag, ns, repo, tag, local,
            digest_remoto=(anterior or {}).get("digest_remoto", ""),
            status="pendente",
            remoto_em=(anterior or {}).get("remoto_em", ""),
            erro=resposta["erro"],
        )
        return await get_image_update(repo_tag)

    if resposta["status"] != "ok":
        await upsert_image_update(
            repo_tag, ns, repo, tag, local,
            digest_remoto="", status="desconhecido", remoto_em="", erro=resposta["erro"],
        )
        return await get_image_update(repo_tag)

    remoto = resposta["digest"]
    if not local or not remoto:
        status = "desconhecido"
    elif local == remoto:
        status = "atualizada"
    else:
        status = "desatualizada"

    await upsert_image_update(
        repo_tag, ns, repo, tag, local,
        digest_remoto=remoto, status=status, remoto_em=resposta["remoto_em"], erro="",
    )
    return await get_image_update(repo_tag)


async def ciclo() -> dict:
    """Uma passada por todas as imagens em uso. Falha numa não para as outras."""
    from routers._proxy import proxy_get

    try:
        imagens = await proxy_get("/images/json")
    except Exception:
        return {"avaliadas": 0, "desatualizadas": 0}

    avaliadas = 0
    for img in imagens if isinstance(imagens, list) else []:
        if not isinstance(img, dict):
            continue
        try:
            if await _uma(img) is not None:
                avaliadas += 1
        except Exception:
            continue

    from db import contar_desatualizadas
    return {"avaliadas": avaliadas, "desatualizadas": await contar_desatualizadas()}


async def updates_loop(intervalo: float = None):
    espera = intervalo or INTERVALO_S
    while True:
        try:
            await ciclo()
            await asyncio.sleep(espera)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(espera)
