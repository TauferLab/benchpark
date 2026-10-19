# Benchpark MCP server

An [MCP](https://modelcontextprotocol.io) server that lets an agent (Claude Code,
Claude Desktop, or any MCP client) use Benchpark end to end. It can:

- learn Benchpark (`guide` serves an agent-oriented guide and every docs page)
- explore systems, benchmarks, experiments and modifiers
- check specs, create systems, experiments and workspaces
- build with Spack in the background, submit to Flux or Slurm (after the user
  approves), and track jobs
- collect data: Ramble figures of merit and pass/fail, Caliper/Thicket summaries,
  and `benchpark analyze` / `query`
- author new systems, Ramble applications, Spack packages and experiments, then
  validate them

It is deliberately small. It is one file, `server.py`, which runs the commands users
already run (`benchpark`, `ramble`, `spack`, `flux`/`slurm`). It keeps its state in
files, so it can restart at any time.

## Files

| File | Purpose |
|---|---|
| `server.py` | The server (tools, resources, prompts) |
| `GUIDE.md` | What the agent reads first: concepts, workflow, authoring templates, gotchas |
| `thicket_summary.py` | Helper that `profile_summary` runs with Benchpark's Python |
| `smoke_test.py` | Calls the read-only tools in-process; no compute, no files kept |
| `requirements.txt` | The same dependencies, for installing with pip instead of uv |

## Registered automatically

The repository root has project configs for common MCP clients. All of them run the
same command from the checkout:

```
uv run --script mcp-servers/benchpark/server.py
```

| Client | File | What the user does after cloning |
|---|---|---|
| Claude Code | `.mcp.json` | Start `claude` in the repo root and approve the `benchpark` server |
| Codex | `.codex/config.toml` | Trust the project; Codex loads project config only for trusted projects |
| Cursor | `.cursor/mcp.json` | Enable the server under Settings → MCP |
| VS Code (Copilot) | `.vscode/mcp.json` | Start the server from the MCP view or `mcp.json` |
| Gemini CLI | `.gemini/settings.json` | Start `gemini` in the repo root |

The only prerequisite is [`uv`](https://docs.astral.sh/uv/) on `PATH`. `server.py`
declares its dependencies inline: `mcp`, Benchpark's runtime packages, and its
`[analyze]` extra (Thicket). On first launch, `uv` builds a cached environment in
about 10–20 seconds; after that, startup takes about 2 seconds. That environment
also runs Benchpark, Ramble and Thicket, so no personal venv is needed. To build it
ahead of time:

```bash
uv run --script mcp-servers/benchpark/server.py < /dev/null
```

Claude Code, Cursor and Gemini CLI start the server from the repo root, so start
them there.

## Configuration

Everything is optional. The variables are read from the environment the client is
started from; Codex's config forwards them explicitly. Put them in your shell
profile:

| Variable | Default | Meaning |
|---|---|---|
| `BENCHPARK_MCP_ROOTS` | the launch directory (the checkout) | `:`-separated directories where systems, experiments and workspaces may be created, e.g. `/usr/WS1/$USER/benchpark-runs` |
| `BENCHPARK_PYTHON` | the server's own Python | A different Python to run Benchpark, Ramble, Spack and Thicket |
| `BENCHPARK_ROOT` | the checkout containing this directory | Benchpark checkout to use |
| `BENCHPARK_MCP_MAX_CHARS` | `20000` | Maximum text returned per command output |

The tools read and write only inside `BENCHPARK_ROOT` and `BENCHPARK_MCP_ROOTS`.
`~/.benchpark` is readable too. Set `BENCHPARK_MCP_ROOTS` to a scratch or workspace
filesystem, because builds are large. `cluster_info` shows the agent the allowed
directories.

## Other ways to run it

Without uv, install the dependencies into any Python 3.11+ environment:

```bash
pip install -r mcp-servers/benchpark/requirements.txt
python mcp-servers/benchpark/server.py      # speaks MCP on stdio
```

To run it from a laptop against the cluster, use SSH as the transport:

```bash
claude mcp add benchpark -- ssh -T tuolumne \
  'cd /path/to/benchpark && BENCHPARK_MCP_ROOTS=/usr/WS1/$USER/benchpark-runs uv run --script mcp-servers/benchpark/server.py'
```

On LLNL systems, `/collab/usr/global/tools/sandbox/codex` runs Codex in a sandbox.
It mounts only the current directory and `~/.codex`, and allows network access only
to LivAI. Inside it, the server cannot reach `uv`'s cache, PyPI, Flux or workspaces
outside the repo. Use plain Codex, or add mounts with the wrapper's `-- --add` option.

## Approvals

These are the tools that spend or release allocation.

- **Claude Code:** `submit` and `cancel` ask for confirmation on every call.
- **Codex:** `.codex/config.toml` sets `approval_mode = "prompt"` for `submit` and
  `cancel`, and `writes` mode for the rest.
- **Other clients:** they see the tools' read-only and destructive annotations.

To make sure an agent can't submit jobs any other way, add deny rules for the shell.
For Claude Code, put these in `.claude/settings.json`:

```json
{ "permissions": { "deny": ["Bash(flux batch:*)", "Bash(sbatch:*)", "Bash(ramble * on*)"] } }
```

## Using it

Ask in plain language, for example:

- "Run RAJAPerf on the GPUs here with Caliper and tell me the slowest kernels."
- "Plan a strong-scaling study of AMG2023 on tuolumne up to 8 nodes and show me the cost."
- "Why did the build in /usr/WS1/me/runs/workspaces/... fail?"
- "Add a Benchpark system definition for this cluster."
- "Add the benchmark at https://github.com/org/app with MPI and ROCm support."

Prompts: `run_benchmark`, `scaling_study`, `add_system`, `add_benchmark`. Claude Code
shows them as `/benchpark:<name>`.

## Tools

| Tool | What it does |
|---|---|
| `guide` | Agent guide (`overview`), list of docs pages (`list`), or one docs page |
| `catalog` | `benchpark list` experiments / systems / benchmarks / modifiers |
| `describe` | Variants and maintainers of an experiment or system, plus its source files |
| `cluster_info` | Hostname → matching system definition, scheduler, queues, the user's banks |
| `list_files`, `read_file`, `write_file` | Scoped file access; `read_file(grep=...)` for logs |
| `validate_specs` | Dry `system init` + `experiment init` in a temp dir; returns the concrete experiments or the error |
| `create_experiment` | `system init` + `experiment init` + `setup` with absolute paths; returns the workspace |
| `build` | `ramble workspace setup` in the background (optionally on a compute node), or `dry_run` to render scripts |
| `status` | Build state, and per experiment: scheduler job, Ramble status, exit codes, last output line, `.cali` count |
| `preview_submission` | Batch directives and launch line per experiment, node-hour upper bound |
| `submit` | `ramble on` (optionally `--where`); records job IDs. Asks the user. |
| `cancel` | Cancels recorded or given jobs. Asks the user. |
| `results` | `ramble workspace analyze -f json`, condensed to status, success criteria and FOMs |
| `profile_summary` | Thicket summary of `.cali` files: top regions, varying metadata |
| `benchpark`, `ramble`, `spack` | Run any subcommand (`ramble` and `spack` with the workspace environment loaded) |

Resources: `benchpark://guide` and `benchpark://docs/{page}`.

## State it keeps

For each workspace:
- `<workspace>/.benchpark-mcp/build.json`: pid, command and log of the background build
- `<workspace>/.benchpark-mcp/jobs.json`: job IDs from `submit`
- `<workspace>/logs/mcp-build.log`: the build's output

Everything else is Benchpark's and Ramble's own files. `status` also recognizes Flux
jobs submitted by hand (it matches the job name to each experiment's
`execute_experiment` path).

## Test

```bash
uv run --no-project --with-requirements requirements.txt python smoke_test.py [path/to/workspace]
npx @modelcontextprotocol/inspector uv run --script server.py   # interactive inspection
```
