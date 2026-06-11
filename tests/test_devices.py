"""Unit tests for backend/app/devices.py — DeviceProtocol and CRC16."""
import pytest
import struct
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
from app.devices import crc16_modbus, DeviceProtocol


class TestCRC16:
    def test_known_vector(self):
        """01 03 00 00 00 01 => CRC 840A (stored big-endian)"""
        result = crc16_modbus(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01]))
        assert result == struct.pack('>H', 0x840A)
        assert len(result) == 2

    def test_empty_input(self):
        result = crc16_modbus(b'')
        assert result == struct.pack('>H', 0xFFFF)

    def test_single_byte(self):
        result = crc16_modbus(bytes([0x00]))
        assert result == struct.pack('>H', 0xBF40)

    def test_returns_two_bytes(self):
        data = bytes([0x01, 0x02, 0x03, 0x04])
        result = crc16_modbus(data)
        assert len(result) == 2

    @pytest.mark.parametrize("data,expected", [
        (bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01]), 0x840A),
        (bytes([0x01, 0x06, 0x00, 0x01, 0x00, 0x17]), 0x9804),
        (bytes([0x11, 0x03, 0x00, 0x6B, 0x00, 0x03]), 0x7687),
    ])
    def test_multiple_known_vectors(self, data, expected):
        assert crc16_modbus(data) == struct.pack('>H', expected)


class TestDeviceProtocol:
    def test_legacy_json_cmd_true(self):
        cmd = DeviceProtocol.legacy_json_cmd('device1', True)
        assert cmd.endswith(b'\n')
        assert b'"device1": true' in cmd

    def test_legacy_json_cmd_false(self):
        cmd = DeviceProtocol.legacy_json_cmd('motor_fwd', False)
        assert b'"motor_fwd": false' in cmd

    def test_mingju_relay_cmd_on(self):
        cmd = DeviceProtocol.mingju_relay_cmd(1, True)
        assert len(cmd) == 8
        assert cmd[0] == 0x01  # slave addr
        assert cmd[1] == 0x05  # func code write single coil

    def test_mingju_relay_cmd_off(self):
        cmd = DeviceProtocol.mingju_relay_cmd(2, False)
        assert len(cmd) == 8
        assert cmd[0] == 0x01

    def test_groups_modbus_tcp_cmd_structure(self):
        cmd = DeviceProtocol.groups_modbus_tcp_cmd(0x0007, 1)
        assert len(cmd) == 12  # MBAP(7) + function(1) + addr(2) + value(2)
        assert cmd[0:2] == struct.pack('>H', 0x0001)  # transaction id

    def test_groups_modbus_tcp_cmd_zero(self):
        cmd = DeviceProtocol.groups_modbus_tcp_cmd(0x0000, 0)
        assert len(cmd) == 12

    def test_teacher_power_cmd_on_dc(self):
        cmd = DeviceProtocol.teacher_power_cmd(True, 22000, 2500, False)
        assert len(cmd) > 0
        assert cmd[0] == 0xA1  # DC slave address

    def test_teacher_power_cmd_off_defaults(self):
        cmd = DeviceProtocol.teacher_power_cmd(False)
        assert len(cmd) > 0

    def test_student_sync_cmd_on_structure(self):
        cmd = DeviceProtocol.student_sync_cmd(0xA1, True, False, 22000, 2500)
        assert len(cmd) > 0
        assert cmd[0] == 0xA1  # slave address

    def test_student_sync_cmd_off(self):
        cmd = DeviceProtocol.student_sync_cmd(0xA1, False)
        assert len(cmd) > 0

    def test_student_sync_broadcast_cmd(self):
        cmds = DeviceProtocol.student_sync_broadcast_cmd(22000, 2500, False, True)
        assert isinstance(cmds, list)
        assert len(cmds) >= 2  # at least A1 and A2

    def test_teacher_power_ac_mode(self):
        cmd = DeviceProtocol.teacher_power_cmd(True, 22000, 2500, True)
        assert len(cmd) > 0
