from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
STATIC_SKILL = ROOT / "skills" / "ansys-mechanical-static"
STUDY_SKILL = ROOT / "skills" / "ansys-design-study"


def test_plugin_manifest_structure() -> None:
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "text-to-ansys"
    assert manifest["version"] == "0.1.0"
    assert manifest["skills"] == "./skills/"
    assert manifest["interface"]["displayName"] == "text-to-ansys"
    assert "hooks" not in manifest
    assert "apps" not in manifest
    assert "mcpServers" not in manifest


def test_local_marketplace_structure() -> None:
    marketplace = json.loads(
        (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert marketplace["name"] == "text-to-ansys-local"
    assert marketplace["interface"]["displayName"]
    assert len(marketplace["plugins"]) == 1
    plugin = marketplace["plugins"][0]
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert plugin["name"] == manifest["name"]
    assert plugin["source"] == {"source": "local", "path": "./"}
    assert plugin["policy"] == {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }
    assert plugin["category"] == "Engineering"


def test_both_skill_frontmatter_and_openai_metadata() -> None:
    expectations = {
        STATIC_SKILL: "ansys-mechanical-static",
        STUDY_SKILL: "ansys-design-study",
    }
    for skill_path, name in expectations.items():
        content = (skill_path / "SKILL.md").read_text(encoding="utf-8")
        _, frontmatter, body = content.split("---", 2)
        metadata = yaml.safe_load(frontmatter)
        assert metadata["name"] == name
        assert metadata["description"]
        openai = yaml.safe_load((skill_path / "agents" / "openai.yaml").read_text(encoding="utf-8"))
        assert openai["interface"]["display_name"]
        assert 25 <= len(openai["interface"]["short_description"]) <= 64
        assert ("$" + name) in openai["interface"]["default_prompt"]
        assert openai["policy"]["allow_implicit_invocation"] is True
        assert body.strip()

    static_text = (STATIC_SKILL / "SKILL.md").read_text(encoding="utf-8")
    static_description = static_text.split("---", 2)[1]
    assert "mechdat" in static_description
    assert "批量静力求解" in static_description
    assert "基于模板修改载荷并生成报告" in static_description
    assert "theoretical finite-element" in static_description
    assert "Required workflow" in static_text
    assert "$ansys-mechanical-static" in (
        STATIC_SKILL / "agents" / "openai.yaml"
    ).read_text(encoding="utf-8")

    study_text = (STUDY_SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "study-wide solver-call ceiling" in study_text
    assert "REVIEW_REQUIRED" in study_text
    assert "not pickle" in study_text
    assert "$ansys-design-study" in (
        STUDY_SKILL / "agents" / "openai.yaml"
    ).read_text(encoding="utf-8")


def test_two_skill_sources_and_no_symlinks() -> None:
    skills = set(ROOT.glob("skills/**/SKILL.md"))
    assert skills == {STATIC_SKILL / "SKILL.md", STUDY_SKILL / "SKILL.md"}
    published_roots = [
        ROOT / ".codex-plugin",
        ROOT / "skills",
        ROOT / "examples",
        ROOT / "schemas",
    ]
    assert not any(
        path.is_symlink()
        for published_root in published_roots
        for path in published_root.rglob("*")
    )


def test_no_scaffold_placeholders() -> None:
    for path in [ROOT / ".codex-plugin" / "plugin.json", *(ROOT / "skills").glob("*/SKILL.md")]:
        assert "[TODO:" not in path.read_text(encoding="utf-8")


def test_required_references_exist() -> None:
    static_refs = {
        "simulation-brief.md", "schema-reference.md", "supported-scope.md",
        "mechanical-execution.md", "dpf-postprocessing.md", "validation-policy.md",
        "visual-review.md", "failure-recovery.md", "official-api-map.md", "engineering-safety.md",
    }
    study_refs = {
        "workflow.md", "specification.md", "quality-evidence.md",
        "portability-windows.md", "surrogates.md",
    }
    assert {path.name for path in (STATIC_SKILL / "references").glob("*.md")} == static_refs
    assert {path.name for path in (STUDY_SKILL / "references").glob("*.md")} == study_refs
    assert (STUDY_SKILL / "LICENSE").is_file()
