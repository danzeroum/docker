def health_status(insp) -> str | None:
    """State.Health.Status do inspect, ou None quando nao ha healthcheck.

    Ausencia de healthcheck e ausencia de dado, nao "saudavel": devolver "ok"
    aqui faria a listagem afirmar saude que ninguem mediu.

    Cada nivel e checado por isinstance, e nao por `.get(k, {})`, porque o
    default so vale quando a chave ESTA AUSENTE. O daemon devolve `Health`
    presente valendo null em container sem healthcheck, e ai `.get("Health", {})`
    entrega None — o `.get("Status")` seguinte levanta AttributeError. Foi assim
    que /api/capacity passou a responder 500.
    """
    if not isinstance(insp, dict):
        return None
    estado = insp.get("State")
    if not isinstance(estado, dict):
        return None
    saude = estado.get("Health")
    if not isinstance(saude, dict):
        return None
    return saude.get("Status") or None


def calc_cpu_percent(raw: dict) -> float:
    cpu_delta = raw.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
    sys_delta = raw.get("cpu_stats", {}).get("system_cpu_usage", 0)
    precpu = raw.get("precpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
    presys = raw.get("precpu_stats", {}).get("system_cpu_usage", 0)
    num_cpus = raw.get("cpu_stats", {}).get("online_cpus", 1)

    if sys_delta and presys:
        cpu_delta_val = cpu_delta - precpu
        sys_delta_val = sys_delta - presys
        if cpu_delta_val > 0 and sys_delta_val > 0:
            return round((cpu_delta_val / sys_delta_val) * num_cpus * 100, 1)
    return 0.0
