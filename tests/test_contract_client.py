import unittest
from unittest.mock import patch

import cli
from tests.conftest import MockHTTPServer


class TestSingularityClientContract(unittest.TestCase):
    def start_server(self, routes):
        server = MockHTTPServer(routes)
        server.start()
        self.addCleanup(server.stop)
        return server

    def client(self, server, *, token="test-token", max_retries=3):
        return cli.SingularityClient(
            server.start(),
            token,
            max_retries=max_retries,
            timeout=5,
        )

    def test_get_returns_parsed_json(self):
        server = self.start_server({
            ("GET", "/v2/task/T-1"): lambda query: (200, {"id": "T-1"}),
        })

        result = self.client(server).get("/v2/task/T-1")

        self.assertEqual(result, {"id": "T-1"})
        self.assertEqual(server.request_log[-1]["method"], "GET")

    def test_post_sends_body(self):
        server = self.start_server({
            ("POST", "/v2/task"): lambda query: (200, {"id": "T-2"}),
        })
        body = {"title": "New task", "projectId": "P-1"}

        result = self.client(server).post("/v2/task", data=body)

        self.assertEqual(result["id"], "T-2")
        self.assertEqual(server.request_log[-1]["json"], body)

    def test_patch_sends_body(self):
        server = self.start_server({
            ("PATCH", "/v2/task/T-1"): lambda query: (200, {"id": "T-1"}),
        })
        body = {"title": "Renamed"}

        self.client(server).patch("/v2/task/T-1", data=body)

        self.assertEqual(server.request_log[-1]["json"], body)
        self.assertEqual(server.request_log[-1]["method"], "PATCH")

    def test_delete_with_params(self):
        server = self.start_server({
            ("DELETE", "/v2/task/T-1"): lambda query: (200, {"deleted": True}),
        })

        result = self.client(server).delete(
            "/v2/task/T-1",
            params={"permanent": "true"},
        )

        self.assertTrue(result["deleted"])
        self.assertEqual(server.request_log[-1]["query"]["permanent"], ["true"])

    def test_429_retries_with_backoff(self):
        state = {"count": 0}

        def route(query):
            state["count"] += 1
            if state["count"] == 1:
                return 429, {"error": "rate limited"}
            return 200, {"id": "T-1"}

        server = self.start_server({("GET", "/v2/task/T-1"): route})

        with patch("cli.time.sleep") as sleep:
            result = self.client(server).get("/v2/task/T-1")

        self.assertEqual(result["id"], "T-1")
        self.assertEqual(state["count"], 2)
        sleep.assert_called_once_with(1)

    def test_500_retries(self):
        state = {"count": 0}

        def route(query):
            state["count"] += 1
            if state["count"] == 1:
                return 500, {"error": "temporary"}
            return 200, {"id": "T-1"}

        server = self.start_server({("GET", "/v2/task/T-1"): route})

        with patch("cli.time.sleep") as sleep:
            result = self.client(server).get("/v2/task/T-1")

        self.assertEqual(result["id"], "T-1")
        self.assertEqual(state["count"], 2)
        sleep.assert_called_once_with(1)

    def test_4xx_no_retry_raises_RuntimeError(self):
        server = self.start_server({
            ("GET", "/v2/task/T-1"): lambda query: (403, {"error": "forbidden"}),
        })

        with self.assertRaises(RuntimeError):
            self.client(server).get("/v2/task/T-1")

        self.assertEqual(len(server.request_log), 1)

    def test_token_redacted_in_error_body(self):
        token = "abc123token"
        server = self.start_server({
            ("GET", "/v2/task/T-1"): lambda query: (
                401,
                {"error": f"Authorization failed: Bearer {token}"},
            ),
        })

        with self.assertRaises(RuntimeError) as ctx:
            self.client(server, token=token).get("/v2/task/T-1")

        self.assertNotIn(token, str(ctx.exception))
        self.assertIn("Bearer ***", str(ctx.exception))

    def test_url_injection_safe(self):
        server = self.start_server({
            ("GET", "/v2/task/T-1"): lambda query: (200, {"id": "T-1"}),
        })

        with self.assertRaises(RuntimeError):
            self.client(server, max_retries=1).get("/v2/task/abc/../../etc")

        self.assertTrue(server.request_log)
        self.assertNotEqual(server.request_log[-1]["path"], "/etc")


if __name__ == "__main__":
    unittest.main(verbosity=2)
