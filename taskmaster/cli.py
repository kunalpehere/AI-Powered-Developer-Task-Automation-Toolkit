"""
TaskMaster - Rich CLI Interface
Beautiful terminal interface with live dashboards, tables, and progress bars.
"""
import asyncio
import argparse
import sqlite3
import logging
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from functools import cached_property
from typing import Optional, List

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.tree import Tree
from rich import box

from .models import TaskPriority, RecurrenceType
from .database import Database
from .scheduler import TaskScheduler
from .organizer import FileOrganizer
from .errors import ConfirmationRequired
from .reporting import emit_json, show_scan_report, show_step_report
from .config import load_workflow, validate_workflow
from .operations import prepare_operation, run_prepared
from .workflows import run_workflow, safe_message
from .schedules import ScheduledTask, utc

console = Console()

class TaskMasterCLI:
    """Main CLI interface for TaskMaster."""

    def __init__(self, db_path: str = "taskmaster.db"):
        self.db_path = str(Path(db_path).expanduser().absolute()) if db_path != ":memory:" else db_path
        self.output_format = "text"
        self.report_command = None

    @cached_property
    def db(self):
        return Database(self.db_path)

    @cached_property
    def scheduler(self):
        return TaskScheduler(self.db)

    @cached_property
    def organizer(self):
        return FileOrganizer(history_recorder=lambda operation: self.db.log_file_operation(operation),
                             history_path=Path(self.db_path))

    def close(self):
        if "organizer" in self.__dict__:
            self.organizer.close()
        if "scheduler" in self.__dict__:
            self.scheduler.close()

    def print_banner(self):
        """Print application banner."""
        banner = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   ████████╗ █████╗ ███████╗██╗  ██╗███╗   ███╗ █████╗ ███████╗████████╗███████╗██████╗  ║
║   ╚══██╔══╝██╔══██╗██╔════╝██║ ██╔╝████╗ ████║██╔══██╗██╔════╝╚══██╔══╝██╔════╝██╔══██╗ ║
║      ██║   ███████║███████╗█████╔╝ ██╔████╔██║███████║███████╗   ██║   █████╗  ██████╔╝ ║
║      ██║   ██╔══██║╚════██║██╔═██╗ ██║╚██╔╝██║██╔══██║╚════██║   ██║   ██╔══╝  ██╔══██╗ ║
║      ██║   ██║  ██║███████║██║  ██╗██║ ╚═╝ ██║██║  ██║███████║   ██║   ███████╗██║  ██║ ║
║      ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═╝ ║
║                                                              ║
║         Advanced Task Scheduler & File Organizer v2.0        ║
╚══════════════════════════════════════════════════════════════╝
        """
        console.print(banner, style="bold cyan")

    def show_dashboard(self):
        """Show live dashboard with task and file stats."""
        stats = self.db.get_stats()
        scheduled = self.db.schedules()
        stats['total_tasks'] += len(scheduled)
        for key, state in [('pending_tasks', 'PENDING'), ('completed_tasks', 'COMPLETED'), ('failed_tasks', 'FAILED')]:
            stats[key] += sum(task.status == state for task in scheduled)

        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=3)
        )
        layout["main"].split_row(
            Layout(name="tasks"),
            Layout(name="files")
        )

        # Header
        header = Panel(
            f"[bold green]TaskMaster[/bold green] | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            style="bold white on blue"
        )
        layout["header"].update(header)

        # Tasks panel
        task_table = Table(title="Task Statistics", box=box.ROUNDED)
        task_table.add_column("Metric", style="cyan")
        task_table.add_column("Count", style="magenta")
        task_table.add_row("Total Tasks", str(stats["total_tasks"]))
        task_table.add_row("Pending", str(stats["pending_tasks"]), style="yellow")
        task_table.add_row("Completed", str(stats["completed_tasks"]), style="green")
        task_table.add_row("Failed", str(stats["failed_tasks"]), style="red")

        layout["tasks"].update(Panel(task_table, border_style="cyan"))

        # Files panel
        file_table = Table(title="File Operations", box=box.ROUNDED)
        file_table.add_column("Metric", style="cyan")
        file_table.add_column("Count", style="magenta")
        file_table.add_row("Operations", str(stats["file_operations"]))
        file_table.add_row("Indexed Files", str(stats["indexed_files"]))

        layout["files"].update(Panel(file_table, border_style="green"))

        # Footer
        footer = Panel(
            "[dim]Press Ctrl+C to exit dashboard[/dim]",
            style="dim"
        )
        layout["footer"].update(footer)

        console.print(layout)

    def show_tasks(self, status_filter: Optional[str] = None):
        """Display tasks in a formatted table."""
        tasks = [task.to_dict() for task in self.db.schedules()] + self.db.get_all_tasks()

        if status_filter:
            tasks = [t for t in tasks if t["status"] == status_filter.upper()]

        if not tasks:
            console.print("[yellow]No tasks found.[/yellow]")
            return

        table = Table(
            title=f"Tasks ({len(tasks)} total)",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold magenta"
        )

        table.add_column("ID", style="dim", width=8)
        table.add_column("Name", style="cyan", min_width=20)
        table.add_column("Status", width=12)
        table.add_column("Priority", width=8)
        table.add_column("Schedule", width=16)
        table.add_column("Runs", width=6)
        table.add_column("Next Run", width=16)

        status_colors = {
            "PENDING": "yellow",
            "RUNNING": "blue",
            "COMPLETED": "green",
            "FAILED": "red",
            "CANCELLED": "dim",
            "PAUSED": "orange3"
        }

        for task in tasks:
            status_color = status_colors.get(task["status"], "white")
            next_run = task["next_run"] or "N/A"
            if next_run != "N/A":
                next_run = next_run[:16]

            table.add_row(
                task["id"],
                task["name"][:30],
                f"[{status_color}]{task['status']}[/{status_color}]",
                str(task["priority"]),
                task["schedule_time"][:16],
                str(task["run_count"]),
                next_run
            )

        console.print(table)

    def add_task_interactive(self):
        """Interactive task creation wizard."""
        console.print("\n[bold cyan]Create New Task[/bold cyan]\n")

        name = Prompt.ask("Task name")

        console.print("\n[bold]Recurrence Options:[/bold]")
        console.print("1. One-time")
        console.print("2. Minutely")
        console.print("3. Hourly")
        console.print("4. Daily")
        console.print("5. Weekly")

        rec_choice = Prompt.ask("Choose recurrence", choices=["1","2","3","4","5"], default="1")
        recurrence_map = {
            "1": RecurrenceType.ONCE,
            "2": RecurrenceType.MINUTELY,
            "3": RecurrenceType.HOURLY,
            "4": RecurrenceType.DAILY,
            "5": RecurrenceType.WEEKLY,
        }
        recurrence = recurrence_map[rec_choice]

        interval = None
        if recurrence == RecurrenceType.MINUTELY:
            interval = int(Prompt.ask("Interval (minutes)", default="5"))

        # Schedule time
        if recurrence == RecurrenceType.ONCE:
            schedule_str = Prompt.ask("UTC schedule time (YYYY-MM-DD HH:MM)",
                                    default=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
            schedule_time = datetime.strptime(schedule_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        else:
            schedule_time = datetime.now(timezone.utc)

        # Priority
        console.print("\n[bold]Priority:[/bold]")
        console.print("1. Low")
        console.print("2. Normal")
        console.print("3. High")
        console.print("4. Critical")

        pri_choice = Prompt.ask("Choose priority", choices=["1","2","3","4"], default="2")
        priority_map = {
            "1": TaskPriority.LOW,
            "2": TaskPriority.NORMAL,
            "3": TaskPriority.HIGH,
            "4": TaskPriority.CRITICAL,
        }
        priority = priority_map[pri_choice]

        # Command type
        console.print("\n[bold]Command Type:[/bold]")
        console.print("1. Shell command")
        console.print("2. Python function (disabled; use Python API)")
        console.print("3. File organization (unavailable; use organize preview/apply)")

        cmd_choice = Prompt.ask("Choose type", choices=["1","2","3"], default="1")

        if cmd_choice == "1":
            command_str = Prompt.ask("Enter shell command")

        elif cmd_choice == "2":
            raise ValueError("Interactive Python expressions are disabled. Use a shell command or the Python API.")

        else:
            raise ValueError('Use task add --workflow FILE --apply --yes for approved scheduled organization')

        # Create task
        task = ScheduledTask(
            name=name,
            operation='subprocess', parameters={'command': command_str}, base_dir=str(Path.cwd()),
            schedule_time=schedule_time.isoformat(),
            recurrence=recurrence.value,
            interval_minutes=interval or 1,
            priority=priority.value
        )

        task_id = self.scheduler.register_task(task)
        console.print(f"\n[green]✓ Task created with ID: {task_id}[/green]")

        return task_id

    def show_plan(self, plan):
        console.print(f"Plan: {len(plan.operations)} operations | {plan.source_root} -> {plan.destination_root}", markup=False)
        for operation in plan.operations:
            reason = operation.validation_error or operation.skipped_reason
            detail = f" | {reason}" if reason else ""
            target = operation.destination or ("(delete)" if operation.action == "delete" else "(invalid destination)")
            console.print(f"{operation.action} {operation.source} -> {target}"
                          f" | conflict={operation.conflict_policy}{detail}", markup=False)

    def show_results(self, results):
        for result in results:
            console.print(f"{result.status}: {result.source} | files={result.filesystem_status}"
                          f" | history={result.history_status}"
                          f"{(' | ' + result.error) if result.error else ''}"
                          f"{(' | History error: ' + result.history_error) if result.history_error else ''}", markup=False)
        report = self.organizer.generate_report(results)
        console.print(f"Successful: {report['successful']}; failed: {report['failed']}; "
                      f"skipped: {report['skipped']}; history failures: {report['history_failed']}")
        if report["dry_run"]:
            console.print(f"Previewed {report['dry_run']} files; no file or history changes applied.")
        return 1 if report["failed"] or report["history_failed"] else 0

    def apply_tracked(self, prepared, *, confirmed: bool):
        prepared.results = None
        workflow = validate_workflow({"version": 1, "name": "direct-organize", "steps": [
            {"id": "organize", "operation": "organize", "parameters": prepared.parameters}]})
        run = run_workflow(workflow, base_dir=Path.cwd(), apply=True, confirmed=confirmed,
                           history_path=Path(self.db_path), database_factory=lambda: self.db,
                           _prepared={"organize": prepared})
        report = run["steps"][0]["report"] or {"schema_version": 1, "command": "organize",
            "mode": "not_run", "complete": False, "operations": [],
            "error": "Application did not start because its run journal could not be written"}
        report = {**report, "complete": run["complete"], "run_id": run["run_id"], "run_history": run["history"]}
        if self.output_format == "json":
            emit_json(report)
        else:
            console.print(f"Run ID: {run['run_id']}")
            if prepared.results is not None:
                self.show_results(prepared.results)
            for error in run["history"]["errors"]:
                console.print(f"{error['code']}: {error['message']}", markup=False)
        return 0 if run["complete"] else 1

    def organize_files_interactive(self):
        source = Path(Prompt.ask("Source directory"))
        destination = Path(Prompt.ask("Destination root (separate from the source)"))
        selection = Prompt.ask("Include patterns (comma separated, e.g. logs/**/*.log)")
        includes = tuple(value.strip() for value in selection.split(","))
        strategy = Prompt.ask("Strategy", choices=["type", "date", "size", "custom"], default="type")
        templates = {"type": "{type}/{relative_dir}/{filename}", "date": "{year}/{month}/{relative_dir}/{filename}",
                     "size": "{size_category}/{relative_dir}/{filename}"}
        template = (Prompt.ask("Destination template relative to destination root")
                    if strategy == "custom" else templates[strategy])
        action = Prompt.ask("Action", choices=["copy", "move"], default="move")
        conflict = Prompt.ask("Existing destination", choices=["error", "skip"], default="error")
        prepared = prepare_operation("organize", {"source": str(source), "destination": str(destination),
            "includes": list(includes), "strategy": strategy if strategy != "custom" else "type",
            "template": template, "action": action, "conflict_policy": conflict},
            base_dir=Path.cwd(), organizer=self.organizer)
        self.show_plan(prepared.plan)
        run_prepared(prepared)
        self.show_results(prepared.results)
        if Confirm.ask("Apply this displayed plan? Source files will be removed for moves.", default=False):
            return self.apply_tracked(prepared, confirmed=True)
        return 0

    def find_duplicates_interactive(self):
        """Interactive duplicate file finder."""
        console.print("\n[bold cyan]Duplicate File Finder[/bold cyan]\n")

        directory = Prompt.ask("Directory to scan", default=str(Path.home()))
        dir_path = Path(directory)

        if not dir_path.exists():
            console.print(f"[red]Directory not found: {directory}[/red]")
            return

        console.print("\n[yellow]Scanning for duplicates...[/yellow]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task("[cyan]Computing checksums...", total=None)
            duplicates = self.organizer.find_duplicates(dir_path)

        if not duplicates:
            console.print("\n[green]No duplicates found![/green]")
            return

        console.print(f"\n[bold]Found {len(duplicates)} duplicate groups[/bold]\n")

        for checksum, paths in list(duplicates.items())[:10]:  # Show first 10
            size = paths[0].stat().st_size
            tree = Tree(f"[bold]{checksum[:16]}...[/bold] ({size / 1024:.1f} KB)")
            for path in paths:
                tree.add(f"[dim]{path}[/dim]")
            console.print(tree)
            console.print()

        if len(duplicates) > 10:
            console.print(f"[dim]... and {len(duplicates) - 10} more groups[/dim]")

        console.print("[yellow]Duplicate reporting only; automatic deletion is disabled.[/yellow]")

    def run_interactive(self):
        """Run interactive mode."""
        self.print_banner()

        while True:
            console.print("\n[bold cyan]Main Menu[/bold cyan]")
            console.print("1. Dashboard")
            console.print("2. View Tasks")
            console.print("3. Add Task")
            console.print("4. Start Scheduler")
            console.print("5. Organize Files")
            console.print("6. Find Duplicates")
            console.print("7. View Statistics")
            console.print("8. Exit")

            choice = Prompt.ask("\nSelect option", choices=["1","2","3","4","5","6","7","8"])

            if choice == "1":
                self.show_dashboard()

            elif choice == "2":
                self.show_tasks()

            elif choice == "3":
                self.add_task_interactive()

            elif choice == "4":
                console.print("\n[yellow]Starting scheduler... Press Ctrl+C to stop[/yellow]")
                try:
                    asyncio.run(self._run_scheduler_live())
                except KeyboardInterrupt:
                    console.print("\n[red]Scheduler stopped.[/red]")

            elif choice == "5":
                self.organize_files_interactive()

            elif choice == "6":
                self.find_duplicates_interactive()

            elif choice == "7":
                stats = self.db.get_stats()
                for key, value in stats.items():
                    console.print(f"[cyan]{key}:[/cyan] {value}")

            elif choice == "8":
                console.print("\n[green]Goodbye![/green]")
                break

    async def _run_scheduler_live(self):
        """Run scheduler with live status updates."""
        console.print('Running durable scheduler; Ctrl+C pauses and terminates active attempts.')
        await self.scheduler.start()

        try:
            while True:
                if self.scheduler._loop_task.done():
                    self.scheduler._loop_task.result()
                    break
                console.clear()
                self.show_dashboard()
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            pass
        finally:
            await self.scheduler.stop()

    def run_cli(self, args: Optional[List[str]] = None):
        """Run with command-line arguments."""
        parser = argparse.ArgumentParser(
            description="TaskMaster - Developer workspace inspection and safe artifact organization",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  %(prog)s --interactive              Launch interactive mode
  %(prog)s task add --name "Backup" --command "rsync -a ~/docs /backup" --schedule "2024-01-01 00:00"
  %(prog)s task list
  %(prog)s inspect --source . --format json
  %(prog)s organize --source . --destination ../organized --include "logs/**/*.log" --dry-run
  %(prog)s duplicates --dir ./sample-artifacts
            """
        )

        parser.add_argument("--database", default=self.db_path, help="Run/history database path (before subcommand)")
        parser.add_argument("--interactive", "-i", action="store_true", 
                           help="Launch interactive mode")

        subparsers = parser.add_subparsers(dest="subcommand", help="Available commands")

        # Task commands
        task_parser = subparsers.add_parser("task", help="Task management")
        task_sub = task_parser.add_subparsers(dest="task_cmd", required=True)

        task_add = task_sub.add_parser("add", help="Add a new task")
        task_add.add_argument("--name", required=True)
        task_kind = task_add.add_mutually_exclusive_group(required=True)
        task_kind.add_argument('--command', help='Explicit trusted shell command; persisted verbatim')
        task_kind.add_argument('--workflow', type=Path, help='Save a validated workflow snapshot')
        task_kind.add_argument('--operation', choices=['inspect', 'duplicates'])
        task_add.add_argument('--source')
        task_add.add_argument('--include', action='append', default=[])
        task_add.add_argument('--apply', action='store_true')
        task_add.add_argument('--yes', action='store_true', help='Approve scheduled file-changing workflow')
        task_add.add_argument('--interval-minutes', type=int, default=1)
        task_add.add_argument('--max-retries', type=int, default=0, help='Additional attempts per occurrence')
        task_add.add_argument('--retry-delay', type=int, default=1)
        task_add.add_argument('--timeout', type=int, default=300)
        task_add.add_argument('--retry-safe', action='store_true')
        task_add.add_argument('--depends-on', action='append', default=[])
        task_add.add_argument("--schedule", required=True, help="ISO date/time with UTC offset; legacy YYYY-MM-DD HH:MM is UTC")
        task_add.add_argument("--recurrence", choices=["once","minutely","hourly","daily","weekly","monthly","custom"],
                             default="once")
        task_add.add_argument("--priority", type=int, choices=[1,2,3,4], default=2)

        task_commands = [task_sub.add_parser('list'), task_sub.add_parser('start'),
                         task_sub.add_parser('run-due'), task_sub.add_parser('attempts')]
        for action in ('pause', 'cancel', 'resume', 'recover'):
            command_parser = task_sub.add_parser(action)
            command_parser.add_argument('task_id')
            if action == 'recover':
                command_parser.add_argument('--acknowledge', action='store_true')
            task_commands.append(command_parser)
        task_commands.append(task_add)
        for command_parser in task_commands:
            command_parser.add_argument('--format', choices=['text', 'json'], default='text')

        def scan_options(command_parser):
            command_parser.add_argument("--exclude", action="append", default=[], help="Repeatable basename or root-relative glob")
            command_parser.add_argument("--no-default-excludes", action="store_true")
            command_parser.add_argument("--no-recursive", action="store_true")
            command_parser.add_argument("--format", choices=["text", "json"], default="text")

        inspect_parser = subparsers.add_parser("inspect", help="Inspect a developer workspace")
        inspect_parser.add_argument("--source", required=True)
        inspect_parser.add_argument("--include", action="append", default=[])
        inspect_parser.add_argument("--top", type=int, default=10, help="Number of largest files to report")
        inspect_parser.add_argument("--min-size", type=int, default=0, help="Minimum bytes for largest-file listing")
        scan_options(inspect_parser)

        # Organize commands
        org_parser = subparsers.add_parser("organize", help="Organize files")
        org_parser.add_argument("--source", required=True)
        selection = org_parser.add_mutually_exclusive_group(required=True)
        selection.add_argument("--include", action="append", help="Select files using repeatable globs")
        selection.add_argument("--all-files", action="store_true", help="Explicitly select every nonexcluded file")
        scan_options(org_parser)
        org_parser.add_argument("--destination", required=True, help="Explicit destination root outside source")
        org_parser.add_argument("--action", choices=["copy", "move"], default="move")
        org_parser.add_argument("--conflict", choices=["error", "skip"], default="error")
        org_parser.add_argument("--template", help="Validated template relative to destination root")
        org_parser.add_argument("--yes", action="store_true", help="Explicitly approve destructive application")
        org_parser.add_argument("--strategy", choices=["type","date","size"], default="type")
        execution_mode = org_parser.add_mutually_exclusive_group()
        execution_mode.add_argument("--dry-run", action="store_true", help="Preview only (the default)")
        execution_mode.add_argument("--apply", action="store_true", help="Apply the displayed plan")

        # Duplicate commands
        dup_parser = subparsers.add_parser("duplicates", help="Find duplicates")
        dup_parser.add_argument("--dir", "--source", dest="dir", required=True)
        dup_parser.add_argument("--include", action="append", default=[])
        scan_options(dup_parser)
        dup_parser.add_argument("--delete", action="store_true",
                                 help="Unavailable: duplicate deletion is disabled")

        workflow_parser = subparsers.add_parser("workflow", help="Validate or run named JSON workflows")
        workflow_sub = workflow_parser.add_subparsers(dest="workflow_cmd", required=True)
        for name in ("validate", "run"):
            command_parser = workflow_sub.add_parser(name)
            command_parser.add_argument("file", type=Path)
            command_parser.add_argument("--format", choices=["text", "json"], default="text")
            if name == "run":
                mode = command_parser.add_mutually_exclusive_group()
                mode.add_argument("--apply", action="store_true")
                mode.add_argument("--dry-run", action="store_true")
                command_parser.add_argument("--yes", action="store_true")
        history_parser = subparsers.add_parser("history", help="Read run history without creating or migrating a database")
        history_sub = history_parser.add_subparsers(dest="history_cmd", required=True)
        listing = history_sub.add_parser("list")
        listing.add_argument("--limit", type=int, default=20)
        showing = history_sub.add_parser("show")
        showing.add_argument("run_id")
        for command_parser in (listing, showing):
            command_parser.add_argument("--format", choices=["text", "json"], default="text")

        parsed = parser.parse_args(args)
        self.db_path = str(Path(parsed.database).expanduser().absolute())
        self.output_format = getattr(parsed, "format", "text")
        self.report_command = parsed.subcommand
        if parsed.interactive and parsed.subcommand:
            parser.error("--interactive cannot be combined with a command")
        if parsed.subcommand == "duplicates" and parsed.delete:
            parser.error("Duplicate deletion is disabled; omit --delete to report full SHA-256 matches.")
        if parsed.subcommand == "organize" and parsed.yes and not parsed.apply:
            parser.error("--yes requires --apply; the default is preview only")

        if parsed.subcommand == "workflow" and parsed.workflow_cmd == "run" and parsed.yes and not parsed.apply:
            parser.error("--yes requires --apply")

        if parsed.interactive or not parsed.subcommand:
            self.run_interactive()
            return

        if parsed.subcommand == "workflow":
            path = parsed.file.expanduser().absolute()
            workflow = load_workflow(path)
            if parsed.workflow_cmd == "validate":
                report = {"schema_version": 1, "command": "workflow", "action": "validate", "complete": True,
                          "config_sha256": workflow.fingerprint, "workflow": workflow.to_dict()}
                if self.output_format == "json":
                    emit_json(report)
                else:
                    console.print(f"Valid workflow: {workflow.name} ({len(workflow.steps)} steps)", markup=False)
                return 0
            report = run_workflow(workflow, base_dir=path.parent, config_path=path,
                                  apply=parsed.apply, confirmed=parsed.yes,
                                  history_path=Path(self.db_path), database_factory=lambda: self.db)
            if self.output_format == "json":
                emit_json(report)
            else:
                console.print(f"Run {report['run_id']}: {report['status']} ({report['mode']})")
                for step in report["steps"]:
                    console.print(f"{step['id']} | {step['operation']} | {step['status']}", markup=False)
                    if step["report"] is not None:
                        show_step_report(console, step["report"])
                    for error in step["diagnostics"]:
                        console.print(f"{error['code']}: {error['message']}", markup=False)
                for error in report["history"]["errors"]:
                    console.print(f"{error['code']}: {error['message']}", markup=False)
            return 0 if report["complete"] else 1

        if parsed.subcommand == "history":
            if parsed.history_cmd == "list":
                report = {"schema_version": 1, "command": "history", "complete": True,
                          "runs": Database.read_runs(self.db_path, limit=parsed.limit)}
                if self.output_format == "json":
                    emit_json(report)
                else:
                    for entry in report["runs"]:
                        console.print(f"{entry['run_id']} | {entry['status']} | {entry['workflow_name']}", markup=False)
                    if not report["runs"]:
                        console.print("No recorded runs.")
            else:
                run = Database.read_runs(self.db_path, run_id=parsed.run_id)
                if run is None:
                    raise ValueError("Run was not found")
                report = {"schema_version": 1, "command": "history", "complete": True, "run": run}
                if self.output_format == "json":
                    emit_json(report)
                else:
                    console.print(f"Run {run['run_id']}: {run['status']}")
                    for step in run["steps"]:
                        console.print(f"{step['id']} | {step['operation']} | {step['status']}", markup=False)
                        if step["report"] is not None:
                            show_step_report(console, step["report"])
                        for error in step["diagnostics"]:
                            console.print(f"{error['code']}: {error['message']}", markup=False)
                    for error in run["history"]["errors"]:
                        console.print(f"{error['code']}: {error['message']}", markup=False)
            return 0

        if parsed.subcommand in {"inspect", "duplicates"}:
            operation = parsed.subcommand
            parameters = {"source": parsed.source if operation == "inspect" else parsed.dir,
                          "includes": parsed.include, "exclusions": parsed.exclude,
                          "use_default_excludes": not parsed.no_default_excludes, "recursive": not parsed.no_recursive}
            if operation == "inspect":
                parameters.update(top=parsed.top, min_size=parsed.min_size)
            report = run_prepared(prepare_operation(operation, parameters, base_dir=Path.cwd()))
            emit_json(report) if self.output_format == "json" else show_scan_report(console, report)
            return 0 if report["complete"] else 1

        if parsed.subcommand == "task":
            if parsed.task_cmd == "add":
                try:
                    schedule_time = (datetime.strptime(parsed.schedule, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
                                     if len(parsed.schedule) == 16 else utc(parsed.schedule))
                except ValueError:
                    parser.error('Invalid schedule; use an ISO UTC offset or YYYY-MM-DD HH:MM (UTC)')
                if parsed.yes and not parsed.apply or parsed.apply and not parsed.workflow:
                    parser.error('--apply/--yes are only for scheduled workflow application')
                base_dir = Path.cwd()
                if parsed.workflow:
                    workflow = load_workflow(parsed.workflow)
                    operation = 'workflow'
                    parameters = {'workflow': workflow.to_dict(), 'apply': parsed.apply, 'confirmed': parsed.yes}
                    base_dir = parsed.workflow.expanduser().absolute().parent
                elif parsed.command:
                    operation, parameters = 'subprocess', {'command': parsed.command}
                else:
                    if not parsed.source:
                        parser.error('--operation requires --source')
                    operation, parameters = parsed.operation, {'source': parsed.source, 'includes': parsed.include}
                task = ScheduledTask(name=parsed.name, operation=operation, parameters=parameters,
                    config_path=str(parsed.workflow.expanduser().absolute()) if parsed.workflow else None,
                    schedule_time=schedule_time.isoformat(), base_dir=str(base_dir), recurrence=parsed.recurrence,
                    priority=parsed.priority, interval_minutes=parsed.interval_minutes, dependencies=parsed.depends_on,
                    max_retries=parsed.max_retries, retry_delay_seconds=parsed.retry_delay,
                    timeout_seconds=parsed.timeout, retry_safe=parsed.retry_safe)
                task_id = self.scheduler.register_task(task)
                report = {'complete': True, 'task_id': task_id}
            elif parsed.task_cmd == "list":
                report = {'complete': True, 'tasks': [task.to_dict() for task in self.db.schedules()],
                          'legacy_tasks': self.db.get_all_tasks()}
            elif parsed.task_cmd == 'attempts':
                report = {'complete': True, 'attempts': self.db.schedule_attempts()}
            elif parsed.task_cmd == 'run-due':
                before = {a['id'] for a in self.db.schedule_attempts()}
                count = asyncio.run(self.scheduler.run_due())
                attempts = [a for a in self.db.schedule_attempts() if a['id'] not in before]
                report = {'complete': all(a['status'] == 'SUCCESS' for a in attempts),
                          'dispatched': count, 'attempt_ids': [a['id'] for a in attempts]}
            elif parsed.task_cmd == "start":
                if self.output_format == 'json':
                    parser.error('task start uses text output; use task run-due --format json for a bounded run')
                try:
                    asyncio.run(self._run_scheduler_live())
                except KeyboardInterrupt:
                    console.print('Stopped; inspect attempts for partial outcomes.')
                return 0
            elif parsed.task_cmd == 'recover':
                self.scheduler.recover_task(parsed.task_id, acknowledged=parsed.acknowledge)
                report = {'complete': True, 'status': 'PAUSED'}
            else:
                getattr(self.scheduler, parsed.task_cmd + '_task')(parsed.task_id)
                report = {'complete': True, 'requested': parsed.task_cmd}
            emit_json(report) if self.output_format == 'json' else console.print(json.dumps(report, indent=2), markup=False)
            return 0 if report['complete'] else 1

        elif parsed.subcommand == "organize":
            parameters = {"source": parsed.source, "destination": parsed.destination,
                          "includes": parsed.include or [], "all_files": parsed.all_files,
                          "exclusions": parsed.exclude, "use_default_excludes": not parsed.no_default_excludes,
                          "recursive": not parsed.no_recursive, "strategy": parsed.strategy,
                          "template": parsed.template, "action": parsed.action, "conflict_policy": parsed.conflict}
            prepared = prepare_operation("organize", parameters, base_dir=Path.cwd(), organizer=self.organizer)
            plan = prepared.plan

            if self.output_format == "text":
                self.show_plan(plan)
            if not parsed.apply:
                report = run_prepared(prepared)
                if self.output_format == "json":
                    emit_json(report)
                    return 0 if report["complete"] else 1
                return self.show_results(prepared.results)
            confirmed = parsed.yes
            if plan.requires_confirmation and not confirmed:
                if self.output_format == "json" or not sys.stdin.isatty():
                    raise ConfirmationRequired("Confirmation required; inspect preview, then use --apply --yes")
                confirmed = Confirm.ask("Apply this displayed plan and remove moved source files?", default=False)
                if not confirmed:
                    console.print("Plan not applied; no files or history changed.")
                    return 0
            return self.apply_tracked(prepared, confirmed=confirmed)

        return 0


def main(args: Optional[List[str]] = None) -> int:
    """Console/module entry point with actionable failures and resource cleanup."""
    # Preserve the caller's encoding while making legacy Windows pipes capable
    # of displaying any path. Unrepresentable text becomes readable escapes;
    # JSON already uses lossless ASCII escapes and remains an exact document.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="backslashreplace")
            except (OSError, ValueError):
                pass  # Some embedding/capture streams cannot be reconfigured.
    logging.basicConfig(level=logging.WARNING)
    cli = TaskMasterCLI()
    try:
        return cli.run_cli(args) or 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        if cli.output_format == "json":
            emit_json({"schema_version": 1, "command": cli.report_command, "complete": False, "error": safe_message(str(error))})
        else:
            console.print(f"Error: {safe_message(str(error))}", markup=False)
        return 1
    finally:
        cli.close()


if __name__ == "__main__":
    raise SystemExit(main())
