# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mcp>=2.3,<3",
#   # Benchpark's runtime needs, so this environment can also run Benchpark/Ramble
#   "pyyaml", "deepdiff", "packaging", "pytest", "scipy",
#   # Benchpark's [analyze] extra, for profile_summary and `benchpark analyze`
#   "llnl-hatchet>=2025.2.0", "llnl-thicket[plotting]>=2026.1.0", "matplotlib",
# ]
# ///
# Copyright 2023 Lawrence Livermore National Security, LLC and other
# Benchpark Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: Apache-2.0
"""Benchpark MCP server.

A thin layer over the tools Benchpark users already run (benchpark, ramble,
spack, flux/slurm). It adds agent-facing context (GUIDE.md and the Benchpark
docs), file access scoped to the Benchpark checkout and configured roots,
background builds, job tracking, and compact status/results.

All state lives in the filesystem (Benchpark's own files, plus
<workspace>/.benchpark-mcp/{build,jobs}.json), so the server can be restarted
at any time.

Configuration (optional environment variables; empty means unset):
  BENCHPARK_ROOT       Benchpark checkout (default: two levels above this file)
  BENCHPARK_PYTHON     Python that runs Benchpark (default: this Python, which
                       `uv run --script` gives Benchpark's requirements)
  BENCHPARK_MCP_ROOTS  os.pathsep-separated directories where systems, experiments
                       and workspaces may be created (default: the launch directory)
"""

import glob
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

HERE = Path(__file__).resolve().parent
BENCHPARK_ROOT = (
    Path(os.environ.get("BENCHPARK_ROOT") or HERE.parents[1]).expanduser().resolve()
)
BENCHPARK_PYTHON = os.environ.get("BENCHPARK_PYTHON") or sys.executable
ROOTS = [
    Path(p).expanduser().resolve()
    for p in (os.environ.get("BENCHPARK_MCP_ROOTS") or os.getcwd()).split(os.pathsep)
    if p
]
READ_ONLY_ROOTS = [Path("~/.benchpark").expanduser().resolve()]
MAX_CHARS = int(os.environ.get("BENCHPARK_MCP_MAX_CHARS", "20000"))
STATE_DIR = ".benchpark-mcp"

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITES = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, open_world_hint=False
)
RUNS_ANYTHING = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, open_world_hint=True
)
ASK_USER = {"anthropic/requiresUserInteraction": True}

INSTRUCTIONS = """\
Benchpark: define, build, run and analyze reproducible HPC benchmark experiments
(RAJAPerf, AMG2023, Kripke, HPL, STREAM, OSU, LAMMPS, ...) on HPC systems
(LLNL El Capitan/Tuolumne/Dane, Frontier, Perlmutter, AWS, ...), and author new
Benchpark systems, benchmarks and experiments.
Start with guide() for the model and workflow. Typical flow: cluster_info ->
describe -> validate_specs -> create_experiment -> build -> status ->
preview_submission (show the user) -> submit -> status -> results / profile_summary.
Never submit jobs with flux batch, sbatch or `ramble on` directly; use submit().
"""

mcp = MCPServer("benchpark", instructions=INSTRUCTIONS)


# ---------------------------------------------------------------- helpers


def _truncate(text, limit=MAX_CHARS):
    if len(text) <= limit:
        return text
    half = limit // 2
    return (
        text[:half]
        + f"\n... [{len(text) - limit} characters omitted; use read_file with grep/start_line"
        " on the log, or narrow the command] ...\n" + text[-half:]
    )


def _env():
    env = dict(os.environ)
    # Make sure `python3` inside benchpark/ramble/spack resolves to BENCHPARK_PYTHON.
    env["PATH"] = str(Path(BENCHPARK_PYTHON).parent) + os.pathsep + env.get("PATH", "")
    return env


def _run(argv, cwd=None, timeout=600, raw=False):
    """Run a command (never through a shell with model input) and capture output.
    raw=True skips truncation, for machine-readable output the server parses."""
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            env=_env(),
            stdin=subprocess.DEVNULL,  # stdin is the MCP channel; never share it
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ToolError(
            f"Timed out after {timeout}s: {shlex.join(argv)}. Pass a larger timeout_s, "
            "or use build() for long builds."
        )
    except FileNotFoundError:
        raise ToolError(f"Command not found: {argv[0]}")
    out = {
        "command": shlex.join(argv),
        "exit_code": proc.returncode,
        "stdout": proc.stdout if raw else _truncate(proc.stdout),
        "stderr": _truncate(proc.stderr, MAX_CHARS // 2),
    }
    if proc.returncode and "ModuleNotFoundError" in proc.stderr:
        out["hint"] = (
            f"BENCHPARK_PYTHON ({BENCHPARK_PYTHON}) is missing a Python package. Point "
            "BENCHPARK_PYTHON at an environment with `pip install -r requirements.txt` "
            "from the Benchpark checkout."
        )
    return out


def _benchpark(args, cwd=None, timeout=900):
    # lib/main.py directly: bin/benchpark re-raises failures as CalledProcessError,
    # which buries the real error message.
    return _run(
        [BENCHPARK_PYTHON, str(BENCHPARK_ROOT / "lib" / "main.py"), *args], cwd, timeout
    )


def _check(result, what):
    if result["exit_code"] != 0:
        text = result["stderr"].strip() or result["stdout"].strip()
        last = text.splitlines()[-1] if text else "(no output)"
        raise ToolError(
            f"{what} failed (exit {result['exit_code']}): {last[:1500]}\n\n"
            f"command: {result['command']}\n\noutput tail:\n{text[-3000:]}"
        )
    return result


def _within(path, roots):
    return any(path == r or r in path.parents for r in roots)


def _resolve(path, write=False):
    """Resolve a user path; relative paths are relative to the Benchpark checkout."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = BENCHPARK_ROOT / p
    p = p.resolve()
    allowed = [BENCHPARK_ROOT, *ROOTS] + ([] if write else READ_ONLY_ROOTS)
    if not _within(p, allowed):
        raise ToolError(
            f"{p} is outside the allowed directories: {', '.join(map(str, allowed))}. "
            "Ask the user to add a parent directory to BENCHPARK_MCP_ROOTS."
        )
    return p


def _workspace(path):
    p = _resolve(path)
    for cand in (p, p / "workspace"):
        if (cand / "configs" / "ramble.yaml").exists():
            return cand
    raise ToolError(
        f"No Ramble workspace at {p} (expected configs/ramble.yaml). Pass the path returned "
        "by create_experiment, e.g. <root>/workspaces/<system>/<experiment>/workspace."
    )


def _experiments_root(ws):
    for parent in ws.parents:
        if (parent / "setup.sh").exists():
            return parent
    raise ToolError(
        f"Could not find setup.sh above {ws}; was it created with `benchpark setup`?"
    )


def _in_workspace(ws, argv, timeout=600):
    """Run a command with the workspace's spack/ramble environment (setup.sh) loaded."""
    setup = shlex.quote(str(_experiments_root(ws) / "setup.sh"))
    script = f'. {setup} >/dev/null 2>&1 && exec "$@"'
    return _run(["bash", "-c", script, "bash", *argv], cwd=str(ws), timeout=timeout)


def _state(ws, name, default=None):
    f = ws / STATE_DIR / name
    return json.loads(f.read_text()) if f.exists() else default


def _save_state(ws, name, data):
    d = ws / STATE_DIR
    d.mkdir(exist_ok=True)
    tmp = d / (name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(d / name)


def _tail(path, n=15):
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return []
    return [line for line in lines if line.strip()][-n:]


def _summarize_ramble_yaml(path):
    """Compact view of a generated ramble.yaml: experiments, variables, software, modifiers."""
    data = yaml.safe_load(Path(path).read_text())["ramble"]
    experiments = []
    for app, app_def in data.get("applications", {}).items():
        for wl, wl_def in app_def.get("workloads", {}).items():
            for name, exp in wl_def.get("experiments", {}).items():
                experiments.append(
                    {
                        "application": app,
                        "workload": wl,
                        "name_template": name,
                        "variables": exp.get("variables", {}),
                        "zips": exp.get("zips") or None,
                        "matrix": exp.get("matrix") or None,
                        "exclude": exp.get("exclude") or None,
                    }
                )
    software = data.get("software", {}).get("packages", {})
    return {
        "experiments": experiments,
        "software": {k: v.get("spack_pkg_spec") or v for k, v in software.items()},
        "modifiers": data.get("modifiers", []),
        "spec": data.get("config", {}).get("spec"),
    }


def _run_dirs(ws):
    return sorted(
        Path(p).parent
        for p in glob.glob(
            str(ws / "experiments" / "*" / "*" / "*" / "execute_experiment")
        )
    )


# ---------------------------------------------------------------- context


@mcp.tool(annotations=READ_ONLY)
def guide(topic: str = "overview") -> str:
    """Benchpark knowledge for agents. Start here.

    topic="overview" returns the agent guide: concepts, spec syntax, workflow, file
    layout, how to author systems/benchmarks/experiments, and gotchas.
    topic="list" lists the Benchpark documentation pages; any page name (for
    example "add-a-system-config", "add-an-experiment", "modifiers", "FAQ",
    "benchpark-analyze") returns that page's text.
    """
    if topic in ("overview", "guide", ""):
        return (HERE / "GUIDE.md").read_text()
    docs = sorted(
        Path(p)
        for p in glob.glob(
            str(BENCHPARK_ROOT / "docs" / "**" / "*.rst"), recursive=True
        )
    )
    if topic == "list":
        return "Documentation pages (pass the name as topic):\n" + "\n".join(
            str(p.relative_to(BENCHPARK_ROOT / "docs").with_suffix("")) for p in docs
        )
    topic = topic.removesuffix(".rst")
    for p in docs:
        if (
            str(p.relative_to(BENCHPARK_ROOT / "docs").with_suffix("")) == topic
            or p.stem == topic
        ):
            return _truncate(p.read_text(), MAX_CHARS * 2)
    raise ToolError(
        f"No documentation page '{topic}'. Call guide(topic='list') to see the pages."
    )


@mcp.tool(annotations=READ_ONLY)
def catalog(kind: str = "experiments") -> str:
    """List what Benchpark defines. kind: "experiments" (benchmark + supported
    programming models + scaling modes), "systems" (with cluster/instance choices),
    "benchmarks", or "modifiers"."""
    if kind not in ("experiments", "systems", "benchmarks", "modifiers"):
        raise ToolError(
            "kind must be one of: experiments, systems, benchmarks, modifiers"
        )
    return _check(_benchpark(["list", kind]), f"benchpark list {kind}")["stdout"]


@mcp.tool(annotations=READ_ONLY)
def describe(kind: str, name: str) -> dict[str, Any]:
    """Describe one experiment or system: variants (values, defaults, descriptions),
    maintainers, hardware (systems), and the source files that define it so you can
    read or copy them. kind: "experiment" or "system". name: e.g. "raja-perf",
    "llnl-elcapitan"."""
    if kind not in ("experiment", "system"):
        raise ToolError('kind must be "experiment" or "system"')
    info = _check(_benchpark(["info", kind, name]), f"benchpark info {kind} {name}")[
        "stdout"
    ]
    info = "\n".join(
        line
        for line in info.splitlines()
        if not line.strip().startswith(("validator:", "sticky:"))
    )
    base = name.split(".")[-1]
    under = base.replace("-", "_")
    if kind == "system":
        candidates = [f"systems/{name}/system.py"]
    else:
        candidates = [
            f"experiments/{name.replace('.', '/')}/experiment.py",
            f"experiments/test/{base}/experiment.py",
            f"repos/ramble_applications/{under}/application.py",
            f"repos/ramble_applications/hecbench/{under}/application.py",
            f"repos/spack_repo/benchpark/packages/{under}/package.py",
        ]
        builtin = (
            READ_ONLY_ROOTS[0]
            / "spack-packages/repos/spack_repo/builtin/packages"
            / under
            / "package.py"
        )
        if builtin.exists():
            candidates.append(str(builtin))
    files = [c for c in candidates if (BENCHPARK_ROOT / c).exists() or Path(c).exists()]
    return {"info": _truncate(info), "source_files": files}


@mcp.tool(annotations=READ_ONLY)
def cluster_info() -> dict[str, Any]:
    """Where am I? Hostname, the Benchpark system definition that matches this
    machine (if any), scheduler, queues/partitions, the user's banks/accounts, and
    the directories this server may create workspaces in (allowed_roots)."""
    host = socket.gethostname()
    base = re.sub(r"\d+$", "", host.split(".")[0])
    matches = []
    for f in sorted(glob.glob(str(BENCHPARK_ROOT / "systems" / "*" / "system.py"))):
        if re.search(rf'["\']{re.escape(base)}["\']', Path(f).read_text()):
            matches.append(Path(f).parent.name)
    out = {
        "hostname": host,
        "cluster_name_guess": base,
        "matching_systems": matches,
        "allowed_roots": [str(r) for r in ROOTS],
        "allowed_roots_note": "Create workspaces under one of these (not inside the "
        "Benchpark checkout). To allow another directory, the user sets "
        "BENCHPARK_MCP_ROOTS before starting the client.",
    }
    if matches:
        out["suggested_system_spec"] = f"{matches[0]} cluster={base}"
    if shutil.which("flux"):
        out["scheduler"] = "flux"
        out["resources"] = _run(["flux", "resource", "list"], timeout=60)["stdout"]
        out["accounts"] = _run(
            ["flux", "account", "view-user", os.environ.get("USER", "")], timeout=60
        )["stdout"]
    elif shutil.which("sinfo"):
        out["scheduler"] = "slurm"
        out["resources"] = _run(["sinfo", "-s"], timeout=60)["stdout"]
        out["accounts"] = _run(
            [
                "sacctmgr",
                "-n",
                "-P",
                "show",
                "assoc",
                f"user={os.environ.get('USER', '')}",
                "format=account,partition,qos",
            ],
            timeout=60,
        )["stdout"]
    else:
        out["scheduler"] = "none found (flux/slurm not on PATH)"
    return out


# ---------------------------------------------------------------- files


@mcp.tool(annotations=READ_ONLY)
def list_files(
    path: str = ".", pattern: str = "*", recursive: bool = False
) -> list[str]:
    """List files under a directory (relative paths are relative to the Benchpark
    checkout). pattern is a glob, e.g. "*.py"; recursive searches subdirectories."""
    root = _resolve(path)
    if not root.is_dir():
        raise ToolError(f"{root} is not a directory")
    it = root.rglob(pattern) if recursive else root.glob(pattern)
    entries = sorted(str(p) + ("/" if p.is_dir() else "") for p in it)
    if len(entries) > 500:
        entries = entries[:500] + [f"... {len(entries) - 500} more; narrow the pattern"]
    return entries


@mcp.tool(annotations=READ_ONLY)
def read_file(
    path: str, start_line: int = 1, max_lines: int = 400, grep: str | None = None
) -> str:
    """Read a text file: Benchpark sources (relative to the checkout), workspace
    files, logs, scripts, results. grep is a regular expression; when given, only
    matching lines (with line numbers and 2 lines of context) are returned. Use it
    for large logs, e.g. grep="error|Error|FAILED"."""
    p = _resolve(path)
    if not p.is_file():
        raise ToolError(f"{p} is not a file")
    lines = p.read_text(errors="replace").splitlines()
    if grep:
        rx = re.compile(grep)
        keep = set()
        for i, line in enumerate(lines):
            if rx.search(line):
                keep.update(range(max(0, i - 2), min(len(lines), i + 3)))
        picked = sorted(keep)[: max_lines * 3]
        body = "\n".join(f"{i + 1}: {lines[i]}" for i in picked)
        return _truncate(f"{p} ({len(lines)} lines, {len(picked)} shown)\n{body}")
    start = max(1, start_line)
    chunk = lines[start - 1 : start - 1 + max_lines]
    more = len(lines) - (start - 1 + len(chunk))
    note = (
        f"\n... {more} more lines; call again with start_line={start + len(chunk)}"
        if more > 0
        else ""
    )
    return _truncate(
        f"{p} (lines {start}-{start + len(chunk) - 1} of {len(lines)})\n"
        + "\n".join(chunk)
        + note
    )


@mcp.tool(annotations=WRITES)
def write_file(path: str, content: str) -> str:
    """Create or overwrite a text file inside the Benchpark checkout or an allowed
    root. Use it to author systems/<name>/system.py, experiments/<name>/experiment.py,
    repos/ramble_applications/<name_>/application.py,
    repos/spack_repo/benchpark/packages/<name_>/package.py, or to edit workspace
    configs. Parent directories are created."""
    p = _resolve(path, write=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    p.write_text(content)
    return f"{'Overwrote' if existed else 'Created'} {p} ({len(content.splitlines())} lines)"


# ---------------------------------------------------------------- commands


@mcp.tool(annotations=RUNS_ANYTHING)
def benchpark(
    args: list[str], cwd: str | None = None, timeout_s: int = 900
) -> dict[str, Any]:
    """Run any benchpark CLI command, e.g. ["system", "init", "--dest=/abs/dir",
    "llnl-cluster", "cluster=dane"], ["experiment", "init", "/abs/sysdir", "saxpy",
    "+openmp"], ["setup", "/abs/sysdir/saxpy", "/abs/experiments_root"], ["audit"],
    ["unit-test", "-k", "experiment"], ["analyze", "--workspace-dir", ws, ...],
    ["query", dir, "--metric", ...], ["show-build", "dump", ws, dest],
    ["system", "external", spec, "--propose"], ["info", ...], ["list", ...].
    cwd defaults to the first allowed root. Use absolute paths."""
    work = _resolve(cwd, write=True) if cwd else ROOTS[0]
    return _benchpark(args, cwd=str(work), timeout=timeout_s)


@mcp.tool(annotations=RUNS_ANYTHING)
def ramble(workspace: str, args: list[str], timeout_s: int = 600) -> dict[str, Any]:
    """Run a ramble command against a workspace, with its spack/ramble environment
    loaded (equivalent to `. setup.sh; ramble --workspace-dir <ws> <args>`).
    Examples: ["workspace", "info", "-v"], ["workspace", "setup", "--dry-run"],
    ["workspace", "analyze", "-f", "json"], ["workspace", "experiment-logs", "--failed"],
    ["workspace", "config", "-p"]. Filters: ["--where", "{n_nodes} == 1"].
    `on` is refused here; use preview_submission + submit."""
    ws = _workspace(workspace)
    if "on" in args:
        raise ToolError(
            "Use preview_submission() and submit() to run experiments, so the user approves the allocation."
        )
    return _in_workspace(
        ws,
        ["ramble", "--color", "never", "--workspace-dir", str(ws), *args],
        timeout=timeout_s,
    )


@mcp.tool(annotations=RUNS_ANYTHING)
def spack(
    workspace: str, args: list[str], env: str | None = None, timeout_s: int = 600
) -> dict[str, Any]:
    """Run a spack command with a workspace's Spack instance. env names a Spack
    environment under <workspace>/software/spack/ (usually the benchmark name with
    underscores, e.g. "raja_perf") to run inside it (`spack -e`). Examples:
    ["find", "-lv"], ["spec", "-I"], ["logs", "caliper"], ["info", "raja-perf"],
    ["config", "blame", "packages"]."""
    ws = _workspace(workspace)
    pre = []
    if env:
        env_dir = ws / "software" / "spack" / env
        if not env_dir.is_dir():
            choices = [
                p.name for p in (ws / "software" / "spack").glob("*") if p.is_dir()
            ]
            raise ToolError(
                f"No Spack environment '{env}' in {ws}. Available: {choices}"
            )
        pre = ["-e", str(env_dir)]
    return _in_workspace(ws, ["spack", *pre, *args], timeout=timeout_s)


# ---------------------------------------------------------------- experiments


@mcp.tool(annotations=READ_ONLY)
def validate_specs(
    system_spec: str, experiment_spec: str | None = None
) -> dict[str, Any]:
    """Check a system spec (and optionally an experiment spec) without keeping any
    files or using compute. Runs `benchpark system init` / `experiment init` in a
    temporary directory and returns the concrete system variables (scheduler, queue,
    timeout, cores/GPUs per node) and the generated experiments (name templates,
    variables, zips/matrices, software specs, modifiers). Errors come back verbatim,
    e.g. invalid variant values or a timeout longer than the queue allows.
    Example: validate_specs("llnl-elcapitan cluster=tuolumne queue=pdebug timeout=30",
    "raja-perf +rocm caliper=time")."""
    tmp = Path(tempfile.mkdtemp(prefix="benchpark-mcp-"))
    try:
        sysdir = tmp / "system"
        _check(
            _benchpark(
                ["system", "init", f"--dest={sysdir}", *shlex.split(system_spec)],
                cwd=str(tmp),
            ),
            "system init",
        )
        variables = yaml.safe_load((sysdir / "variables.yaml").read_text())["variables"]
        concrete = yaml.safe_load((sysdir / "system_id.yaml").read_text())["system"][
            "spec"
        ]
        out = {"system": {"spec": concrete, "variables": variables}}
        if experiment_spec:
            _check(
                _benchpark(
                    [
                        "experiment",
                        "init",
                        "--dest",
                        "exp",
                        str(sysdir),
                        *shlex.split(experiment_spec),
                    ],
                    cwd=str(tmp),
                ),
                "experiment init",
            )
            out["experiment"] = _summarize_ramble_yaml(sysdir / "exp" / "ramble.yaml")
            out["note"] = (
                "List-valued variables expand into several experiments (zipped unless in "
                "'matrix'). build(dry_run=True) after create_experiment renders every script."
            )
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@mcp.tool(annotations=WRITES)
def create_experiment(
    system_spec: str,
    experiment_spec: str,
    root: str,
    system_name: str | None = None,
    experiment_name: str | None = None,
) -> dict[str, Any]:
    """Create everything needed to build and run an experiment, under root (an
    absolute directory inside an allowed root):
      <root>/<system_name>/                     system definition (reused if it exists
                                                with the same spec)
      <root>/<system_name>/<experiment_name>/   ramble.yaml
      <root>/workspaces/<system_name>/<experiment_name>/workspace   Ramble workspace
    system_name defaults to "<system>-<cluster>", experiment_name to the benchmark name.
    The first setup in a root clones spack/ramble into <root>/workspaces (minutes).
    Returns the workspace path to pass to build/status/submit/results."""
    root_p = _resolve(root, write=True)
    root_p.mkdir(parents=True, exist_ok=True)
    sys_tokens = shlex.split(system_spec)
    exp_tokens = shlex.split(experiment_spec)
    if not system_name:
        flavor = next(
            (
                t.split("=", 1)[1]
                for t in sys_tokens
                if t.startswith(("cluster=", "instance_type="))
            ),
            None,
        )
        system_name = sys_tokens[0] + (f"-{flavor}" if flavor else "")
    experiment_name = experiment_name or exp_tokens[0].split(".")[-1]
    sysdir = root_p / system_name
    notes = []

    if sysdir.exists():
        cmd = yaml.safe_load((sysdir / "system_id.yaml").read_text())["system"].get(
            "benchpark_system_command", ""
        )
        old = [t for t in shlex.split(cmd)[3:] if not t.startswith("--dest")]
        if sorted(old) != sorted(sys_tokens):
            raise ToolError(
                f"{sysdir} already holds a different system spec ({' '.join(old)}). "
                "Pass another system_name, or delete that directory."
            )
        notes.append(f"Reused existing system definition {sysdir}")
    else:
        _check(
            _benchpark(
                ["system", "init", f"--dest={sysdir}", *sys_tokens], cwd=str(root_p)
            ),
            "system init",
        )

    expdir = sysdir / experiment_name
    if expdir.exists():
        raise ToolError(
            f"{expdir} already exists. Pass another experiment_name, or delete it first."
        )
    _check(
        _benchpark(
            ["experiment", "init", "--dest", experiment_name, str(sysdir), *exp_tokens],
            cwd=str(root_p),
        ),
        "experiment init",
    )
    experiments_root = root_p / "workspaces"
    _check(
        _benchpark(
            ["setup", str(expdir), str(experiments_root)], cwd=str(root_p), timeout=1800
        ),
        "benchpark setup",
    )
    ws = experiments_root / system_name / experiment_name / "workspace"
    return {
        "workspace": str(ws),
        "system_dir": str(sysdir),
        "experiment_dir": str(expdir),
        "experiments_root": str(experiments_root),
        "experiment": _summarize_ramble_yaml(expdir / "ramble.yaml"),
        "notes": notes,
        "next": "build(workspace) to compile (background), or build(workspace, dry_run=True) to render scripts only.",
    }


@mcp.tool(annotations=RUNS_ANYTHING)
def build(
    workspace: str,
    dry_run: bool = False,
    on_compute_node: bool = False,
    queue: str | None = None,
    time_minutes: int = 60,
    where: str | None = None,
) -> dict[str, Any]:
    """Build a workspace: `ramble workspace setup` (Spack concretize + install, then
    render each experiment's execute_experiment script).
    dry_run=True renders scripts without compiling and returns right away.
    Otherwise the build runs in the background; poll status(workspace).
    on_compute_node=True runs it inside a one-node allocation (flux run / srun) on
    `queue` for up to time_minutes, instead of on the login node.
    where is a Ramble filter such as "{n_nodes} == 1"."""
    ws = _workspace(workspace)
    filt = ["--where", where] if where else []
    if dry_run:
        res = _check(
            _in_workspace(
                ws,
                [
                    "ramble",
                    "--workspace-dir",
                    str(ws),
                    "workspace",
                    "setup",
                    "--dry-run",
                    *filt,
                ],
            ),
            "dry run",
        )
        return {
            "scripts": [str(d / "execute_experiment") for d in _run_dirs(ws)],
            "output_tail": res["stdout"][-3000:],
        }

    prev = _state(ws, "build.json")
    if prev and _pid_alive(prev["pid"]):
        raise ToolError(
            f"A build is already running (pid {prev['pid']}). Check status({str(ws)!r})."
        )
    launcher = []
    if on_compute_node:
        if shutil.which("flux"):
            launcher = [
                "flux",
                "run",
                "-N1",
                "--exclusive",
                "-t",
                f"{time_minutes}m",
            ] + (["-q", queue] if queue else [])
        elif shutil.which("srun"):
            launcher = ["srun", "-N1", "--exclusive", "-t", str(time_minutes)] + (
                ["-p", queue] if queue else []
            )
        else:
            raise ToolError("No flux or srun found to run the build on a compute node.")
    cmd = [*launcher, "ramble", "--workspace-dir", str(ws), "workspace", "setup", *filt]
    log = ws / "logs" / "mcp-build.log"
    log.parent.mkdir(exist_ok=True)
    setup = shlex.quote(str(_experiments_root(ws) / "setup.sh"))
    script = f'. {setup} >/dev/null 2>&1 && "$@"; echo "BENCHPARK_MCP_EXIT=$?"'
    with open(log, "w") as fh:
        proc = subprocess.Popen(
            ["bash", "-c", script, "bash", *cmd],
            cwd=str(ws),
            env=_env(),
            stdin=subprocess.DEVNULL,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # keeps running if the server restarts
        )
    _save_state(
        ws,
        "build.json",
        {
            "pid": proc.pid,
            "started": time.time(),
            "log": str(log),
            "command": shlex.join(cmd),
        },
    )
    return {
        "started": True,
        "pid": proc.pid,
        "log": str(log),
        "next": "Poll status(workspace) every minute or two.",
    }


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # reap if it is our own child, so it does not linger as a zombie
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True


def _build_status(ws):
    b = _state(ws, "build.json")
    if not b:
        return None
    lines = _tail(b["log"], 400)
    code = next(
        (
            int(m.group(1))
            for line in lines
            if (m := re.match(r"BENCHPARK_MCP_EXIT=(\d+)", line))
        ),
        None,
    )
    state = (
        "running"
        if _pid_alive(b["pid"]) and code is None
        else ("succeeded" if code == 0 else "failed")
    )
    out = {
        "state": state,
        "elapsed_min": round((time.time() - b["started"]) / 60, 1),
        "command": b["command"],
        "log": b["log"],
    }
    if state == "succeeded":
        return out
    out["log_tail"] = lines[-12:]
    # Ramble streams Spack's output to per-experiment logs under logs/setup.<ts>/
    detail = [
        p
        for p in glob.glob(str(ws / "logs" / "setup.*" / "*.out"))
        if os.path.getmtime(p) >= b["started"]
    ]
    if detail:
        newest = max(detail, key=os.path.getmtime)
        dlines = _tail(newest, 2000)
        installed = [
            m.group(1)
            for line in dlines
            if (m := re.match(r"^\s*[a-z0-9]{7} (\S+@\S+) /\S+ \(", line))
        ]
        out["detail_log"] = newest
        out["detail_log_tail"] = [line[-300:] for line in dlines[-8:]]
        if installed:
            out["installed_packages"] = installed
    if state == "failed":
        out["hint"] = (
            "Find the cause with read_file(<log>, grep='Error|error:'), then the files under "
            "logs/setup.<timestamp>/ and the Spack stage logs in <experiments_root>/builds/."
        )
    return out


# ---------------------------------------------------------------- running


_DIRECTIVE = re.compile(r"^#\s*(flux:|SBATCH|BSUB|PBS|PJM)")
_LAUNCH = re.compile(r"^\s*(flux run|srun|mpirun|mpiexec|jsrun|aprun)\b")


@mcp.tool(annotations=READ_ONLY)
def preview_submission(workspace: str) -> dict[str, Any]:
    """Show what submit() would send to the scheduler: for each experiment, its batch
    directives (nodes, walltime, queue, bank) and launch line, plus totals. Show this
    to the user and get their approval before calling submit()."""
    ws = _workspace(workspace)
    dirs = _run_dirs(ws)
    if not dirs:
        raise ToolError(
            "No execute_experiment scripts yet. Run build(workspace) (or build(dry_run=True)) first."
        )
    jobs, node_minutes = [], 0
    for d in dirs:
        text = (d / "execute_experiment").read_text().splitlines()
        directives = [line.strip() for line in text if _DIRECTIVE.match(line)]
        launch = next((line.strip() for line in text if _LAUNCH.match(line)), None)
        joined = " ".join(directives)
        # node and walltime flags as the allocation modifier writes them for
        # flux (-N, -t 30m), slurm (--time 120), lsf (-nnodes, -W hh:mm),
        # pjm (node=, elapse=hh:mm:ss) and pbs (select=, walltime=hh:mm:ss)
        nodes = re.search(r"(?:-N|--nodes|-nnodes|node=|select=)[ =]?(\d+)", joined)
        walltime = re.search(r"(?:-t|--time|-W|elapse=|walltime=)[ =]?([\d:]+)", joined)
        if nodes and walltime:
            parts = [int(x) for x in walltime.group(1).split(":")]
            minutes = parts[0] if len(parts) == 1 else parts[0] * 60 + parts[1]
            node_minutes += int(nodes.group(1)) * minutes
        jobs.append(
            {
                "experiment": d.name,
                "directives": directives,
                "launch": _truncate(launch or "", 400),
            }
        )
    return {
        "workspace": str(ws),
        "count": len(jobs),
        "node_hours_upper_bound": round(node_minutes / 60, 2)
        if node_minutes
        else "unknown",
        "jobs": jobs[:100],
        "built": (_build_status(ws) or {}).get(
            "state", "unknown (not built through this server)"
        ),
    }


@mcp.tool(annotations=RUNS_ANYTHING, meta=ASK_USER)
def submit(workspace: str, where: str | None = None) -> dict[str, Any]:
    """Submit a built workspace's experiments to the batch scheduler (`ramble on`).
    This spends the user's allocation: call preview_submission first, show it to the
    user, and only call submit after they approve. where is a Ramble filter such as
    "{n_nodes} <= 2" to submit a subset. Job IDs are recorded for status()/cancel()."""
    ws = _workspace(workspace)
    if not _run_dirs(ws):
        raise ToolError("Nothing to submit. Run build(workspace) first.")
    filt = ["--where", where] if where else []
    res = _in_workspace(
        ws, ["ramble", "--workspace-dir", str(ws), "on", *filt], timeout=900
    )
    ids = []
    for line in res["stdout"].splitlines():
        line = line.strip()
        # flux batch prints an F58 id (ƒ... or f...); sbatch/bsub/qsub print their own forms
        if re.fullmatch(r"[fƒ][1-9A-HJ-NP-Za-km-z]{6,15}", line) and any(
            ch.isdigit() for ch in line
        ):
            ids.append(line)
        elif m := re.search(
            r"Submitted batch job (\d+)|Job <(\d+)> is submitted|^(\d+\.\S+)$", line
        ):
            ids.append(next(g for g in m.groups() if g))
    jobs = _state(ws, "jobs.json", [])
    jobs += [{"id": i, "submitted": time.time(), "where": where} for i in ids]
    _save_state(ws, "jobs.json", jobs)
    _check(res, "ramble on")
    return {
        "submitted": len(ids),
        "job_ids": ids,
        "output_tail": res["stdout"][-2000:],
        "next": "Poll status(workspace).",
    }


def _scheduler_jobs(ws, recorded):
    """Map execute_experiment path -> latest scheduler record."""
    by_name = {}
    if shutil.which("flux"):
        res = _run(["flux", "jobs", "-a", "--json", "-c", "2000"], timeout=60, raw=True)
        if res["exit_code"] == 0:
            try:
                for j in sorted(
                    json.loads(res["stdout"])["jobs"],
                    key=lambda j: j.get("t_submit", 0),
                ):
                    if j.get("name", "").startswith(str(ws)):
                        by_name[j["name"]] = {
                            "id": j.get("jobid") or j.get("id"),
                            "state": j.get("state"),
                            "result": j.get("result"),
                            "returncode": j.get("returncode"),
                            "runtime_min": round(j.get("runtime", 0) / 60, 1),
                            "nodes": j.get("nnodes"),
                            "queue": j.get("queue"),
                        }
            except (ValueError, KeyError):
                pass
    elif shutil.which("squeue") and recorded:
        ids = ",".join(j["id"] for j in recorded)
        res = _run(
            [
                "sacct",
                "-n",
                "-P",
                "-X",
                "-j",
                ids,
                "-o",
                "JobID,JobName%300,State,ExitCode,Elapsed,NNodes",
            ],
            timeout=60,
            raw=True,
        )
        for line in res["stdout"].splitlines():
            f = line.split("|")
            if len(f) >= 6:
                by_name[f[1]] = {
                    "id": f[0],
                    "state": f[2],
                    "exit": f[3],
                    "elapsed": f[4],
                    "nodes": f[5],
                }
    return by_name


@mcp.tool(annotations=READ_ONLY)
def status(workspace: str) -> dict[str, Any]:
    """Everything about a workspace's progress in one call: background build state
    (with log tail), and for each experiment the scheduler job (id, state, result,
    runtime), Ramble status, exit codes, the output file's last line, and how many
    Caliper .cali files exist. Ramble status reads SETUP until results() runs analyze;
    trust the scheduler and exit codes while jobs are live."""
    ws = _workspace(workspace)
    recorded = _state(ws, "jobs.json", [])
    sched = _scheduler_jobs(ws, recorded)
    exps = []
    for d in _run_dirs(ws):
        entry = {"experiment": d.name, "dir": str(d.relative_to(ws))}
        job = sched.get(str(d / "execute_experiment"))
        if job:
            entry["job"] = job
        st = d / "ramble_status.json"
        if st.exists():
            entry["ramble_status"] = json.loads(st.read_text()).get("experiment_status")
        codes = _tail(d / "exit_codes.out", 4)
        if codes:
            entry["exit_codes"] = codes
        out = d / f"{d.name}.out"
        if out.exists():
            entry["output_last_line"] = (_tail(out, 1) or [""])[0][-300:]
        cali = len(list(d.glob("*.cali")))
        if cali:
            entry["cali_files"] = cali
        exps.append(entry)
    result = {
        "workspace": str(ws),
        "build": _build_status(ws),
        "experiments": exps[:200],
    }
    if len(exps) > 200:
        result["omitted_experiments"] = len(exps) - 200
    if recorded:
        result["recorded_job_ids"] = [j["id"] for j in recorded][-50:]
    matched = {str(d / "execute_experiment") for d in _run_dirs(ws)}
    unmatched = [job for name, job in sched.items() if name not in matched]
    if unmatched:  # e.g. Slurm, whose job names are not the script paths
        result["jobs"] = unmatched[-50:]
    if not exps:
        building = (result["build"] or {}).get("state") == "running"
        result["hint"] = (
            "Build in progress; scripts appear when it finishes."
            if building
            else "No experiments rendered yet: run build(workspace)."
        )
    return result


@mcp.tool(annotations=RUNS_ANYTHING, meta=ASK_USER)
def cancel(
    job_ids: list[str] | None = None, workspace: str | None = None
) -> dict[str, Any]:
    """Cancel scheduler jobs, given explicit job_ids or all jobs recorded for a
    workspace by submit(). Ask the user first."""
    ids = list(job_ids or [])
    if workspace:
        ids += [j["id"] for j in _state(_workspace(workspace), "jobs.json", [])]
    if not ids:
        raise ToolError("No job ids given and none recorded for this workspace.")
    if shutil.which("flux"):
        return _run(["flux", "cancel", *ids], timeout=120)
    if shutil.which("scancel"):
        return _run(["scancel", *ids], timeout=120)
    raise ToolError("Neither flux nor scancel is available.")


# ---------------------------------------------------------------- data


@mcp.tool(annotations=READ_ONLY)
def results(workspace: str, analyze: bool = True, max_foms: int = 30) -> dict[str, Any]:
    """Experiment outcomes: runs `ramble workspace analyze -f json` (unless analyze=False)
    and returns, per experiment, status, nodes/ranks, success criteria (each check
    PASSED/FAILED) and figures of merit. Experiments with no output yet are NOT_RUN.
    An app criterion PASSED with `exit-code` FAILED usually means the run finished
    but a process exited non-zero."""
    ws = _workspace(workspace)
    if analyze:
        _check(
            _in_workspace(
                ws,
                [
                    "ramble",
                    "--workspace-dir",
                    str(ws),
                    "workspace",
                    "analyze",
                    "-f",
                    "json",
                    "text",
                ],
                timeout=1800,
            ),
            "ramble workspace analyze",
        )
    f = ws / "results" / "results.latest.json"
    if not f.exists():
        raise ToolError(
            "No results yet. Experiments must have run; then call results(workspace)."
        )
    data = json.loads(f.read_text())
    exps = []
    for e in data.get("experiments", []):
        run_dir = (
            ws
            / "experiments"
            / str(e.get("application_namespace"))  # dir name, e.g. raja_perf
            / str(e.get("workload_name"))
            / str(e.get("experiment_name"))
        )
        out_file = run_dir / f"{e.get('experiment_name')}.out"
        if not out_file.exists() or out_file.stat().st_size == 0:
            # Ramble reports never-submitted experiments as FAILED
            exps.append({"experiment": e.get("name"), "status": "NOT_RUN"})
            continue
        foms = []
        for ctx in e.get("CONTEXTS", []):
            prefix = "" if ctx.get("name") == "null" else f"[{ctx.get('name')}] "
            for fom in ctx.get("foms", []):
                foms.append(
                    f"{prefix}{fom['name']} = {fom['value']} {fom.get('units', '')}".strip()
                )
        exps.append(
            {
                "experiment": e.get("name"),
                "status": e.get("EXPERIMENT_STATUS"),
                "n_nodes": e.get("n_nodes"),
                "n_ranks": e.get("n_ranks"),
                "success_criteria": e.get("SUCCESS_CRITERIA"),
                "foms": foms[:max_foms]
                + (
                    [f"... {len(foms) - max_foms} more"] if len(foms) > max_foms else []
                ),
            }
        )
    return {"results_file": str(f), "experiments": exps}


@mcp.tool(annotations=READ_ONLY)
def profile_summary(
    path: str,
    metric: str = "Avg time/rank",
    top_n: int = 20,
    region_filter: str | None = None,
) -> dict[str, Any]:
    """Summarize Caliper profiles with Thicket. path is an experiment run directory,
    a workspace, or any directory/file of .cali files. Returns profile count,
    metadata columns that vary across profiles, and the top_n regions by metric
    (mean/min/max across profiles). region_filter is a regex on region names.
    Requires thicket in BENCHPARK_PYTHON's environment. For scaling charts use
    benchpark(["analyze", "--workspace-dir", ws, ...])."""
    p = _resolve(path)
    args = [
        BENCHPARK_PYTHON,
        "-I",
        str(HERE / "thicket_summary.py"),
        str(p),
        metric,
        str(top_n),
        region_filter or "",
    ]
    res = _check(_run(args, timeout=900), "Thicket summary")
    return json.loads(res["stdout"])


# ---------------------------------------------------------------- resources and prompts


@mcp.resource(
    "benchpark://guide", name="Benchpark agent guide", mime_type="text/markdown"
)
def guide_resource() -> str:
    return (HERE / "GUIDE.md").read_text()


@mcp.resource(
    "benchpark://docs/{page}",
    name="Benchpark documentation page",
    mime_type="text/x-rst",
)
def docs_resource(page: str) -> str:
    return guide(page)


@mcp.prompt()
def run_benchmark(
    benchmark: str, system: str = "this machine", goal: str = "a quick test run"
) -> str:
    """Define, build, run and report a benchmark."""
    return (
        f"Run the Benchpark benchmark '{benchmark}' on {system}; the goal is {goal}. "
        "Use cluster_info and describe to choose the system spec (ask me for bank/queue "
        "if unclear) and experiment variants, check them with validate_specs, then "
        "create_experiment, build, show me preview_submission and wait for my approval "
        "before submit. Watch status, then summarize results and profile_summary."
    )


@mcp.prompt()
def scaling_study(
    benchmark: str, system: str, mode: str = "strong", max_nodes: int = 8
) -> str:
    """Plan and run a scaling study with a chart."""
    return (
        f"Plan a {mode}-scaling study of '{benchmark}' on {system} up to {max_nodes} nodes. "
        "Use describe to find its scaling variants (scaling-factor, scaling-iterations, "
        "n_repeats), validate_specs to show me the experiment list and node counts, and "
        "preview_submission for the cost before submitting. After the runs, use "
        "benchpark analyze for the chart and explain where scaling efficiency drops."
    )


@mcp.prompt()
def add_system(name: str, description: str = "") -> str:
    """Author a new Benchpark system definition."""
    return (
        f"Add a Benchpark system named '{name}'. {description} Read guide() section 7 and "
        "guide('add-a-system-config'), pick the closest existing system with catalog('systems') "
        "and describe, gather hardware, scheduler, queues, compilers and MPI from this machine "
        "(cluster_info, `benchpark system external <spec> --new-system`), write "
        f"systems/{name}/system.py, and validate with validate_specs('{name} ...', 'saxpy +openmp'). "
        "Show me the file before finishing."
    )


@mcp.prompt()
def add_benchmark(name: str, source: str = "", programming_models: str = "mpi") -> str:
    """Author a new benchmark (Spack package, Ramble application, experiment)."""
    return (
        f"Add the benchmark '{name}' to Benchpark (source: {source or 'ask me'}; programming "
        f"models: {programming_models}). Follow guide() section 8: check for an existing Spack "
        "package, write the Ramble application and the experiment by adapting the closest "
        "existing benchmark, then validate with validate_specs, benchpark(['audit']), "
        "build(dry_run=True), and one small test run once I approve it."
    )


def main():
    mcp.run()


if __name__ == "__main__":
    main()
