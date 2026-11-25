import unittest
import os
from datetime import datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import cast, create_engine
from sqlalchemy.dialects.mysql import CHAR
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql import visitors

import credit_dashboard_routes as reporting
from auth import CurrentUser, get_current_active_user
from database import get_db
from database import SessionLocal
from models import AIModel, AgentRun, AgentSession, CreditAccount, CreditLedger, ModelRunCredential


class CreditDashboardTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        for model in (AIModel, AgentRun, AgentSession, CreditAccount, CreditLedger, ModelRunCredential):
            model.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.db.add_all([
            AIModel(id=1, user_id=7, name="Historic model", provider="test", is_deleted=True),
            AgentSession(id=1, agent_id=1, user_id=7, title="Session", model_id=99, is_deleted=True),
            CreditAccount(id=1, user_id=7, available_balance=97, reserved_balance=100),
            CreditAccount(id=2, user_id=8, available_balance=50, reserved_balance=0),
        ])
        self.start, self.end = reporting._period("custom", "2026-09-08", "2026-09-08")
        # Settled just after midnight in Beijing, though the run started the previous day.
        self.add_run("old", 7, "settled", 3, datetime(2026, 9, 7, 16, 1), status="failed")
        self.add_run("other", 8, "settled", 5, datetime(2026, 9, 7, 18))
        self.add_run("pending", 7, "pending_reconciliation", 0, None)
        self.add_run("before", 7, "settled", 9, datetime(2026, 9, 7, 15, 59))
        self.add_run("after", 7, "settled", 11, datetime(2026, 9, 8, 16))
        for entry_type, amount in (("initial_claim", 200), ("daily_claim", 100),
                                   ("admin_adjustment", 20), ("admin_adjustment", -5),
                                   ("run_reservation", -100)):
            self.add_ledger(7, entry_type, amount, datetime(2026, 9, 7, 17))
        self.db.commit()
        app = FastAPI()
        app.include_router(reporting.personal_router)
        app.include_router(reporting.summary_router)
        self.user = CurrentUser(user_id=7)
        app.dependency_overrides[get_current_active_user] = lambda: self.user
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def add_ledger(self, user_id, kind, amount, at, run_id=None):
        identity = self.db.query(CreditLedger).count() + len([row for row in self.db.new if isinstance(row, CreditLedger)]) + 1
        self.db.add(CreditLedger(id=identity, user_id=user_id, entry_type=kind, amount=amount,
                                 available_after=97, reserved_after=0, run_id=run_id,
                                 business_key=f"entry-{identity}", created_at=at))

    def add_run(self, run_id, user_id, settlement, charged, at, status="succeeded"):
        self.db.add(AgentRun(id=run_id, agent_id=1, session_id=1, user_id=user_id,
                             status=status, settlement_status=settlement, reserved_points=100,
                             charged_points=charged, created_at=datetime(2026, 9, 7, 16) if not at else datetime(2026, 9, 7, 12)))
        count = self.db.query(ModelRunCredential).count() + 1
        self.db.add(ModelRunCredential(id=count, run_id=run_id, user_id=user_id, model_id=1,
                                       pricing_version_id=1, token_hash=run_id, max_points=100,
                                       expires_at=datetime(2027, 1, 1)))
        if at:
            self.add_ledger(user_id, "run_settlement", 100 - charged, at, run_id)
        self.db.flush()

    def usage(self, user_id=7, granularity="day"):
        return reporting.build_usage(self.db, user_id, self.start, self.end, granularity)

    def test_consumption_uses_actual_charge_not_reserved_or_returned_amount(self):
        result = self.usage()
        self.assertEqual(result["summary"]["consumed_points"], Decimal("3.00"))
        self.assertEqual(result["summary"]["claimed_points"], Decimal("300.00"))
        self.assertEqual(result["summary"]["adjustment_added"], Decimal("20.00"))
        self.assertEqual(result["summary"]["adjustment_deducted"], Decimal("5.00"))
        self.assertEqual(result["summary"]["reserved_balance"], Decimal("100.00"))
        self.assertEqual(result["summary"]["pending_runs"], 1)
        self.assertEqual(result["summary"]["run_count"], 1)

    def test_global_equals_sum_of_personal_and_preserves_historic_model(self):
        result = self.usage(None)
        self.assertEqual(result["summary"]["consumed_points"], self.usage(7)["summary"]["consumed_points"] + self.usage(8)["summary"]["consumed_points"])
        self.assertEqual(result["summary"]["active_users"], 2)
        self.assertEqual(result["summary"]["available_balance"], Decimal("147.00"))
        self.assertEqual(result["models"][0]["model_name"], "Historic model")
        self.assertEqual(result["models"][0]["consumed_points"], Decimal("8.00"))

    def test_trend_uses_beijing_settlement_date_and_fills_empty_buckets(self):
        for granularity, length in (("hour", 24), ("day", 1), ("week", 1)):
            trend = self.usage(granularity=granularity)["trend"]
            self.assertEqual(len(trend), length)
            self.assertEqual(sum(row["consumed_points"] for row in trend), Decimal("3.00"))
            self.assertEqual(sum(row["claimed_points"] for row in trend), Decimal("300.00"))
            self.assertTrue(trend[0]["bucket"].endswith("+08:00"))

    def test_pending_run_has_no_charge_and_failed_run_still_counts(self):
        result = reporting.build_runs(self.db, 7, self.start, self.end, 0, 16)
        self.assertEqual(result["total"], 2)
        entries = {row["run_id"]: row for row in result["items"]}
        self.assertIsNone(entries["pending"]["charged_points"])
        self.assertEqual(entries["old"]["status"], "failed")
        self.assertEqual(entries["old"]["charged_points"], Decimal("3.00"))
        self.assertEqual(entries["old"]["session_title"], "Session")

    def test_pagination_and_ledger_filter(self):
        first = reporting.build_runs(self.db, None, self.start, self.end, 0, 1)
        second = reporting.build_runs(self.db, None, self.start, self.end, 1, 1)
        self.assertEqual(first["total"], 3)
        self.assertNotEqual(first["items"][0]["run_id"], second["items"][0]["run_id"])
        ledger = reporting.build_ledger(self.db, 7, self.start, self.end, 0, 1, "admin_adjustment")
        self.assertEqual(ledger["total"], 2)
        self.assertEqual(len(ledger["items"]), 1)
        users = reporting.build_users(self.db, None, self.start, self.end, 0, 1)
        self.assertEqual(users["total"], 2)
        self.assertEqual(users["items"][0]["user_id"], 8)

    def test_empty_account_does_not_require_policy_or_sub2api(self):
        result = self.usage(999)
        self.assertEqual(result["summary"]["run_count"], 0)
        self.assertEqual(result["summary"]["consumed_points"], 0)
        self.assertEqual(result["summary"]["available_balance"], 0)
        self.assertEqual(result["models"], [])

    def test_api_scope_and_validation(self):
        params = {"period": "custom", "start_date": "2026-09-08", "end_date": "2026-09-08"}
        for suffix in ("", "/runs", "/ledger", "/users"):
            self.assertEqual(self.client.get(f"/api/dashboard/summary/credit-usage{suffix}", params=params).status_code, 403)
        for suffix in ("", "/runs", "/ledger"):
            url = f"/api/dashboard/personal/credit-usage{suffix}"
            self.assertEqual(self.client.get(url, params={**params, "user_id": 8}).status_code, 403)
            self.assertEqual(self.client.get(url, params=params).status_code, 200)
        self.assertEqual(self.client.get(
            "/api/dashboard/personal/credit-usage/runs",
            params={**params, "status": "metering"},
        ).status_code, 200)
        self.assertEqual(self.client.get(
            "/api/dashboard/personal/credit-usage/ledger",
            params={**params, "entry_type": "model_usage"},
        ).status_code, 200)
        self.user = CurrentUser(user_id=7, is_superuser=True)
        result = self.client.get("/api/dashboard/summary/credit-usage", params={**params, "user_id": 8})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(Decimal(str(result.json()["summary"]["consumed_points"])), Decimal("5.00"))
        self.assertEqual(self.client.get("/api/dashboard/personal/credit-usage/runs", params={**params, "limit": 0}).status_code, 422)
        self.assertEqual(self.client.get("/api/dashboard/personal/credit-usage", params={**params, "start_date": "bad"}).status_code, 400)


@unittest.skipUnless(os.environ.get("AIHUB_TEST_MYSQL") == "1", "Set AIHUB_TEST_MYSQL=1 for read-only MySQL integration checks")
class CreditDashboardMySQLTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        if self.db.bind.dialect.name not in {"mysql", "mariadb"}:
            self.skipTest("MySQL database required")
        self.start, self.end = reporting._period("7d", None, None)

    def check_scope(self, user_id):
        for granularity in ("hour", "day", "week"):
            usage = reporting.build_usage(self.db, user_id, self.start, self.end, granularity)
            self.assertEqual(sum(item["consumed_points"] for item in usage["trend"]), usage["summary"]["consumed_points"])
        runs = reporting.build_runs(self.db, user_id, self.start, self.end, 0, 16, "settled")
        self.assertEqual(runs["total"], usage["summary"]["run_count"])
        ledger = reporting.build_ledger(self.db, user_id, self.start, self.end, 0, 16)
        self.assertGreaterEqual(ledger["total"], len(ledger["items"]))
        users = reporting.build_users(self.db, user_id, self.start, self.end, 0, 16)
        self.assertGreaterEqual(users["total"], len(users["items"]))

    def test_personal_queries_with_actual_mysql_collations(self):
        account = self.db.query(CreditAccount.user_id).order_by(CreditAccount.user_id).first()
        self.check_scope(account[0] if account else 1)

    def test_global_queries_with_actual_mysql_collations(self):
        self.check_scope(None)

    def test_run_joins_accept_ascii_and_utf8mb4_ids(self):
        for charset, collation in (("ascii", "ascii_bin"), ("utf8mb4", "utf8mb4_general_ci")):
            with self.subTest(charset=charset):
                # Simulate legacy column encodings in a read-only query, without ALTER TABLE.
                def encoded_run_id(element):
                    if getattr(element, "table", None) is AgentRun.__table__ and getattr(element, "name", None) == "id":
                        return cast(element, CHAR(32, charset=charset)).collate(collation)

                statement = visitors.replacement_traverse(
                    reporting._runs(self.db, None).select().limit(0), {}, encoded_run_id,
                )
                sql = str(statement.compile(dialect=self.db.bind.dialect))
                self.assertIn(f"CHARACTER SET {charset}", sql)
                self.assertEqual(self.db.execute(statement).all(), [])


if __name__ == "__main__":
    unittest.main()
