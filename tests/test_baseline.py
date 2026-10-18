import hashlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from taskmaster.cli import TaskMasterCLI, main
from taskmaster.models import FileRule
from taskmaster.plugins import ImageProcessorPlugin, PluginManager


@pytest.mark.parametrize("fast_mode", [True, False])
def test_matching_prefix_does_not_make_duplicates(organizer, tmp_path, fast_mode):
    source = tmp_path / "files"
    source.mkdir()
    (source / "a.bin").write_bytes(b"x" * 1024 + b"A")
    (source / "b.bin").write_bytes(b"x" * 1024 + b"B")
    assert organizer.find_duplicates(source, fast_mode=fast_mode) == {}
    assert organizer.db.get_stats()["indexed_files"] == 0


def test_duplicates_use_full_sha256_and_include_every_member(organizer, tmp_path):
    source = tmp_path / "files"
    source.mkdir()
    paths = [source / name for name in ("a.log", "b.log", "c.log")]
    for path in paths:
        path.write_bytes(b"same\n")
    assert organizer.find_duplicates(source) == {hashlib.sha256(b"same\n").hexdigest(): paths}


@pytest.mark.parametrize("action", ["copy", "move", "rename"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_existing_destination_is_preserved(organizer, tmp_path, action, dry_run):
    source, target = tmp_path / "input/source.txt", tmp_path / "output/target.txt"
    source.parent.mkdir(exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("new")
    target.write_text("original")
    organizer.dry_run = dry_run
    result = organizer.organize_file(source, FileRule("collision", "*", str(target), action=action), destination_root=tmp_path / "output", confirmed=True)
    assert result.status == "failed"
    assert "already exists" in result.error
    assert source.read_text() == "new"
    assert target.read_text() == "original"


def test_destination_created_during_copy_is_preserved(organizer, tmp_path, monkeypatch):
    source, target = tmp_path / "input/source.txt", tmp_path / "output/target.txt"
    source.parent.mkdir(exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("source")
    original_open = Path.open

    def raced_open(path, mode="r", *args, **kwargs):
        if path == target and mode == "xb":
            with original_open(target, "w") as writer:
                writer.write("concurrent")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", raced_open)
    result = organizer.organize_file(source, FileRule("race", "*", str(target), action="move"), destination_root=tmp_path / "output", confirmed=True)
    assert result.status == "failed"
    assert source.read_text() == "source"
    assert target.read_text() == "concurrent"


def test_destination_directory_is_not_treated_as_a_move_target(organizer, tmp_path):
    source, target = tmp_path / "input/source.txt", tmp_path / "output/target"
    source.parent.mkdir(exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("keep")
    target.mkdir()
    result = organizer.organize_file(source, FileRule("directory", "*", str(target)), destination_root=tmp_path / "output", confirmed=True)
    assert result.status == "failed"
    assert source.read_text() == "keep"
    assert not list(target.iterdir())


def test_interactive_duplicate_report_never_offers_deletion(organizer, tmp_path, monkeypatch):
    source = tmp_path / "files"
    source.mkdir()
    for name in ("a.txt", "b.txt"):
        (source / name).write_text("same")
    cli = TaskMasterCLI()
    cli.organizer = organizer
    monkeypatch.setattr("taskmaster.cli.Prompt.ask", lambda *args, **kwargs: str(source))
    confirm = Mock(side_effect=AssertionError("Deletion confirmation must not be requested"))
    monkeypatch.setattr("taskmaster.cli.Confirm.ask", confirm)
    cli.find_duplicates_interactive()
    confirm.assert_not_called()
    assert len(list(source.iterdir())) == 2


@pytest.mark.parametrize("action", ["copy", "move", "rename"])
def test_basic_file_operation(organizer, tmp_path, action):
    source, target = tmp_path / "input/source.log", tmp_path / "output/result.log"
    source.parent.mkdir(exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"log contents")
    result = organizer.organize_file(source, FileRule("basic", "*", str(target), action=action), destination_root=tmp_path / "output", confirmed=True)
    assert result.status == "success"
    assert target.read_bytes() == b"log contents"
    assert source.exists() == (action == "copy")


def test_invalid_action_has_no_file_side_effects(organizer, tmp_path):
    source = tmp_path / "input/source.txt"
    source.parent.mkdir(exist_ok=True)
    source.write_text("keep")
    target = tmp_path / "output/absent/result.txt"
    rule = FileRule("invalid", "*", str(target), action="bogus")
    with pytest.raises(ValueError, match="Unsupported action"):
        organizer.add_rule(rule)
    with pytest.raises(ValueError, match="Unsupported action"):
        organizer.organize_file(source, rule, destination_root=tmp_path / "output", confirmed=True)
    assert source.read_text() == "keep"
    assert not target.parent.exists()


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_invalid_scan_source(organizer, tmp_path, kind):
    source = tmp_path / kind
    if kind == "file":
        source.write_text("not a directory")
    with pytest.raises((FileNotFoundError, NotADirectoryError), match="Source"):
        organizer.scan_directory(source)


def test_metadata_failure_is_reported_per_file(organizer, tmp_path, monkeypatch):
    source = tmp_path / "input/source.txt"
    source.parent.mkdir(exist_ok=True)
    source.write_text("keep")
    monkeypatch.setattr(organizer, "get_file_info", Mock(side_effect=PermissionError("denied")))
    result = organizer.organize_file(source, FileRule("metadata", "*", "out.txt"), destination_root=tmp_path / "output", confirmed=True)
    assert result.status == "failed"
    assert "denied" in result.error
    assert source.read_text() == "keep"


def test_hash_failure_is_not_silently_ignored(organizer, tmp_path, monkeypatch):
    source = tmp_path / "files"
    source.mkdir()
    (source / "one.log").write_text("log")
    (source / "two.log").write_text("log")
    monkeypatch.setattr(organizer, "calculate_checksum", Mock(side_effect=PermissionError("denied")))
    with pytest.raises(ValueError, match="denied"):
        organizer.find_duplicates(source)


def test_task_add_dispatch_preserves_shell_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli = TaskMasterCLI()
    try:
        assert cli.run_cli(["task", "add", "--name", "probe", "--command", "echo correct",
                            "--schedule", "2026-10-15 12:00"]) == 0
        task = next(iter(cli.scheduler.tasks.values()))
        assert task.operation == 'subprocess'
        assert task.parameters == {'command': 'echo correct'}
        restored = cli.db.schedules()[0]
        assert restored.parameters == task.parameters
    finally:
        cli.close()


def test_cli_errors_and_deletion_guard_preserve_files(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for command in ("organize", "duplicates"):
        option = "--source" if command == "organize" else "--dir"
        assert main([command, option, "missing"] + (["--destination", "output", "--all-files"] if command == "organize" else [])) == 1
        assert "Source directory does not exist" in capsys.readouterr().out
    source = tmp_path / "files"
    source.mkdir()
    for name in ("a.log", "b.log"):
        (source / name).write_text("same")
    with pytest.raises(SystemExit) as error:
        main(["duplicates", "--dir", str(source), "--delete"])
    assert error.value.code == 2
    assert len(list(source.iterdir())) == 2


def test_cli_collision_returns_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "files"
    source.mkdir()
    (source / "one.txt").write_text("source")
    target = tmp_path / "organized/documents/one.txt"
    target.parent.mkdir(parents=True)
    target.write_text("existing")
    assert main(["organize", "--all-files", "--source", str(source), "--destination", "organized", "--apply", "--yes"]) == 1
    assert "Destination already exists" in capsys.readouterr().out
    assert target.read_text() == "existing"
    assert (source / "one.txt").read_text() == "source"


def test_cli_preview_preserves_source(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "files"
    source.mkdir()
    (source / "one.log").write_text("source")
    assert main(["organize", "--all-files", "--source", str(source), "--destination", "organized", "--dry-run"]) == 0
    assert (source / "one.log").read_text() == "source"
    assert not (tmp_path / "organized").exists()
    assert "Previewed 1 files" in capsys.readouterr().out


@pytest.mark.parametrize("args", [["--help"], ["organize", "--source", ".", "--strategy", "size"],
    ["task"], ["task", "add", "--name", "x", "--command", "echo x", "--schedule", "bad"]])
def test_parse_only_paths_do_not_create_database(tmp_path, monkeypatch, args):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == (0 if args == ["--help"] else 2)
    assert not (tmp_path / "taskmaster.db").exists()


def test_plugin_import_and_explicit_registration(tmp_path):
    manager = PluginManager(tmp_path)
    plugin = ImageProcessorPlugin()
    manager.register_file_plugin(plugin)
    assert manager.get_file_plugin_for_extension(".png") is plugin
    assert manager.list_plugins()["file_plugins"] == ["image_processor"]


def test_module_help_and_demo_in_disposable_directory(tmp_path):
    root = Path(__file__).resolve().parents[1]
    help_result = subprocess.run([sys.executable, "-B", "-m", "taskmaster", "--help"],
                                 cwd=root, capture_output=True, text=True, timeout=20)
    assert help_result.returncode == 0, help_result.stderr
    demo = subprocess.run([sys.executable, "-B", "-m", "taskmaster.demo", "--directory", str(tmp_path)],
                          cwd=root, capture_output=True, text=True, timeout=20)
    assert demo.returncode == 0, demo.stderr
    assert "Full SHA-256 duplicate groups: 1" in demo.stdout
    assert not list(tmp_path.iterdir())
