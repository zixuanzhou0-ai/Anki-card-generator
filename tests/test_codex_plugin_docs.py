from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_codex_plugin_docs.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_codex_plugin_docs", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CodexPluginDocumentationTests(unittest.TestCase):
    def test_documentation_baseline_is_self_consistent(self) -> None:
        validator = load_validator()
        self.assertEqual(validator.validate_docs(), [])

    def test_m0_is_completed_without_claiming_plugin_completion(self) -> None:
        docs_dir = ROOT / "docs" / "codex-plugin"
        readme = (docs_dir / "README.md").read_text(encoding="utf-8")
        roadmap = (docs_dir / "ROADMAP.md").read_text(encoding="utf-8")
        limitations = (docs_dir / "LIMITATIONS.md").read_text(encoding="utf-8")
        reliability = (docs_dir / "RELIABILITY_AND_VERIFICATION.md").read_text(encoding="utf-8")

        for text in (readme, roadmap, limitations, reliability):
            self.assertIn("V15", text)
            self.assertIn("V14", text)
            self.assertIn("V10", text)
            self.assertIn("preflight", text)
            self.assertIn("真实 Anki", text)

        self.assertIn("M0 已完成", roadmap)
        self.assertIn("下一阶段为 M1", roadmap)
        self.assertIn("M1 Headless Card Service", readme)
        self.assertIn("genanki==0.13.1", readme)
        self.assertIn("不表示所有依赖都已完成哈希锁定", readme)
        self.assertIn("紧贴 `importPackage` 前", readme + roadmap + limitations + reliability)
        self.assertIn("双 collection", readme + roadmap + limitations + reliability)
        self.assertIn("退出码为 1", reliability)
        self.assertNotIn("M0 的 verifier fail-open 仍真实存在", readme + roadmap + limitations + reliability)
        self.assertNotIn("当前 verifier 因 V1 + startswith", readme + roadmap + limitations + reliability)
        self.assertNotIn("Computer Use 当前不可用", readme + roadmap + limitations + reliability)

    def test_release_smoke_cannot_skip_apkg_verifier(self) -> None:
        smoke = (ROOT / "scripts" / "smoke_release.ps1").read_text(encoding="utf-8")
        self.assertIn('throw "Required APKG verifier is missing: $VerifyScript"', smoke)
        self.assertNotIn("if (Test-Path $VerifyScript)", smoke)
        self.assertEqual(smoke.count("& $Python $VerifyScript"), 3)

    def test_m0_verification_report_preserves_evidence_boundaries(self) -> None:
        report = (
            ROOT / "docs" / "codex-plugin" / "M0_VERIFICATION_REPORT_2026-07-17.md"
        ).read_text(encoding="utf-8")

        self.assertIn("20 notes / 20 cards / 52", report)
        self.assertIn("52 个实际媒体 SHA-256", report)
        self.assertIn("20 张连续复习", report)
        self.assertIn("不能证明真人语义", report)
        self.assertIn("不能宣称全部媒体路径都流式化", report)
        self.assertIn("不能把 603 和 576 相加", report)
        self.assertIn("Codex 插件 manifest", report)
        self.assertNotIn("Computer Use 当前不可用", report)
        self.assertNotIn(".tmp", report)
        self.assertNotIn(chr(92).join(("C:", "Users", "")), report)


if __name__ == "__main__":
    unittest.main()
