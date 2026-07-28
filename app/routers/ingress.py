import os
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Query
from collections import OrderedDict

router = APIRouter(prefix="/api", tags=["ingress"])

NGINX_CONFIG = os.getenv("NGINX_CONFIG_PATH", "/etc/nginx/nginx.conf")


def _catalog_to_public(cat):
    public_set = {s.primary_name for s in cat.public_servers}
    hosts = OrderedDict()
    for s in cat.servers:
        name = s.primary_name
        if name == "_":
            continue
        if name not in hosts:
            hosts[name] = {"internal": False, "ssl": False}
        is80 = any(l["port"] == 80 for l in s.listen)
        is443 = any(l["port"] == 443 for l in s.listen)
        entry = hosts[name]
        if "localhost" in s.server_name:
            entry["internal"] = True
        if s.auth_basic:
            entry["auth_basic"] = True
        bot_filter = any(
            x in (loc.path or "")
            for loc in s.locations
            for x in ("wp-login", "login.cgi")
        )
        if bot_filter:
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
            entry["ssl"] = True
            entry.setdefault("cert_paths", set())
            if s.ssl_cert:
                entry["cert_paths"].add(s.ssl_cert)
            upstreams = sorted(set(
                l.proxy_pass_resolved for l in s.locations if l.proxy_pass_resolved
            ))
            if upstreams:
                entry.setdefault("upstreams", set()).update(upstreams)
            if s.has_hsts:
                entry["hsts"] = True
            if s.has_http2:
                entry["http2"] = True
            pi = {
                "upstreams": upstreams,
                "locations": len(s.locations),
            }
            if s.ssl_cert:
                pi["ssl_cert"] = s.ssl_cert
            entry["port_443"] = pi

    ordered = OrderedDict(sorted(hosts.items()))
    result = {}
    for k, v in ordered.items():
        cv = {}
        if v.get("internal"):
            cv["internal"] = True
        if v.get("auth_basic"):
            cv["auth_basic"] = True
        if v.get("bot_filter"):
            cv["bot_filter"] = True
        if v.get("hsts"):
            cv["hsts"] = True
        if v.get("http2"):
            cv["http2"] = True
        if v.get("ssl"):
            cv["ssl"] = True
        certs = v.get("cert_paths")
        if certs:
            cv["cert_path"] = sorted(certs)[0]
        us = v.get("upstreams")
        if us:
            cv["upstreams"] = sorted(us)
        if "port_80" in v:
            cv["port_80"] = v["port_80"]
        if "port_443" in v:
            cv["port_443"] = {kk: vv for kk, vv in v["port_443"].items() if kk != "ssl_cert"}
        result[k] = cv

    return {
        "hosts": result,
        "totals": {
            "total": len(ordered),
            "public": len(public_set),
            "with_ssl": sum(1 for v in ordered.values() if not v.get("internal") and v.get("ssl")),
            "with_hsts": sum(1 for v in ordered.values() if not v.get("internal") and v.get("hsts")),
            "with_auth": sum(1 for v in ordered.values() if not v.get("internal") and v.get("auth_basic")),
            "with_bot_filter": sum(1 for v in ordered.values() if not v.get("internal") and v.get("bot_filter")),
            "with_http2": sum(1 for v in ordered.values() if not v.get("internal") and v.get("http2")),
        },
        "parsed_at": cat.parsed_at,
        "warnings": cat.parse_warnings,
    }


@router.get("/ingress")
async def get_ingress():
    from ingress.parser import parse_file
    if not os.path.isfile(NGINX_CONFIG):
        return {
            "error": f"nginx config not found: {NGINX_CONFIG}",
            "hosts": {},
            "totals": {"total": 0, "public": 0},
            "parsed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    cat = parse_file(NGINX_CONFIG)
    if cat is None:
        return {
            "error": f"failed to parse: {NGINX_CONFIG}",
            "hosts": {},
            "totals": {"total": 0, "public": 0},
            "parsed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    return _catalog_to_public(cat)
