from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import credit_billing


class _Query:
    def __init__(self, runs):
        self.runs = runs

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def limit(self, value):
        self.runs = self.runs[:value]
        return self

    def all(self):
        return self.runs


class _DB:
    def __init__(self, runs):
        self.runs = runs

    def query(self, model):
        assert model is credit_billing.AgentRun
        return _Query(list(self.runs))


def test_point_value_normalizes_to_two_decimal_places():
    assert credit_billing.point_value(None) == Decimal("0.00")
    assert credit_billing.point_value("1.235") == Decimal("1.24")


def test_calculate_points_rounds_nonzero_usage_up():
    pricing = SimpleNamespace(
        input_rate=2,
        output_rate=5,
        cache_read_rate=1,
        cache_creation_rate=3,
        rate_scale=1000,
    )

    assert credit_billing.calculate_points({"input_tokens": 1}, pricing) == Decimal("0.01")
    assert credit_billing.calculate_points({"input_tokens": 500}, pricing) == Decimal("1.00")
    assert credit_billing.calculate_points({"output_tokens": 201}, pricing) == Decimal("1.01")
    assert credit_billing.calculate_points({}, pricing) == Decimal("0.00")


def test_reconcile_pending_runs_retries_and_counts_completed_settlements():
    runs = [
        SimpleNamespace(id="run-1", user_id=7, status="cancelled", settlement_status="pending_reconciliation"),
        SimpleNamespace(id="run-2", user_id=7, status="succeeded", settlement_status="pending_reconciliation"),
        SimpleNamespace(
            id="run-3",
            user_id=7,
            status="failed",
            settlement_status="reserved",
            finished_at=datetime.now(timezone.utc),
        ),
    ]

    def settle(_db, run, _status):
        if run.id == "run-1":
            run.settlement_status = "settled"

    with patch.object(credit_billing, "settle_platform_run", side_effect=settle) as mocked:
        settled = credit_billing.reconcile_pending_platform_runs(
            _DB(runs), user_id=7, limit=20
        )

    assert settled == 1
    assert mocked.call_count == 3


if __name__ == "__main__":
    test_point_value_normalizes_to_two_decimal_places()
    test_calculate_points_rounds_nonzero_usage_up()
    test_reconcile_pending_runs_retries_and_counts_completed_settlements()
    print("credit billing tests passed")
