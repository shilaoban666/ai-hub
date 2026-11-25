import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import knowledge_routes as kr
from auth import CurrentUser, get_current_active_user
from database import get_db
from knowledge_clients import KnowledgeServiceError, estimate_tokens, sign_acs3
from knowledge_models import (
    KnowledgeCallHit, KnowledgeCallLog, KnowledgeDingtalkIdentity, KnowledgeDocLink, KnowledgeSettings,
    KnowledgeUpload,
)

TABLES = (KnowledgeSettings, KnowledgeDingtalkIdentity, KnowledgeUpload, KnowledgeCallLog, KnowledgeCallHit,
          KnowledgeDocLink)


class FakeBailian:
    def __init__(self, parse_status="PARSE_SUCCESS", job_status="COMPLETED", fail_lease=False):
        self.parse_status, self.job_status, self.fail_lease = parse_status, job_status, fail_lease
        self.calls = []

    def apply_upload_lease(self, category_id, name, md5, size):
        self.calls.append(("lease", category_id, name, size))
        if self.fail_lease:
            raise KnowledgeServiceError("百炼接口错误（Forbidden）")
        return {"FileUploadLeaseId": "lease-1", "Param": {"Url": "https://oss/x", "Method": "PUT"}}

    def put_to_lease(self, lease, path):
        self.calls.append(("put", os.path.exists(path)))

    def add_file(self, lease_id, category_id):
        return {"FileId": "file_1"}

    def describe_file(self, file_id):
        return {"Status": self.parse_status}

    def add_documents_to_index(self, index_id, ids):
        self.calls.append(("index", index_id, tuple(ids)))
        return {"Id": "job-1"}

    def index_job_status(self, index_id, job_id):
        return {"Status": self.job_status}

    def retrieve(self, index_id, query, rerank_top_n=5):
        return {"Nodes": [{"Score": 0.9, "Text": "报销需要在三十天内提交", "Metadata": {"doc_name": "报销制度"}},
                          {"Score": 0.5, "Text": "", "Metadata": {"doc_name": "报销制度"}}]}

    def delete_index_document(self, index_id, ids):
        self.calls.append(("unindex", index_id, tuple(ids)))

    def delete_file(self, file_id):
        self.calls.append(("delete_file", file_id))

    def list_index_documents(self, index_id, page, page_size, name):
        return {"TotalCount": 2, "Documents": [{"Id": "file_1", "Name": "a.txt", "Status": "FINISH"},
                                               {"Id": "file_2", "Name": "b.txt", "Status": "FINISH"}]}


class FakeDingtalk:
    def __init__(self, fail=False):
        self.fail, self.uploaded = fail, []

    def upload_file(self, union_id, folder, path, name, size):
        if self.fail:
            raise KnowledgeServiceError("钉钉接口错误（403）")
        self.uploaded.append((union_id, folder, name, size))
        return {"id": "dentry-9", "uuid": "uuid-9"}

    def upload_to_space(self, union_id, space_id, parent_id, path, name, size, parent_uuid=None):
        self.parent_uuid = parent_uuid
        if self.fail:
            raise KnowledgeServiceError("钉钉接口错误（403）")
        self.uploaded.append((union_id, f"{space_id}/{parent_id}", name, size))
        return {"id": "dentry-9", "uuid": "uuid-9"}

    def delete_dentry(self, union_id, space_id, dentry_id):
        self.deleted = (union_id, space_id, dentry_id)

    def list_team_spaces(self, union_id):
        return [{"spaceId": "s1", "spaceName": "全员文件夹", "spaceType": "org"}, {"spaceName": "无 id"}]

    resolved_type = "FOLDER"
    resolved_status = "NORMAL"

    def resolve_dentry(self, union_id, dentry_uuid):
        return {"space_id": "s1", "dentry_id": "9", "uuid": dentry_uuid, "name": "群公告",
                "path": "/历史归档/群公告", "type": self.resolved_type,
                "status": self.resolved_status}

    def list_space_folders(self, union_id, space_id, parent_id):
        self.listed = (union_id, space_id, parent_id)
        return [{"id": "42", "uuid": "u42", "name": "表单台账", "type": "FOLDER"}]

    def node_url(self, union_id, node_uuid):
        return f"https://alidocs.dingtalk.com/i/nodes/{node_uuid}"


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        for table in TABLES:
            table.__table__.create(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        app = FastAPI()
        app.include_router(kr.router)
        app.include_router(kr.usage_router)
        self.user = CurrentUser(user_id=7, is_superuser=True)
        app.dependency_overrides[get_current_active_user] = lambda: self.user
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        patcher = mock.patch.object(kr, "POLL_INTERVAL_SECONDS", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        kr._doc_list_cache.clear()  # module-level cache of index document lists
        kr._access_cache.clear()
        # Department lookups call IAM; by default nobody belongs to any department.
        self.departments = {}
        dept = mock.patch.object(kr, "load_departments",
                                 side_effect=lambda ids, auth: {i: self.departments.get(i, ()) for i in ids})
        dept.start()
        self.addCleanup(dept.stop)
        # Background link lookups would open real database sessions; tests that need them run them inline.
        links = mock.patch.object(kr, "_start_link_lookup")
        links.start()
        self.addCleanup(links.stop)

    def _row(self, **values):
        row = KnowledgeUpload(user_id=7, index_id="idx", category_id="cate", file_name="a.txt",
                              file_size=3, status="uploading", **values)
        self.db.add(row)
        self.db.commit()
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        handle.write(b"abc")
        handle.close()
        return row.id, handle.name

    def _run(self, upload_id, path, bailian, dingtalk=None):
        kr.process_upload(upload_id, path, session_factory=self.Session,
                          bailian_factory=lambda db: bailian, dingtalk_factory=lambda db: dingtalk or FakeDingtalk())
        self.db.expire_all()
        return self.db.get(KnowledgeUpload, upload_id)

    def test_acs3_signature_matches_official_example(self):
        headers = sign_acs3(
            method="POST", host="ecs.cn-shanghai.aliyuncs.com", path="/",
            query={"ImageId": "win2019_1809_x64_dtc_zh-cn_40G_alibase_20230811.vhd", "RegionId": "cn-shanghai"},
            headers={"x-acs-action": "RunInstances", "x-acs-version": "2014-05-26",
                     "x-acs-date": "2023-10-26T10:22:32Z",
                     "x-acs-signature-nonce": "3156853299f313e23d1673dc12e1703d"},
            body=b"", access_key_id="YourAccessKeyId", access_key_secret="YourAccessKeySecret")
        self.assertTrue(headers["authorization"].endswith(
            "Signature=06563a9e1b43f5dfe96b81484da74bceab24a1d853912eee15083a6f0f3283c0"))

    def test_bailian_throttling_is_retried_then_succeeds(self):
        import httpx
        import knowledge_clients as kc
        replies = iter([
            httpx.Response(429, json={"Code": "Throttling.Api", "Message": "flow control"}),
            httpx.Response(200, json={"Success": True, "Data": {"TotalCount": 1, "Documents": []}}),
        ])
        seen = []

        def handler(request):
            seen.append(request.headers["x-acs-signature-nonce"])
            return next(replies)

        client = kc.BailianClient(endpoint="bailian.example", access_key_id="ak", access_key_secret="sk",
                                  workspace_id="ws", transport=httpx.MockTransport(handler))
        with mock.patch.object(kc, "THROTTLE_BACKOFF_SECONDS", 0):
            self.assertEqual(client.list_index_documents("idx")["TotalCount"], 1)
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0], seen[1], "each retry is signed afresh")

    def test_startup_schema_upgrade_is_idempotent_and_never_raises(self):
        from sqlalchemy import inspect, text
        import knowledge_models as km
        old = create_engine("sqlite://", poolclass=StaticPool)
        with old.begin() as connection:  # tables as first shipped, before the late columns
            connection.execute(text("CREATE TABLE knowledge_call_logs (id INTEGER PRIMARY KEY, query TEXT)"))
            connection.execute(text("CREATE TABLE knowledge_settings (id INTEGER PRIMARY KEY)"))
        km.ensure_schema(old)
        km.ensure_schema(old)  # second start: nothing left to do
        columns = {column["name"] for column in inspect(old).get_columns("knowledge_call_logs")}
        self.assertTrue({"external_id", "session_id"} <= columns)
        self.assertIn("uq_knowledge_calls_external", {i["name"] for i in inspect(old).get_indexes("knowledge_call_logs")})
        self.assertIn("upload_departments", {c["name"] for c in inspect(old).get_columns("knowledge_settings")})
        from sqlalchemy.exc import OperationalError
        broken = mock.Mock()
        broken.begin.side_effect = OperationalError("ALTER", {}, Exception("ALTER command denied"))
        with mock.patch("sqlalchemy.inspect", return_value=mock.Mock(has_table=lambda t: True,
                                                                    get_columns=lambda t: [])):
            km.ensure_schema(broken)  # logged, not raised: AI Hub still starts

    def test_token_estimate_counts_cjk_per_char(self):
        self.assertEqual(estimate_tokens("报销流程"), 4)
        self.assertEqual(estimate_tokens("abcdefgh"), 2)
        self.assertEqual(estimate_tokens(None), 0)

    def test_upload_pipeline_completes_and_syncs_dingtalk(self):
        self.db.add(KnowledgeDingtalkIdentity(user_id=7, union_id="union-7"))
        upload_id, path = self._row(sync_dingtalk=True, dingtalk_folder_id="folder-1", dingtalk_status="pending")
        dingtalk = FakeDingtalk()
        row = self._run(upload_id, path, FakeBailian(), dingtalk)
        self.assertEqual((row.status, row.bailian_file_id, row.bailian_job_id), ("completed", "file_1", "job-1"))
        self.assertEqual((row.dingtalk_status, row.dingtalk_dentry_id), ("success", "uuid-9"))
        self.assertEqual(row.dingtalk_url, "https://alidocs.dingtalk.com/i/nodes/uuid-9")
        self.assertEqual(dingtalk.uploaded, [("union-7", "folder-1", "a.txt", 3)])
        self.assertFalse(os.path.exists(path), "temp file must be removed")

    def test_team_files_picker_and_upload_use_drive_spaces(self):
        self.db.add(KnowledgeDingtalkIdentity(user_id=7, union_id="union-7"))
        self.db.commit()
        dingtalk = FakeDingtalk()
        with mock.patch.object(kr, "dingtalk_client", return_value=dingtalk):
            spaces = self.client.get("/api/knowledge/dingtalk/workspaces").json()["items"]
            self.assertEqual(spaces, [{"workspace_id": "s1", "root_node_id": "s1/0", "name": "全员文件夹", "type": "org"}])
            folders = self.client.get("/api/knowledge/dingtalk/folders?parent_node_id=s1/0").json()["items"]
            self.assertEqual(folders, [{"node_id": "s1/42/u42", "name": "表单台账", "has_children": True}])
            self.assertEqual(dingtalk.listed, ("union-7", "s1", "0"), "listed as the bound user")
            resolved = self.client.get("/api/knowledge/dingtalk/resolve-folder", params={
                "link": "https://alidocs.dingtalk.com/i/desktop/folders/G1DKw2zgV2zXoPYZTdwllgjQVB5r9YAn"}).json()
            self.assertEqual(resolved, {"node_id": "s1/9/G1DKw2zgV2zXoPYZTdwllgjQVB5r9YAn", "name": "群公告",
                                        "path": "全员文件夹 / 历史归档 / 群公告"})
            dingtalk.resolved_type = "FILE"
            not_folder = self.client.get("/api/knowledge/dingtalk/resolve-folder",
                                         params={"link": "https://alidocs.dingtalk.com/i/nodes/ABCDEFGH12345678"})
            self.assertEqual(not_folder.status_code, 400)
            dingtalk.resolved_type, dingtalk.resolved_status = "FOLDER", "DELETED"
            deleted = self.client.get("/api/knowledge/dingtalk/resolve-folder",
                                      params={"link": "https://alidocs.dingtalk.com/i/nodes/ABCDEFGH12345678"}).json()
            self.assertIn("已被删除", deleted["detail"])
            self.assertEqual(self.client.get("/api/knowledge/dingtalk/resolve-folder",
                                             params={"link": "not a link"}).status_code, 400)
        upload_id, path = self._row(sync_dingtalk=True, dingtalk_folder_id="s1/42/u42", dingtalk_status="pending")
        row = self._run(upload_id, path, FakeBailian(), dingtalk)
        self.assertEqual(row.dingtalk_status, "success")
        self.assertEqual(dingtalk.uploaded, [("union-7", "s1/42", "a.txt", 3)])
        self.assertEqual(dingtalk.parent_uuid, "u42", "uploads address the folder by its uuid")
        self.db.expire_all()
        recent = self.client.get("/api/knowledge/dingtalk/recent-folders").json()["items"]
        self.assertEqual(recent, [{"node_id": "s1/42/u42", "path": "s1/42/u42"}], "recent targets for one-click reuse")

    def test_delete_upload_removes_index_file_and_drive_copy(self):
        self.db.add(KnowledgeDingtalkIdentity(user_id=7, union_id="union-7"))
        self.db.commit()
        dingtalk, bailian = FakeDingtalk(), FakeBailian()
        upload_id, path = self._row(sync_dingtalk=True, dingtalk_folder_id="s1/42", dingtalk_status="pending")
        row = self._run(upload_id, path, bailian, dingtalk)
        self.assertEqual(row.dingtalk_dentry_id, "s1/dentry-9", "space uploads keep a deletable ref")
        other = self.Session()
        other.add(KnowledgeUpload(user_id=8, index_id="idx", category_id="c", file_name="x.txt", file_size=1,
                                  status="completed"))
        other.commit()
        foreign_id = other.query(KnowledgeUpload).filter_by(user_id=8).one().id
        other.close()
        with mock.patch.object(kr, "bailian_client", return_value=bailian), \
                mock.patch.object(kr, "dingtalk_client", return_value=dingtalk):
            self.assertEqual(self.client.delete(f"/api/knowledge/uploads/{foreign_id}").status_code, 404,
                             "only the uploader may delete")
            result = self.client.delete(f"/api/knowledge/uploads/{upload_id}").json()
        self.assertEqual(result["removed"], ["知识库", "百炼应用数据", "钉盘"])
        self.assertIn(("unindex", "idx", ("file_1",)), bailian.calls)
        self.assertIn(("delete_file", "file_1"), bailian.calls)
        self.assertEqual(dingtalk.deleted, ("union-7", "s1", "dentry-9"))
        self.db.expire_all()
        self.assertIsNone(self.db.get(KnowledgeUpload, upload_id))

    def test_drive_permission_denied_explains_what_to_do(self):
        self.db.add(KnowledgeDingtalkIdentity(user_id=7, union_id="union-7"))
        upload_id, path = self._row(sync_dingtalk=True, dingtalk_folder_id="s1/42", dingtalk_status="pending")
        denied = FakeDingtalk()
        denied.upload_to_space = mock.Mock(side_effect=KnowledgeServiceError("钉钉接口错误（permissionDenied：no privilege）"))
        row = self._run(upload_id, path, FakeBailian(), denied)
        self.assertEqual(row.dingtalk_status, "failed")
        self.assertIn("没有上传权限", row.dingtalk_error)

    def test_document_search_matches_part_of_the_name(self):
        class ManyDocs(FakeBailian):
            def list_index_documents(self, index_id, page, page_size, name):
                docs = [{"Id": f"f{i}", "Name": f"木质工艺品调研{i}" if i % 2 else f"报销制度{i}"} for i in range(150)]
                return {"TotalCount": 150, "Documents": docs[(page - 1) * page_size:page * page_size]}

        kr._doc_list_cache.clear()
        with mock.patch.object(kr, "bailian_client", return_value=ManyDocs()):
            found = self.client.get("/api/knowledge/documents?index_id=idx&name=木质&page=2&page_size=20").json()
        self.assertEqual(found["total"], 75)
        self.assertEqual(len(found["items"]), 20)
        self.assertTrue(all("木质" in item["name"] for item in found["items"]))

    def test_dingtalk_failure_does_not_undo_import(self):
        self.db.add(KnowledgeDingtalkIdentity(user_id=7, union_id="union-7"))
        upload_id, path = self._row(sync_dingtalk=True, dingtalk_folder_id="f", dingtalk_status="pending")
        row = self._run(upload_id, path, FakeBailian(), FakeDingtalk(fail=True))
        self.assertEqual((row.status, row.dingtalk_status), ("completed", "failed"))
        self.assertIn("403", row.dingtalk_error)

    def test_dingtalk_copy_waits_for_successful_import(self):
        self.db.add(KnowledgeDingtalkIdentity(user_id=7, union_id="union-7"))
        for bailian in (FakeBailian(parse_status="PARSE_FAILED"), FakeBailian(fail_lease=True)):
            upload_id, path = self._row(sync_dingtalk=True, dingtalk_folder_id="f", dingtalk_status="pending")
            dingtalk = FakeDingtalk()
            row = self._run(upload_id, path, bailian, dingtalk)
            self.assertEqual((row.status, row.dingtalk_status), ("failed", "failed"))
            self.assertEqual(dingtalk.uploaded, [], "nothing goes to the drive when the import fails")
            self.assertIn("未同步到钉盘", row.dingtalk_error)

    def test_oauth_state_is_bound_to_user_and_expires(self):
        state = kr.make_state(7, now=1000)
        self.assertTrue(kr.verify_state(state, 7, now=1500))
        self.assertFalse(kr.verify_state(state, 8, now=1500))
        self.assertFalse(kr.verify_state(state, 7, now=1000 + kr.STATE_TTL_SECONDS + 1))
        self.assertFalse(kr.verify_state(state[:-1] + "0", 7, now=1500))

    def test_settings_hide_secrets_and_require_superuser(self):
        with mock.patch.object(kr, "encrypt_agent_credential", side_effect=lambda v, purpose: f"enc:{v}"):
            result = self.client.put("/api/knowledge/settings", json={
                "bailian_access_key_id": "LTAIabcdefgh", "bailian_access_key_secret": "secret-value",
                "bailian_workspace_id": "llm-ws", "default_index_id": "53zmggcvov"}).json()
        self.assertEqual(result["bailian_access_key_secret_masked"], "已保存")
        self.assertNotIn("secret-value", str(result))
        self.assertTrue(result["bailian_configured"])
        self.user = CurrentUser(user_id=8)
        self.assertEqual(self.client.put("/api/knowledge/settings", json={}).status_code, 403)
        public = self.client.get("/api/knowledge/settings").json()
        self.assertNotIn("bailian_access_key_id", public)
        self.assertEqual(self.client.get("/api/dashboard/summary/knowledge-usage").status_code, 403)

    def test_department_rules_for_usage_board_and_upload(self):
        self.departments = {8: ("软件开发部", "后端组"), 9: ("人力资源部",), 10: ("运营部",)}
        expected = {8: (True, True), 9: (False, True), 10: (False, False)}
        for user_id, (view, upload) in expected.items():
            self.user = CurrentUser(user_id=user_id)
            access = self.client.get("/api/knowledge/access").json()
            self.assertEqual((access["can_view_usage"], access["can_upload"]), (view, upload), user_id)
            usage = self.client.get("/api/dashboard/summary/knowledge-usage?period=today").status_code
            self.assertEqual(usage, 200 if view else 403, user_id)
        self.user = CurrentUser(user_id=10)
        with mock.patch.object(kr, "bailian_client"):
            denied = self.client.post("/api/knowledge/uploads", data={"index_id": "i", "category_id": "c"},
                                      files={"files": ("a.txt", b"x")})
        self.assertEqual(denied.status_code, 403)
        self.assertIn("暂未开通", denied.json()["detail"])
        self.user = CurrentUser(user_id=1, is_superuser=True)
        self.assertTrue(self.client.get("/api/knowledge/access").json()["can_view_usage"], "superusers always may")

    def test_department_lists_are_editable_and_lookup_failure_denies(self):
        saved = self.client.put("/api/knowledge/settings", json={"usage_departments": ["运营部", " 运营部 "],
                                                                  "upload_departments": []}).json()
        self.assertEqual((saved["usage_departments"], saved["upload_departments"]), (["运营部"], []))
        self.departments = {10: ("运营部",)}
        self.user = CurrentUser(user_id=10)
        self.assertEqual(self.client.get("/api/knowledge/access").json()["can_view_usage"], True)
        kr._access_cache.clear()
        from fastapi import HTTPException as HttpError
        with mock.patch.object(kr, "load_departments", side_effect=HttpError(503, "部门数据查询失败")):
            access = self.client.get("/api/knowledge/access").json()
            self.assertEqual((access["can_upload"], access["can_view_usage"]), (False, False))
            self.assertIn("部门数据查询失败", access["error"])
            self.assertEqual(self.client.get("/api/dashboard/summary/knowledge-usage").status_code, 503,
                             "an unknown department never grants access")

    def test_retrieve_logs_call_and_usage_reports_ratios(self):
        with mock.patch.object(kr, "bailian_client", return_value=FakeBailian()):
            response = self.client.post("/api/knowledge/retrieve", json={
                "query": "报销多久提交", "index_id": "idx", "index_name": "合趣AI知识库", "source": "agent",
                "session_id": "s-1"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["usage"]["rag_tokens"], 6 + 11)
        failing = mock.Mock()
        failing.retrieve.side_effect = KnowledgeServiceError("百炼接口错误（Throttling）")
        with mock.patch.object(kr, "bailian_client", return_value=failing):
            self.assertEqual(self.client.post("/api/knowledge/retrieve", json={
                "query": "x", "index_id": "idx2", "source": "agent"}).status_code, 502)
        self.db.add(KnowledgeCallLog(user_id=8, index_id="idx", index_name="合趣AI知识库", source="api",
                                     query="q", status="success", rag_tokens=3,
                                     created_at=datetime(2020, 1, 1)))  # outside range
        self.db.commit()
        usage = self.client.get("/api/dashboard/summary/knowledge-usage?period=today&granularity=hour").json()
        summary = usage["summary"]
        self.assertEqual((summary["total_calls"], summary["success_calls"], summary["success_rate"]), (2, 1, 50.0))
        self.assertEqual(summary["rag_tokens"], 17)
        by_index = {item["index_id"]: item for item in usage["by_index"]}
        self.assertEqual(by_index["idx"]["index_name"], "合趣AI知识库")
        self.assertEqual(by_index["idx"]["call_ratio"], 50.0)
        self.assertEqual(by_index["idx"]["token_ratio"], 100.0)
        self.assertEqual(sum(bucket["calls"] for bucket in usage["trend"]), 2)
        self.assertEqual((summary["sessions"], summary["active_users"]), (1, 1))
        self.assertEqual(usage["top_documents"], [{"doc_name": "报销制度", "hits": 1, "hit_rate": 100.0}])
        self.assertEqual(len(usage["daily"]), 1)
        self.assertEqual({k: usage["daily"][0][k] for k in ("calls", "failed_calls", "users", "sessions")},
                         {"calls": 2, "failed_calls": 1, "users": 1, "sessions": 1})
        calls = self.client.get("/api/dashboard/summary/knowledge-usage/calls?period=today&status=error").json()
        self.assertEqual(calls["total"], 1)
        self.assertIn("Throttling", calls["items"][0]["error_message"])

    def test_usage_answers_who_adoption_and_solved_questions(self):
        now = datetime.utcnow()
        self.db.add_all([
            # user 8 used it long ago, so is not new; user 9 is new; user 7 only ran console tests
            KnowledgeCallLog(user_id=8, index_id="idx", source="api", query="old", status="success",
                             result_count=2, created_at=datetime(2020, 1, 1)),
            KnowledgeCallLog(user_id=8, index_id="idx", source="xiaoqu", query="a", status="success",
                             result_count=3, created_at=now),
            KnowledgeCallLog(user_id=8, index_id="idx", source="agent", query="a2", status="success",
                             result_count=1, created_at=now),
            KnowledgeCallLog(user_id=9, index_id="idx", source="workbuddy", query="b", status="success",
                             result_count=0, created_at=now),
            KnowledgeCallLog(user_id=9, index_id="idx", source="workbuddy", query="c", status="error",
                             created_at=now),
            KnowledgeCallLog(user_id=7, index_id="idx", source="console", query="t", status="success",
                             result_count=5, created_at=now),
        ])
        self.db.commit()
        usage = self.client.get("/api/dashboard/summary/knowledge-usage?period=today").json()
        summary = usage["summary"]
        self.assertEqual((summary["total_calls"], summary["answered_calls"], summary["unanswered_calls"]), (4, 2, 1))
        self.assertEqual(summary["answer_rate"], 50.0)
        self.assertEqual((summary["active_users"], summary["new_users"], summary["total_users"]), (2, 1, 2))
        self.assertEqual({item["source"]: item["calls"] for item in usage["by_source"]}, {"workbuddy": 2, "xiaoqu": 2},
                         "AI Hub agent calls count as 小趣")
        users = {item["user_id"]: item for item in usage["by_user"]}
        self.assertEqual((users[9]["is_new"], users[8]["is_new"], users[8]["answered_calls"]), (True, False, 2))
        self.assertEqual(sum(bucket["new_users"] for bucket in usage["trend"]), 1)
        self.assertEqual(sum(b["unanswered_calls"] for b in usage["trend"]), 1)
        self.assertEqual({k: usage["daily"][0][k] for k in ("answered_calls", "unanswered_calls")},
                         {"answered_calls": 2, "unanswered_calls": 1}, "daily rows carry answered counts")
        with_tests = self.client.get("/api/dashboard/summary/knowledge-usage?period=today&include_tests=true").json()
        self.assertEqual((with_tests["summary"]["total_calls"], with_tests["summary"]["new_users"]), (5, 2))
        gaps = self.client.get("/api/dashboard/summary/knowledge-usage/calls?period=today&status=unanswered").json()
        self.assertEqual([item["query"] for item in gaps["items"]], ["b"])

    def _chat_blocks(self, tool_id="toolu_1", query="报销需要哪些材料", truncated=False):
        import json as _json
        result = _json.dumps({"total": 2, "nodes": [
            {"score": 0.8, "metadata": {"doc_id": "file_1", "content": "报销需在三十天内提交"}},
            {"score": 0.5, "metadata": {"doc_id": "file_2", "doc_name": "差旅制度", "content": "差旅标准"}},
        ]}, ensure_ascii=False)
        if truncated:
            result = result[:result.index("差旅标准")]  # cut mid-way, as long stored results are
        return [
            {"type": "tool_use", "name": "mcp__online-knowledge-base__BailianKnowledgeBaseRetrieve",
             "input": {"IndexId": "idx", "Query": query, "RerankTopN": 10}, "tool_use_id": tool_id, "duration_ms": 640},
            {"type": "tool_result", "tool_use_id": tool_id, "content": result, "is_error": False},
            {"type": "tool_use", "name": "mcp__online-mcp__invoke_service_api", "input": {}, "tool_use_id": "other"},
            {"type": "tool_result", "tool_use_id": "other", "content": "{}", "is_error": False},
            {"type": "text", "content": "答复"},
        ]

    def test_chat_knowledge_searches_count_as_xiaoqu_once(self):
        with mock.patch.object(kr, "bailian_client", return_value=FakeBailian()):
            added = kr.record_chat_knowledge_calls(self.db, self._chat_blocks(), user_id=7, session_id=570)
            again = kr.record_chat_knowledge_calls(self.db, self._chat_blocks(), user_id=7, session_id=570)
        self.assertEqual((added, again), (1, 0), "only knowledge tools count, and each tool call once")
        log = self.db.query(KnowledgeCallLog).one()
        self.assertEqual((log.source, log.index_id, log.result_count, log.session_id, log.latency_ms),
                         ("xiaoqu", "idx", 2, "570", 640))
        self.assertEqual(log.rag_tokens, estimate_tokens("报销需要哪些材料") + estimate_tokens("报销需在三十天内提交")
                         + estimate_tokens("差旅标准"))
        hits = {hit.doc_name for hit in self.db.query(KnowledgeCallHit).all()}
        self.assertEqual(hits, {"a.txt", "差旅制度"}, "doc names come from the result, else the index list")

    def test_search_tool_results_nested_under_data_are_read(self):
        import json as _json
        text = _json.dumps({"data": {"total": 1, "nodes": [{"score": 0.9, "metadata": {"content": "HRBP：刘美婷"}}]}},
                           ensure_ascii=False)
        self.assertEqual([node["text"] for node in kr.parse_chat_retrieval(text)], ["HRBP：刘美婷"])
        blocks = [{"type": "tool_use", "name": "mcp__online-knowledge-base__BailianKnowledgeSearch",
                   "input": {"agentId": "aid-1", "query": "运营部门的HRBP是谁"}, "tool_use_id": "s1"},
                  {"type": "tool_result", "tool_use_id": "s1", "content": text}]
        calls = kr.chat_knowledge_calls(blocks, "default-idx")
        self.assertEqual((calls[0]["index_id"], len(calls[0]["nodes"])), ("default-idx", 1))

    def test_trimmed_chat_results_still_count_their_passages(self):
        nodes = kr.parse_chat_retrieval(kr._tool_text(self._chat_blocks(truncated=True)[1]["content"]))
        self.assertEqual([node["doc_id"] for node in nodes], ["file_1"])
        failed = self._chat_blocks()
        failed[1]["is_error"] = True
        calls = kr.chat_knowledge_calls(failed, None)
        self.assertEqual((calls[0]["status"], calls[0]["nodes"]), ("error", []))

    def test_saved_reply_hook_never_breaks_the_chat(self):
        with mock.patch.object(kr, "record_chat_knowledge_calls", side_effect=RuntimeError("db down")):
            kr.record_chat_knowledge_safely(self.engine, self._chat_blocks(), user_id=7, session_id=1,
                                            background=False)  # no raise
        with mock.patch.object(kr, "bailian_client", return_value=FakeBailian()):
            kr.record_chat_knowledge_safely(self.engine, self._chat_blocks(tool_id="t9"), user_id=7, session_id=1,
                                            background=False)
        self.db.expire_all()
        self.assertEqual(self.db.query(KnowledgeCallLog).filter_by(external_id="t9").count(), 1)
        started = []
        with mock.patch.object(kr.threading, "Thread") as thread:
            thread.return_value.start.side_effect = lambda: started.append(True)
            kr.record_chat_knowledge_safely(self.engine, self._chat_blocks(tool_id="t10"), user_id=7, session_id=1)
        self.assertEqual(started, [True], "by default the chat hands the work to a background thread")

    def test_backfill_reads_recent_chats_once(self):
        import json as _json
        from datetime import timedelta
        from models import AgentMessage, AgentSession
        for table in (AgentSession.__table__, AgentMessage.__table__):
            table.create(self.engine)
        now = datetime.utcnow()
        self.db.add(AgentSession(id=5, agent_id=17, user_id=42))
        self.db.add_all([
            AgentMessage(session_id=5, role="assistant", created_at=now - timedelta(days=2),
                         content=_json.dumps({"blocks": self._chat_blocks(tool_id="recent")}, ensure_ascii=False)),
            AgentMessage(session_id=5, role="assistant", created_at=now - timedelta(days=20),
                         content=_json.dumps({"blocks": self._chat_blocks(tool_id="old")}, ensure_ascii=False)),
        ])
        self.db.commit()
        with mock.patch.object(kr, "bailian_client", return_value=FakeBailian()):
            first = self.client.post("/api/dashboard/summary/knowledge-usage/backfill-chats?days=7").json()
            second = self.client.post("/api/dashboard/summary/knowledge-usage/backfill-chats?days=7").json()
        self.assertEqual((first["recorded"], second["recorded"]), (1, 0))
        log = self.db.query(KnowledgeCallLog).one()
        self.assertEqual((log.user_id, log.external_id, log.source), (42, "recent", "xiaoqu"))
        self.user = CurrentUser(user_id=7, is_superuser=False)
        self.assertEqual(self.client.post("/api/dashboard/summary/knowledge-usage/backfill-chats").status_code, 403)

    def test_upload_rejects_bad_type_and_missing_binding(self):
        with mock.patch.object(kr, "bailian_client"), mock.patch.object(kr, "dingtalk_client"), \
                mock.patch.object(kr, "_start_worker") as start:
            bad = self.client.post("/api/knowledge/uploads", data={"index_id": "i", "category_id": "c"},
                                   files={"files": ("run.exe", b"x")})
            self.assertEqual(bad.status_code, 400)
            unbound = self.client.post("/api/knowledge/uploads", data={
                "index_id": "i", "category_id": "c", "sync_dingtalk": "true", "dingtalk_folder_id": "f"},
                files={"files": ("a.md", b"# hi")})
            self.assertEqual(unbound.status_code, 400)
            ok = self.client.post("/api/knowledge/uploads", data={"index_id": "i", "category_id": "c"},
                                  files=[("files", ("a.md", b"# hi")), ("files", ("b.pdf", b"%PDF"))])
            self.assertEqual(ok.status_code, 200, ok.text)
            self.assertEqual(start.call_count, 2)
            for _, (upload_id, path), _ in start.mock_calls:
                os.remove(path)

    def test_documents_carry_dingtalk_links_and_uploads_stay_private(self):
        self.db.add_all([
            KnowledgeUpload(user_id=8, index_id="idx", category_id="c", file_name="a.txt", file_size=1,
                            status="completed", bailian_file_id="file_1", dingtalk_url="https://alidocs/x"),
            KnowledgeUpload(user_id=7, index_id="idx", category_id="c", file_name="b.txt", file_size=1,
                            status="completed", bailian_file_id="file_9"),
        ])
        self.db.commit()
        with mock.patch.object(kr, "bailian_client", return_value=FakeBailian()):
            docs = self.client.get("/api/knowledge/documents?index_id=idx").json()["items"]
        self.assertEqual({d["id"]: d["dingtalk_url"] for d in docs}, {"file_1": "https://alidocs/x", "file_2": None})
        uploads = self.client.get("/api/knowledge/uploads?scope=all").json()["items"]
        self.assertEqual([u["file_name"] for u in uploads], ["b.txt"], "superusers also see only their own")

    def test_link_table_rows_parse(self):
        text = "文件名:木质工艺品一次调研表\n文件目录:全员文件夹/表单台账\n钉钉链接:https://alidocs.dingtalk.com/i/nodes/A"
        self.assertEqual(kr.parse_link_rows(text), [("木质工艺品一次调研表", "全员文件夹/表单台账",
                                                     "https://alidocs.dingtalk.com/i/nodes/A")])
        self.assertEqual(kr.parse_link_rows("规则说明:2. 再检索一次"), [])

    def test_documents_without_upload_get_link_from_table_and_cache_it(self):
        table = "钉钉文件链接对照表"

        class TableBailian(FakeBailian):
            queries = []

            def retrieve(self, index_id, query, rerank_top_n=5):
                self.queries.append(query)
                return {"Nodes": [
                    {"Text": "文件名:b\n文件目录:d\n钉钉链接:https://alidocs/b", "Metadata": {"doc_name": table}},
                    # near-duplicate names must not be confused with the exact one
                    {"Text": "文件名:b2\n文件目录:d\n钉钉链接:https://alidocs/b2", "Metadata": {"doc_name": table}},
                    {"Text": "文件名:b\n钉钉链接:https://evil/x", "Metadata": {"doc_name": "别的文档"}},
                ]}

            def list_index_documents(self, index_id, page, page_size, name):
                return {"TotalCount": 2, "Documents": [{"Id": "file_2", "Name": "b"}, {"Id": "file_3", "Name": "c"}]}

        fake = TableBailian()
        run_now = lambda index_id, names: kr.table_links(self.db, index_id, names)  # noqa: E731
        with mock.patch.object(kr, "bailian_client", return_value=fake), \
                mock.patch.object(kr, "_start_link_lookup", side_effect=run_now):
            first = self.client.get("/api/knowledge/documents?index_id=idx").json()
            self.assertTrue(first["links_pending"], "unknown links are looked up without holding the list")
            docs = self.client.get("/api/knowledge/documents?index_id=idx").json()["items"]
            self.assertEqual({d["id"]: d["dingtalk_url"] for d in docs}, {"file_2": "https://alidocs/b", "file_3": None})
            self.assertEqual(sorted(fake.queries), [f"{table} b", f"{table} c"])
            fake.queries.clear()
            self.client.get("/api/knowledge/documents?index_id=idx")
            self.assertEqual(fake.queries, [], "hits and misses are cached")
        self.assertEqual(self.db.query(KnowledgeDocLink).filter_by(doc_name="b2").one().dingtalk_url, "https://alidocs/b2")
        self.assertEqual(self.db.query(KnowledgeCallLog).count(), 0, "link lookups are not RAG usage")
        miss = self.db.query(KnowledgeDocLink).filter_by(doc_name="c").one()
        miss.checked_at = datetime(2020, 1, 1)
        self.db.commit()
        with mock.patch.object(kr, "bailian_client", return_value=fake), \
                mock.patch.object(kr, "_start_link_lookup", side_effect=run_now):
            self.client.get("/api/knowledge/documents?index_id=idx")
        self.assertEqual(fake.queries, [f"{table} c"], "old misses are retried")

    def test_stale_rows_are_failed_after_restart(self):
        upload_id, path = self._row()
        os.remove(path)
        self.db.query(KnowledgeUpload).update({"updated_at": datetime(2020, 1, 1)})
        self.db.commit()
        items = self.client.get("/api/knowledge/uploads").json()["items"]
        self.assertEqual(items[0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
