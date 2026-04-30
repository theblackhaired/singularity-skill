import unittest
from unittest.mock import patch

from pagination import iterate_pages


class MockClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        if not self.pages:
            return {}
        return self.pages.pop(0)


class TestIteratePages(unittest.TestCase):
    def test_single_page_short(self):
        """A short first page completes after one fetch."""
        client = MockClient([{"tasks": [1, 2, 3]}])

        result = iterate_pages(client, "/tasks", page_size=1000)

        self.assertEqual(result["fetched_pages"], 1)
        self.assertFalse(result["partial"])
        self.assertEqual(result["fetched_items"], 3)
        self.assertEqual(result["wrapper_key"], "tasks")
        self.assertEqual(len(client.calls), 1)

    def test_single_page_full(self):
        """A full page requires one extra empty-page fetch to prove completion."""
        client = MockClient([{"tasks": list(range(1000))}, {"tasks": []}])

        result = iterate_pages(client, "/tasks")

        self.assertEqual(result["fetched_pages"], 2)
        self.assertFalse(result["partial"])
        self.assertEqual(result["items"], list(range(1000)))
        self.assertEqual(result["fetched_items"], 1000)

    def test_multi_page_complete(self):
        """Multiple full pages complete when a later short page is fetched."""
        client = MockClient([
            {"tasks": list(range(1000))},
            {"tasks": list(range(1000, 2000))},
            {"tasks": list(range(2000, 2010))},
        ])

        result = iterate_pages(client, "/tasks")

        self.assertEqual(result["fetched_pages"], 3)
        self.assertEqual(result["fetched_items"], 2010)
        self.assertEqual(len(result["items"]), 2010)
        self.assertFalse(result["partial"])

    def test_max_pages_truncation(self):
        """Hitting max_pages returns a partial result with a truncation warning."""
        client = MockClient([
            {"tasks": list(range(1000))},
            {"tasks": list(range(1000, 2000))},
            {"tasks": list(range(2000, 3000))},
        ])

        result = iterate_pages(client, "/tasks", max_pages=2)

        self.assertEqual(result["fetched_pages"], 2)
        self.assertTrue(result["partial"])
        self.assertEqual(result["fetched_items"], 2000)
        self.assertIn("truncated", " ".join(result["warnings"]))

    def test_offset_increments_correctly(self):
        """Offsets advance by page_size for each requested page."""
        client = MockClient([
            {"tasks": list(range(100))},
            {"tasks": list(range(100, 200))},
            {"tasks": list(range(200, 250))},
        ])

        iterate_pages(client, "/tasks", page_size=100)

        self.assertEqual([call[1]["offset"] for call in client.calls], [0, 100, 200])

    def test_caller_params_preserved(self):
        """Caller params are preserved alongside paginator-owned params."""
        client = MockClient([
            {"tasks": list(range(1000))},
            {"tasks": []},
        ])

        iterate_pages(client, "/tasks", params={"projectId": "P-1"})

        for _, params in client.calls:
            self.assertEqual(params["projectId"], "P-1")
            self.assertEqual(params["maxCount"], 1000)
            self.assertIn("offset", params)

    def test_caller_pagination_params_stripped(self):
        """Caller pagination params are stripped and replaced by paginator values."""
        client = MockClient([{"tasks": [1]}])

        iterate_pages(
            client,
            "/tasks",
            params={"maxCount": 5, "offset": 999, "limit": 20},
            page_size=1000,
        )

        params = client.calls[0][1]
        self.assertEqual(params["maxCount"], 1000)
        self.assertEqual(params["offset"], 0)
        self.assertNotIn("limit", params)

    def test_wrapper_key_autodetect(self):
        """Default wrapper key detection recognizes common response fields."""
        client = MockClient([{"projects": ["P-1", "P-2"]}])

        result = iterate_pages(client, "/projects")

        self.assertEqual(result["wrapper_key"], "projects")

    def test_wrapper_key_explicit(self):
        """Explicit wrapper_keys selects the caller-provided response field."""
        client = MockClient([{"foo": [1, 2, 3]}])

        result = iterate_pages(client, "/foo", wrapper_keys=["foo"])

        self.assertEqual(result["wrapper_key"], "foo")
        self.assertEqual(result["items"], [1, 2, 3])

    def test_list_response(self):
        """Bare list responses are treated as items without a wrapper key."""
        client = MockClient([[1, 2, 3]])

        result = iterate_pages(client, "/list")

        self.assertEqual(result["items"], [1, 2, 3])
        self.assertIsNone(result["wrapper_key"])
        self.assertFalse(result["partial"])

    def test_no_wrapper_match(self):
        """Dict responses without list fields complete as an empty page."""
        client = MockClient([{"unknown": "string"}])

        result = iterate_pages(client, "/unknown")

        self.assertEqual(result["items"], [])
        self.assertFalse(result["partial"])
        self.assertEqual(result["fetched_pages"], 1)

    def test_client_error_returns_partial(self):
        """Fetch exceptions return accumulated items as a partial result."""
        client = MockClient([{"tasks": list(range(1000))}])
        original_get = client.get

        def fail_on_second_page(path, params=None):
            if len(client.calls) == 1:
                raise RuntimeError("API down")
            return original_get(path, params)

        client.get = fail_on_second_page

        result = iterate_pages(client, "/tasks")

        self.assertEqual(result["fetched_pages"], 1)
        self.assertTrue(result["partial"])
        self.assertEqual(result["items"], list(range(1000)))
        self.assertIn("page_fetch_failed", " ".join(result["warnings"]))
        self.assertIn("API down", " ".join(result["warnings"]))

    def test_page_size_clamped_to_1000(self):
        """Requested page sizes above the API cap are clamped to 1000."""
        client = MockClient([{"tasks": [1]}])

        iterate_pages(client, "/tasks", page_size=2000)

        self.assertEqual(client.calls[0][1]["maxCount"], 1000)

    def test_throttle_ms_sleep(self):
        """A positive throttle sleeps after full pages before continuing."""
        client = MockClient([
            {"tasks": list(range(1000))},
            {"tasks": list(range(1000, 2000))},
            {"tasks": []},
        ])

        with patch("pagination.time.sleep") as sleep:
            iterate_pages(client, "/tasks", throttle_ms=1)

        self.assertGreaterEqual(sleep.call_count, 1)
        sleep.assert_called_with(0.001)

    def test_invalid_page_size_raises(self):
        """Non-positive page sizes are rejected before any fetch."""
        with self.assertRaises(ValueError):
            iterate_pages(MockClient([]), "/tasks", page_size=0)
        with self.assertRaises(ValueError):
            iterate_pages(MockClient([]), "/tasks", page_size=-5)


if __name__ == "__main__":
    unittest.main()
