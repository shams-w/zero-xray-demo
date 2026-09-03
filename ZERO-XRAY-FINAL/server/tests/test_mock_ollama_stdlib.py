"""
Regression tests for tools/mock_ollama_responses.py and
tools/mock_ollama_server_stdlib.py.

Unlike tests/test_mock_ollama_server.py (which drives the full
FastAPI mock over a real uvicorn subprocess and is skipped when
fastapi/uvicorn aren't installed), everything here uses ONLY the
standard library, so it always runs -- including in minimal/offline
environments that don't have the web stack installed. It exists to
give the same "real HTTP round trip through core/llm.py" confidence
in those environments.
"""

import json
import os
import unittest

import requests

from tools.mock_ollama_responses import _route_response
from tools.mock_ollama_server_stdlib import start_server


class RouteResponseTestCase(unittest.TestCase):
    """The pure routing logic, no HTTP involved."""

    def test_semantic_steps_never_exceeds_raw_lines(self):
        user_prompt = "1. one\n2. two\n3. three\n4. four\n5. five\n"
        result = _route_response([
            {"role": "system", "content": "You are a meticulous process analyst who does things"},
            {"role": "user", "content": user_prompt},
        ])
        self.assertLessEqual(len(result["steps"]), 5)

    def test_standards_only_returns_ids_present_in_prompt(self):
        result = _route_response([
            {"role": "system", "content": "You are a government service standards compliance agent."},
            {"role": "user", "content": "Catalog includes STD-01 and STAGE-07 among others."},
        ])
        for std_id in result["applicable_standard_ids"]:
            self.assertIn(std_id, ("STD-01", "STAGE-07"))

    def test_unknown_caller_gets_generic_valid_json(self):
        result = _route_response([
            {"role": "system", "content": "You are an unrecognized future agent."},
            {"role": "user", "content": "anything"},
        ])
        self.assertIsInstance(result, dict)


class StdlibServerHttpTestCase(unittest.TestCase):
    """Drives the zero-dependency stdlib mock server over a real
    HTTP connection (127.0.0.1, ephemeral port), proving the full
    transport layer -- not just the in-process routing function --
    behaves like Ollama's /api/chat."""

    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.thread = start_server(host="127.0.0.1", port=0)
        cls.host = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join(timeout=5)

    def setUp(self):
        os.environ.pop("ZX_MOCK_FAILURE_MODE", None)

    def test_version_and_tags(self):
        version = requests.get(f"{self.host}/api/version", timeout=5)
        self.assertEqual(version.status_code, 200)
        tags = requests.get(f"{self.host}/api/tags", timeout=5)
        self.assertEqual(tags.status_code, 200)
        self.assertTrue(tags.json()["models"])

    def test_chat_success_routes_to_matching_agent(self):
        response = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": "qwen3:4b",
                "messages": [
                    {"role": "system", "content": "You are a government service gap analysis agent."},
                    {"role": "user", "content": "STAGE-01 applies here."},
                ],
                "stream": False,
            },
            timeout=5,
        )
        self.assertEqual(response.status_code, 200)
        content = response.json()["message"]["content"]
        parsed = json.loads(content)
        self.assertIn("gaps", parsed)

    def test_chat_empty_response_failure_mode(self):
        os.environ["ZX_MOCK_FAILURE_MODE"] = "empty_response"
        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json={"model": "qwen3:4b", "messages": [], "stream": False},
                timeout=5,
            )
        finally:
            os.environ.pop("ZX_MOCK_FAILURE_MODE", None)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"]["content"], "")
        self.assertEqual(response.json()["done_reason"], "length")

    def test_chat_500_failure_mode(self):
        os.environ["ZX_MOCK_FAILURE_MODE"] = "chat_500"
        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json={"model": "qwen3:4b", "messages": [], "stream": False},
                timeout=5,
            )
        finally:
            os.environ.pop("ZX_MOCK_FAILURE_MODE", None)
        self.assertEqual(response.status_code, 500)

    def test_chat_invalid_json_failure_mode_returns_malformed_text(self):
        os.environ["ZX_MOCK_FAILURE_MODE"] = "invalid_json"
        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json={"model": "qwen3:4b", "messages": [], "stream": False},
                timeout=5,
            )
        finally:
            os.environ.pop("ZX_MOCK_FAILURE_MODE", None)
        self.assertEqual(response.status_code, 200)
        content = response.json()["message"]["content"]
        with self.assertRaises(json.JSONDecodeError):
            json.loads(content)


if __name__ == "__main__":
    unittest.main()
