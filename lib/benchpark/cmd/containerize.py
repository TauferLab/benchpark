# Copyright 2023 Lawrence Livermore National Security, LLC and other
# Benchpark Project Developers. See the top-level COPYRIGHT file for details.
#
# Copyright 2013-2023 Spack Project Developers.
#
# SPDX-License-Identifier: Apache-2.0

import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from jinja2 import Template

import benchpark.paths
from benchpark.runtime import RuntimeResources

bootstrapper = RuntimeResources(benchpark.paths.benchpark_home)  # noqa
bootstrapper.bootstrap()  # noqa


template_path = benchpark.paths.benchpark_root / "share" / "templates"


default_spack_version = "0.22.2"
valid_container_oses_and_pkgs = {
    "rockylinux:9": [
        "git",
        "python3-devel",
        "python3-pip",
        "vim",
        "shadow-utils",
    ],
}
valid_mpi_types_and_specs = {
    "openmpi": ["openmpi@4.1.5 fabrics=ofi", "libfabric fabrics=sockets,tcp,udp,verbs"],
}


def populate_templating_dict(args):
    template_dict = {
        "mpi": {
            "name": args.mpi_type,
            "specs": valid_mpi_types_and_specs[args.mpi_type],
        },
        "container": {
            "template_dir": str(template_path),
            "template": "container/{}.dockerfile".format(
                "_".join(args.container_os.split(":"))
            ),
            "os": args.container_os,
            "spack_version": args.spack_version,
            "strip": "false" if args.disable_strip else "true",
            "os_packages": valid_container_oses_and_pkgs[args.container_os],
        },
    }
    return template_dict


def generate_spack_env(template_dict, tmp_path):
    template = None
    with open(str(template_path / "spack_env_template.yaml"), "r") as f:
        template = Template(f.read())
        template = template.render(template_dict)
    if template is None:
        raise RuntimeError("Failed to populate template for Spack environment")
    with open(str(tmp_path / "spack.yaml"), "w") as f:
        f.write(template)


def generate_container_definition(tmp_path):
    recipe = subprocess.check_output(
        f"source {bootstrapper.spack_location}/share/spack/setup-env.sh && spack env activate . && spack containerize",
        cwd=str(tmp_path),
        shell=True,
        text=True,
        encoding="utf-8",
    )
    # cwd = Path.cwd()
    # os.chdir(str(tmp_path))
    # try:
    #     # config = spack_container_module.validate(str(tmp_path / "spack.yaml"))
    #     # recipe = spack_container_module.recipe(config)
    #     config = spack.container.validate(str(tmp_path / "spack.yaml"))
    #     recipe = spack.container.recipe(config)
    # finally:
    #     os.chdir(str(cwd))
    return recipe


def setup_parser(root_parser):
    root_parser.add_argument(
        "container_os",
        type=str,
        choices=list(valid_container_oses_and_pkgs.keys()),
        help="The base OS for the container",
    )
    root_parser.add_argument(
        "mpi_type",
        type=str,
        choices=list(valid_mpi_types_and_specs.keys()),
        help="The type of MPI for the container",
    )
    root_parser.add_argument(
        "--spack_version",
        type=str,
        default=default_spack_version,
        help="Version of Spack to use to install global packages in the container",
    )
    root_parser.add_argument(
        "--disable_strip",
        action="store_true",
        default=False,
        help="Disable stripping of Spack-installed packages in the container",
    )
    root_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Path to write the container definition. Will dump to stdout if not provided",
    )
    root_parser.add_argument(
        "--print_spack_yaml",
        "-p",
        action="store_true",
        default=False,
        help="If provided, print the generated spack.yaml file to stdout",
    )


def command(args):
    template_dict = populate_templating_dict(args)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir).resolve()
        if not tmp_path.is_dir():
            raise FileNotFoundError(
                "Python's 'tempfile' module didn't correctly create a temporary directory"
            )
        generate_spack_env(template_dict, tmp_path)
        dockerfile_contents = generate_container_definition(tmp_path)
        if args.print_spack_yaml:
            print(
                "Container definition was generated from the following spack.yaml:",
                end="\n\n",
            )
            with open(str(tmp_path / "spack.yaml"), "r") as f:
                print(f.read(), end="\n\n")
    if args.output is None:
        print("Benchpark generated the following container definition:", end="\n\n")
        print(dockerfile_contents)
    else:
        with open(str(args.output.expanduser().resolve()), "w") as f:
            f.write(dockerfile_contents)
