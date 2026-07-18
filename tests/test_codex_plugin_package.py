from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "anki-study-agent"
SKILL = PLUGIN / "skills" / "anki-study-agent"


class CodexPluginPackageTests(unittest.TestCase):
    def test_passive_manifest_is_installable_without_fake_runtime_components(self) -> None:
        manifest_path = PLUGIN / ".codex-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(PLUGIN.name, "anki-study-agent")
        self.assertEqual(manifest["name"], PLUGIN.name)
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertNotIn("mcpServers", manifest)
        self.assertNotIn("apps", manifest)
        self.assertNotIn("hooks", manifest)
        self.assertFalse((PLUGIN / ".mcp.json").exists())
        self.assertFalse((PLUGIN / ".app.json").exists())

        prompts = manifest["interface"]["defaultPrompt"]
        self.assertIsInstance(prompts, list)
        self.assertGreaterEqual(len(prompts), 1)
        self.assertLessEqual(len(prompts), 3)
        self.assertTrue(all(isinstance(prompt, str) and len(prompt) <= 128 for prompt in prompts))

    def test_skill_has_no_placeholders_and_routes_to_complete_contracts(self) -> None:
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("[TODO:", skill_text)
        self.assertTrue(skill_text.startswith("---\nname: anki-study-agent\n"))
        self.assertIn("system.get_capabilities", skill_text)
        self.assertIn("local plugin runtime is not registered", skill_text)

        references = {
            "learning-contract.md",
            "workflow-contract.md",
            "source-and-safety.md",
        }
        for reference in references:
            self.assertIn(f"(references/{reference})", skill_text)
            reference_text = (SKILL / "references" / reference).read_text(encoding="utf-8")
            self.assertGreater(len(reference_text.strip()), 200)
            self.assertNotIn("[TODO:", reference_text)

    def test_skill_metadata_requires_explicit_skill_name_in_default_prompt(self) -> None:
        metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('display_name: "Anki Study Agent"', metadata)
        self.assertIn("$anki-study-agent", metadata)


if __name__ == "__main__":
    unittest.main()
