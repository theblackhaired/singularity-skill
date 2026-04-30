import unittest

import cli
from tests.conftest import MockHTTPServer


class TestDerivedToolContracts(unittest.TestCase):
    def start_server(self, routes):
        server = MockHTTPServer(routes)
        server.start()
        self.addCleanup(server.stop)
        return server

    def client(self, server, *, max_retries=1):
        return cli.SingularityClient(
            server.start(),
            "test-token",
            max_retries=max_retries,
            timeout=5,
        )

    def call_tool(self, server, tool_name, args):
        res_key, handler = cli.TOOL_DISPATCH[tool_name]
        return handler(self.client(server), res_key, args)

    def test_task_full_returns_status_ok(self):
        server = self.start_server({
            ("GET", "/v2/task/T-1"): lambda query: (
                200,
                {"id": "T-1", "status": "ok", "title": "Task"},
            ),
            ("GET", "/v2/note"): lambda query: (
                200,
                {"notes": [{"id": "N-1", "content": "note body"}]},
            ),
        })

        result = self.call_tool(server, "task_full", {"task_id": "T-1"})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["task"]["status"], "ok")
        self.assertEqual(result["note"]["id"], "N-1")

    def test_task_full_degraded_when_note_endpoint_fails(self):
        server = self.start_server({
            ("GET", "/v2/task/T-1"): lambda query: (
                200,
                {"id": "T-1", "status": "ok"},
            ),
            ("GET", "/v2/note"): lambda query: (500, {"error": "down"}),
        })

        result = self.call_tool(server, "task_full", {"task_id": "T-1"})

        self.assertEqual(result["task"]["id"], "T-1")
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["note_status"], "error")
        self.assertTrue(result["warnings"])

    def test_project_tasks_full_uses_server_side_filter(self):
        server = self.start_server({
            ("GET", "/v2/task"): lambda query: (
                200,
                {"tasks": [{"id": "T-1", "projectId": "P-1"}]},
            ),
        })

        result = self.call_tool(
            server,
            "project_tasks_full",
            {"project_id": "P-1", "include_notes": False},
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["total_tasks"], 1)
        self.assertEqual(server.request_log[-1]["query"]["projectId"], ["P-1"])

    def test_inbox_list_partial_when_page_limit_hit(self):
        tasks = [
            {"id": f"T-{idx}", "projectId": ""}
            for idx in range(1000)
        ]
        server = self.start_server({
            ("GET", "/v2/task"): lambda query: (200, {"tasks": tasks}),
        })

        result = self.call_tool(
            server,
            "inbox_list",
            {"include_notes": False, "page_limit": 1},
        )

        self.assertEqual(result["total"], 1000)
        self.assertTrue(result["partial"])
        self.assertEqual(result["status"], "degraded")
        self.assertIn("truncated", " ".join(result["warnings"]))

    def test_inbox_list_filters_only_no_projectid(self):
        server = self.start_server({
            ("GET", "/v2/task"): lambda query: (
                200,
                {
                    "tasks": [
                        {"id": "T-INBOX", "projectId": ""},
                        {"id": "T-PROJECT", "projectId": "P-1"},
                    ],
                },
            ),
        })

        result = self.call_tool(
            server,
            "inbox_list",
            {"include_notes": False},
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["tasks"][0]["id"], "T-INBOX")
        self.assertNotIn("T-PROJECT", {task["id"] for task in result["tasks"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
