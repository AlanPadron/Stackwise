"""Archive intake: validation before extraction, and safe extraction."""

import stat
import zipfile
from dataclasses import replace

import pytest

from app.analysis.config import resolve_config
from app.analysis.errors import InvalidSourceError, ResourceLimitError, SourceAcquisitionError
from app.analysis.sources.archive import (
    ArchiveSourceProvider,
    extract_archive,
    hash_tree,
    inspect_archive,
    repository_root,
)
from app.analysis.workspace import RunWorkspace


def _zip(path, files: dict[str, str], *, compression=zipfile.ZIP_STORED):
    with zipfile.ZipFile(path, "w", compression) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def _zip_with_special_entry(path, name: str, mode: int, content: str = "x"):
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo(name)
        info.external_attr = mode << 16
        archive.writestr(info, content)
    return path


# --- happy path --------------------------------------------------------------


def test_extract_strips_the_single_wrapper_directory(temp_root):
    archive = _zip(temp_root / "a.zip", {"repo-main/app.py": "x = 1\n", "repo-main/pkg/b.py": "y = 1\n"})
    destination = temp_root / "out"

    report = extract_archive(archive, destination, resolve_config())

    assert report.files == 2
    assert repository_root(destination).name == "repo-main"
    assert (destination / "repo-main" / "app.py").is_file()


def test_repository_root_is_not_stripped_when_the_archive_is_flat(temp_root):
    archive = _zip(temp_root / "b.zip", {"app.py": "x = 1\n", "README.md": "# hi\n"})
    destination = temp_root / "out"

    extract_archive(archive, destination, resolve_config())

    assert repository_root(destination) == destination


def test_source_provider_reports_snapshot_metadata(temp_root):
    archive = _zip(temp_root / "d.zip", {"repo-main/app.py": "x = 1\n"})
    workspace = RunWorkspace.create()
    try:
        provider = ArchiveSourceProvider(
            archive, config=resolve_config(), source_type="github", origin="octocat/hello@main"
        )
        snapshot = provider.acquire(workspace)

        assert snapshot.source_type == "github"
        assert snapshot.origin == "octocat/hello@main"
        assert snapshot.root.name == "repo-main"
        assert snapshot.content_hash and len(snapshot.content_hash) == 64
        assert snapshot.root.is_dir()
    finally:
        workspace.cleanup()


def test_hash_tree_is_stable_and_content_sensitive(temp_root):
    first = temp_root / "one"
    second = temp_root / "two"
    for root, content in ((first, "x = 1\n"), (second, "x = 2\n")):
        root.mkdir()
        (root / "app.py").write_text(content, encoding="utf-8")

    assert hash_tree(first, budget_bytes=1024) == hash_tree(first, budget_bytes=1024)
    assert hash_tree(first, budget_bytes=1024) != hash_tree(second, budget_bytes=1024)


# --- rejected archives -------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["../outside.py", "a/../../outside.py", "/etc/passwd", "C:/windows/x.py", "..\\outside.py", "a\\..\\..\\b.py"],
)
def test_path_traversal_entries_are_rejected(temp_root, name):
    archive = _zip(temp_root / "evil.zip", {name: "pwned\n", "ok.py": "x = 1\n"})
    with pytest.raises(InvalidSourceError):
        inspect_archive(archive, resolve_config())


def test_absolute_and_control_character_names_are_rejected(temp_root):
    for name in ("/absolute.py", "bad\x01name.py"):
        archive = _zip(temp_root / f"evil_{abs(hash(name))}.zip", {name: "x"})
        with pytest.raises(InvalidSourceError):
            inspect_archive(archive, resolve_config())


def test_symlink_and_special_entries_are_rejected(temp_root):
    symlink = _zip_with_special_entry(
        temp_root / "link.zip", "link", stat.S_IFLNK | 0o777, "/etc/passwd"
    )
    fifo = _zip_with_special_entry(temp_root / "fifo.zip", "pipe", stat.S_IFIFO | 0o644)

    for archive in (symlink, fifo):
        with pytest.raises(InvalidSourceError):
            inspect_archive(archive, resolve_config())


def test_too_many_files_is_a_resource_limit(temp_root):
    config = resolve_config()
    files = {f"mod_{index}.py": "x = 1\n" for index in range(config.max_file_count + 1)}
    archive = _zip(temp_root / "many.zip", files)

    with pytest.raises(ResourceLimitError):
        inspect_archive(archive, config)


def test_oversized_file_is_a_resource_limit(temp_root):
    config = resolve_config()
    archive = _zip(temp_root / "big.zip", {"big.py": "x" * (config.max_file_bytes + 1)})
    with pytest.raises(ResourceLimitError):
        inspect_archive(archive, config)


def test_total_extracted_size_is_a_resource_limit(temp_root):
    config = replace(resolve_config(), max_extracted_bytes=1024 * 1024)
    archive = _zip(
        temp_root / "total.zip",
        {f"m{index}.py": "x" * (400 * 1024) for index in range(4)},
    )
    with pytest.raises(ResourceLimitError):
        inspect_archive(archive, config)


def test_deeply_nested_paths_are_rejected(temp_root):
    config = resolve_config()
    nested = "/".join(f"level{index}" for index in range(config.max_workspace_depth + 2)) + "/app.py"
    archive = _zip(temp_root / "deep.zip", {nested: "x = 1\n"})

    with pytest.raises(ResourceLimitError):
        inspect_archive(archive, config)


def test_archive_without_files_is_rejected(temp_root):
    empty = temp_root / "empty.zip"
    zipfile.ZipFile(empty, "w").close()
    with pytest.raises(InvalidSourceError):
        inspect_archive(empty, resolve_config())

    only_directories = temp_root / "dirs.zip"
    with zipfile.ZipFile(only_directories, "w") as archive:
        archive.writestr("pkg/", "")
    with pytest.raises(InvalidSourceError):
        extract_archive(only_directories, temp_root / "out", resolve_config())


def test_zero_byte_file_inside_an_archive_is_allowed(temp_root):
    """A zero-byte file is a normal (if useless) entry — it is skipped, not rejected."""
    archive = _zip(temp_root / "zero.zip", {"empty.py": ""})
    destination = temp_root / "out"
    report = extract_archive(archive, destination, resolve_config())
    assert report.files == 1
    assert (destination / "empty.py").is_file()


def test_non_zip_and_missing_archive_are_rejected(temp_root):
    not_a_zip = temp_root / "not_a_zip.zip"
    not_a_zip.write_bytes(b"just text")
    with pytest.raises(InvalidSourceError):
        inspect_archive(not_a_zip, resolve_config())

    with pytest.raises(SourceAcquisitionError):
        inspect_archive(temp_root / "missing.zip", resolve_config())


def test_archive_larger_than_the_limit_is_rejected(temp_root):
    archive = _zip(temp_root / "large.zip", {"a.py": "#" * (2 * 1024 * 1024)})
    tight = replace(resolve_config(), max_archive_bytes=1024)
    with pytest.raises(ResourceLimitError):
        inspect_archive(archive, tight)


def test_inspect_archive_does_not_write_anything(temp_root):
    archive = _zip(temp_root / "clean.zip", {"repo-main/app.py": "x = 1\n"})
    destination = temp_root / "untouched"

    inspect_archive(archive, resolve_config())

    assert not destination.exists()
