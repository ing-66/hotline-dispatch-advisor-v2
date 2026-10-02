"""MySQL 轻量连接池（无 ORM，SQL 直连）。

- 懒创建 + 上限控制（pool_size）；空闲连接队列复用；
- 归还时校验连接存活（ping），损坏连接丢弃并新建；
- 所有连接建立后设置 UTC 时区与 utf8mb4 字符集。
- 进程退出时调用 close_all() 释放。
"""
from __future__ import annotations

import queue
import threading
import time

import pymysql
from pymysql.cursors import DictCursor

_CHARSET = "utf8mb4"


class _Connection:
    """包装 pymysql 连接并记录空闲起始时间，支持空闲超时回收。"""

    __slots__ = ("conn", "created_at", "idle_since")

    def __init__(self, conn: pymysql.Connection):
        self.conn = conn
        self.created_at = time.time()
        self.idle_since = time.time()


def _conn_alive(conn: pymysql.Connection) -> bool:
    """探测连接是否仍可用。

    注意：pymysql ping() 成功时返回 None（而不是 True），因此不能用返回值
    当布尔判断；必须用「是否抛出异常」判定。修复：连接池此前把 None 误判为
    不健康，导致每次归还都被关闭、连接从不复用。
    """
    try:
        conn.ping(reconnect=False)
        return True
    except pymysql.MySQLError:
        return False


class MysqlPool:
    """简单可靠的 MySQL 连接池。

    用法::

        pool = MysqlPool(host=..., user=..., password=..., database=..., pool_size=5)
        with pool.acquire() as cursor:
            cursor.execute("SELECT 1")
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3306,
        user: str = "",
        password: str = "",
        database: str = "",
        pool_size: int = 5,
        connect_timeout: int = 5,
        max_idle_seconds: float = 300.0,
    ):
        self._params = dict(
            host=host,
            port=int(port),
            user=user,
            password=password,
            database=database,
            charset=_CHARSET,
            autocommit=True,
            connect_timeout=int(connect_timeout),
            cursorclass=DictCursor,
        )
        self._pool_size = max(1, int(pool_size))
        self._max_idle_seconds = max_idle_seconds
        self._idle: queue.Queue[_Connection] = queue.Queue(maxsize=self._pool_size)
        self._lock = threading.Lock()
        self._created = 0  # 当前已创建连接数（含借出）
        self._closed = False

    def _connect(self) -> pymysql.Connection:
        try:
            conn = pymysql.connect(**self._params)
        except pymysql.MySQLError as exc:  # 认证/连接/库不存在等
            raise DatabaseUnavailable(f"MySQL 连接失败: {exc}") from exc
        with conn.cursor() as cur:
            cur.execute("SET time_zone = '+00:00'")
        return conn

    def _new_connection(self) -> _Connection:
        wrapper = _Connection(self._connect())
        return wrapper

    def _discard(self, wrapper: _Connection) -> None:
        """关闭并释放一个损坏/过期连接，容量计数回退。"""
        try:
            wrapper.conn.close()
        except Exception:
            pass
        with self._lock:
            self._created = max(0, self._created - 1)

    def acquire(self):
        """借出一个连接（优先复用空闲连接）。线程安全。"""
        if self._closed:
            raise DatabaseUnavailable("连接池已关闭")
        # 先尝试复用空闲连接；stale 或已断开的直接丢弃
        while True:
            try:
                wrapper = self._idle.get_nowait()
            except queue.Empty:
                wrapper = None
                break
            stale = (time.time() - wrapper.idle_since) > self._max_idle_seconds
            if stale or not _conn_alive(wrapper.conn):
                self._discard(wrapper)
                continue
            return _Lease(self, wrapper)
        # 无可用空闲：在容量内新建
        with self._lock:
            if self._created < self._pool_size:
                self._created += 1
                try:
                    return _Lease(self, self._new_connection())
                except Exception:
                    self._created -= 1
                    raise
        # 容量用尽：阻塞等待归还
        wrapper = self._idle.get()
        if not _conn_alive(wrapper.conn):
            self._discard(wrapper)
            wrapper = self._new_connection()
        return _Lease(self, wrapper)

    def release(self, wrapper: _Connection, healthy: bool = True) -> None:
        if self._closed or not healthy:
            try:
                wrapper.conn.close()
            except Exception:
                pass
            with self._lock:
                self._created = max(0, self._created - 1)
            return
        wrapper.idle_since = time.time()
        try:
            self._idle.put_nowait(wrapper)
        except queue.Full:
            try:
                wrapper.conn.close()
            except Exception:
                pass
            with self._lock:
                self._created = max(0, self._created - 1)

    def close_all(self) -> None:
        with self._lock:
            self._closed = True
            while True:
                try:
                    wrapper = self._idle.get_nowait()
                    try:
                        wrapper.conn.close()
                    except Exception:
                        pass
                    self._created = max(0, self._created - 1)
                except queue.Empty:
                    break

    def health(self) -> dict:
        """只读健康探测：返回 ok / 错误信息，不抛出异常。"""
        try:
            with self.acquire() as cur:
                cur.execute("SELECT VERSION() AS version, @@time_zone AS tz, @@character_set_server AS cs")
                row = cur.fetchone()
                cur.execute("SELECT 1 AS one")
                row["ping"] = cur.fetchone()["one"]
                return {"ok": True, "version": row["version"], "time_zone": row["tz"], "charset": row["cs"]}
        except Exception as exc:  # noqa: BLE001 —— 健康检查需把所有异常转成结构化结果
            return {"ok": False, "error": str(exc)}


class _Lease:
    """上下文管理器：with pool.acquire() as cursor。归还时自动 ping 检测。"""

    __slots__ = ("pool", "wrapper", "cursor")

    def __init__(self, pool: MysqlPool, wrapper: _Connection):
        self.pool = pool
        self.wrapper = wrapper
        self.cursor = wrapper.conn.cursor()

    def __enter__(self):
        return self.cursor

    def __exit__(self, exc_type, exc, tb):
        healthy = True
        try:
            if exc_type is not None:
                # 事务/语句异常：回滚（autocommit 下无碍），连接仍可复用
                try:
                    self.wrapper.conn.rollback()
                except Exception:
                    healthy = False
            else:
                # ping 成功返回 None 而非 True，不能直接当布尔值
                healthy = _conn_alive(self.wrapper.conn)
        except Exception:
            healthy = False
        try:
            self.cursor.close()
        except Exception:
            healthy = False
        self.pool.release(self.wrapper, healthy=healthy)
        return False  # 不吞异常


class DatabaseUnavailable(RuntimeError):
    """MySQL 不可用（连接拒绝/认证失败/库不存在/超时）时抛出的明确错误。"""


# ---------------------------------------------------------------------------
# 进程级默认池（懒初始化）
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_pool: MysqlPool | None = None


def configure_pool(raw_config: dict | None = None, database: str = "dev") -> MysqlPool:
    """按主配置创建/重建进程级连接池。返回池实例。"""
    from .config import mysql_config

    cfg = mysql_config(raw_config, database=database)
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close_all()
        _pool = MysqlPool(
            host=cfg["host"],
            port=cfg["port"],
            user=cfg["user"],
            password=cfg["password"],
            database=cfg["database"],
            pool_size=cfg["pool_size"],
            connect_timeout=cfg["connect_timeout"],
        )
        return _pool


def get_pool(raw_config: dict | None = None, database: str = "dev") -> MysqlPool | None:
    """返回进程级池；若配置未启用或缺少凭据则返回 None。"""
    from .config import is_enabled, mysql_config

    if not is_enabled(raw_config):
        return None
    cfg = mysql_config(raw_config, database=database)
    if not cfg["user"]:
        return None
    global _pool
    with _lock:
        if _pool is None:
            _pool = MysqlPool(
                host=cfg["host"],
                port=cfg["port"],
                user=cfg["user"],
                password=cfg["password"],
                database=cfg["database"],
                pool_size=cfg["pool_size"],
                connect_timeout=cfg["connect_timeout"],
            )
        return _pool


def close_all() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close_all()
            _pool = None
