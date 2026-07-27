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
