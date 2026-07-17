from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs" / "codex-plugin"

REQUIRED_DOCUMENTS = {
    "ARCHITECTURE.md",
    "BENCHMARK_AND_EVALUATION.md",
    "DECISIONS.md",
    "DESIGN_REVIEW_RECORD.md",
    "GLOSSARY.md",
    "LEARNING_DESIGN.md",
    "LIMITATIONS.md",
    "M0_VERIFICATION_REPORT_2026-07-17.md",
    "MCP_TOOL_REFERENCE.md",
    "PLUGIN_PACKAGE_REFERENCE.md",
    "PRODUCT_SPEC.md",
    "README.md",
    "RELIABILITY_AND_VERIFICATION.md",
    "ROADMAP.md",
    "SECURITY_AND_PRIVACY.md",
    "SKILL_BEHAVIOR.md",
    "SOURCE_ADAPTERS.md",
    "STUDY_IR_REFERENCE.md",
    "TRACEABILITY_MATRIX.md",
    "USER_JOURNEYS.md",
    "UX_AND_HOST_SURFACES.md",
}

LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
STATUS_MARKERS = ("CURRENT", "PROPOSED", "DEFERRED", "EXPERIMENT")


def _fence_issues(path: Path, text: str) -> list[str]:
    issues: list[str] = []
    open_fence: tuple[str, int, int] | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = FENCE_RE.match(line)
        if not match:
            continue
        token = match.group(1)
        if open_fence is None:
            open_fence = (token[0], len(token), line_number)
        elif token[0] == open_fence[0] and len(token) >= open_fence[1]:
            open_fence = None
    if open_fence is not None:
        issues.append(f"{path.name}:{open_fence[2]} has an unclosed Markdown fence")
    return issues


def _link_issues(path: Path, text: str) -> list[str]:
    issues: list[str] = []
    for raw_target in LINK_RE.findall(text):
        target = raw_target.strip().strip("<>")
        parsed = urlsplit(target)
        if parsed.scheme or target.startswith("#"):
            continue
        relative_path = unquote(parsed.path)
        if not relative_path:
            continue
        resolved = (path.parent / relative_path).resolve()
        try:
            resolved.relative_to(ROOT.resolve())
        except ValueError:
            issues.append(f"{path.name}: link escapes the repository: {raw_target}")
            continue
        if not resolved.exists():
            issues.append(f"{path.name}: missing local link target: {raw_target}")
    return issues


def validate_docs() -> list[str]:
    issues: list[str] = []
    actual_documents = {path.name for path in DOCS_DIR.glob("*.md")}
    missing = sorted(REQUIRED_DOCUMENTS - actual_documents)
    if missing:
        issues.append("missing required documents: " + ", ".join(missing))

    readme_targets: set[str] = set()
    readme_path = DOCS_DIR / "README.md"
    if readme_path.exists():
        readme_text = readme_path.read_text(encoding="utf-8")
        for target in LINK_RE.findall(readme_text):
            parsed = urlsplit(target.strip().strip("<>"))
            if not parsed.scheme and parsed.path.lower().endswith(".md"):
                readme_targets.add(Path(unquote(parsed.path)).name)
        missing_from_map = sorted((REQUIRED_DOCUMENTS - {"README.md"}) - readme_targets)
        if missing_from_map:
            issues.append("README document map omits: " + ", ".join(missing_from_map))

    for path in sorted(DOCS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if not lines or not lines[0].startswith("# "):
            issues.append(f"{path.name}: first line must be a level-one title")
        header = "\n".join(lines[:12])
        if not any(marker in header for marker in STATUS_MARKERS):
            issues.append(f"{path.name}: header has no CURRENT/PROPOSED/DEFERRED/EXPERIMENT marker")
        if "日期：" not in header:
            issues.append(f"{path.name}: header has no baseline date")
        issues.extend(_fence_issues(path, text))
        issues.extend(_link_issues(path, text))

    package_reference = DOCS_DIR / "PLUGIN_PACKAGE_REFERENCE.md"
    if package_reference.exists():
        text = package_reference.read_text(encoding="utf-8")
        if '"mcp_servers"' in text:
            issues.append("PLUGIN_PACKAGE_REFERENCE.md: obsolete mcp_servers key is forbidden")
        for required_text in ('"mcpServers"', "agents/", "openai.yaml"):
            if required_text not in text:
                issues.append(f"PLUGIN_PACKAGE_REFERENCE.md: missing {required_text}")
    return issues


def main() -> int:
    issues = validate_docs()
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}")
        return 1
    print(f"Validated {len(REQUIRED_DOCUMENTS)} Codex plugin design documents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
