import subprocess
import json
import asyncio
import tempfile
import subprocess
import unittest
import uuid
from types import SimpleNamespace
from os import chdir, getcwd
from pathlib import Path

import code_reviewer


class FakeScenarioTests(unittest.TestCase):
    """Fake scenario: detect a hard-coded secret and approve its patch."""

    def test_parse_review_and_apply_approved_patch(self):
        review = code_reviewer.parse_json_response(
            '{"issues":[{"title":"Secret","severity":"critical","file":"app.py",'
            '"line":"1","description":"Credential is committed.","solution":"Use an environment variable."}]}'
        )
        self.assertEqual(review["issues"][0]["severity"], "critical")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "app.py").write_text('TOKEN = "secret"\n', encoding="utf-8")
            patch_text = """--- a/app.py
+++ b/app.py
@@ -1 +1,2 @@
-TOKEN = "secret"
+import os
+TOKEN = os.environ["TOKEN"]
"""
            original_directory = getcwd()
            try:
                chdir(root)
                code_reviewer.apply_patch(patch_text, lambda _: None)
                self.assertEqual(
                    (root / "app.py").read_text(encoding="utf-8"),
                    'import os\nTOKEN = os.environ["TOKEN"]\n',
                )
            finally:
                chdir(original_directory)

    def test_invalid_review_is_rejected(self):
        with self.assertRaises(ValueError):
            code_reviewer.parse_json_response("not json")

    def test_assistant_lookup_works_with_sdk_without_name_filter(self):
        class FakeClient:
            def __init__(self):
                self.created = False

            async def list_assistants(self, limit=100):
                self.limit = limit
                return [SimpleNamespace(name="CodeReviewer", assistant_id=uuid.UUID(int=1))]

            async def create_assistant(self, **kwargs):
                self.created = True
                return SimpleNamespace(assistant_id="new-assistant")

        with tempfile.TemporaryDirectory() as directory:
            assistant_file = Path(directory) / "codeReviewer.json"
            client = FakeClient()
            assistant_id = asyncio.run(
                code_reviewer.load_or_create_assistant(client, assistant_file, lambda _: None)
            )
            self.assertEqual(assistant_id, str(uuid.UUID(int=1)))
            self.assertFalse(client.created)
            self.assertEqual(json.loads(assistant_file.read_text())["assistant_id"], str(uuid.UUID(int=1)))


if __name__ == "__main__":
    unittest.main()
