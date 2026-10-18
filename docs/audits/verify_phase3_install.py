"""Verify Phase 3 wheels/editable entry points outside the checkout on Windows.

Requires .venv and a normal wheel installation in .venv-phase3. Each run gets
new disposable fixture paths under .install-check; evidence replaces the JSON
results and sample reports in this directory, never application/user files.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
output = ROOT / "docs/audits"
scratch = ROOT / ".install-check/phase3-outside"
scratch.mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp(prefix="verified-", dir=scratch))
project = work / "workspace"
project.mkdir()
clean = ROOT / ".venv-phase3/Scripts"
editable = ROOT / ".venv/Scripts"
entries = {"src/main.py": b"print('keep')\n", "logs/app.log": b"log\n",
           "logs/nested/app.log": b"log\n", "reports/总结.csv": b"a,b\n1,2\n",
           "LICENSE": b"license", "empty/a": b"", "empty/b": b"",
           ".git/config": b"git", "venv/skip.py": b"skip"}
for name, data in entries.items():
    target = project / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
environment = dict(os.environ)
environment.pop("PYTHONPATH", None)
environment["PYTHONDONTWRITEBYTECODE"] = "1"
results = []


def check(label, args, expected=0, as_json=False):
    args = [str(arg) for arg in args]
    result = subprocess.run(args, cwd=project, env=environment, capture_output=True, text=True, timeout=30)
    results.append(dict(check=label, argv=args, exit_code=result.returncode,
                        stdout=result.stdout, stderr=result.stderr))
    assert result.returncode == expected, (label, result.stdout, result.stderr)
    print(f"{len(results)}: {label} passed", flush=True)
    return json.loads(result.stdout) if as_json else result.stdout


for prefix, label in ((clean, "wheel"), (editable, "editable")):
    check(label + " module help", [prefix / "python.exe", "-B", "-m", "taskmaster", "--help"])
    for name in ("taskmaster.exe", "tm.exe"):
        check(label + " " + name + " help", [prefix / name, "--help"])
check("wheel MVP imports outside checkout", [clean / "python.exe", "-I", "-c",
      "import taskmaster, taskmaster.scanning, taskmaster.inspection, taskmaster.duplicates, "
      "taskmaster.reporting, importlib.util; print(taskmaster.__file__); "
      "assert '.venv-phase3' in taskmaster.__file__; "
      "assert importlib.util.find_spec('PIL') is None; assert importlib.util.find_spec('PyPDF2') is None"])
check("wheel disposable full MVP demo", [clean / "python.exe", "-B", "-m", "taskmaster.demo", "--directory", work])
inspection = check("wheel inspection JSON", [clean / "tm.exe", "inspect", "--source", ".", "--format", "json"], as_json=True)
assert inspection["summary"]["file_count"] == 7 and inspection["complete"]
check("wheel inspection text", [clean / "tm.exe", "inspect", "--source", ".", "--top", "3"])
assert check("wheel repeated inspection JSON", [clean / "tm.exe", "inspect", "--source", ".", "--format", "json"], as_json=True) == inspection
duplicates = check("wheel duplicate JSON", [clean / "tm.exe", "duplicates", "--dir", ".", "--format", "json"], as_json=True)
assert duplicates["summary"]["duplicate_groups"] == 2 and duplicates["summary"]["hashed_files"] == 4
check("wheel duplicate text", [clean / "tm.exe", "duplicates", "--dir", "."])
assert check("wheel repeated duplicate JSON", [clean / "tm.exe", "duplicates", "--dir", ".", "--format", "json"], as_json=True) == duplicates
excluded = check("wheel custom excludes", [clean / "tm.exe", "inspect", "--source", ".", "--exclude", "logs/", "--format", "json"], as_json=True)
assert excluded["summary"]["file_count"] == 5
all_files = check("wheel default-exclusion override", [clean / "tm.exe", "inspect", "--source", ".", "--no-default-excludes", "--format", "json"], as_json=True)
assert all_files["summary"]["file_count"] == 9 and not (project / "taskmaster.db").exists()
copy, move = work / "copy", work / "move"
flags = ["organize", "--source", ".", "--include", "logs/**/*.log", "--include", "reports/**", "--format", "json"]
preview = check("wheel selected preview JSON", [clean / "tm.exe", *flags, "--destination", copy], as_json=True)
assert len(preview["operations"]) == 3 and not copy.exists() and not (project / "taskmaster.db").exists()
check("wheel JSON requires approval", [clean / "tm.exe", *flags, "--destination", copy, "--apply"], 1, True)
check("wheel missing source selection", [clean / "tm.exe", "organize", "--source", ".", "--destination", copy], 2)
copied = check("wheel selected copy JSON", [clean / "tm.exe", *flags, "--destination", copy, "--action", "copy", "--apply"], as_json=True)
assert copied["summary"]["successful"] == 3 and (copy / "data/reports/总结.csv").read_bytes() == entries["reports/总结.csv"]
assert all((project / name).read_bytes() == data for name, data in entries.items())
assert (project / "taskmaster.db").exists()
moved = check("wheel project-root selection with existing history", [clean / "tm.exe", *flags, "--destination", move, "--apply", "--yes"], as_json=True)
assert moved["summary"]["successful"] == 3 and not (project / "logs/app.log").exists()
assert (project / "src/main.py").read_bytes() == entries["src/main.py"] and (project / ".git/config").read_bytes() == b"git"
check("wheel no matching artifacts", [clean / "tm.exe", *flags, "--destination", work / "absent"], 1, True)
check("wheel history-file protection", [clean / "tm.exe", "organize", "--source", ".", "--destination", work / "unsafe", "--all-files", "--format", "json"], 1, True)
size = check("wheel size strategy", [clean / "tm.exe", "organize", "--source", ".", "--destination", work / "size", "--include", "LICENSE", "--strategy", "size", "--format", "json"], as_json=True)
assert Path(size["operations"][0]["destination"]).relative_to(work / "size").as_posix() == "small/LICENSE"
check("wheel traversal refusal", [clean / "tm.exe", "organize", "--source", ".", "--destination", work / "bad", "--include", "LICENSE", "--template", "../escape", "--format", "json"], 1, True)
check("wheel missing-root JSON", [clean / "tm.exe", "inspect", "--source", "missing", "--format", "json"], 1, True)
check("wheel automatic deletion disabled", [clean / "tm.exe", "duplicates", "--dir", ".", "--delete"], 2)
check("wheel retained task dispatch", [clean / "tm.exe", "task", "add", "--name", "probe", "--command", "echo phase3", "--schedule", "2026-10-15 12:00"])
check("wheel retained task list", [clean / "tm.exe", "task", "list"])
check("clean dependency consistency", [editable / "python.exe", "-m", "pip", "--python", clean / "python.exe", "check"])
for name, report in (("phase3-install-results.json", {"cwd": str(project), "checks": results}),
                     ("phase3-sample-inspection.json", inspection),
                     ("phase3-sample-duplicates.json", duplicates),
                     ("phase3-sample-organization.json", preview)):
    (output / name).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(f"{len(results)} installed-package checks passed; sample reports saved.")
