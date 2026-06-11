"""Unit tests for backend/app/protocol_485.py — frame builders."""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
from app.protocol_485 import (
    build_computer_frame,
    build_lifting_frame,
    build_lowxstb_frame,
    build_vfd_power_frame,
    build_vfd_speed_frame,
)


class TestComputerLiftingFrames:
    def test_computer_on(self):
        frame = build_computer_frame(True)
        assert isinstance(frame, bytes)
        assert len(frame) > 0
        assert b'"device1": true' in frame

    def test_computer_off(self):
        frame = build_computer_frame(False)
        assert b'"device1": false' in frame

    def test_lifting_up(self):
        frame = build_lifting_frame('up')
        assert isinstance(frame, bytes)
        assert b'"motor_fwd": true' in frame

    def test_lifting_down(self):
        frame = build_lifting_frame('down')
        assert b'"motor_bwd": true' in frame

    def test_lifting_stop(self):
        frame = build_lifting_frame('stop')
        assert b'"motor_fwd": false' in frame
        assert b'"motor_bwd": false' in frame

    def test_lifting_bool_true_is_up(self):
        frame = build_lifting_frame(True)
        assert b'"motor_fwd": true' in frame

    def test_lifting_bool_false_is_down(self):
        frame = build_lifting_frame(False)
        assert b'"motor_bwd": true' in frame


class TestLowXSTBFrame:
    def test_sync_on_dc(self):
        state = {'LowDC_AC': 0, 'LowDYSZ': 220, 'LowDLSZ': 2.5}
        frame = build_lowxstb_frame(state, True)
        assert isinstance(frame, bytes)
        assert len(frame) > 0
        assert frame[0] == 0xA1  # DC slave address

    def test_sync_on_ac(self):
        state = {'LowDC_AC': 1, 'LowDYSZ': 220, 'LowDLSZ': 3.0}
        frame = build_lowxstb_frame(state, True)
        assert frame[0] == 0xA2  # AC slave address

    def test_sync_off(self):
        state = {'LowDC_AC': 0, 'LowDYSZ': 0, 'LowDLSZ': 0}
        frame = build_lowxstb_frame(state, False)
        assert len(frame) > 0

    def test_default_values_when_missing(self):
        state = {}
        frame = build_lowxstb_frame(state, True)
        assert isinstance(frame, bytes)
        assert frame[0] == 0xA1


class TestVFDFrames:
    def test_vfd_power_on(self):
        frame = build_vfd_power_frame(True, 1, 0x2000)
        assert len(frame) == 8
        assert frame[0] == 0x01  # slave
        assert frame[1] == 0x06  # write single register

    def test_vfd_power_off(self):
        frame = build_vfd_power_frame(False, 2, 0x2000)
        assert len(frame) == 8

    def test_vfd_speed_default_map(self):
        frame = build_vfd_speed_frame('1', 1, 0x2001, {'1': 10, '2': 20, '3': 30})
        assert len(frame) == 8
        assert frame[1] == 0x06

    def test_vfd_speed_unknown_key_fallback(self):
        frame = build_vfd_speed_frame('99', 1, 0x2001, {'1': 10})
        assert len(frame) == 8
