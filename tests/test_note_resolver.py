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
        """GET /v2/note/N-<id> returning a valid note resolves to ok."""
        raw = {"id": "N-T-1", "containerId": "T-1", "content": "hello"}
        client = MockClient({"/v2/note/N-T-1": raw})

        result = resolve_note(client, "T-1")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["note_status"], "ok")
        self.assertEqual(result["content"], "hello")
        self.assertEqual(result["note_id"], "N-T-1")
        self.assertEqual(result["raw"], raw)
        self.assertEqual(result["warnings"], [])

    def test_uses_deterministic_path_not_list_filter(self):
        """resolve_note must call /v2/note/N-<id>, never /v2/note?containerId=
        (the list endpoint ignores containerId server-side and would return
        an arbitrary note — that was the original bug)."""
        client = MockClient({"/v2/note/N-T-abc": {
            "id": "N-T-abc", "containerId": "T-abc", "content": "x"
        }})

        resolve_note(client, "T-abc")

        self.assertEqual(client.calls, [("/v2/note/N-T-abc", None)])

    def test_explicit_note_id_overrides_formula(self):
        """If caller passes note_id (e.g. task['note']), it is used as-is."""
        client = MockClient({"/v2/note/N-explicit": {
            "id": "N-explicit", "containerId": "T-1", "content": "x"
        }})

        result = resolve_note(client, "T-1", note_id="N-explicit")

        self.assertEqual(client.calls, [("/v2/note/N-explicit", None)])
        self.assertEqual(result["status"], "ok")

    def test_404_means_missing(self):
        """HTTP 404 (note doesn't exist) maps to ok/missing, not error."""
        client = MockClient({
            "/v2/note/N-T-1": RuntimeError("HTTP 404 Not Found on GET /v2/note/N-T-1"),
        })

        result = resolve_note(client, "T-1")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["note_status"], "missing")
        self.assertIsNone(result["raw"])
        self.assertEqual(result["warnings"], [])

    def test_500_is_degraded_error(self):
        """Non-404 HTTP errors propagate as degraded with the error text."""
        client = MockClient({
            "/v2/note/N-T-1": RuntimeError("HTTP 500 boom"),
        })

        result = resolve_note(client, "T-1")

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["note_status"], "error")
        self.assertIn("HTTP 500", result["warnings"][0])

    def test_unexpected_exception(self):
        """Unexpected client exceptions are wrapped as degraded errors."""
        client = MockClient({"/v2/note/N-T-1": ValueError("boom")})

        result = resolve_note(client, "T-1")

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["note_status"], "error")
        self.assertIn("ValueError", result["warnings"][0])
        self.assertIn("boom", result["warnings"][0])

    def test_empty_container_id(self):
        """An empty container id degrades without making an HTTP call."""
        client = MockClient({})

        result = resolve_note(client, "")

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["note_status"], "error")
        self.assertTrue(result["warnings"])
        self.assertEqual(len(client.calls), 0)

    def test_container_id_mismatch_is_shape_mismatch(self):
        """If the backend returns a note for a different container,
        surface it as shape_mismatch — never hand back wrong data silently
        (this was the symptom of the original bug)."""
        client = MockClient({"/v2/note/N-T-1": {
            "id": "N-T-1", "containerId": "P-other", "content": "x"
        }})

        result = resolve_note(client, "T-1")

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["note_status"], "shape_mismatch")
        self.assertIn("containerId mismatch", result["warnings"][0])

    def test_empty_dict_response_means_missing(self):
        """Some backends return {} for a missing note rather than 404."""
        client = MockClient({"/v2/note/N-T-1": {}})

        result = resolve_note(client, "T-1")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["note_status"], "missing")

    def test_non_dict_response_is_shape_mismatch(self):
        """A list/string response from /v2/note/{id} is a shape error."""
        client = MockClient({"/v2/note/N-T-1": ["not", "a", "dict"]})

        result = resolve_note(client, "T-1")

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["note_status"], "shape_mismatch")

    def test_note_id_with_special_chars_is_url_quoted(self):
        """Path component is URL-encoded — defends against id injection."""
        client = MockClient({"/v2/note/N-T-a%2Fb": {
            "id": "N-T-a/b", "containerId": "T-a/b", "content": "x"
        }})

        resolve_note(client, "T-a/b")

        # Slash in id must be percent-encoded so it doesn't traverse the path.
        self.assertEqual(client.calls[-1][0], "/v2/note/N-T-a%2Fb")


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
