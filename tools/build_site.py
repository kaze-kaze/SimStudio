"""Build the public GitHub Pages site from an explicit source allowlist.

This is an offline documentation build. It cannot invoke an ANSYS solver.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import posixpath
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from string import Template
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import markdown

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/kaze-kaze/SimStudio/blob/main/"
REPORT = "docs/reports/mechanical-test-2026-09-06"
DOCUMENTS = (
    REPORT + ".md", REPORT + ".zh-CN.md", "docs/windows-testing.md",
    "CONTRIBUTING.md", "SECURITY.md", "ROADMAP.md", "CHANGELOG.md",
    "examples/cantilever/README.md", "examples/cantilever/demo/README.md",
)
ASSETS = (
    "docs/site/site.css", "docs/site/icon.svg", "docs/assets/overview.png",
    "LICENSE", "NOTICE", "examples/cantilever/simulation.yaml",
    "examples/cantilever/cantilever.step", "examples/cantilever/expected.json",
    *("examples/cantilever/demo/" + name for name in (
        "index.html", "style.css", "demo.js", "evidence.js",
        "assets/mesh.png", "assets/total-deformation.png", "assets/equivalent-stress.png",
    )),
    *("docs/reports/evidence/2026-09-06/" + name for name in (
        "summary.json", "cases.json", "provenance.json",
    )),
)
PAGES = {name: name.removesuffix(".md") + ".html" for name in DOCUMENTS}
PAGES["README.md"] = "index.html"


def source(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = root / relative
    if ".." in Path(relative).parts or not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError(f"Missing or external public source: {relative}")
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError(f"Symlink in public source: {relative}")
        current = current.parent
    return path


def rewrite_links(content: str, relative: str, root: Path) -> str:
    """Retain project-relative URLs, mapping hosted Markdown to readable pages."""
    def replace(match: re.Match) -> str:
        attribute, delimiter, href = match.groups()
        parts = urlsplit(html.unescape(href))
        if parts.scheme or parts.netloc or not parts.path or parts.path.startswith("/"):
            return match.group()
        target = posixpath.normpath(posixpath.join(posixpath.dirname(relative), unquote(parts.path)))
        if target in PAGES:
            new = posixpath.relpath(PAGES[target], posixpath.dirname(relative) or ".")
        elif target in ASSETS or target in DOCUMENTS or target == "index.html" or target in PAGES.values():
            return match.group()
        else:
            source(root, target)
            new = REPO + quote(target, safe="/")
        value = urlunsplit(("", "", new, parts.query, parts.fragment))
        return attribute + "=" + delimiter + html.escape(value, quote=True) + delimiter
    return re.sub(r"(?<![\w:-])(href|src)\s*=\s*([\"'])(.*?)\2", replace, content, flags=re.I | re.S)


def render_document(relative: str, root: Path) -> str:
    text = source(root, relative).read_text(encoding="utf-8")
    renderer = markdown.Markdown(extensions=["extra", "toc", "sane_lists"])
    body = rewrite_links(renderer.convert(text), relative, root)
    body = body.replace("<table>", '<div class="table-scroll" tabindex="0" role="region" aria-label="Data table"><table>').replace("</table>", "</table></div>")
    heading = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    if heading is None:
        raise ValueError(f"Public document requires a level-one title: {relative}")
    title = re.sub(r"<[^>]+>", "", heading[1])
    chinese = "zh-CN" in relative
    prefix = posixpath.relpath(".", posixpath.dirname(relative) or ".") + "/"
    language_link = ""
    if relative.startswith(REPORT + "."):
        other = "mechanical-test-2026-09-06" + (".html" if chinese else ".zh-CN.html")
        label = "English" if chinese else "简体中文"
        language_link = f'<a href="{other}">{label}</a>'
    return Template(source(root, "docs/site/report.html").read_text(encoding="utf-8")).substitute(
        lang="zh-CN" if chinese else "en", title=html.escape(html.unescape(title)),
        description=html.escape(html.unescape(title) + " — SimStudio public documentation."),
        root=prefix, body=body, toc=renderer.toc, language_link=language_link,
        source_url=REPO + quote(relative, safe="/"),
        skip_label="跳转到正文" if chinese else "Skip to content",
        contents_label="本页目录" if chinese else "ON THIS PAGE",
        demo_label="悬臂梁实例" if chinese else "Cantilever demo",
        source_label="查看原文" if chinese else "View source",
        home_label="项目首页" if chinese else "Project home",
        category="TEST REPORT" if relative.startswith(REPORT + ".") else "DOCUMENTATION",
    )


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        for attribute in ("src", "href"):
            if attrs.get(attribute):
                self.links.append(attrs[attribute])


def check_site(directory: Path) -> dict:
    pages = {}
    for path in directory.rglob("*.html"):
        parser = Links()
        parser.feed(path.read_text(encoding="utf-8"))
        pages[path.resolve()] = parser
    count = 0
    for path, parser in pages.items():
        for href in parser.links:
            parts = urlsplit(href)
            if parts.scheme or parts.netloc:
                continue
            if parts.path.startswith("/"):
                raise ValueError(f"Root-relative URL breaks project Pages: {href}")
            target = (path.parent / unquote(parts.path)).resolve() if parts.path else path
            if target.is_dir():
                target /= "index.html"
            if not target.is_relative_to(directory.resolve()) or not target.is_file():
                raise ValueError(f"Broken public link in {path.name}: {href}")
            if parts.fragment and target in pages and unquote(parts.fragment) not in pages[target].ids:
                raise ValueError(f"Missing public anchor in {path.name}: {href}")
            count += 1
    return {"status": "PASS", "html_pages": len(pages), "local_links": count, "solver_started": False}


def build(root: Path, output: Path) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new or empty site output directory")
    output.mkdir(parents=True, exist_ok=True)
    for relative in (*ASSETS, *DOCUMENTS):
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source(root, relative), target)
    homepage = source(root, "docs/site/index.html").read_text(encoding="utf-8")
    (output / "index.html").write_text(homepage, encoding="utf-8", newline="\n")
    demo = output / "examples/cantilever/demo/index.html"
    demo.write_text(rewrite_links(demo.read_text(encoding="utf-8"),
                                  "examples/cantilever/demo/index.html", root),
                    encoding="utf-8", newline="\n")
    for relative in DOCUMENTS:
        (output / PAGES[relative]).write_text(render_document(relative, root),
                                             encoding="utf-8", newline="\n")
    (output / ".nojekyll").touch()
    result = check_site(output)
    result["files"] = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted(output.rglob("*")) if p.is_file()}
    (output / "site-manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/site")
    parser.add_argument("--check", type=Path, help="Check an already-built site instead")
    args = parser.parse_args()
    try:
        result = check_site(args.check) if args.check else build(ROOT, args.out)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
