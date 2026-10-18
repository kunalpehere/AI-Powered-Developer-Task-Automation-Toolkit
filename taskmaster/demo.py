"""Disposable planning demo: python -m taskmaster.demo --directory ./demo-work.

Only a newly created temporary child of the selected existing directory is used.
The demo inspects, previews/applies copies to disposable outputs, and reports
duplicates; it never runs the scheduler or creates a database.
"""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from .models import FileRule
from .organizer import FileOrganizer
from .inspection import inspect_project


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path.cwd(),
                        help="Existing directory in which to create disposable fixtures")
    options = parser.parse_args(args)
    if not options.directory.is_dir():
        parser.error("--directory must be an existing directory")
    root = options.directory.resolve()
    with TemporaryDirectory(prefix="taskmaster-demo-", dir=root) as temporary:
        base = Path(temporary).resolve()
        if base.parent != root:
            raise RuntimeError("Unexpected demo fixture location")
        source = base / "samples"
        source.mkdir()
        (source / "first.log").write_text("sample log\n", encoding="utf-8")
        (source / "second.log").write_text("sample log\n", encoding="utf-8")
        organizer = FileOrganizer()
        try:
            print("Inspection:", inspect_project(source)["summary"])
            rule = FileRule("preview", "*.log", "{filename}", action="copy")
            organizer.add_rule(rule)
            plan = organizer.plan_directory(source, base / "output", includes=("*.log",))
            print(organizer.generate_report(organizer.preview(plan)))
            print("Copy result:", organizer.generate_report(organizer.apply(plan)))
            print(f"Full SHA-256 duplicate groups: {len(organizer.find_duplicates(source))}")
            print("Only disposable copies were created; no database was initialized.")
        finally:
            organizer.close()
    print("Demo complete; disposable fixtures removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
