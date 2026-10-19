# Benchpark guide for agents

Benchpark makes HPC benchmark runs reproducible by splitting a run into three
independent specifications, then generating a Ramble workspace that Spack builds
and a batch scheduler runs. This guide gives you the model you need to use every
part of it through this MCP server. Read docs with `guide(topic=...)`; call
`guide(topic="list")` to see every topic.

## 1. Mental model

| Layer | Answers | Lives in |
|---|---|---|
| **System** | What machine? Hardware, scheduler, queues, compilers, MPI, external packages | `systems/<name>/system.py` |
| **Benchmark** | How to build it (Spack) and run it (Ramble) | `repos/spack_repo/benchpark/packages/<name_>/package.py` (only if Benchpark needs its own recipe; otherwise Spack's builtin repo), `repos/ramble_applications/<name_>/application.py` |
| **Experiment** | What study? Programming model, problem sizes, scaling, modifiers | `experiments/<name>/experiment.py` |

`<name_>` means the benchmark name with `-` replaced by `_` (`raja-perf` -> `raja_perf`).

Pipeline:

```
system spec ──► system dir (variables.yaml, software.yaml, packages.yaml, system.pkl)
experiment spec + system dir ──► ramble.yaml
benchpark setup ──► Ramble workspace (+ private spack/ramble clones in the experiments root)
ramble workspace setup ──► Spack builds software, renders execute_experiment scripts
ramble on ──► flux batch / sbatch each execute_experiment
ramble workspace analyze ──► results.latest.json (figures of merit, pass/fail)
Caliper .cali files ──► Thicket / benchpark analyze / benchpark query
```

## 2. Spec syntax

Specs look like Spack specs without `@`/`%`: `name +flag ~flag key=value key=a,b`.

- System: `llnl-elcapitan cluster=tuolumne compiler=cce bank=fractale queue=pdebug timeout=30`
- Experiment: `raja-perf +rocm +strong caliper=time,mpi n_repeats=3`
- Namespaced experiment: `hecbench.softmax +rocm`; the fast test fixture is `saxpy`
  (namespace `test`), which pairs well with system `generic-x86`.

Rules enforced at concretization:

- Exactly one programming model among `+openmp`, `+cuda`, `+rocm` (MPI-only is the
  default `+mpi` for experiments that declare `ProgrammingModelType.Mpionly`).
- At most one of `+strong`, `+weak`, `+throughput`.
- System `timeout` (minutes) must fit the chosen `queue` limit. The default is
  120. Many debug queues allow only 60, so set `timeout=` explicitly.
- Variant values must be in the declared list. `describe()` shows them.

## 3. Tool map

| Goal | Tools |
|---|---|
| Orient yourself | `cluster_info`, `catalog`, `describe`, `guide` |
| Check specs cheaply (no files kept, no compute) | `validate_specs` |
| Create system + experiment + workspace | `create_experiment` (or `benchpark` with `system init`, `experiment init`, `setup`) |
| Build (Spack) | `build` (background) then `status`; `build(dry_run=True)` renders scripts without compiling |
| Run | `preview_submission`, show the user, then `submit` |
| Watch | `status` |
| Collect data | `results` (Ramble FOMs + pass/fail), `profile_summary` (Thicket over .cali), `benchpark` with `analyze` / `query` |
| Fix problems | `status`, `read_file(grep=...)` on logs, `spack` (`logs`, `spec -I`, `find`) |
| Author systems / benchmarks / experiments | `read_file` an example, `write_file`, then `validate_specs`, `benchpark audit`, `benchpark unit-test` |
| Anything else | `benchpark`, `ramble`, `spack` run any subcommand |

## 4. Running an experiment (happy path)

1. `cluster_info()` tells you which system definition matches this machine, the
   scheduler, and the queues and banks. Ask the user for the bank and queue if
   they are unclear.
2. `describe("experiment", name)` lists workloads, versions, programming models,
   scaling modes and variants.
3. `validate_specs(system_spec, experiment_spec)` shows the concrete experiments
   (names, n_nodes / n_ranks / n_gpus, problem sizes) and catches spec errors in
   seconds. Iterate here.
4. `create_experiment(system_spec, experiment_spec, root=...)` creates
   `<root>/<system_name>/`, `<root>/<system_name>/<experiment_name>/ramble.yaml`,
   and the workspace `<root>/workspaces/<system_name>/<experiment_name>/workspace`.
5. `build(workspace)` starts the Spack build in the background. It can take minutes
   to an hour. Poll `status(workspace)`. Set `on_compute_node=True` to build inside
   a one-node allocation instead of on the login node.
6. `preview_submission(workspace)` shows each job's nodes, walltime, queue and bank.
   **Show it to the user and get approval**, then call `submit(workspace)`.
7. `status(workspace)` reports scheduler state per experiment, exit codes, outputs
   and `.cali` counts.
8. `results(workspace)` gives figures of merit and success criteria.
   `profile_summary(path)` gives the slowest regions from Caliper data.

To rerun with changed experiment parameters, delete `<workspace>/experiments`
(FAQ). After changing system config or a `package.py`, run the build again.

## 5. Reading results correctly

- Ramble status is only final after `ramble workspace analyze`, which `results()`
  runs for you. Before that it reads `SETUP` even while the job runs. Use `status()`.
- `SUCCESS_CRITERIA` lists each check. `modifier::exit-code::Final Exit Code Zero =
  FAILED` together with `application::<app>::pass = PASSED` means the app finished
  and printed its success line but a process exited non-zero, often during teardown.
  The data is usually usable. Say so instead of reporting a plain failure.
- Caliper writes `.cali` files into each experiment's run directory. The `caliper=`
  variant chooses the mode: `time`, `mpi`, `rocm`, `cuda`, `topdown-*`, ... (multi-valued).
- `benchpark analyze --workspace-dir <ws>` makes charts and CSVs into
  `<ws>/analyze/`. It requires a scaling run (`+strong`/`+weak`/`+throughput`).
  For anything else, use `profile_summary`.
- `benchpark query <dirs> --metric "<metric>" --query-regions-byname <region>`
  writes a CSV into the working directory.

## 6. Where files live

```
<system_dir>/                               # benchpark system init --dest (absolute)
  system_id.yaml variables.yaml software.yaml system.pkl auxiliary_software_files/
  <experiment>/ramble.yaml                  # benchpark experiment init
<experiments_root>/                         # benchpark setup <exp_dir> <experiments_root>
  setup.sh  spack/  ramble/  spack-packages/  builds/ (spack stage)  spack-cache/
  <system>/<experiment>/workspace/
    configs/             ramble.yaml, variables.yaml, execute_experiment.tpl (symlinks)
    software/spack/<env>/spack.yaml, spack.lock
    logs/                setup.latest.out, setup.<ts>/..., execute.<ts>/..., mcp-build.log
    experiments/<app>/<workload>/<experiment_name>/
        execute_experiment  <experiment_name>.out  exit_codes.out  ramble_status.json
        *.cali  *_metadata.json
    results/results.latest.json
    .benchpark-mcp/      build.json, jobs.json (written by this server)
```

Some docs pages (`experiments_root_structure`, `set-of-experiments`) show the
system and experiment levels swapped. The tree above matches the code.

Build-failure clues: `logs/setup.latest.out`, the per-experiment logs under
`logs/setup.<ts>/`, and Spack stage logs `<experiments_root>/builds/spack-stage-*/spack-build-out.txt`
or `<experiments_root>/builds/spack-stage-*.log`. `spack(workspace, ["logs", "<pkg>"])` also works.

## 7. Authoring a new system

Read `guide("add-a-system-config")` and copy the closest existing system
(`catalog("systems")`). Good templates:

- CPU cluster with Slurm: `systems/llnl-cluster/system.py`
- AMD GPU with Flux: `systems/llnl-elcapitan/system.py`
- NVIDIA GPU: `systems/lbnl-perlmutter/system.py`
- Minimal: `systems/generic-x86/system.py`

A system class:

```python
from benchpark.directives import maintainers, variant
from benchpark.openmpsystem import OpenMPCPUOnlySystem
from benchpark.paths import hardware_descriptions
from benchpark.system import JobQueue, System, compiler_def, compiler_section_for

class MySite(System):            # directory name: systems/my-site/
    maintainers("github-handle")
    id_to_resources = {           # one entry per cluster / instance type
        "clusterA": {
            "cpu_arch": "zen4", "sys_cores_per_node": 96, "scheduler": "slurm",
            "sys_mem_per_node_GB": 512, "system_site": "mysite",
            "queues": [JobQueue("debug", 60, 4), JobQueue("batch", 1440, 128)],
            "hardware_key": str(hardware_descriptions) + "/<Integrator-proc-net>/hardware_description.yaml",
        },
    }
    variant("cluster", default="clusterA", values=("clusterA",), description="Which cluster")
    variant("compiler", default="gcc", values=("gcc",), description="Which compiler")
    variant("queue", default="none", values=("none", "debug", "batch"), description="Queue")
    variant("bank", default="none", values=("none", "myproj"), description="Account")

    def __init__(self, spec):
        super().__init__(spec)
        self.programming_models = [OpenMPCPUOnlySystem()]   # + CudaSystem() / ROCmSystem()
        for k, v in self.id_to_resources[self.spec.variants["cluster"][0]].items():
            setattr(self, k, v)

    def compute_compilers_section(self):
        return compiler_section_for("gcc", [compiler_def(
            "gcc@13.3.1 languages=c,c++,fortran", "/usr/", {"c": "gcc", "cxx": "g++", "fortran": "gfortran"})])

    def compute_packages_section(self):
        return {"packages": {"mpi": {"buildable": False},
                             "openmpi": {"externals": [{"spec": "openmpi@4.1.6", "prefix": "/opt/openmpi"}]},
                             "cmake": {"externals": [{"spec": "cmake@3.26.5", "prefix": "/usr"}], "buildable": False}}}

    def compute_software_section(self):
        return {"software": {"packages": {"default-compiler": {"pkg_spec": "gcc@13.3.1"},
                                          "default-mpi": {"pkg_spec": "openmpi@4.1.6"}}}}
```

- Required attributes: `sys_cores_per_node`, `scheduler` (`slurm`, `flux`, `lsf`,
  `pbs`, `pjm`, `mpi`), and `timeout` (from the base variant).
- GPU systems add `sys_gpus_per_node`, plus `rocm_arch`/`rocm_version`/`gtl_flag`
  for ROCm or `cuda_arch`/`cuda_version` for CUDA. They also add `rocm`/`cuda` variants.
- Find externals on a machine with
  `benchpark(["system", "external", "<spec>", "--new-system"])`. To compare an
  existing system with the machine, use `--propose`; to rewrite `system.py`, use
  `--apply` (ask the user first).
- Validate with `validate_specs("<new system spec>", "saxpy +openmp")`, then
  `benchpark(["unit-test", "-k", "system"])`.

## 8. Authoring a new benchmark

Three pieces. Copy from the closest existing benchmark (`catalog("experiments")`)
and read `guide("add-an-experiment")`, `guide("add-a-ramble-application")` and
`guide("add-a-spack-package")`.

**Spack package.** First check whether the builtin Spack repo already has it:
`read_file("~/.benchpark/spack-packages/repos/spack_repo/builtin/packages/<name_>/package.py")`
or `spack(workspace, ["info", "<name>"])`. Add
`repos/spack_repo/benchpark/packages/<name_>/package.py` only for a new or
modified recipe. Benchpark's repo takes precedence over builtin.

**Ramble application** (`repos/ramble_applications/<name_>/application.py`):

```python
from ramble.appkit import *

class MyApp(ExecutableApplication):
    """One-line description"""
    name = "my-app"
    tags("synthetic", "single-node")
    executable("run", "my_app -n {n} {extra_args}", use_mpi=True)
    workload("standard", executables=["run"])
    workload_variable("n", default="1024", description="problem size", workloads=["standard"])
    workload_variable("extra_args", default="", description="extra args", workloads=["standard"])
    figure_of_merit("Runtime", fom_regex=r"Time:\s+(?P<t>[0-9.]+)", group_name="t", units="s")
    success_criteria("pass", mode="string", match=r"Run complete",
                     file="{experiment_run_dir}/{experiment_name}.out")
```

FOM regexes run against `{experiment_run_dir}/{experiment_name}.out` by default.
To test them, run a quick job and then `results()`, or `read_file` the `.out` and
check the regex yourself.

**Experiment** (`experiments/<name>/experiment.py`):

```python
from benchpark.caliper import Caliper
from benchpark.directives import maintainers, variant
from benchpark.experiment import Experiment
from benchpark.programming_model import ProgrammingModel, ProgrammingModelType
from benchpark.scaling import Scaling, ScalingMode

class MyApp(Experiment,
            ProgrammingModel(ProgrammingModelType.Mpionly, ProgrammingModelType.Rocm),
            Scaling(ScalingMode.Strong, ScalingMode.Weak), Caliper):
    variant("workload", default="standard", description="workload")
    variant("version", default="1.0", values=("1.0", "latest"), description="app version")
    maintainers("github-handle")

    def compute_applications_section(self):
        self.add_experiment_variable("n", 1048576, True)        # named -> in experiment name
        self.add_experiment_variable("n_resources", 4, False)
        self.set_required_variables(process_problem_size="{n}",
                                    total_problem_size="{n}*{n_resources}")
        self.register_scaling_config({
            ScalingMode.Strong: {"n_resources": lambda var, itr, dim, f: var.val(dim) * f,
                                 "n": lambda var, itr, dim, f: var.val(dim) // f},
            ScalingMode.Weak:   {"n_resources": lambda var, itr, dim, f: var.val(dim) * f,
                                 "n": lambda var, itr, dim, f: var.val(dim)}})
        if self.spec.satisfies("+rocm"):
            self.add_experiment_variable("n_gpus", "{n_resources}", True)
        else:
            self.add_experiment_variable("n_ranks", "{n_resources}", True)

    def compute_package_section(self):
        self.add_package_spec(self.name, [f"my-app{self.determine_version()} +mpi"])
```

- Required variables: `n_resources`, `process_problem_size`, `total_problem_size`.
- Resource variables read by the allocation modifier: `n_nodes`, `n_ranks`,
  `n_gpus`, `n_threads_per_proc`, `n_ranks_per_node`, `n_cores_per_rank`.
- `add_experiment_variable(name, values, named=False, matrixed=False)`: a list makes a
  vector. Vectors are zipped unless `matrixed=True`, which takes the cross product.
  A dict makes a named zip.
- `self.spec.satisfies("+rocm")` / `("exec_mode=perf")` branches on variants.
- Validate with `validate_specs(system, "my-app +rocm")`, `benchpark(["audit"])`,
  then a real `build(dry_run=True)` and a small run.

## 9. Modifiers and helpers

Every experiment gets the `allocation` and `exit-code` modifiers. Optional ones are
turned on through experiment variants:

- `caliper=time,mpi,rocm,...`: Caliper profiling, writes `.cali`
- `affinity=on`: binding report
- `hwloc=on`: topology
- `githash=on` (default): source git metadata

See `guide("modifiers")`.

## 10. Gotchas

- Always use absolute paths for `--dest` and `setup` targets. Relative paths are
  stored verbatim and break if you change directory. `create_experiment` handles this.
- `system init` and `experiment init` refuse existing directories. Pick a new name
  or delete the old directory.
- `benchpark setup` deletes and recreates an existing workspace at the same location.
- The first `setup` in a new experiments root clones Spack, Ramble and spack-packages
  into it. This takes a few minutes; later setups in the same root are fast.
- Every `benchpark` command checks that `~/.benchpark` matches the pinned commits
  in `checkout-versions.yaml`, and may update it.
- `benchpark system id` and `system init --basedir` are currently broken. Use `--dest`.
- Don't submit jobs with `flux batch`, `sbatch` or `ramble on` directly. Use
  `submit`, so the user approves the allocation.
