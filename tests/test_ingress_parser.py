"""Testes do parser de configuracao nginx."""

import os
import sys

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


def _load(name):
    path = os.path.join(FIXTURES, name)
    with open(path) as f:
        return f.read()


def test_parser_vps_encontra_15_dominios():
    from ingress.parser import parse_nginx
    text = _load("nginx-vps.conf")
    cat = parse_nginx(text)
    names = set()
    for s in cat.servers:
        for n in s.server_name:
            if n != "_":
                names.add(n)
    assert len(names) == 15, f"Esperado 15 dominios, achou {len(names)}: {sorted(names)}"


def test_parser_vps_tem_14_ssl():
    from ingress.parser import parse_nginx
    text = _load("nginx-vps.conf")
    cat = parse_nginx(text)
    ssl_servers = [s for s in cat.servers if s.has_ssl]
    assert len(ssl_servers) == 14


def test_parser_vps_todos_ssl_tem_cert():
    from ingress.parser import parse_nginx
    text = _load("nginx-vps.conf")
    cat = parse_nginx(text)
    for s in cat.servers:
        if s.has_ssl:
            assert s.ssl_cert, f"SSL sem cert: {s.primary_name}"
            assert s.ssl_cert_key, f"SSL sem key: {s.primary_name}"


def test_parser_vps_resolve_set_upstream():
    from ingress.parser import parse_nginx
    text = _load("nginx-vps.conf")
    cat = parse_nginx(text)

    prompte_ssl = [s for s in cat.servers if "prompte.buildtovalue.cloud" in s.server_name and s.has_ssl]
    assert len(prompte_ssl) == 1
    root_loc = [l for l in prompte_ssl[0].locations if l.path == "/" and l.modifier in (None, "~*")]
    assert len(root_loc) >= 1
    resolved = root_loc[-1].proxy_pass_resolved if root_loc else None
    assert resolved == "http://prompte-frontend:80", f"Esperado http://prompte-frontend:80, obteve {resolved}"


def test_parser_vps_rewrite_break():
    from ingress.parser import parse_nginx
    text = _load("nginx-vps.conf")
    cat = parse_nginx(text)

    cripto_ssl = [s for s in cat.servers if "criptotrade.buildtovalue.cloud" in s.server_name and s.has_ssl]
    assert len(cripto_ssl) == 1
    api_loc = [l for l in cripto_ssl[0].locations if l.path == "/api/"]
    assert len(api_loc) == 1
    assert api_loc[0].rewrite is not None
    assert api_loc[0].proxy_pass_resolved == "http://criptotrade-app:8000"


def test_parser_vps_todas_upstreams_resolvidas():
    from ingress.parser import parse_nginx
    text = _load("nginx-vps.conf")
    cat = parse_nginx(text)
    upstreams = set()
    for s in cat.servers:
        for l in s.locations:
            if l.proxy_pass_resolved and l.proxy_pass_resolved.startswith("http"):
                target = l.proxy_pass_resolved.split("//")[1].split(":")[0]
                upstreams.add(target)
    conhecidos = {"prompte-frontend", "btvchatcorp-frontend-1", "central-inteligencia-juridica",
                   "executagent-studio", "familia-web", "btv-governance", "conciliaai-backend",
                   "criptotrade-app", "criptotrade-frontend", "giva-api-1", "giva-frontend-1",
                   "btv-squad-dashboard", "docker-cockpit", "mixlirous-api", "http2-backend",
                   "no-ssl-backend"}
    for u in upstreams:
        assert u in conhecidos or u.startswith("$"), f"Upstream nao reconhecido: {u}"


def test_parser_vps_hsts_em_todos_ssl():
    from ingress.parser import parse_nginx
    text = _load("nginx-vps.conf")
    cat = parse_nginx(text)
    for s in cat.servers:
        if s.has_ssl and s.primary_name not in ("_",):
            assert s.has_hsts, f"SSL sem HSTS: {s.primary_name}"


def test_parser_vps_sem_http2():
    from ingress.parser import parse_nginx
    text = _load("nginx-vps.conf")
    cat = parse_nginx(text)
    for s in cat.servers:
        if s.has_ssl:
            assert not s.has_http2, f"SSL com http2 na fixture real: {s.primary_name}"


def test_parser_vps_sem_gzip():
    from ingress.parser import parse_nginx
    text = _load("nginx-vps.conf")
    cat = parse_nginx(text)
    assert cat.global_config.get("gzip") is None


def test_parser_vps_include_guard():
    from ingress.parser import parse_nginx
    text = _load("nginx-vps.conf")
    cat = parse_nginx(text)
    assert len(cat.parse_warnings) == 0, f"Esperado sem warnings, obteve: {cat.parse_warnings}"


def test_parser_synthetic_http2():
    from ingress.parser import parse_nginx
    text = _load("nginx-synthetic.conf")
    cat = parse_nginx(text)
    http2_servers = [s for s in cat.servers if s.has_http2]
    assert len(http2_servers) == 1
    assert http2_servers[0].primary_name == "http2-test.buildtovalue.cloud"


def test_parser_synthetic_gzip():
    from ingress.parser import parse_nginx
    text = _load("nginx-synthetic.conf")
    cat = parse_nginx(text)
    assert cat.global_config.get("gzip") == "on"
    assert "text/plain" in (cat.global_config.get("gzip_types") or "")


def test_parser_synthetic_include_guard():
    from ingress.parser import parse_nginx
    text = _load("nginx-synthetic.conf")
    cat = parse_nginx(text)
    assert len(cat.parse_warnings) >= 1
    assert any("conf.d" in w for w in cat.parse_warnings)


def test_parser_synthetic_sem_ssl():
    from ingress.parser import parse_nginx
    text = _load("nginx-synthetic.conf")
    cat = parse_nginx(text)
    no_ssl = [s for s in cat.servers if not s.has_ssl and s.primary_name != "_"]
    assert len(no_ssl) == 1
    assert no_ssl[0].primary_name == "no-ssl-test.buildtovalue.cloud"


def test_parser_synthetic_upstream_literal():
    from ingress.parser import parse_nginx
    text = _load("nginx-synthetic.conf")
    cat = parse_nginx(text)
    no_ssl = [s for s in cat.servers if s.primary_name == "no-ssl-test.buildtovalue.cloud"]
    assert len(no_ssl) == 1
    locs = [l for l in no_ssl[0].locations if l.path == "/"]
    assert len(locs) == 1
    assert locs[0].proxy_pass_resolved == "http://no-ssl-backend:80"


def _build_snapshot_data(cat):
    from collections import OrderedDict
    hosts = OrderedDict()
    for s in cat.servers:
        name = s.primary_name
        if name == "_":
            continue
        if name not in hosts:
            hosts[name] = {"_internal": False, "_has_ssl": False}
        is80 = any(l["port"] == 80 for l in s.listen)
        is443 = any(l["port"] == 443 for l in s.listen)
        entry = hosts[name]
        if "localhost" in s.server_name:
            entry["_internal"] = True
        if s.auth_basic:
            entry["auth_basic"] = True
        for loc in s.locations:
            if "wp-login" in (loc.path or "") or "login.cgi" in (loc.path or ""):
                entry["bot_filter"] = True
        if is80:
            pi = {"https_redirect": False, "acme_challenge": False, "upstream": None}
            for loc in s.locations:
                if loc.path == "/.well-known/acme-challenge/":
                    pi["acme_challenge"] = True
                if loc.path == "/":
                    if loc.return_code == 301:
                        pi["https_redirect"] = True
                    elif loc.proxy_pass_resolved:
                        pi["upstream"] = loc.proxy_pass_resolved
            entry["port_80"] = pi
        if is443:
            entry["_has_ssl"] = True
            pi = {
                "upstreams": sorted(set(l.proxy_pass_resolved for l in s.locations if l.proxy_pass_resolved)),
                "ssl_cert": s.ssl_cert,
                "hsts": s.has_hsts,
                "http2": s.has_http2,
                "locations": len(s.locations),
            }
            entry["port_443"] = pi
    ordered = OrderedDict(sorted(hosts.items()))
    publics = {k: v for k, v in ordered.items() if not v.get("_internal")}
    # Strip internal keys from output
    cleaned = OrderedDict()
    for k, v in ordered.items():
        cv = {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
        if v.get("_internal"):
            cv["internal"] = True
        cleaned[k] = cv
    # If internal host has no meaningful port info, only keep internal flag
    for k, v in cleaned.items():
        if v.get("internal") and "port_80" not in v and "port_443" not in v:
            pass
    return {
        "hosts": cleaned,
        "totals": {
            "hosts": len(ordered),
            "public_hosts": len(publics),
            "with_ssl": sum(1 for k, v in publics.items() if v.get("_has_ssl")),
            "with_hsts": sum(1 for k, v in publics.items() if v.get("port_443", {}).get("hsts")),
            "with_auth": sum(1 for k, v in publics.items() if v.get("auth_basic")),
            "with_bot_filter": sum(1 for k, v in publics.items() if v.get("bot_filter")),
            "with_http2": sum(1 for k, v in publics.items() if v.get("port_443", {}).get("http2")),
        },
    }


def test_parser_vps_snapshot():
    import json
    from ingress.parser import parse_nginx
    text = _load("nginx-vps.conf")
    cat = parse_nginx(text)

    # No upstream should contain $ (proves variable resolution)
    for s in cat.servers:
        for loc in s.locations:
            if loc.proxy_pass_resolved:
                assert "$" not in loc.proxy_pass_resolved, (
                    f"Upstream nao resolvido em {s.primary_name}: {loc.proxy_pass_resolved}"
                )

    data = _build_snapshot_data(cat)
    snapshot_path = os.path.join(FIXTURES, "nginx-vps.snapshot.json")
    with open(snapshot_path) as f:
        expected = json.load(f)

    assert data["totals"] == expected["totals"], (
        f"Totais divergem: obtido={data['totals']}, esperado={expected['totals']}"
    )
    assert data["hosts"] == expected["hosts"], (
        f"Hosts divergem do snapshot. Regere com: python -c 'from tests.test_ingress_parser import _build_snapshot_data, _load; from ingress.parser import parse_nginx; import json; cat = parse_nginx(_load(\"nginx-vps.conf\")); print(json.dumps(_build_snapshot_data(cat), indent=2, ensure_ascii=False))'"
    )
