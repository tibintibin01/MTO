from pathlib import Path
from copy import deepcopy
import json
import shutil
import pytest
import tomllib

from scripts.check_dependency_policy import (
    EXACT_DEVELOPMENT_TOOLS,
    EXACT_FRONTEND_MINIMUMS,
    EXACT_RUNTIME_MINIMUMS,
    PROJECT_ROOT,
    parse_direct_requirements,
    parse_hash_lock,
    validate_lock_portability,
    validate_repository,
    validate_workflow_action_pins,
    check_frontend_transitive_security,
    check_guarded_frontend_package,
    _check_exact_versions,
    _check_minimums,
)


@pytest.mark.parametrize("version,valid", [("0.12.18", False), ("0.13.4", True)])
def test_lock_generator_uses_reviewed_patched_version(version, valid):
    assert EXACT_DEVELOPMENT_TOOLS["uv"] == "0.13.4"
    findings = _check_exact_versions(
        {"uv": version}, {"uv": "0.13.4"}, Path("dev-requirements.txt"), "BUILD"
    )
    assert (findings == []) is valid


@pytest.mark.parametrize(
    "name,old,new",
    [
        ("black", "26.3.1", "26.10.1"),
        ("brotli", "1.2.0", "1.2.1"),
        ("filelock", "3.32.6", "4.2.1"),
        ("msgpack", "1.2.2", "1.2.3"),
        ("setuptools", "84.0.0", "84.1.0"),
    ],
)
def test_reviewed_build_security_pins_reject_previous_versions(name, old, new):
    assert EXACT_DEVELOPMENT_TOOLS[name] == new
    path = Path("dev-requirements.txt")
    assert _check_exact_versions({name: old}, {name: new}, path, "BUILD")
    assert not _check_exact_versions({name: new}, {name: new}, path, "BUILD")


def test_build_backend_uses_the_same_patched_setuptools_pin():
    project = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert (
        "setuptools==" + EXACT_DEVELOPMENT_TOOLS["setuptools"]
        in project["build-system"]["requires"]
    )


def test_msgpack_security_pin_is_development_only():
    runtime, runtime_findings = parse_direct_requirements(
        PROJECT_ROOT / "requirements.txt"
    )
    runtime_lock, lock_findings = parse_hash_lock(PROJECT_ROOT / "requirements.lock")
    development, dev_findings = parse_direct_requirements(
        PROJECT_ROOT / "dev-requirements.txt"
    )
    dev_lock, dev_lock_findings = parse_hash_lock(
        PROJECT_ROOT / "dev-requirements.lock"
    )
    assert not runtime_findings + lock_findings + dev_findings + dev_lock_findings
    assert "msgpack" not in runtime and "msgpack" not in runtime_lock
    assert development["msgpack"] == dev_lock["msgpack"] == "1.2.3"


@pytest.mark.parametrize(
    "name,old_version,patched_version",
    [("pillow", "12.3.0", "13.0.0"), ("certifi", "2026.7.22", "2026.10.19")],
)
def test_image_and_public_tls_security_floors(name, old_version, patched_version):
    minimum = {name: EXACT_RUNTIME_MINIMUMS[name]}
    assert minimum[name] == patched_version
    assert [
        row["code"]
        for row in _check_minimums(
            {name: old_version}, minimum, Path("requirements.txt"), "PYTHON"
        )
    ] == ["PYTHON_SECURITY_FLOOR"]
    assert (
        _check_minimums(
            {name: patched_version}, minimum, Path("requirements.txt"), "PYTHON"
        )
        == []
    )


def test_indexed_source_map_vulnerability_is_rejected_in_nested_copies():
    findings = check_frontend_transitive_security(
        {"node_modules/next/node_modules/source-map-js": {"version": "1.2.1"}},
        Path("package-lock.json"),
    )
    assert [row["code"] for row in findings] == ["FRONTEND_TRANSITIVE_SECURITY_FLOOR"]


def test_patched_source_map_dependency_is_accepted():
    assert (
        check_frontend_transitive_security(
            {"node_modules/source-map-js": {"version": "1.2.2"}},
            Path("package-lock.json"),
        )
        == []
    )


def test_unversioned_source_map_dependency_fails_closed():
    assert (
        check_frontend_transitive_security(
            {"node_modules/source-map-js": {}}, Path("package-lock.json")
        )[0]["code"]
        == "FRONTEND_TRANSITIVE_INVALID_VERSION"
    )


@pytest.mark.parametrize(
    "name,old,new",
    [("next", "16.3.8", "16.4.3"), ("eslint-config-next", "16.3.8", "16.4.3")],
)
def test_website_framework_security_floor(name, old, new):
    assert EXACT_FRONTEND_MINIMUMS[name] == new
    assert _check_minimums({name: old}, {name: new}, Path("package.json"), "WEB")
    assert not _check_minimums({name: new}, {name: new}, Path("package.json"), "WEB")


@pytest.mark.parametrize("name,patched", [("undici", "6.29.1"), ("zod", "4.6.6")])
@pytest.mark.parametrize("version", [None, "old", "unreviewed_major", "patched"])
def test_website_security_pins_apply_to_every_nested_copy(name, patched, version):
    actual = {
        None: None,
        "old": "6.28.1" if name == "undici" else "4.4.3",
        "unreviewed_major": "7.0.0" if name == "undici" else "5.0.0",
        "patched": patched,
    }[version]
    locked = {"node_modules/parent/node_modules/" + name: {"version": actual}}
    findings = check_frontend_transitive_security(locked, Path("package-lock.json"))
    assert (findings == []) == (version == "patched")


def test_website_security_overrides_match_the_reviewed_lock():
    package = json.loads((PROJECT_ROOT / "frontend/package.json").read_text())
    for name, patched in {"undici": "6.29.1", "zod": "4.6.6"}.items():
        assert package["overrides"][name] == patched
    assert package["dependencies"]["@serwist/next"] == "9.5.12"
    assert package["devDependencies"]["serwist"] == "9.5.12"


def test_repository_dependency_policy_passes():
    findings, counts = validate_repository(PROJECT_ROOT)

    assert findings == []
    assert counts["runtime_direct"] > 0
    assert counts["frontend_locked"] > counts["frontend_direct"]


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "changed_code",
        "missing_checksum",
        "arbitrary_path",
        "runtime",
        "upstream_copy",
        "lifecycle_hook",
    ],
)
def test_local_build_backport_is_exact_source_only_not_a_general_pin_bypass(
    tmp_path, case
):
    folder = tmp_path / "frontend/vendor/braces-guarded"
    shutil.copytree(PROJECT_ROOT / "frontend/vendor/braces-guarded", folder)
    package = json.loads((PROJECT_ROOT / "frontend/package.json").read_text())
    locked = deepcopy(
        json.loads((PROJECT_ROOT / "frontend/package-lock.json").read_text())[
            "packages"
        ]
    )
    if case == "changed_code":
        (folder / "lib/guard.js").write_text("module.exports={};\n")
    elif case == "missing_checksum":
        (folder / "PATCH-SHA256.json").unlink()
    elif case == "arbitrary_path":
        package["devDependencies"]["braces"] = "file:../../other"
    elif case == "runtime":
        locked["vendor/braces-guarded"]["dev"] = False
        package["dependencies"]["braces"] = package["devDependencies"].pop("braces")
    elif case == "upstream_copy":
        locked["node_modules/any/node_modules/braces"] = {
            "version": "3.0.3",
            "dev": True,
        }
    elif case == "lifecycle_hook":
        manifest = json.loads((folder / "package.json").read_text())
        manifest["scripts"] = {"postinstall": "unexpected-command"}
        (folder / "package.json").write_text(json.dumps(manifest))
    findings = check_guarded_frontend_package(tmp_path, package, locked)
    assert (findings == []) == (case == "valid")
    assert all(row["code"] == "FRONTEND_BUILD_BACKPORT_INVALID" for row in findings)


def test_desktop_packager_is_an_exact_reviewed_direct_dependency():
    packages, findings = parse_direct_requirements(
        PROJECT_ROOT / "dev-requirements.txt"
    )

    assert findings == []
    assert packages["pyinstaller"] == EXACT_DEVELOPMENT_TOOLS["pyinstaller"]


def test_unpinned_python_dependency_is_rejected(tmp_path: Path):
    manifest = tmp_path / "requirements.txt"
    manifest.write_text("fastapi>=1.0\n", encoding="utf-8")

    packages, findings = parse_direct_requirements(manifest)

    assert packages == {}
    assert [item["code"] for item in findings] == ["PYTHON_NOT_EXACTLY_PINNED"]


def test_python_lock_entry_requires_sha256(tmp_path: Path):
    lock = tmp_path / "requirements.lock"
    lock.write_text("fastapi==1.0\n", encoding="utf-8")

    packages, findings = parse_hash_lock(lock)

    assert packages == {"fastapi": "1.0"}
    assert [item["code"] for item in findings] == ["LOCK_ENTRY_WITHOUT_SHA256"]


def test_non_universal_python_lock_is_rejected(tmp_path: Path):
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "# generated without cross-platform resolution\n"
        "fastapi==1.0 \\\n"
        "    --hash=sha256:abc\n",
        encoding="utf-8",
    )

    findings = validate_lock_portability(lock)

    assert [item["code"] for item in findings] == ["LOCK_NOT_UNIVERSAL"]


def test_unmarked_windows_only_package_is_rejected(tmp_path: Path):
    lock = tmp_path / "dev-requirements.lock"
    lock.write_text(
        "# uv pip compile --universal\n" "pywin32==312 \\\n" "    --hash=sha256:abc\n",
        encoding="utf-8",
    )

    findings = validate_lock_portability(lock)

    assert [item["code"] for item in findings] == ["WINDOWS_ONLY_LOCK_MARKER_MISSING"]


def test_marked_windows_only_package_in_universal_lock_is_accepted(tmp_path: Path):
    lock = tmp_path / "dev-requirements.lock"
    lock.write_text(
        "# uv pip compile --universal\n"
        "pywin32==312 ; sys_platform == 'win32' \\\n"
        "    --hash=sha256:abc\n",
        encoding="utf-8",
    )

    assert validate_lock_portability(lock) == []


def test_mutable_workflow_action_is_rejected(tmp_path: Path):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "steps:\n  - uses: actions/checkout@v4\n", encoding="utf-8"
    )

    findings, action_count = validate_workflow_action_pins(tmp_path)

    assert action_count == 1
    assert [item["code"] for item in findings] == ["WORKFLOW_ACTION_NOT_IMMUTABLE"]
