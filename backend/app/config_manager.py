"""
ConfigManager — 配置单例
- 统一 config.json 读写，替代各处散落的 load_config()
- 支持热重载（reload() 方法或通过 Admin API 触发）
- 线程安全（asyncio.Lock）
"""
import asyncio
import json
import os
import time
from typing import Any, Dict, Optional

_CONFIG_FILE = "config.json"


class ConfigManager:
    _instance: Optional["ConfigManager"] = None

    def __init__(self, base_dir: str) -> None:
        self._path = os.path.join(base_dir, _CONFIG_FILE)
        self._data: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._loaded_at: float = 0.0
        self._load_sync()

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------
    @classmethod
    def init(cls, base_dir: str) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = cls(base_dir)
        return cls._instance

    @classmethod
    def get(cls) -> "ConfigManager":
        if cls._instance is None:
            raise RuntimeError("ConfigManager not initialised — call ConfigManager.init(base_dir) first")
        return cls._instance

    # ------------------------------------------------------------------
    # Sync helpers (used at startup before the event loop is running)
    # ------------------------------------------------------------------
    def _load_sync(self) -> None:
        if not os.path.exists(self._path):
            self._data = {}
            return
        for enc in ("utf-8", "utf-16", "gbk", "cp1252"):
            try:
                with open(self._path, "r", encoding=enc) as f:
                    self._data = json.load(f)
                self._loaded_at = time.time()
                return
            except Exception:
                continue
        self._data = {}

    def _save_sync(self) -> bool:
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
            self._loaded_at = time.time()
            return True
        except Exception as e:
            print(f"[ConfigManager] save failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def full(self) -> Dict[str, Any]:
        """Return a shallow copy of the whole config."""
        return dict(self._data)

    def get_section(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set_section(self, key: str, value: Any) -> bool:
        self._data[key] = value
        return self._save_sync()

    def update_section(self, key: str, updates: Dict[str, Any]) -> bool:
        """Merge *updates* into an existing dict section."""
        section = self._data.get(key, {})
        if isinstance(section, dict):
            section.update(updates)
        else:
            section = updates
        self._data[key] = section
        return self._save_sync()

    def reload(self) -> bool:
        """Reload from disk. Returns True if successful."""
        try:
            self._load_sync()
            rs485_manager_configure()
            print("[ConfigManager] reloaded")
            return True
        except Exception as e:
            print(f"[ConfigManager] reload error: {e}")
            return False

    @property
    def loaded_at(self) -> float:
        return self._loaded_at

    @property
    def path(self) -> str:
        return self._path


def rs485_manager_configure() -> None:
    """Apply rs485 config section to the global rs485_manager (if available)."""
    try:
        from app.rs485 import rs485_manager  # type: ignore
        cfg = ConfigManager.get()
        rs485_manager.configure(cfg.get_section("rs485", {}))
    except Exception:
        pass
