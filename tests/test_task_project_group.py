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

    def call_task_move(self, server, args):
        resource, handler = cli.TOOL_DISPATCH["task_move"]
        client = cli.SingularityClient(
            server.start(), "test-token", max_retries=1, timeout=5
        )
        return handler(client, resource, args)

    def test_task_move_is_blocked_in_read_only_mode(self):
        self.assertIn("task_move", cli.WRITE_TOOLS)

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

    def test_task_move_resolves_section_title_and_verifies_result(self):
        server = self.start_server({
            ("GET", "/v2/task-group"): lambda query: (
                200,
                {
                    "taskGroups": [
                        {
                            "id": "Q-BACKLOG",
                            "title": "Бэклог",
                            "parent": "P-TARGET",
                            "parentOrder": 20,
                            "removed": False,
                        },
                        {
                            "id": "Q-ACTIVE",
                            "title": "В работе",
                            "parent": "P-TARGET",
                            "parentOrder": 10,
                            "removed": False,
                        },
                    ]
                },
            ),
            ("PATCH", "/v2/task/T-1"): lambda query: (
                200,
                {
                    "id": "T-1",
                    "projectId": "P-TARGET",
                    "group": "Q-ACTIVE",
                },
            ),
            ("GET", "/v2/task/T-1"): lambda query: (
                200,
                {
                    "id": "T-1",
                    "projectId": "P-TARGET",
                    "group": "Q-ACTIVE",
                },
            ),
        })

        result = self.call_task_move(server, {
            "id": "T-1",
            "project_id": "P-TARGET",
            "section": "в РАБОТЕ",
        })

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["section"]["id"], "Q-ACTIVE")
        self.assertTrue(result["section"]["verified_for_project"])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(
            server.request_log[0]["query"]["parent"],
            ["P-TARGET"],
        )
        self.assertEqual(
            server.request_log[1]["json"],
            {"projectId": "P-TARGET", "group": "Q-ACTIVE"},
        )

    def test_task_move_with_section_id_does_not_require_task_group_scope(self):
        server = self.start_server({
            ("GET", "/v2/task-group/Q-ACTIVE"): lambda query: (
                200,
                {
                    "id": "Q-ACTIVE",
                    "title": "В работе",
                    "parent": "P-TARGET",
                    "removed": False,
                },
            ),
            ("PATCH", "/v2/task/T-1"): lambda query: (
                200,
                {
                    "id": "T-1",
                    "projectId": "P-TARGET",
                    "group": "Q-ACTIVE",
                },
            ),
            ("GET", "/v2/task/T-1"): lambda query: (
                200,
                {
                    "id": "T-1",
                    "projectId": "P-TARGET",
                    "group": "Q-ACTIVE",
                },
            ),
        })

        result = self.call_task_move(server, {
            "id": "T-1",
            "project_id": "P-TARGET",
            "section_id": "Q-ACTIVE",
        })

        self.assertEqual(result["section"]["id"], "Q-ACTIVE")
        self.assertTrue(result["section"]["verified_for_project"])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(
            [request["method"] for request in server.request_log],
            ["GET", "PATCH", "GET"],
        )

    def test_task_move_rejects_section_id_from_another_project_before_patch(self):
        server = self.start_server({
            ("GET", "/v2/task-group/Q-FOREIGN"): lambda query: (
                200,
                {
                    "id": "Q-FOREIGN",
                    "title": "В работе",
                    "parent": "P-OTHER",
                    "removed": False,
                },
            ),
        })

        with self.assertRaisesRegex(ValueError, "target project"):
            self.call_task_move(server, {
                "id": "T-1",
                "project_id": "P-TARGET",
                "section_id": "Q-FOREIGN",
            })

        self.assertEqual(
            [request["method"] for request in server.request_log],
            ["GET"],
        )

    def test_task_move_rejects_ambiguous_section_title_before_patch(self):
        server = self.start_server({
            ("GET", "/v2/task-group"): lambda query: (
                200,
                {
                    "taskGroups": [
                        {
                            "id": "Q-1",
                            "title": "В работе",
                            "parent": "P-TARGET",
                            "removed": False,
                        },
                        {
                            "id": "Q-2",
                            "title": "В работе",
                            "parent": "P-TARGET",
                            "removed": False,
                        },
                    ]
                },
            ),
        })

        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.call_task_move(server, {
                "id": "T-1",
                "project_id": "P-TARGET",
                "section": "В работе",
            })

        self.assertEqual(
            [request["method"] for request in server.request_log],
            ["GET"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
