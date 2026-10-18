# Platform validation

The CI target matrix is Windows and Ubuntu with CPython 3.12, 3.13 and 3.14.
Local evidence is Windows / Python 3.12.4. Matrix configuration is not a passing
CI result: hosted runs require a connected repository. WSL is installed on this
host without a Linux distribution, so no local Linux result is claimed.

- Pattern matching is case-sensitive on every platform, independently of the
  filesystem's case rules. Paths in reports retain platform-native spelling.
- Organization rejects nonportable destination components and reserved Windows
  names even on POSIX. Unicode filenames and JSON reports are supported; text
  output escapes characters unavailable in a terminal's encoding.
- Source/destination symlinks, Windows junctions and reparse points are rejected.
  Real junction fixtures are exercised on Windows. Real file-symlink tests skip
  if the account lacks privileges; Linux should exercise the symlink path.
- File access/write/unlink failures are primarily injected to produce repeatable
  tests. Running as root/admin can bypass ordinary permission bits, so the suite
  does not equate chmod-based tests with complete ACL coverage.
- SQLite and filesystem changes are separate. Power loss, network filesystems,
  full ACL/alternate-stream preservation and hostile concurrent mutation are not
  certified by these tests.
- Use `.venv/Scripts/python.exe` on Windows and `.venv/bin/python` on Linux.
  Quote globs so the shell passes them unchanged. `--database` precedes the
  command; its parent directory must exist.
- Some managed Windows environments deny the default temporary directory. Point
  `TEMP` and `TMP` at an existing writable directory before venv, pip, build and
  installed-package checks. The verifier creates/removes only its own temporary
  directory. Coverage data for subprocesses uses the configured project paths.

- Phase 6 timeout/cancellation tests exercise real Windows Job Object cleanup of
  nested descendants. POSIX uses process-group termination; that branch awaits
  hosted Linux results. Abrupt POSIX owner death can leave children alive, so
  interrupted schedules block dispatch pending explicit operator review.

The current `requires-python` is a lower bound, not a claim that future Python
versions or macOS have passed. A release needs actual green matrix results and
the separate provenance gate in [RELEASE.md](RELEASE.md).
