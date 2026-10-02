from app.core.settings import get_settings, Settings


def test_default_strategy_is_dual_write():
    s = Settings(_env_file=None)
    assert s.order_sync_strategy == "dual_write"


def test_strategy_is_locked_to_dual_write(monkeypatch):
    """Strategy B is out of scope. `polling` must be rejected outright, not accepted."""
    import pytest
    from pydantic import ValidationError

    monkeypatch.setenv("ORDER_SYNC_STRATEGY", "polling")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError):
            get_settings()
    finally:
        monkeypatch.delenv("ORDER_SYNC_STRATEGY", raising=False)
        get_settings.cache_clear()


def test_seed_anchor_date_default():
    assert get_settings().seed_anchor_date == "2026-09-30T00:00:00Z"
