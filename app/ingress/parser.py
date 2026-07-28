"""Parser de configuracao nginx para extrair servidores, dominios e upstreams."""

import os
import re
from datetime import datetime, timezone

_RE_LISTEN = re.compile(r"listen\s+(.+?)(?:;|\s*{)")
_RE_SERVER_NAME = re.compile(r"server_name\s+(.+?);")
_RE_SSL_CERT = re.compile(r"ssl_certificate\s+(.+?);")
_RE_SSL_CERT_KEY = re.compile(r"ssl_certificate_key\s+(.+?);")
_RE_PROXY_PASS = re.compile(r"proxy_pass\s+(.+?);")
_RE_SET = re.compile(r"set\s+\$(\w+)\s+\"(.+?)\";")
_RE_REWRITE = re.compile(r"rewrite\s+(\S+)\s+(\S+)\s*(?:\s+(last|break))?;")
_RE_ADD_HEADER = re.compile(r"add_header\s+(\S+)\s+(.+?)\s*(?:always)?;")
_RE_RETURN = re.compile(r"return\s+(\d+)\s*(.*?);")
_RE_AUTH_BASIC = re.compile(r"auth_basic\s+\"(.*?)\";")
_RE_AUTH_USER_FILE = re.compile(r"auth_basic_user_file\s+(.+?);")
_RE_ROOT = re.compile(r"root\s+(.+?);")
_RE_INDEX = re.compile(r"index\s+(.+?);")
_RE_CLIENT_MAX = re.compile(r"client_max_body_size\s+(.+?);")
_RE_PROXY_TIMEOUT = re.compile(r"proxy_read_timeout\s+(.+?);")
_RE_PROXY_BUFFERING = re.compile(r"proxy_buffering\s+(off|on);")
_RE_GZIP = re.compile(r"gzip\s+(on|off);")
_RE_GZIP_TYPES = re.compile(r"gzip_types\s+(.+?);")
_RE_INCLUDE = re.compile(r"include\s+(.+?);")
_RE_RESOLVER = re.compile(r"resolver\s+(.+?);")
_RE_SERVER_TOKENS = re.compile(r"server_tokens\s+(.+?);")
_RE_SSL_PROTOCOLS = re.compile(r"ssl_protocols\s+(.+?);")
_RE_SSL_CIPHERS = re.compile(r"ssl_ciphers\s+(.+?);")
_RE_AUTOINDEX = re.compile(r"autoindex\s+(.+?);")


def parse_ts(ts_str):
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _strip_comment(text):
    return "\n".join(
        line[:line.index("#")] if "#" in line else line
        for line in text.split("\n")
    )


class IngressCatalog:
    def __init__(self):
        self.servers = []
        self.upstreams = {}
        self.global_config = {}
        self.includes = []
        self.parse_warnings = []
        self.parsed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @property
    def _internal_hosts(self):
        hosts = set()
        for s in self.servers:
            if s.is_internal:
                hosts.add(s.primary_name)
        return hosts

    @property
    def public_servers(self):
        internal = self._internal_hosts
        return [s for s in self.servers if s.primary_name not in internal]


class ServerBlock:
    def __init__(self):
        self.listen = []
        self.server_name = []
        self.is_default = False
        self.has_ssl = False
        self.ssl_cert = None
        self.ssl_cert_key = None
        self.locations = []
        self.headers = {}
        self.auth_basic = None
        self.auth_user_file = None
        self.root = None
        self.index = None
        self.gzip = None
        self.gzip_types = None
        self.has_http2 = False
        self.has_hsts = False
        self.ssl_protocols = None
        self.ssl_ciphers = None
        self.client_max_body_size = None
        self._variables = {}

    @property
    def primary_name(self):
        for n in self.server_name:
            if n != "_":
                return n
        return self.server_name[0] if self.server_name else "_"

    @property
    def is_internal(self):
        return "_" in self.server_name or "localhost" in self.server_name


class LocationBlock:
    def __init__(self, path, modifier=None):
        self.path = path
        self.modifier = modifier
        self.proxy_pass = None
        self.proxy_pass_resolved = None
        self.rewrite = None
        self.headers = {}
        self.root = None
        self.return_code = None
        self.return_body = None
        self.client_max_body_size = None
        self.proxy_read_timeout = None
        self.proxy_buffering = None
        self.autoindex = None
        self._variables = {}

    @property
    def is_exact(self):
        return self.modifier == "="

    @property
    def is_prefix(self):
        return self.modifier == "^~"

    @property
    def is_regex(self):
        return self.modifier == "~" or self.modifier == "~*"


def _parse_listen(s):
    parts = s.strip().split()
    result = {"port": 80, "ssl": False, "default": False, "ipv6": False, "http2": False}
    for p in parts:
        p = p.strip()
        if p == "ssl":
            result["ssl"] = True
        elif p == "default_server":
            result["default"] = True
        elif p == "http2":
            result["http2"] = True
        elif p == "proxy_protocol":
            pass
        elif p.startswith("[::]"):
            result["ipv6"] = True
            port_part = p.split(":")[-1] if ":" in p else "80"
            result["port"] = int(port_part) if port_part.isdigit() else 80
        elif p.isdigit():
            result["port"] = int(p)
    return result


def _resolve_proxy_pass(raw, variables):
    if not raw:
        return None
    var_match = re.match(r"\$(\w+)", raw)
    if var_match and var_match.group(0) == raw.strip():
        resolved = variables.get(var_match.group(1))
        return resolved if resolved else raw
    return raw


def parse_nginx(text, source="<string>"):
    catalog = IngressCatalog()
    text = _strip_comment(text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    ctx_stack = []
    current_block = None
    current_server = None
    current_location = None
    vars_scope = {}
    in_http = False
    in_server = False
    in_location = False
    in_events = False

    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#"):
            continue

        if line.startswith("events {"):
            brace_count = line.count("{") - line.count("}")
            while brace_count > 0 and i < len(lines):
                l = lines[i].strip()
                i += 1
                if "{" in l:
                    brace_count += l.count("{")
                if "}" in l:
                    brace_count -= l.count("}")
            continue

        if line.startswith("http {"):
            http_brace = line.count("{") - line.count("}")
            while http_brace > 0 and i < len(lines):
                l = lines[i].strip()
                i += 1
                if not l or l.startswith("#"):
                    continue

                if "{" in l:
                    http_brace += l.count("{")
                if "}" in l:
                    http_brace -= l.count("}")

                if http_brace == 0:
                    break

                if l.startswith("include "):
                    m = _RE_INCLUDE.search(l)
                    if m:
                        inc = m.group(1).strip()
                        catalog.includes.append(inc)
                        if inc not in ("/etc/nginx/mime.types",):
                            catalog.parse_warnings.append(
                                f"Include fora de mime.types: {inc}"
                            )

                elif l.startswith("resolver "):
                    m = _RE_RESOLVER.search(l)
                    if m:
                        catalog.global_config["resolver"] = m.group(1).strip()

                elif l.startswith("server_tokens "):
                    m = _RE_SERVER_TOKENS.search(l)
                    if m:
                        catalog.global_config["server_tokens"] = m.group(1).strip()

                elif l.startswith("gzip ") or l.startswith("gzip_types "):
                    m = _RE_GZIP.search(l)
                    if m:
                        catalog.global_config["gzip"] = m.group(1).strip()
                    m = _RE_GZIP_TYPES.search(l)
                    if m:
                        catalog.global_config["gzip_types"] = m.group(1).strip()

                elif l.startswith("server {"):
                    sb_brace = l.count("{") - l.count("}")
                    block_lines = []
                    after_brace = l[l.index("{")+1:].strip()
                    if after_brace:
                        # if sb_brace > 0: this line's content after '{' is part of the server body
                        # if sb_brace == 0: it's a one-liner with closing on same line
                        pass
                    if sb_brace == 0:
                        one_liner = after_brace.rstrip("}").strip()
                        if one_liner:
                            for stmt in one_liner.split(";"):
                                stmt = stmt.strip()
                                if stmt:
                                    block_lines.append(stmt + ";")
                    else:
                        # multi-line server: extract directives after '{' on opening line
                        if after_brace:
                            for stmt in after_brace.split(";"):
                                stmt = stmt.strip()
                                if stmt:
                                    block_lines.append(stmt + ";")
                    while sb_brace > 0 and i < len(lines):
                        sl = lines[i].strip()
                        i += 1
                        if not sl:
                            continue
                        if "{" in sl:
                            sb_brace += sl.count("{")
                        if "}" in sl:
                            sb_brace -= sl.count("}")
                        block_lines.append(sl)

                    if block_lines:
                        current_server = ServerBlock()
                        _parse_server_block(block_lines, current_server, catalog)
                        catalog.servers.append(current_server)
            continue

    return catalog


def _process_directive(line, server, current_location_block, catalog):
    m = _RE_LISTEN.search(line)
    if m:
        parsed = _parse_listen(m.group(1))
        server.listen.append(parsed)
        if parsed["ssl"]:
            server.has_ssl = True
        if parsed["default"]:
            server.is_default = True
        if parsed.get("http2"):
            server.has_http2 = True
        return

    m = _RE_SERVER_NAME.search(line)
    if m:
        server.server_name = m.group(1).strip().split()
        return

    m = _RE_SSL_CERT.search(line)
    if m:
        server.ssl_cert = m.group(1).strip()
        server.has_ssl = True
        return

    m = _RE_SSL_CERT_KEY.search(line)
    if m:
        server.ssl_cert_key = m.group(1).strip()
        return

    m = _RE_ADD_HEADER.search(line)
    if m:
        key = m.group(1).strip()
        val = m.group(2).strip().strip(";").strip('"')
        if current_location_block:
            current_location_block.headers[key] = val
        else:
            server.headers[key] = val
        if key.lower() == "strict-transport-security":
            if current_location_block:
                pass
            else:
                server.has_hsts = True
        return

    m = _RE_AUTH_BASIC.search(line)
    if m:
        server.auth_basic = m.group(1).strip()
        return

    m = _RE_AUTH_USER_FILE.search(line)
    if m:
        server.auth_user_file = m.group(1).strip()
        return

    m = _RE_ROOT.search(line)
    if m:
        val = m.group(1).strip().strip(";")
        if current_location_block:
            current_location_block.root = val
        else:
            server.root = val
        return

    m = _RE_AUTOINDEX.search(line)
    if m:
        val = m.group(1).strip()
        if current_location_block:
            current_location_block.autoindex = val
        return

    m = _RE_INDEX.search(line)
    if m:
        server.index = m.group(1).strip()
        return

    m = _RE_CLIENT_MAX.search(line)
    if m:
        if current_location_block:
            current_location_block.client_max_body_size = m.group(1).strip()
        else:
            server.client_max_body_size = m.group(1).strip()
        return

    m = _RE_PROXY_TIMEOUT.search(line)
    if m:
        if current_location_block:
            current_location_block.proxy_read_timeout = m.group(1).strip()
        return

    m = _RE_PROXY_BUFFERING.search(line)
    if m:
        if current_location_block:
            current_location_block.proxy_buffering = m.group(1).strip()
        return

    m = _RE_SET.search(line)
    if m:
        var_name = m.group(1)
        var_val = m.group(2)
        if current_location_block:
            current_location_block._variables[var_name] = var_val
        else:
            server._variables[var_name] = var_val
        return

    m = _RE_PROXY_PASS.search(line)
    if m:
        raw = m.group(1).strip().strip(";")
        if current_location_block:
            current_location_block.proxy_pass = raw
        return

    m = _RE_REWRITE.search(line)
    if m:
        pattern = m.group(1)
        replacement = m.group(2)
        if current_location_block:
            current_location_block.rewrite = {"pattern": pattern, "replacement": replacement}
        return

    m = _RE_RETURN.search(line)
    if m:
        code = int(m.group(1))
        body = m.group(2).strip().strip(";").strip('"')
        if current_location_block:
            current_location_block.return_code = code
            current_location_block.return_body = body
        return

    m = _RE_SSL_PROTOCOLS.search(line)
    if m:
        server.ssl_protocols = m.group(1).strip()
        return

    m = _RE_SSL_CIPHERS.search(line)
    if m:
        server.ssl_ciphers = m.group(1).strip()
        return


def _parse_server_block(lines, server, catalog):
    current_location_block = None
    for line in lines:
        if not line or line.startswith("#"):
            continue

        if line.startswith("location ") or line.startswith("location ~") or line.startswith("location ^~") or line.startswith("location =") or line.startswith("location @") or line.startswith("location ~*"):
            mod = None
            rest = line[len("location "):].strip()
            if rest.startswith("="):
                mod = "="
                rest = rest[1:].strip()
            elif rest.startswith("^~"):
                mod = "^~"
                rest = rest[2:].strip()
            elif rest.startswith("~*"):
                mod = "~*"
                rest = rest[3:].strip()
            elif rest.startswith("~"):
                mod = "~"
                rest = rest[1:].strip()
            elif rest.startswith("@"):
                mod = "@"
                rest = rest[1:].strip()

            path = rest.split("{")[0].strip() if "{" in rest else rest.strip()
            current_location_block = LocationBlock(path, modifier=mod)
            server.locations.append(current_location_block)
            if "{" in rest:
                inner = rest.split("{", 1)[1]
                if "}" in inner:
                    inner = inner.rstrip("}").strip()
                    for stmt in inner.split(";"):
                        stmt = stmt.strip()
                        if stmt:
                            _process_directive(stmt + ";", server, current_location_block, catalog)
                    current_location_block = None
                    continue
            continue

        if line == "}" and current_location_block:
            current_location_block = None
            continue
        if line == "}":
            continue

        _process_directive(line, server, current_location_block, catalog)

    for loc in server.locations:
        scope_vars = dict(server._variables)
        scope_vars.update(loc._variables)
        loc.proxy_pass_resolved = _resolve_proxy_pass(loc.proxy_pass, scope_vars)


def parse_file(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r") as f:
        text = f.read()
    return parse_nginx(text, source=path)
