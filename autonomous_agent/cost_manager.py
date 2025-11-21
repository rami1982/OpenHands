import json
import os
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable, Dict, Optional

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Assuming RateLimitError is raised by the underlying LLM client
# Based on search, it's defined here:
from openhands.integrations.service_types import RateLimitError
from openhands.llm.llm import LLM

# Custom exceptions for the orchestrator
class BudgetExhaustedError(Exception):
    """Raised when the token budget for the period is exceeded."""
    def __init__(self, message, reset_time=None):
        super().__init__(message)
        self.reset_time = reset_time

class ExtendedRateLimitError(Exception):
    """Raised when retries for a rate limit error have been exhausted."""
    pass

class TokenCostManager:
    """
    Manages API budget, tracks token usage, and handles transient LLM rate limits.
    """
    def __init__(
        self,
        config: Dict[str, Any],
        state_file: str = "autonomous_agent_state.json",
    ):
        self.budget_period = config.get("budget_period", "monthly")
        self.token_budget = float(config.get("token_budget", 1000000))
        self.cost_per_1000_tokens = float(config.get("cost_per_1000_tokens", 0.03))
        self.state_file = state_file

        # Rate limit retry settings
        self.retry_multiplier = int(config.get("retry_multiplier", 1))
        self.retry_min_wait = int(config.get("retry_min_wait", 4))
        self.retry_max_wait = int(config.get("retry_max_wait", 60))
        self.max_retries = int(config.get("max_retries", 5))

        self.state = self._load_state()

    def _load_state(self) -> Dict:
        """Loads the manager's state from a file."""
        if os.path.exists(self.state_file):
            with open(self.state_file, "r") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    pass
        return self._get_initial_state()

    def _save_state(self):
        """Saves the current state to the file."""
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=4)

    def _get_initial_state(self) -> Dict:
        """Returns the initial state structure."""
        return {
            "current_period_start": self._get_period_start().isoformat(),
            "tokens_used_this_period": 0,
            "cost_this_period": 0.0,
        }
    
    def _get_period_start(self, now: Optional[datetime] = None) -> datetime:
        """Calculates the start of the current budget period."""
        now = now or datetime.utcnow()
        if self.budget_period == "daily":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if self.budget_period == "hourly":
            return now.replace(minute=0, second=0, microsecond=0)
        # Default to monthly
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def _get_period_end(self, period_start: datetime) -> datetime:
        if self.budget_period == 'hourly':
            return period_start + timedelta(hours=1)
        if self.budget_period == 'daily':
            return period_start + timedelta(days=1)
        # Monthly
        next_month = period_start.replace(day=28) + timedelta(days=4)  # Go to next month
        return next_month.replace(day=1)


    def _reset_if_new_period(self):
        """Resets the token and cost tracking if a new budget period has started."""
        period_start_dt = datetime.fromisoformat(self.state["current_period_start"])
        if datetime.utcnow() >= self._get_period_end(period_start_dt):
            self.state = self._get_initial_state()
            self._save_state()

    def check_and_record_usage(self, tokens: int):
        """
        Checks if the requested tokens are within budget and records the usage.

        Args:
            tokens: The number of tokens about to be used.

        Raises:
            BudgetExhaustedError: If the usage would exceed the configured budget.
        """
        self._reset_if_new_period()

        if self.token_budget > 0 and (self.state["tokens_used_this_period"] + tokens) > self.token_budget:
            period_start = datetime.fromisoformat(self.state["current_period_start"])
            reset_time = self._get_period_end(period_start)
            raise BudgetExhaustedError(
                f"Budget exhausted. Attempting to use {tokens} tokens, but only "
                f"{self.token_budget - self.state['tokens_used_this_period']} remaining.",
                reset_time=reset_time
            )

        cost = (tokens / 1000) * self.cost_per_1000_tokens
        self.state["tokens_used_this_period"] += tokens
        self.state["cost_this_period"] += cost
        self._save_state()
        print(f"Tokens used: {tokens}. Total for period: {self.state['tokens_used_this_period']}. Cost: ${cost:.4f}")

    def get_wrapped_llm_client(self, original_llm: LLM) -> LLM:
        """
        Returns a new LLM instance where the 'completion' method is wrapped
        with budget checks and rate limit handling.
        """
        
        original_completion = original_llm.completion

        @retry(
            wait=wait_exponential(multiplier=self.retry_multiplier, min=self.retry_min_wait, max=self.retry_max_wait),
            stop=stop_after_attempt(self.max_retries),
            retry=retry_if_exception_type(RateLimitError),
            reraise=True # re-raise the exception if the retries fail
        )
        @wraps(original_completion)
        def wrapped_completion(*args, **kwargs):
            # Estimate prompt tokens for proactive check. This is a rough heuristic.
            messages = kwargs.get("messages", [])
            estimated_prompt_tokens = int(len(str(messages)) / 4)

            try:
                # 1. Proactive Budget Check on estimated prompt tokens
                self.check_and_record_usage(estimated_prompt_tokens)

                # 2. Call the original LLM method
                response = original_completion(*args, **kwargs)

                # 3. Get actual token counts from the response
                usage = response.get("usage", {})
                actual_prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)

                # 4. Adjust usage based on actuals
                # We've already recorded the estimated prompt tokens.
                # We need to account for the difference and the completion tokens.
                adjustment = (actual_prompt_tokens - estimated_prompt_tokens) + completion_tokens
                if adjustment != 0:
                    self.check_and_record_usage(adjustment)

                return response

            except RateLimitError as e:
                print(f"Rate limit error encountered. Retrying... ({e})")
                # Before retrying, we should undo the recorded usage
                self.check_and_record_usage(-estimated_prompt_tokens)
                raise  # Re-raise for tenacity to handle
            except BudgetExhaustedError:
                 # If the proactive check fails, undo the recorded usage before raising
                self.check_and_record_usage(-estimated_prompt_tokens)
                raise
            except Exception as e:
                # For any other exception, also undo the recorded usage
                self.check_and_record_usage(-estimated_prompt_tokens)
                raise


        # We need to create a new LLM or modify the existing one.
        # Let's try to replace the method on the original llm object.
        original_llm.completion = wrapped_completion
        return original_llm
