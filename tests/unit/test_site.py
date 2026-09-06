from __future__ import annotations

import base64
import hashlib
import json
import runpy
from pathlib import Path
from urllib.parse import urljoin

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = runpy.run_path(str(ROOT / "tools/build_site.py"))
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
)


def write(root: Path, relative: str, content: str | bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


@pytest.fixture
def site_source(tmp_path):
    """Exercise the real allowlist and template without unpublished repository assets."""
    root = tmp_path / "source"
    for relative in TOOL["ASSETS"]:
        content = PNG if relative.endswith(".png") else f"fixture: {relative}\n"
        write(root, relative, content)
    for relative in TOOL["DOCUMENTS"]:
        write(root, relative, "# Public guide\n\n## Load cases\n\nFixture documentation.\n")
    write(root, "docs/site/report.html", (ROOT / "docs/site/report.html").read_bytes())
    write(root, "docs/site/index.html", '<h1 id="home">Home</h1>')
    write(root, "examples/cantilever/demo/index.html", '<a href="README.md#load-cases">Guide</a>')
    return root


def parse_page(path):
    parser = TOOL["Links"]()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


@pytest.mark.parametrize("existing_empty", [False, True])
def test_build_publishes_only_allowlisted_sources_and_generated_pages(
    site_source, tmp_path, existing_empty,
):
    private = {
        "docs/site/extra.html", "docs/assets/extra.png", "docs/reports/unreviewed.md",
        "docs/reports/evidence/2026-09-06/private.zip",
        "examples/cantilever/demo/assets/private.mechdb",
        "examples/cantilever/demo/job.rst", "test-records/private.json",
        "build/solver/ds.dat", "private.tar.gz", ".env",
    }
    for relative in private:
        write(site_source, relative, b"PRIVATE: never publish this payload")
    output = tmp_path / "public"
    if existing_empty:
        output.mkdir()
    result = TOOL["build"](site_source, output)
    published = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
    expected = set(TOOL["ASSETS"]) | set(TOOL["DOCUMENTS"]) | set(TOOL["PAGES"].values())
    assert published == expected | {".nojekyll", "site-manifest.json"}
    assert not published & private
    assert all(b"PRIVATE: never publish" not in p.read_bytes() for p in output.rglob("*") if p.is_file())
    for relative in (*TOOL["DOCUMENTS"], "examples/cantilever/simulation.yaml", "docs/assets/overview.png"):
        assert (output / relative).read_bytes() == (site_source / relative).read_bytes()
    assert result["status"] == "PASS"
    assert result["html_pages"] == len(TOOL["DOCUMENTS"]) + 2
    assert result["solver_started"] is False
    assert json.loads((output / "site-manifest.json").read_text()) == result
    assert result["files"] == {
        name: hashlib.sha256((output / name).read_bytes()).hexdigest()
        for name in published - {"site-manifest.json"}
    }


def test_nested_markdown_links_and_anchors_survive_project_deployment(site_source, tmp_path):
    relative = "examples/cantilever/demo/README.md"
    write(site_source, relative, """# Demo guide

## Load cases

[Local](#load-cases)
[Home](../../../README.md#home)
[Guide](../../../docs/windows-testing.md?view=full&lang=en#load-cases)
[Source](../simulation.yaml)
![Preview](../../../docs/assets/overview.png)
""")
    output = tmp_path / "public"
    TOOL["build"](site_source, output)
    page = output / "examples/cantilever/demo/README.html"
    parsed = parse_page(page)
    assert "load-cases" in parsed.ids
    assert {
        "#load-cases", "../../../index.html#home",
        "../../../docs/windows-testing.html?view=full&lang=en#load-cases",
        "../simulation.yaml", "../../../docs/assets/overview.png",
    } <= set(parsed.links)
    base = "https://example.test/SimStudio/examples/cantilever/demo/README.html"
    assert "https://example.test/SimStudio/docs/windows-testing.html?view=full&lang=en#load-cases" in {
        urljoin(base, link) for link in parsed.links
    }
    assert "README.html#load-cases" in parse_page(page.parent / "index.html").links
    assert TOOL["check_site"](output)["status"] == "PASS"


@pytest.mark.parametrize("attribute", ["href", "src"])
def test_build_rejects_unknown_missing_link(site_source, tmp_path, attribute):
    write(site_source, "docs/windows-testing.md",
          f'# Guide\n\n<a {attribute}="missing%20file.json">Missing</a>')
    with pytest.raises(ValueError, match=r"Missing or external public source: docs/missing file\.json"):
        TOOL["build"](site_source, tmp_path / "public")


def test_existing_unpublished_source_links_to_repository_without_copying(site_source, tmp_path):
    write(site_source, "reference notes.md", "# Reference\n")
    write(site_source, "docs/windows-testing.md",
          '# Guide\n\n[Reference](../reference%20notes.md?plain=1#reference)')
    output = tmp_path / "public"
    TOOL["build"](site_source, output)
    assert TOOL["REPO"] + "reference%20notes.md?plain=1#reference" in parse_page(
        output / "docs/windows-testing.html",
    ).links
    assert not (output / "reference notes.md").exists()


@pytest.mark.parametrize("href", ["#absent", "windows-testing.md#absent"])
def test_build_rejects_missing_markdown_anchor(site_source, tmp_path, href):
    write(site_source, "docs/release-preparation.md", f"# Release\n\n[Missing]({href})")
    with pytest.raises(ValueError, match="Missing public anchor"):
        TOOL["build"](site_source, tmp_path / "public")


@pytest.mark.parametrize("href", ["/SimStudio/index.html", "../outside.html", "missing.html"])
def test_check_site_rejects_root_relative_missing_and_escaping_urls(tmp_path, href):
    output = tmp_path / "public"
    write(tmp_path, "outside.html", "<h1>Outside</h1>")
    write(output, "index.html", f'<a href="{href}">Target</a>')
    with pytest.raises(ValueError, match=r"Root-relative URL|Broken public link"):
        TOOL["check_site"](output)


def test_check_site_decodes_anchors_and_resolves_directory_indexes(tmp_path):
    write(tmp_path, "index.html", '<a href="guide/?view=full#load%20case">Guide</a>')
    write(tmp_path, "guide/index.html", '<h1 id="load case">Guide</h1>')
    result = TOOL["check_site"](tmp_path)
    assert result["html_pages"] == 2
    assert result["local_links"] == 1


@pytest.mark.parametrize("sentinel", ["index.html", ".keep", "nested/old.json"])
def test_build_refuses_nonempty_output_without_changing_existing_files(tmp_path, sentinel):
    output = tmp_path / "public"
    path = write(output, sentinel, b"previous publication\x00\xff")
    before = path.read_bytes(), path.stat().st_mtime_ns
    entries = set(output.rglob("*"))
    # A missing source proves that the destination guard runs before source access.
    with pytest.raises(ValueError, match="new or empty site output directory"):
        TOOL["build"](tmp_path / "missing-source", output)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert set(output.rglob("*")) == entries


@pytest.mark.parametrize("directory", [False, True], ids=["file", "parent-directory"])
@pytest.mark.parametrize("external", [False, True], ids=["internal", "external"])
def test_build_rejects_symlinked_sources(
    site_source, tmp_path, create_symlink, directory, external,
):
    link = site_source / ("docs/assets" if directory else "docs/assets/overview.png")
    target = (tmp_path if external else site_source) / "stored-asset"
    link.rename(target)
    create_symlink(link, target, is_directory=directory)
    error = "Missing or external public source" if external else "Symlink in public source"
    with pytest.raises(ValueError, match=error):
        TOOL["build"](site_source, tmp_path / "public")


@pytest.mark.parametrize("kind", ["parent", "absolute", "reentry"])
def test_source_rejects_traversal_even_when_target_exists(tmp_path, kind):
    root = tmp_path / "source"
    root.mkdir()
    outside = write(tmp_path, "outside.txt", "private")
    write(root, "public.txt", "public")
    relative = {
        "parent": "../outside.txt",
        "absolute": str(outside),
        "reentry": "../source/public.txt",
    }[kind]
    with pytest.raises(ValueError, match="Missing or external public source"):
        TOOL["source"](root, relative)


def test_build_rejects_url_encoded_source_escape(site_source, tmp_path):
    write(tmp_path, "outside.txt", "private")
    write(site_source, "docs/windows-testing.md",
          "# Guide\n\n[Outside](%2e%2e/%2e%2e/outside.txt)")
    with pytest.raises(ValueError, match="Missing or external public source"):
        TOOL["build"](site_source, tmp_path / "public")


@pytest.mark.parametrize("attribute", ["href", "HREF", "href = "],
                         ids=["lowercase", "uppercase", "spaced"])
def test_embedded_html_links_are_rewritten_to_readable_markdown_pages(
    site_source, tmp_path, attribute,
):
    assignment = attribute if "=" in attribute else attribute + "="
    write(site_source, "docs/release-preparation.md",
          f'# Release\n\n<a {assignment}"windows-testing.md#load-cases">Guide</a>')
    output = tmp_path / "public"
    TOOL["build"](site_source, output)
    assert "windows-testing.html#load-cases" in parse_page(
        output / "docs/release-preparation.html",
    ).links
