import re

_SENSITIVE_KEYS = re.compile(
    r"(?i)(pass|secret|token|credential|apikey|_key$|private)"
)
_URI_CREDENTIAL = re.compile(r"(://)([^@]+?)(@)")

_MASK = "********"


def _mask_uri_credential(value: str) -> str:
    def _replace(m: re.Match) -> str:
        return m.group(1) + _MASK + m.group(3)

    return _URI_CREDENTIAL.sub(_replace, value)


def mask_value(key: str, value: str) -> str:
    if _SENSITIVE_KEYS.search(key):
        return _MASK
    if isinstance(value, str) and "://" in value:
        return _mask_uri_credential(value)
    return value


def _walk_and_mask(obj):
    if isinstance(obj, dict):
        return {k: _walk_and_mask(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_and_mask(v) for v in obj]
    return obj


def _mask_env(env_list: list) -> list:
    masked = []
    for entry in env_list:
        if "=" not in entry:
            masked.append(entry)
            continue
        key, _, value = entry.partition("=")
        masked.append(f"{key}={mask_value(key, value)}")
    return masked


def _mask_cmd_args(cmd: list | None) -> list | None:
    if cmd is None:
        return None
    masked = []
    for arg in cmd:
        if "=" in arg:
            key, _, value = arg.partition("=")
            if _SENSITIVE_KEYS.search(key):
                masked.append(f"{key}={_MASK}")
                continue
        masked.append(arg)
    return masked


def _mask_entrypoint(entrypoint: list | str | None):
    if entrypoint is None:
        return None
    if isinstance(entrypoint, list):
        return _mask_cmd_args(entrypoint)
    return entrypoint


def mask_inspect(data: dict) -> dict:
    data = _walk_and_mask(data)
    config = data.get("Config") or {}
    if isinstance(config.get("Env"), list):
        config["Env"] = _mask_env(config["Env"])
    if isinstance(config.get("Cmd"), list):
        config["Cmd"] = _mask_cmd_args(config["Cmd"])
    if config.get("Entrypoint") is not None:
        config["Entrypoint"] = _mask_entrypoint(config["Entrypoint"])
    if isinstance(config.get("Labels"), dict):
        config["Labels"] = {
            k: mask_value(k, v) for k, v in config["Labels"].items()
        }
    return data
