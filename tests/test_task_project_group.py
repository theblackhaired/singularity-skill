import unittest

import cli
from tests.conftest import MockHTTPServer


class TestTaskProjectGroupIntegrity(unittest.TestCase):
    def start_server(self, routes):
        server = MockHTTPServer(routes)
        server.start()
        self.addCleanup(server.stop)
        return server

    def call_task_update(self, server, args):
        resource, handler = cli.TOOL_DISPATCH["task_update"]
        client = cli.SingularityClient(
            server.start(), "test-token", max_retries=1, timeout=5
        )
        return handler(client, resource, args)

    def test_project_move_requires_group(self):
        server = self.start_server({})

        with self.assertRaisesRegex(ValueError, "also requires group"):
            self.call_task_update(
                server, {"id": "T-1", "projectId": "P-TARGET"}
            )

        self.assertEqual(server.request_log, [])

    def test_project_move_patches_matching_group(self):
        server = self.start_server({
            ("GET", "/v2/task-group/Q-TARGET"): lambda query: (
                200, {"id": "Q-TARGET", "parent": "P-TARGET"}
            ),
            ("PATCH", "/v2/task/T-1"): lambda query: (
                200, {"id": "T-1", "projectId": "P-TARGET", "group": "Q-TARGET"}
            ),
        })

        result = self.call_task_update(server, {
            "id": "T-1",
            "projectId": "P-TARGET",
            "group": "Q-TARGET",
        })

        self.assertEqual(result["group"], "Q-TARGET")
        self.assertEqual(
            server.request_log[-1]["json"],
            {"projectId": "P-TARGET", "group": "Q-TARGET"},
        )

    def test_project_move_rejects_foreign_group(self):
        server = self.start_server({
            ("GET", "/v2/task-group/Q-OTHER"): lambda query: (
                200, {"id": "Q-OTHER", "parent": "P-OTHER"}
            ),
        })

        with self.assertRaisesRegex(ValueError, "belongs to"):
            self.call_task_update(server, {
                "id": "T-1",
                "projectId": "P-TARGET",
                "group": "Q-OTHER",
            })

        self.assertEqual(len(server.request_log), 1)

    def test_group_only_repair_validates_current_project(self):
        server = self.start_server({
            ("GET", "/v2/task-group/Q-TARGET"): lambda query: (
                200, {"id": "Q-TARGET", "parent": "P-TARGET"}
            ),
            ("GET", "/v2/task/T-1"): lambda query: (
                200, {"id": "T-1", "projectId": "P-TARGET"}
            ),
            ("PATCH", "/v2/task/T-1"): lambda query: (
                200, {"id": "T-1", "projectId": "P-TARGET", "group": "Q-TARGET"}
            ),
        })

        result = self.call_task_update(
            server, {"id": "T-1", "group": "Q-TARGET"}
        )

        self.assertEqual(result["group"], "Q-TARGET")


if __name__ == "__main__":
    unittest.main(verbosity=2)
