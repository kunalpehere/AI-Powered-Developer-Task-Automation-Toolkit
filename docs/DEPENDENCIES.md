# Dependency baseline and review

TaskMaster's only direct runtime dependency is `rich>=13.8,<14`. The pinned
runtime closure is Rich 13.9.4, markdown-it-py 4.2.0, mdurl 0.1.2 and Pygments
2.21.0. Optional Pillow/PyPDF2 are not installed or advertised as supported.
Development tools remain optional and are not required by the wheel at runtime.

The [lockfile guide](../requirements/README.md) explains regeneration. Both
baselines pin exact versions and accepted SHA-256 download hashes. Install with
`--require-hashes`; install the local project separately with `--no-deps
--no-build-isolation`. Generated requirements retain dependency origins for review.
The build uses the pinned development setuptools/wheel without hidden build
isolation downloads. This is reproducible dependency selection, not a claim of
bit-for-bit wheel reproducibility across operating systems or timestamps.

## Advisory checks

Use the commands in [RELEASE.md](RELEASE.md). `pip-audit` queries the PyPI advisory
service for the pinned requirements. `--disable-pip` reads the committed resolved
versions without asking pip to resolve/install them. Actual artifact hash
verification happens during `pip install --require-hashes`, not during this
metadata-only advisory lookup. CI checks runtime and development baselines separately and
fails on findings or lookup errors. No vulnerability IDs are ignored.

The recorded Phase 5 audit is a point-in-time advisory check, not proof that
packages are bug-free, nonmalicious or suitable for every use. It does not scan
the project source, OS, interpreter, GitHub Actions or arbitrary dynamic plugins.
Rerun after dependency updates and before publishing. Known scheduler/filesystem
limitations require the separate behavioral review described in the README.

Primary references used to configure the tooling:

- [pip-audit usage and security model](https://github.com/pypa/pip-audit#usage)
- [pip-tools hash generation](https://github.com/jazzband/pip-tools#using-hashes)
- [Ruff configuration](https://docs.astral.sh/ruff/configuration/)
- [Coverage subprocess collection](https://coverage.readthedocs.io/en/latest/subprocess.html)
- [GitHub's Python CI guide](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)

Third-party license metadata/notices are inventoried separately from the supplied
TaskMaster snapshot. Their metadata does not resolve that snapshot's missing
upstream terms. Preserve package notices when distributing dependencies and
resolve the project provenance gate in [ATTRIBUTION.md](../ATTRIBUTION.md).
