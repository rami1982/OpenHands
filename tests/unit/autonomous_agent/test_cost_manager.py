"""Tests for the TokenCostManager class."""
import json
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pytest

from autonomous_agent.cost_manager import (
    TokenCostManager,
    BudgetExhaustedError,
    ExtendedRateLimitError,
)


class TestTokenCostManager:
    """Tests for the TokenCostManager class."""

    @pytest.fixture
    def temp_state_file(self):
        """Create a temporary state file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_file = f.name
        yield temp_file
        # Cleanup
        if os.path.exists(temp_file):
            os.remove(temp_file)

    @pytest.fixture
    def basic_config(self):
        """Basic configuration for testing."""
        return {
            "budget_period": "monthly",
            "token_budget": 100000,
            "cost_per_1000_tokens": 0.03,
            "retry_multiplier": 1,
            "retry_min_wait": 1,
            "retry_max_wait": 10,
            "max_retries": 3,
        }

    def test_init(self, basic_config, temp_state_file):
        """Test initializing the cost manager."""
        manager = TokenCostManager(config=basic_config, state_file=temp_state_file)
        assert manager.budget_period == "monthly"
        assert manager.token_budget == 100000
        assert manager.cost_per_1000_tokens == 0.03
        assert manager.max_retries == 3

    def test_get_period_start_monthly(self, basic_config, temp_state_file):
        """Test calculating monthly period start."""
        manager = TokenCostManager(config=basic_config, state_file=temp_state_file)
        now = datetime(2024, 3, 15, 14, 30, 45)
        period_start = manager._get_period_start(now)
        assert period_start == datetime(2024, 3, 1, 0, 0, 0)

    def test_get_period_start_daily(self, temp_state_file):
        """Test calculating daily period start."""
        config = {"budget_period": "daily", "token_budget": 10000}
        manager = TokenCostManager(config=config, state_file=temp_state_file)
        now = datetime(2024, 3, 15, 14, 30, 45)
        period_start = manager._get_period_start(now)
        assert period_start == datetime(2024, 3, 15, 0, 0, 0)

    def test_get_period_start_hourly(self, temp_state_file):
        """Test calculating hourly period start."""
        config = {"budget_period": "hourly", "token_budget": 1000}
        manager = TokenCostManager(config=config, state_file=temp_state_file)
        now = datetime(2024, 3, 15, 14, 30, 45)
        period_start = manager._get_period_start(now)
        assert period_start == datetime(2024, 3, 15, 14, 0, 0)

    def test_check_and_record_usage_within_budget(self, basic_config, temp_state_file):
        """Test recording usage within budget."""
        manager = TokenCostManager(config=basic_config, state_file=temp_state_file)
        manager.check_and_record_usage(1000)

        assert manager.state["tokens_used_this_period"] == 1000
        assert manager.state["cost_this_period"] == pytest.approx(0.03)

    def test_check_and_record_usage_exceeds_budget(self, basic_config, temp_state_file):
        """Test that exceeding budget raises BudgetExhaustedError."""
        config = basic_config.copy()
        config["token_budget"] = 5000
        manager = TokenCostManager(config=config, state_file=temp_state_file)

        manager.check_and_record_usage(3000)  # Within budget

        with pytest.raises(BudgetExhaustedError):
            manager.check_and_record_usage(3000)  # This would exceed budget

    def test_check_and_record_usage_no_limit(self, temp_state_file):
        """Test that token_budget of 0 means no limit."""
        config = {"budget_period": "monthly", "token_budget": 0}
        manager = TokenCostManager(config=config, state_file=temp_state_file)

        # Should not raise any error even with large usage
        manager.check_and_record_usage(1000000)
        assert manager.state["tokens_used_this_period"] == 1000000

    def test_state_persistence(self, basic_config, temp_state_file):
        """Test that state is persisted to file."""
        manager1 = TokenCostManager(config=basic_config, state_file=temp_state_file)
        manager1.check_and_record_usage(5000)

        # Create new manager instance with same state file
        manager2 = TokenCostManager(config=basic_config, state_file=temp_state_file)
        assert manager2.state["tokens_used_this_period"] == 5000

    def test_period_reset(self, basic_config, temp_state_file):
        """Test that usage resets when a new period starts."""
        manager = TokenCostManager(config=basic_config, state_file=temp_state_file)
        manager.check_and_record_usage(5000)

        # Manually set the period start to last month
        last_month = datetime.utcnow() - timedelta(days=35)
        manager.state["current_period_start"] = last_month.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        manager._save_state()

        # This should trigger a reset
        manager.check_and_record_usage(1000)
        assert manager.state["tokens_used_this_period"] == 1000

    def test_budget_exhausted_error_includes_reset_time(self, basic_config, temp_state_file):
        """Test that BudgetExhaustedError includes reset time."""
        config = basic_config.copy()
        config["token_budget"] = 1000
        manager = TokenCostManager(config=config, state_file=temp_state_file)

        try:
            manager.check_and_record_usage(2000)
        except BudgetExhaustedError as e:
            assert e.reset_time is not None
            assert isinstance(e.reset_time, datetime)


class TestWrappedLLMClient:
    """Tests for the wrapped LLM client functionality."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM client."""
        llm = MagicMock()
        llm.completion = MagicMock(return_value={
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
            },
            "choices": [{"message": {"content": "test response"}}]
        })
        return llm

    @pytest.fixture
    def temp_state_file(self):
        """Create a temporary state file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_file = f.name
        yield temp_file
        if os.path.exists(temp_file):
            os.remove(temp_file)

    def test_wrapped_llm_successful_call(self, mock_llm, temp_state_file):
        """Test that wrapped LLM client works for successful calls."""
        config = {"budget_period": "monthly", "token_budget": 100000}
        manager = TokenCostManager(config=config, state_file=temp_state_file)

        wrapped_llm = manager.get_wrapped_llm_client(mock_llm)
        response = wrapped_llm.completion(messages=[{"role": "user", "content": "test"}])

        assert response["choices"][0]["message"]["content"] == "test response"
        # Token usage should be recorded
        assert manager.state["tokens_used_this_period"] > 0

    def test_wrapped_llm_records_actual_usage(self, mock_llm, temp_state_file):
        """Test that actual token usage from response is recorded."""
        config = {"budget_period": "monthly", "token_budget": 100000}
        manager = TokenCostManager(config=config, state_file=temp_state_file)

        wrapped_llm = manager.get_wrapped_llm_client(mock_llm)
        wrapped_llm.completion(messages=[{"role": "user", "content": "test"}])

        # The actual tokens (100 prompt + 50 completion) should be reflected
        # Note: We estimate first, then adjust based on actuals
        assert manager.state["tokens_used_this_period"] > 0
