from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "ansys-mechanical-static"


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


def test_skill_frontmatter_and_openai_metadata() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    assert metadata["name"] == "ansys-mechanical-static"
    assert "mechdat" in metadata["description"]
    assert "批量静力求解" in metadata["description"]
    assert "基于模板修改载荷并生成报告" in metadata["description"]
    assert "theoretical finite-element" in metadata["description"]
    assert "Required workflow" in body
    openai = yaml.safe_load((SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    assert openai["interface"]["display_name"]
    assert "$ansys-mechanical-static" in openai["interface"]["default_prompt"]


def test_single_skill_source_and_no_symlinks() -> None:
    skills = list(ROOT.glob("skills/**/SKILL.md"))
    assert skills == [SKILL / "SKILL.md"]
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
    for path in [ROOT / ".codex-plugin" / "plugin.json", SKILL / "SKILL.md"]:
        assert "[TODO:" not in path.read_text(encoding="utf-8")


def test_required_references_exist() -> None:
    required = {
        "simulation-brief.md",
        "schema-reference.md",
        "supported-scope.md",
        "mechanical-execution.md",
        "dpf-postprocessing.md",
        "validation-policy.md",
        "visual-review.md",
        "failure-recovery.md",
        "official-api-map.md",
        "engineering-safety.md",
    }
    assert {path.name for path in (SKILL / "references").glob("*.md")} == required
