#!/usr/bin/env python3

from jinja2 import Template
from pathlib import Path
import shutil

BENCHPARK_ROOT = Path(__file__).expanduser().resolve().parent.parent
DOCKER_ROOT = BENCHPARK_ROOT / "docker"
SETUP_SCRIPT_TEMPLATE = DOCKER_ROOT / "templates" / "setup_benchmark.sh.in"
RUN_SCRIPT_TEMPLATE = DOCKER_ROOT / "templates" / "run_benchmark.sh.in"
DOCKERFILE_TEMPLATE = DOCKER_ROOT / "templates" / "Dockerfile.run.in"


def create_directories_for_benchmark(benchmark_name):
    benchmark_dir = DOCKER_ROOT / "repo" / benchmark_name
    if benchmark_dir.exists():
        if benchmark_dir.is_dir():
            shutil.rmtree(str(benchmark_dir))
        else:
            raise FileExistsError(
                "{} exists, but is not a directory".format(str(benchmark_dir))
            )
    benchmark_dir.mkdir(parents=True)
    return benchmark_dir


def create_setup_script_for_benchmark(benchmark_name, benchmark_dir):
    output_setup_script_path = benchmark_dir / str(SETUP_SCRIPT_TEMPLATE.stem)
    template = None
    template_data = {
        "benchmark_name": benchmark_name,
    }
    with open(str(SETUP_SCRIPT_TEMPLATE), "r") as f:
        template = Template(f.read())
        template = template.render(template_data)
    if template is None:
        raise RuntimeError("Failed to fill template for setup script")
    if not isinstance(template, str):
        raise RuntimeError("Got wrong type for rendered template")
    with open(str(output_setup_script_path), "w") as f:
        f.write(template)
    return output_setup_script_path


def create_run_script_for_benchmark(benchmark_name, benchmark_dir):
    output_run_script_path = benchmark_dir / str(RUN_SCRIPT_TEMPLATE.stem)
    template = None
    template_data = {
        "benchmark_name": benchmark_name,
    }
    with open(str(RUN_SCRIPT_TEMPLATE), "r") as f:
        template = Template(f.read())
        template = template.render(template_data)
    if template is None:
        raise RuntimeError("Failed to fill template for run script")
    if not isinstance(template, str):
        raise RuntimeError("Got wrong type for rendered template")
    with open(str(output_run_script_path), "w") as f:
        f.write(template)
    return output_run_script_path


def create_dockerfile_for_benchmark(
    benchmark_name, setup_script_path, run_script_path, benchmark_dir
):
    output_dockerfile_path = benchmark_dir / str(DOCKERFILE_TEMPLATE.stem)
    template = None
    template_data = {
        "setup_script_path_from_root": setup_script_path.relative_to(BENCHPARK_ROOT),
        "run_script_path_from_root": run_script_path.relative_to(BENCHPARK_ROOT),
        "setup_script_name": setup_script_path.name,
        "run_script_name": run_script_path.name,
    }
    with open(str(DOCKERFILE_TEMPLATE), "r") as f:
        template = Template(f.read())
        template = template.render(template_data)
    if template is None:
        raise RuntimeError("Failed to fill template for Dockerfile")
    if not isinstance(template, str):
        raise RuntimeError("Got wrong type for rendered template")
    with open(str(output_dockerfile_path), "w") as f:
        f.write(template)
    return output_dockerfile_path


def create_docker_material_for_benchmark(benchmark_name):
    benchmark_dir = create_directories_for_benchmark(benchmark_name)
    setup_script_path = create_setup_script_for_benchmark(benchmark_name, benchmark_dir)
    run_script_path = create_run_script_for_benchmark(benchmark_name, benchmark_dir)
    create_dockerfile_for_benchmark(
        benchmark_name, setup_script_path, run_script_path, benchmark_dir
    )


def get_benchmark_names():
    experiments_dir = BENCHPARK_ROOT / "experiments"
    exp_repo_dir = BENCHPARK_ROOT / "var" / "exp_repo" / "experiments"
    benchmarks = set()
    for bmarks in experiments_dir.iterdir():
        if bmarks.is_dir():
            benchmarks.add(bmarks.name)
    for bmarks in exp_repo_dir.iterdir():
        if bmarks.is_dir():
            benchmarks.add(bmarks.name)
    return list(benchmarks)


def main():
    benchmarks = get_benchmark_names()
    for bmark in benchmarks:
        create_docker_material_for_benchmark(bmark)


if __name__ == "__main__":
    main()
