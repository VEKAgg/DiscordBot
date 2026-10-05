"""Tests for src/core/runtime_state.py — tracking cogs, errors, recovery."""

from __future__ import annotations

from datetime import UTC, datetime

from src.core.runtime_state import RuntimeState


class TestRuntimeStateTracking:
    def test_loaded_cogs_default_empty(self):
        state = RuntimeState()
        assert state.loaded_cogs == []

    def test_failed_cogs_default_empty(self):
        state = RuntimeState()
        assert state.failed_cogs == []

    def test_degraded_features_default_empty(self):
        state = RuntimeState()
        assert state.degraded_features == []

    def test_load_cog(self):
        state = RuntimeState()
        state.loaded_cogs.append('src.cogs.admin.basic')
        assert 'src.cogs.admin.basic' in state.loaded_cogs

    def test_fail_cog(self):
        state = RuntimeState()
        state.failed_cogs.append('src.cogs.radio.radio')
        assert 'src.cogs.radio.radio' in state.failed_cogs

    def test_degraded_feature(self):
        state = RuntimeState()
        state.degraded_features.append('database')
        assert 'database' in state.degraded_features


class TestDbErrorTracking:
    def test_last_db_error_default_none(self):
        state = RuntimeState()
        assert state.last_db_error is None

    def test_set_last_db_error(self):
        state = RuntimeState()
        state.last_db_error = 'ConnectionRefused: host unreachable'
        assert state.last_db_error == 'ConnectionRefused: host unreachable'

    def test_clear_db_error(self):
        state = RuntimeState()
        state.last_db_error = 'some error'
        state.clear_db_error()
        assert state.last_db_error is None

    def test_clear_when_already_none(self):
        state = RuntimeState()
        state.clear_db_error()
        assert state.last_db_error is None


class TestRecoveryTime:
    def test_last_recovery_time_default_none(self):
        state = RuntimeState()
        assert state.last_recovery_time is None

    def test_set_recovery_time(self):
        state = RuntimeState()
        now = datetime.now(UTC)
        state.last_recovery_time = now
        assert state.last_recovery_time == now


class TestAlertStateCache:
    def test_cache_default_empty(self):
        state = RuntimeState()
        assert state.alert_state_cache == {}

    def test_cache_mixed_data(self):
        state = RuntimeState()
        state.alert_state_cache['task_fail:rss'] = 3
        state.alert_state_cache['healthy_count'] = 1
        assert state.alert_state_cache['task_fail:rss'] == 3
        assert state.alert_state_cache['healthy_count'] == 1

    def test_cache_clear(self):
        state = RuntimeState()
        state.alert_state_cache['key'] = 'value'
        state.alert_state_cache.clear()
        assert state.alert_state_cache == {}
