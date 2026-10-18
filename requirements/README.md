# Tested dependency baseline

`runtime.txt` and `dev.txt` are generated, fully pinned, hashed requirements.
Runtime has no audit/test/build dependencies. Dev includes runtime plus the tools
declared in `pyproject.toml`; pip/setuptools/wheel are pinned build tooling.
The initial baseline was resolved on Windows / CPython 3.12. CI installs the same
pins on Windows and Linux / 3.12–3.14. Those other combinations are targets until
their CI jobs have actually passed. Hashes cover available distribution files;
they verify downloads, not the safety or provenance of package contents.

Generate updates intentionally, then review and rerun audit/tests/package checks:

```text
python -m piptools compile --generate-hashes --strip-extras --no-emit-index-url --output-file requirements/runtime.txt pyproject.toml
python -m piptools compile --allow-unsafe --extra dev --generate-hashes --strip-extras --no-emit-index-url --output-file requirements/dev.txt pyproject.toml
```

`--allow-unsafe` is pip-tools' historical name for including pip/setuptools in
the lock; it does not waive hash verification or permit unsafe project execution.
The generated files do not pin TaskMaster itself. Install the selected baseline
with `--require-hashes`, then install the local project with `--no-deps
--no-build-isolation`. Do not use the lockfiles to claim deterministic wheel bytes
or an offline build without first downloading all required artifacts. Exact
versions reduce environment drift; audits must still be repeated over time.
