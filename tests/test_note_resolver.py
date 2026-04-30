"""Unit tests for note_resolver.py.

Run: python -m unittest tests.test_note_resolver -v
"""

import unittest

from note_resolver import note_capability_ok, resolve_note


class MockClient:
    def __init__(self, responses):
        # responses: dict path -> response (or callable -> response)
        self._responses = responses
        self.calls = []  # for assertions

    def get(self, path, params=None):
        self.calls.append((path, params))
        r = self._responses.get(path)
        if callable(r):
            return r(params)
        if isinstance(r, Exception):
            raise r
        return r


class TestNoteResolver(unittest.TestCase):
    def test_success_path(self):
        """A valid notes wrapper returns the first note content and raw note."""
        raw = {"id": "N-1", "content": "hello"}
        client = MockClient({"/v2/note": {"notes": [raw]}})

        result = resolve_note(client, "T-1")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["note_status"], "ok")
        self.assertEqual(result["content"], "hello")
        self.assertEqual(result["note_id"], "N-1")
        self.assertEqual(result["raw"], raw)
        self.assertEqual(result["warnings"], [])

    def test_empty_notes_array(self):
        """An empty notes array is a successful missing-note result."""
        client = MockClient({"/v2/note": {"notes": []}})

        result = resolve_note(client, "T-1")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["note_status"], "missing")
        self.assertIsNone(result["content"])
        self.assertIsNone(result["raw"])

    def test_missing_wrapper_key(self):
        """A response without the notes wrapper key is a shape mismatch."""
        client = MockClient({"/v2/note": {"foo": "bar"}})

        result = resolve_note(client, "T-1")

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["note_status"], "shape_mismatch")
        self.assertTrue(result["warnings"])
        self.assertIn("notes", result["warnings"][0])

    def test_wrapper_not_array(self):
        """The notes wrapper must be an array."""
        client = MockClient({"/v2/note": {"notes": "string"}})

        result = resolve_note(client, "T-1")

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["note_status"], "shape_mismatch")

    def test_first_note_not_dict(self):
        """The first notes item must be an object."""
        client = MockClient({"/v2/note": {"notes": ["string-not-dict"]}})

        result = resolve_note(client, "T-1")

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["note_status"], "shape_mismatch")

    def test_runtime_error_from_client(self):
        """RuntimeError from the client is returned as degraded note error."""
        client = MockClient({"/v2/note": RuntimeError("HTTP 500")})

        result = resolve_note(client, "T-1")

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["note_status"], "error")
        self.assertIn("HTTP 500", result["warnings"][0])

    def test_unexpected_exception_from_client(self):
        """Unexpected client exceptions include exception type and message."""
        client = MockClient({"/v2/note": ValueError("boom")})

        result = resolve_note(client, "T-1")

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["note_status"], "error")
        self.assertIn("ValueError", result["warnings"][0])
        self.assertIn("boom", result["warnings"][0])

    def test_empty_container_id(self):
        """An empty container id degrades without making an HTTP call."""
        client = MockClient({"/v2/note": {"notes": []}})

        result = resolve_note(client, "")

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["note_status"], "error")
        self.assertTrue(result["warnings"])
        self.assertEqual(len(client.calls), 0)

    def test_url_params_correct(self):
        """resolve_note calls /v2/note with containerId and maxCount=1."""
        client = MockClient({"/v2/note": {"notes": []}})

        resolve_note(client, "T-abc")

        self.assertEqual(
            client.calls[-1],
            ("/v2/note", {"containerId": "T-abc", "maxCount": 1}),
        )


class TestNoteCapability(unittest.TestCase):
    def test_capability_ok_true(self):
        """Capability is true when /v2/note returns a notes array wrapper."""
        client = MockClient({"/v2/note": {"notes": []}})

        self.assertTrue(note_capability_ok(client))

    def test_capability_ok_false_on_404(self):
        """Capability is false when /v2/note raises a 404 RuntimeError."""
        client = MockClient({"/v2/note": RuntimeError("HTTP 404")})

        self.assertFalse(note_capability_ok(client))

    def test_capability_ok_false_on_bad_shape(self):
        """Capability is false when /v2/note lacks the notes wrapper."""
        client = MockClient({"/v2/note": {"foo": "bar"}})

        self.assertFalse(note_capability_ok(client))


if __name__ == "__main__":
    unittest.main(verbosity=2)
