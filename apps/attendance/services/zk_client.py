"""Thin adapter over pyzk so device sync can be tested with a fake. Read-only: never disables the device."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, List

from apps.users.models import ZKConfig

CONNECT_TIMEOUT = 20


@dataclass(frozen=True)
class ZKRecord:
    user_id: str
    timestamp: datetime


class ZKSession:
    def __init__(self, conn):
        self._conn = conn

    def get_attendance(self) -> List[ZKRecord]:
        return [ZKRecord(str(a.user_id), a.timestamp) for a in self._conn.get_attendance()]


@contextmanager
def open_device(config: ZKConfig) -> Iterator[ZKSession]:
    from zk import ZK

    conn = ZK(config.ip, port=config.port, timeout=CONNECT_TIMEOUT, password=int(config.password or 0),
              force_udp=config.force_udp, ommit_ping=config.ommit_ping).connect()
    try:
        yield ZKSession(conn)
    finally:
        conn.disconnect()


# device_sync calls this attribute; tests replace it with a fake.
OPEN_DEVICE = open_device
