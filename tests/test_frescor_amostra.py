"""A idade dos numeros aparece na tela, e o intervalo configurado para de mentir.

MEDIDO NA BANCADA, com carga e sem:

    containers rodando   ciclo real   atraso mediano   atraso maximo
            42              24 s          17,2 s          37,3 s
            11              16 s           9,5 s          20,4 s
      configurado           10 s

E o atraso NAO cresce com a carga: 16,5s com 2 operadores simultaneos, 20,7s com
50, zero erros em ambos. A lentidao nao vem de disputa — vem da conta:

    ciclo = n_containers x ~2,0s / SAMPLER_STATS_CONCURRENCY + SAMPLER_INTERVAL

Os ~2,0s sao inerentes: `/stats?stream=false` faz o daemon amostrar DUAS vezes
para calcular delta de CPU. Logo `SAMPLER_CONTAINER_INTERVAL` deixa de ser
respeitado por volta de oito containers.

Dois defeitos de HONESTIDADE saem disso, e sao o que este arquivo trava:

  1. a pilula dizia "ao vivo" enquanto o numero tinha 37s — e `stats_as_of` ja
     viajava na resposta, sem ninguem ler;
  2. `SAMPLER_CONTAINER_INTERVAL` e um botao que nao obedece, e nada avisava.

Nenhum dos dois e problema de desempenho. 50 operadores simultaneos rodaram com
p50 de 40ms e zero erro; a capacidade esta boa. O que estava errado era o painel
afirmar o que nao podia cumprir.
"""
import asyncio
import logging
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(RAIZ, "app", "static", "js")
sys.path.insert(0, os.path.join(RAIZ, "app"))
os.environ.setdefault("SOCKET_PROXY", "http://docker-socket-proxy:2375")


# ---------------------------------------------------------------------------
# o servidor mede e publica o ciclo
# ---------------------------------------------------------------------------

def test_o_ciclo_e_medido_e_nao_presumido():
    import sampler
    assert hasattr(sampler, "_ultimo_ciclo_s")
    fonte = open(os.path.join(RAIZ, "app", "sampler.py")).read()
    assert "time.monotonic()" in fonte and "_ultimo_ciclo_s = round(" in fonte, (
        "o ciclo voltou a ser presumido a partir da configuracao")


def test_acessor_devolve_o_medido_e_o_alvo(monkeypatch):
    """Os DOIS numeros, porque idade so vira 'atraso' contra o que o servidor de
    fato consegue entregar — e quem sabe isso e o servidor, nao o front."""
    import sampler
    monkeypatch.setenv("SAMPLER_CONTAINER_INTERVAL", "10")
    monkeypatch.setattr(sampler, "_ultimo_ciclo_s", 24.3)
    ciclo, alvo = sampler.get_ciclo_de_stats()
    assert ciclo == 24.3
    assert alvo == 10.0


def test_get_container_stats_manteve_a_aridade():
    """Cinco chamadores desempacotam dois valores. Enfiar um terceiro ali
    quebraria todos por uma informacao que so um deles usa."""
    import sampler
    assert len(sampler.get_container_stats()) == 2


def test_o_overview_publica_ciclo_e_alvo():
    fonte = open(os.path.join(RAIZ, "app", "routers", "overview.py")).read()
    assert '"stats_ciclo_s"' in fonte
    assert '"stats_intervalo_alvo_s"' in fonte
    assert "get_ciclo_de_stats" in fonte


# ---------------------------------------------------------------------------
# o descompasso grita — uma vez, nao a cada volta
# ---------------------------------------------------------------------------

def test_avisa_quando_o_intervalo_nao_cabe(monkeypatch, caplog):
    import sampler
    monkeypatch.setenv("SAMPLER_CONTAINER_INTERVAL", "10")
    monkeypatch.setattr(sampler, "_avisou_intervalo", False)
    with caplog.at_level(logging.WARNING):
        sampler._avisar_se_o_intervalo_nao_cabe(24.0, 42)
    assert any("NAO" in r.message or "nao esta sendo respeitado" in r.getMessage()
               for r in caplog.records), "o descompasso passou em silencio"
    assert "42" in caplog.text and "24" in caplog.text, (
        "o aviso precisa dizer QUANTOS containers e QUANTO levou")


def test_avisa_uma_vez_por_transicao(monkeypatch, caplog):
    """Um aviso a cada 20s vira ruido, e ruido no log e a forma mais eficiente
    de esconder um aviso."""
    import sampler
    monkeypatch.setenv("SAMPLER_CONTAINER_INTERVAL", "10")
    monkeypatch.setattr(sampler, "_avisou_intervalo", False)
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            sampler._avisar_se_o_intervalo_nao_cabe(24.0, 42)
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_nao_avisa_quando_cabe(monkeypatch, caplog):
    import sampler
    monkeypatch.setenv("SAMPLER_CONTAINER_INTERVAL", "10")
    monkeypatch.setattr(sampler, "_avisou_intervalo", False)
    with caplog.at_level(logging.WARNING):
        sampler._avisar_se_o_intervalo_nao_cabe(4.0, 5)
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


# ---------------------------------------------------------------------------
# a concorrencia virou botao de verdade
# ---------------------------------------------------------------------------

def test_a_concorrencia_e_configuravel():
    """O semaforo JA existia com 4 cravado — meu diagnostico inicial de 'leque
    ilimitado' estava errado, e a medicao me corrigiu. O que faltava era ele ser
    ajustavel: e ELE, e nao `SAMPLER_CONTAINER_INTERVAL`, que governa de fato a
    frequencia acima de um punhado de containers."""
    fonte = open(os.path.join(RAIZ, "app", "sampler.py")).read()
    assert "SAMPLER_STATS_CONCURRENCY" in fonte
    assert "asyncio.Semaphore(_CONCORRENCIA_STATS)" in fonte


def test_o_padrao_preserva_o_comportamento_anterior(monkeypatch):
    """Tornar configuravel nao pode mudar o que roda hoje em producao."""
    monkeypatch.delenv("SAMPLER_STATS_CONCURRENCY", raising=False)
    import importlib
    import sampler
    importlib.reload(sampler)
    assert sampler._CONCORRENCIA_STATS == 4


def test_concorrencia_nunca_e_zero(monkeypatch):
    """Zero travaria a coleta para sempre, em silencio."""
    monkeypatch.setenv("SAMPLER_STATS_CONCURRENCY", "0")
    import importlib
    import sampler
    importlib.reload(sampler)
    assert sampler._CONCORRENCIA_STATS >= 1
    monkeypatch.delenv("SAMPLER_STATS_CONCURRENCY", raising=False)
    importlib.reload(sampler)


# ---------------------------------------------------------------------------
# a pilula conta a idade
# ---------------------------------------------------------------------------

def test_a_regua_le_stats_as_of():
    """O dado ja viajava na resposta e o front nao o lia — o defeito inteiro."""
    regua = open(os.path.join(JS, "kernel", "regua.js")).read()
    assert "stats_as_of" in regua
    assert "export function informarIdadeDaAmostra" in regua


def test_o_limiar_vem_do_servidor_e_nao_do_front():
    """Cravar '10s' no JS repetiria o erro original: um numero que o servidor nao
    consegue cumprir, agora em dois lugares."""
    regua = open(os.path.join(JS, "kernel", "regua.js")).read()
    assert "stats_ciclo_s" in regua
    assert "stats_intervalo_alvo_s" in regua


def test_o_kernel_entrega_a_idade_junto_do_dado():
    """`stats_as_of` so vale contra o instante em que a resposta chegou; fora
    desse ponto a idade seria palpite."""
    app_js = open(os.path.join(JS, "kernel", "app.js")).read()
    assert "informarIdadeDaAmostra(_dados.overview)" in app_js
    i_busca = app_js.index("async function buscar")
    assert app_js.index("informarIdadeDaAmostra(_dados.overview)") > i_busca


def test_atraso_nao_usa_a_cor_de_aviso():
    """24s num host com 42 containers e o ritmo POSSIVEL, nao um incidente.
    Pintar de amarelo o normal ensina o operador a ignorar amarelo."""
    css = open(os.path.join(RAIZ, "app", "static", "css", "components.css")).read()
    i = css.index(".rg-vivo.rg-atrasado")
    regra = css[i:css.index("}", i)]
    assert "--warn" not in regra and "--bad" not in regra, (
        "o estado normal-porem-lento ganhou cor de alarme")


def test_atrasado_nao_e_pausado():
    """A leitura ACONTECE; o numero e que tem idade. Herdar `rg-pausado` mataria
    o pulso e diria que nada esta sendo lido, o que seria outra mentira."""
    regua = open(os.path.join(JS, "kernel", "regua.js")).read()
    assert "rg-atrasado" in regua
    css = open(os.path.join(RAIZ, "app", "static", "css", "components.css")).read()
    assert ".rg-vivo.rg-atrasado .rg-vivo-pulso" not in css


@pytest.mark.parametrize("idade,ciclo,esperado_atrasado", [
    (2, 10, False),     # dentro do ciclo
    (14, 10, False),    # 1.4x — folga de meio ciclo, o laco normal oscila
    (16, 10, True),     # 1.6x — passou
    (37, 24, True),     # o caso medido com 42 containers
    (20, 24, False),    # ciclo grande: 20s e normal se a coleta leva 24
])
def test_regra_do_limiar(idade, ciclo, esperado_atrasado):
    """A regra em Python, espelhando o JS: atrasado = idade > ciclo * 1.5.

    Sem a folga, a pilula piscaria 'atrasado' a cada volta normal do laco — e um
    indicador que pisca sem motivo e um indicador que ninguem olha.
    """
    assert (idade > ciclo * 1.5) is esperado_atrasado
    regua = open(os.path.join(JS, "kernel", "regua.js")).read()
    assert "ciclo * 1.5" in regua, "o JS deixou de usar a mesma regra"
