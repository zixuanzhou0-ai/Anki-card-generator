from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from card_service.mcp_anki_tools import ANKI_TOOL_NAMES
from card_service.mcp_candidate_tools import CANDIDATE_TOOL_NAMES
from card_service.mcp_card_plan_tools import CARD_PLAN_TOOL_NAMES
from card_service.mcp_card_tools import CARD_TOOL_NAMES
from card_service.mcp_input_tools import INPUT_TOOL_NAMES
from card_service.mcp_inspection_tools import INSPECTION_TOOL_NAMES
from card_service.mcp_package_tools import PACKAGE_TOOL_NAMES
from card_service.mcp_project_tools import PROJECT_TOOL_NAMES
from card_service.mcp_resource_tools import RESOURCE_GRANT_TOOL_NAMES
from card_service.mcp_selection_tools import SELECTION_TOOL_NAMES
from card_service.mcp_stdio import CAPABILITY_TOOL_NAME
from card_service.mcp_system_tools import SYSTEM_TOOL_NAMES
from card_service.mcp_task_tools import TASK_TOOL_NAMES


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

    def test_current_skill_workflow_names_only_real_public_tools(self) -> None:
        workflow = (SKILL / "references" / "workflow-contract.md").read_text(encoding="utf-8")
        current_workflow = workflow.split("## Current public tool workflow", 1)[1].split(
            "## Planned but unavailable tools", 1
        )[0]
        named_tools = set(
            re.findall(r"`((?:system|study|cards|anki)\.[a-z0-9_]+)`", current_workflow)
        )
        public_tools = {
            CAPABILITY_TOOL_NAME,
            *RESOURCE_GRANT_TOOL_NAMES,
            *SYSTEM_TOOL_NAMES,
            *PROJECT_TOOL_NAMES,
            *INPUT_TOOL_NAMES,
            *INSPECTION_TOOL_NAMES,
            *CANDIDATE_TOOL_NAMES,
            *SELECTION_TOOL_NAMES,
            *CARD_PLAN_TOOL_NAMES,
            *CARD_TOOL_NAMES,
            *PACKAGE_TOOL_NAMES,
            *TASK_TOOL_NAMES,
            *ANKI_TOOL_NAMES,
        }
        self.assertEqual(named_tools, public_tools)

        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        skill_named_tools = set(
            re.findall(r"`((?:system|study|cards|anki)\.[a-z0-9_]+)`", skill_text)
        )
        self.assertLessEqual(skill_named_tools, public_tools)

    def test_skill_metadata_requires_explicit_skill_name_in_default_prompt(self) -> None:
        metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('display_name: "Anki Study Agent"', metadata)
        self.assertIn("$anki-study-agent", metadata)


if __name__ == "__main__":
    unittest.main()
