"""MySQL 健康检查。

返回结构化结果 dict，绝不抛出异常、绝不输出凭据：

- 未启用/缺凭据 -> ``{"enabled": false, "configured": false, ...}``
- 可用           -> ``{"enabled": true, "ok": true, "version": "...", "latency_ms": 12, ...}``
- 不可用         -> ``{"enabled": true, "ok": false, "error": "分类后的明确错误", ...}``
"""
from __future__ import annotations

import time

from .pool import MysqlPool, DatabaseUnavailable


def _categorize(exc: BaseException) -> str:
    msg = str(exc)
    low = msg.lower()
    if "access denied" in low or "1045" in msg:
        return f"认证失败（用户名或密码错误）: {msg}"
    if "unknown database" in low or "1049" in msg:
        return f"数据库不存在: {msg}"
    if "connection refused" in low or "2003" in msg or "timed out" in low or "timeout" in low or "2002" in msg:
        return f"无法连接 MySQL 服务（请确认服务已启动、主机端口正确）: {msg}"
    if "can't connect" in low:
        return f"无法连接 MySQL 服务: {msg}"
    return f"MySQL 检查失败: {msg}"


def check_mysql(raw_config: dict | None = None, database: str = "dev") -> dict:
    """对目标库做一次连接探测。

    raw_config: 主 config dict（含 mysql 段）；database: dev | test。
    """
    from .config import is_enabled, mysql_config

    if not is_enabled(raw_config):
        return {"enabled": False, "ok": None, "detail": "mysql.enabled=false（未启用，现有链路不受影响）"}

    cfg = mysql_config(raw_config, database=database)
    if not cfg.get("user") or not cfg.get("password") or not cfg.get("database"):
        return {
            "enabled": True,
            "ok": False,
            "detail": "MySQL 已启用但凭据/库名未配置（config.yaml mysql: 段或 HOTLINE_MYSQL_* 环境变量）",
            "database": cfg.get("database"),
        }

    start = time.time()
    try:
        probe = MysqlPool(
            host=cfg["host"],
            port=cfg["port"],
            user=cfg["user"],
            password=cfg["password"],
            database=cfg["database"],
            pool_size=1,
            connect_timeout=cfg["connect_timeout"],
        )
        result = probe.health()
        probe.close_all()
        latency_ms = int((time.time() - start) * 1000)
        result["enabled"] = True
        result["database"] = cfg["database"]
        result["latency_ms"] = latency_ms
        if result.get("ok"):
            return result
        result["error"] = _categorize(RuntimeError(result.get("error", "unknown")))
        return result
    except DatabaseUnavailable as exc:
        return {
            "enabled": True,
            "ok": False,
            "error": _categorize(exc),
            "database": cfg.get("database"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "enabled": True,
            "ok": False,
            "error": _categorize(exc),
            "database": cfg.get("database"),
        }


def format_check(result: dict) -> str:
    """把 check_mysql 结果格式化为单行文本（供 CLI 显示，无凭据）。"""
    if not result.get("enabled"):
        return f"[mysql] 未启用（{result.get('detail')}）"
    if result.get("ok"):
        db = result.get("database", "")
        return (
            f"[mysql] 正常 db={db} version={result.get('version')} "
            f"time_zone={result.get('time_zone')} charset={result.get('charset')} "
            f"latency={result.get('latency_ms')}ms"
        )
    return f"[mysql] 异常 db={result.get('database')} error={result.get('error') or result.get('detail')}"
