"""
Helen WiFi - Server Resource Monitor
Uses psutil to monitor CPU, memory, disk, and network usage.
"""
import logging

import psutil

logger = logging.getLogger("BRO.monitor")


def get_system_stats():
    """Get current system resource usage."""
    cpu_percent = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()

    return {
        "cpu_percent": cpu_percent,
        "cpu_count": psutil.cpu_count(),
        "memory": {
            "total": mem.total,
            "available": mem.available,
            "used": mem.used,
            "percent": mem.percent,
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
        },
        "network": {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        },
    }


def get_process_stats():
    """Get stats for the current server process."""
    proc = psutil.Process()
    with proc.oneshot():
        return {
            "pid": proc.pid,
            "cpu_percent": proc.cpu_percent(),
            "memory_mb": round(proc.memory_info().rss / 1048576, 1),
            "threads": proc.num_threads(),
            "open_files": len(proc.open_files()),
            "connections": len(proc.net_connections()),
        }
