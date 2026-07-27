"""Testes do sampler: shape do retorno e geracao de warnings."""
import pytest
from unittest.mock import patch, MagicMock


def _patch_psutil(memory_percent=50, disk_percent=50, swap_percent=30, cpu_percent=30):
    """Patcheia psutil com valores controlados e retorna os mocks."""
    mock_mem = MagicMock()
    mock_mem.total = 16 * 1024**3
    mock_mem.used = 8 * 1024**3
    mock_mem.available = 8 * 1024**3
    mock_mem.percent = memory_percent

    mock_swap = MagicMock()
    mock_swap.total = 2 * 1024**3
    mock_swap.used = 1 * 1024**3
    mock_swap.free = 1 * 1024**3
    mock_swap.percent = swap_percent

    mock_disk = MagicMock()
    mock_disk.device = "/dev/sda1"
    mock_disk.mountpoint = "/"
    mock_disk.fstype = "ext4"
    mock_disk_usage = MagicMock()
    mock_disk_usage.total = 100 * 1024**3
    mock_disk_usage.used = int(disk_percent / 100 * 100 * 1024**3)
    mock_disk_usage.free = 100 * 1024**3 - mock_disk_usage.used
    mock_disk_usage.percent = disk_percent

    mock_net = MagicMock()
    mock_net.bytes_sent = 1000
    mock_net.bytes_recv = 2000
    mock_net.packets_sent = 500
    mock_net.packets_recv = 600

    return {
        "virtual_memory": mock_mem,
        "swap_memory": mock_swap,
        "disk_partitions": [mock_disk],
        "disk_usage": mock_disk_usage,
        "net_io_counters": mock_net,
    }


def test_sample_shape():
    """_sample() retorna dict com as chaves esperadas."""
    from sampler import _sample

    mocks = _patch_psutil()
    with patch.multiple(
        "psutil",
        cpu_percent=lambda interval=0: 42.0,
        cpu_count=lambda logical=True: 4,
        virtual_memory=lambda: mocks["virtual_memory"],
        swap_memory=lambda: mocks["swap_memory"],
        disk_partitions=lambda all=False: mocks["disk_partitions"],
        disk_usage=lambda path: mocks["disk_usage"],
        net_io_counters=lambda: mocks["net_io_counters"],
        net_if_addrs=lambda: {},
        boot_time=lambda: 1000,
    ):
        result = _sample()

    assert "sampled_at" in result
    assert result["cpu"]["percent"] == 42.0
    assert result["memory"]["total"] == 16 * 1024**3
    assert result["memory"]["used"] == 8 * 1024**3
    assert result["memory"]["free"] == 8 * 1024**3
    assert result["memory"]["percent"] == 50
    assert result["swap"]["used"] == 1 * 1024**3
    assert result["disks"][0]["used"] == int(0.5 * 100 * 1024**3)
    assert result["disks"][0]["percent"] == 50.0
    assert result["uptime_seconds"] > 0
    assert result["warnings"] == []


def test_sample_warnings_disk_high():
    """Disco acima de 90% gera warning crit."""
    from sampler import _sample

    mocks = _patch_psutil(disk_percent=95)
    with patch.multiple(
        "psutil",
        cpu_percent=lambda interval=0: 42.0,
        cpu_count=lambda logical=True: 4,
        virtual_memory=lambda: mocks["virtual_memory"],
        swap_memory=lambda: mocks["swap_memory"],
        disk_partitions=lambda all=False: mocks["disk_partitions"],
        disk_usage=lambda path: mocks["disk_usage"],
        net_io_counters=lambda: mocks["net_io_counters"],
        net_if_addrs=lambda: {},
        boot_time=lambda: 1000,
    ):
        result = _sample()

    warnings = [w for w in result["warnings"] if "Disco" in w.get("message", "")]
    assert len(warnings) == 1
    assert warnings[0]["level"] == "crit"


def test_sample_warnings_cpu_high():
    """CPU acima de 80% gera warning warn."""
    from sampler import _sample

    mocks = _patch_psutil()
    with patch.multiple(
        "psutil",
        cpu_percent=lambda interval=0: 85.0,
        cpu_count=lambda logical=True: 4,
        virtual_memory=lambda: mocks["virtual_memory"],
        swap_memory=lambda: mocks["swap_memory"],
        disk_partitions=lambda all=False: mocks["disk_partitions"],
        disk_usage=lambda path: mocks["disk_usage"],
        net_io_counters=lambda: mocks["net_io_counters"],
        net_if_addrs=lambda: {},
        boot_time=lambda: 1000,
    ):
        result = _sample()

    warnings = [w for w in result["warnings"] if "CPU" in w.get("message", "")]
    assert len(warnings) == 1
    assert warnings[0]["level"] == "warn"


def test_sample_warnings_multiple():
    """Multiplos limiares ultrapassados geram multiplos warnings."""
    from sampler import _sample

    mocks = _patch_psutil(memory_percent=90, disk_percent=95, swap_percent=85, cpu_percent=90)
    with patch.multiple(
        "psutil",
        cpu_percent=lambda interval=0: 90.0,
        cpu_count=lambda logical=True: 4,
        virtual_memory=lambda: mocks["virtual_memory"],
        swap_memory=lambda: mocks["swap_memory"],
        disk_partitions=lambda all=False: mocks["disk_partitions"],
        disk_usage=lambda path: mocks["disk_usage"],
        net_io_counters=lambda: mocks["net_io_counters"],
        net_if_addrs=lambda: {},
        boot_time=lambda: 1000,
    ):
        result = _sample()

    # Pelo menos 3 das 4 categorias devem ter warnings (CPU, mem, swap, disk)
    assert len(result["warnings"]) >= 3
