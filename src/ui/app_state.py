"""PyQt 控制中心共用的界面状态。"""

from __future__ import annotations

from typing import Any, Dict, List

from PyQt5.QtCore import QObject, pyqtSignal


class AppState(QObject):
    """顶层页面共用的轻量可观察状态容器。"""

    device_changed = pyqtSignal(dict)
    run_status_changed = pyqtSignal(str)
    elapsed_changed = pyqtSignal(int)
    battle_count_changed = pyqtSignal(int)
    active_deck_changed = pyqtSignal(dict)
    rotation_status_changed = pyqtSignal(dict)
    log_added = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.device: Dict[str, Any] = {
            "connected": False,
            "serial": "",
            "server": "国服",
            "model": "",
            "resolution": "",
            "message": "尚未连接设备",
        }
        self.run_status = "disconnected"
        self.elapsed_seconds = 0
        self.battle_count = 0
        self.active_deck: Dict[str, Any] = {
            "name": "未命名卡组",
            "count": 0,
            "distinct_count": 0,
            "costs": {},
            "file": None,
            "applied": True,
        }
        self.rotation_status: Dict[str, Any] = {
            "enabled": False,
            "state": "disabled",
            "current_slot": None,
            "current_name": "",
            "next_slot": None,
            "next_name": "",
            "completed": 0,
            "interval": 0,
            "remaining": 0,
        }
        self.logs: List[str] = []

    def set_device(self, **values: Any) -> None:
        self.device.update(values)
        self.device_changed.emit(dict(self.device))

    def set_run_status(self, status: str) -> None:
        value = str(status or "stopped")
        if value == self.run_status:
            return
        self.run_status = value
        self.run_status_changed.emit(value)

    def set_elapsed(self, seconds: int) -> None:
        value = max(0, int(seconds or 0))
        self.elapsed_seconds = value
        self.elapsed_changed.emit(value)

    def set_battle_count(self, count: int) -> None:
        value = max(0, int(count or 0))
        self.battle_count = value
        self.battle_count_changed.emit(value)

    def set_active_deck(self, data: Dict[str, Any]) -> None:
        if isinstance(data, dict):
            self.active_deck.update(data)
        self.active_deck_changed.emit(dict(self.active_deck))

    def set_rotation_status(self, data: Dict[str, Any]) -> None:
        if isinstance(data, dict):
            self.rotation_status.update(data)
        self.rotation_status_changed.emit(dict(self.rotation_status))

    def append_log(self, message: Any) -> None:
        text = str(message or "")
        if not text:
            return
        self.logs.append(text)
        if len(self.logs) > 5000:
            del self.logs[: len(self.logs) - 5000]
        self.log_added.emit(text)
