"""Unit tests for backend/app/config_manager.py — ConfigManager singleton."""
import pytest
import json
import os
import tempfile
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
from app.config_manager import ConfigManager


class TestConfigManager:
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton between tests."""
        ConfigManager._instance = None
        yield
        ConfigManager._instance = None

    def test_init_creates_instance(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = ConfigManager.init(td)
            assert mgr is not None
            assert isinstance(mgr.full(), dict)

    def test_singleton_returns_same_instance(self):
        with tempfile.TemporaryDirectory() as td:
            a = ConfigManager.init(td)
            b = ConfigManager.get()
            assert a is b

    def test_get_without_init_raises(self):
        ConfigManager._instance = None
        with pytest.raises(RuntimeError, match='not initialised'):
            ConfigManager.get()

    def test_full_returns_copy(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = ConfigManager.init(td)
            data = mgr.full()
            data['modified'] = True
            assert 'modified' not in mgr.full()

    def test_set_and_get_section(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = ConfigManager.init(td)
            mgr.set_section('test', {'key': 'value'})
            assert mgr.get_section('test') == {'key': 'value'}

    def test_get_nonexistent_section(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = ConfigManager.init(td)
            assert mgr.get_section('nonexistent') is None
            assert mgr.get_section('nonexistent', 'default') == 'default'

    def test_update_section_merges(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = ConfigManager.init(td)
            mgr.set_section('rs485', {'enabled': True, 'port': 'COM1'})
            mgr.update_section('rs485', {'port': 'COM3', 'baudrate': 9600})
            section = mgr.get_section('rs485')
            assert section['enabled'] is True
            assert section['port'] == 'COM3'
            assert section['baudrate'] == 9600

    def test_save_and_reload(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = ConfigManager.init(td)
            mgr.set_section('test', {'saved': True})
            # Reload
            assert mgr.reload()
            assert mgr.get_section('test') == {'saved': True}

    def test_path_property(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = ConfigManager.init(td)
            assert mgr.path == os.path.join(td, 'config.json')

    def test_init_with_no_config_file(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = ConfigManager.init(td)
            assert mgr.full() == {}

    def test_init_with_existing_config(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = os.path.join(td, 'config.json')
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump({'existing': True}, f)
            mgr = ConfigManager.init(td)
            assert mgr.get_section('existing') is True
