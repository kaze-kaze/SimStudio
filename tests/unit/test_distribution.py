from __future__ import annotations

import io
import json
import runpy
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest
from setuptools.command.egg_info import FileList

ROOT = Path(__file__).resolve().parents[2]
TOOL = runpy.run_path(str(ROOT / "tools/check_distribution.py"))
CORE = {
    "README.zh-CN.md", "docs/assets/overview.png", "docs/site/index.html",
    "docs/site/site.css", "docs/site/report.html", "tools/build_site.py",
}
OPTIONAL = {
    "docs/site/site.js", "docs/site/README.md", "tools/check_site.py",
    "docs/site/icons/mark.svg", "docs/assets/mark.svg",
}


def archive(tmp_path, names, *, kind="tar.gz", prefix="text_to_ansys-0.1.0/"):
    path = tmp_path / ("text_to_ansys-0.1.0." + kind)
    if kind in {"zip", "whl"}:
        with zipfile.ZipFile(path, "w") as output:
            for name in names:
                member = zipfile.ZipInfo(prefix + name)
                # Preserve malformed foreign names instead of Windows separator normalization.
                member.filename = prefix + name
                output.writestr(member, b"public source fixture")
    else:
        with tarfile.open(path, "w:gz") as output:
            for name in names:
                content = b"public source fixture"
                member = tarfile.TarInfo(prefix + name)
                member.size = len(content)
                output.addfile(member, io.BytesIO(content))
    return path


@pytest.mark.parametrize("kind", ["tar.gz", "zip"])
def test_source_contract_accepts_core_without_optional_files(tmp_path, kind):
    required = TOOL["REQUIRED"]
    assert required >= CORE
    assert not OPTIONAL & required
    result = TOOL["inspect"](archive(tmp_path, required, kind=kind))
    assert result["status"] == "PASS"
    assert result["kind"] == ("source_zip" if kind == "zip" else "sdist")


@pytest.mark.parametrize("missing", sorted(CORE))
def test_source_contract_rejects_missing_presentation_sources(tmp_path, missing):
    path = archive(tmp_path, TOOL["REQUIRED"] - {missing})
    with pytest.raises(ValueError) as error:
        TOOL["inspect"](path)
    assert json.loads(str(error.value)) == {"missing": [missing], "forbidden": []}


@pytest.mark.parametrize("kind", ["tar.gz", "zip"])
@pytest.mark.parametrize(
    "name",
    [
        "BUILD/saved.json", "test-records/archive.json", "docs/site/result.RST",
        "docs/site/ds.dat", "docs/site/solver/state.json", "docs/assets/license/AnsysCL.log",
        "docs/site/private.zip", "../escaped.md", "docs\\site\\private.mechdb",
    ],
)
def test_source_rejects_private_artifacts_and_unsafe_paths(tmp_path, kind, name):
    path = archive(tmp_path, [*TOOL["REQUIRED"], name], kind=kind)
    with pytest.raises(ValueError) as error:
        TOOL["inspect"](path)
    assert any(name in value for value in json.loads(str(error.value))["forbidden"])


@pytest.mark.parametrize("prefix", ["/", "../", "C:/", "build/", ""])
def test_archive_root_is_checked_before_stripping(tmp_path, prefix):
    with pytest.raises(ValueError):
        TOOL["inspect"](archive(tmp_path, TOOL["REQUIRED"], prefix=prefix))


@pytest.mark.parametrize("kind", ["tar.gz", "zip"])
def test_source_rejects_case_collisions_and_multiple_roots(tmp_path, kind):
    path = archive(tmp_path, [*TOOL["REQUIRED"], "readme.md"], kind=kind)
    with pytest.raises(ValueError, match=r"readme\.md"):
        TOOL["inspect"](path)
    path = archive(tmp_path, [*("one/" + name for name in TOOL["REQUIRED"]), "two/extra.md"],
                   prefix="", kind=kind)
    with pytest.raises(ValueError, match=r"two/extra\.md"):
        TOOL["inspect"](path)


@pytest.mark.parametrize("kind", ["tar", "zip"])
def test_archive_links_are_rejected_without_extraction(tmp_path, kind):
    path = tmp_path / ("linked." + kind)
    name = "package/docs/site/linked.html"
    if kind == "tar":
        with tarfile.open(path, "w") as output:
            for link_type in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                member = tarfile.TarInfo(name)
                member.type = link_type
                member.linkname = "../../private.txt"
                output.addfile(member)
    else:
        with zipfile.ZipFile(path, "w") as output:
            member = zipfile.ZipInfo(name)
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            output.writestr(member, "../../private.txt")
    with pytest.raises(ValueError, match=r"linked\.html"):
        TOOL["inspect"](path)


def test_wheel_is_cli_only_and_main_preserves_json_and_exit_codes(tmp_path, monkeypatch, capsys):
    names = ["ansys_skill/cli.py", "text_to_ansys-0.1.0.dist-info/METADATA",
             "text_to_ansys-0.1.0.dist-info/licenses/LICENSE"]
    archive(tmp_path, names, kind="whl", prefix="")
    monkeypatch.setattr("sys.argv", ["check_distribution.py", str(tmp_path)])
    assert TOOL["main"]() == 0
    result = capsys.readouterr()
    assert not result.err
    assert json.loads(result.out)["artifacts"][0]["scope"] == "CLI only"
    archive(tmp_path, [*names, "docs/site/index.html"], kind="whl", prefix="")
    assert TOOL["main"]() == 1
    result = capsys.readouterr()
    assert not result.out
    assert json.loads(result.err)["forbidden"] == ["docs/site/index.html"]


def test_manifest_includes_public_site_assets_and_excludes_local_solver_outputs(tmp_path, monkeypatch):
    public = TOOL["REQUIRED"] | OPTIONAL
    private = {"build/secret.json", "test-records/secret.json", "docs/site/job.rst",
               "docs/site/job.dat", "docs/site/ansyscl.log"}
    for name in public | private:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"manifest fixture")
    monkeypatch.chdir(tmp_path)
    files = FileList()
    files.findall()
    for line in (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines():
        files.process_template_line(line)
    included = {Path(name).as_posix() for name in files.files}
    assert public <= included
    assert not private & included
