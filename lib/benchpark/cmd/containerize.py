# Copyright 2023 Lawrence Livermore National Security, LLC and other
# Benchpark Project Developers. See the top-level COPYRIGHT file for details.
#
# Copyright 2013-2023 Spack Project Developers.
#
# SPDX-License-Identifier: Apache-2.0

import argparse
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
    if args.extra_labels is not None:
        template_dict["extra_labels"] = [
            "{}: {}".format(k, v) for k, v in args.extra_labels.items()
        ]
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
    return recipe


class ExtraLabelAction(argparse.Action):
    def _parse_single(self, val):
        return val.split("=", 2)

    def __call__(self, parser, args, values, option_string=None):
        d = getattr(args, self.dest) or {}
        if isinstance(values, str):
            k, v = self._parse_single(values)
            d[k] = v
        else:
            for val in values:
                k, v = self._parse_single(val)
                d[k] = v
        setattr(args, self.dest, d)


class ListOsAction(argparse.Action):
    def __init__(self, option_strings, dest, **kwargs):
        local_kwargs = kwargs.copy()
        for reserved in ["nargs", "default"]:
            if reserved in kwargs:
                del local_kwargs[reserved]
        return super().__init__(
            option_strings, dest, nargs=0, default=argparse.SUPPRESS, **local_kwargs
        )

    def __call__(self, parser, args, values, option_string=None):
        print("The following operating systems can be used in Benchpark containers:")
        print(" ".join(valid_container_oses_and_pkgs.keys()))
        parser.exit()


class ListMpiAction(argparse.Action):
    def __init__(self, option_strings, dest, **kwargs):
        local_kwargs = kwargs.copy()
        for reserved in ["nargs", "default"]:
            if reserved in kwargs:
                del local_kwargs[reserved]
        return super().__init__(
            option_strings, dest, nargs=0, default=argparse.SUPPRESS, **local_kwargs
        )

    def __call__(self, parser, args, values, option_string=None):
        print("The following types of MPI can be used in Benchpark containers:")
        print(" ".join(valid_mpi_types_and_specs.keys()))
        parser.exit()


class ListMpiSpecsAction(argparse.Action):
    def __init__(self, option_strings, dest, **kwargs):
        local_kwargs = kwargs.copy()
        for reserved in ["nargs", "default", "type"]:
            if reserved in kwargs:
                del local_kwargs[reserved]
        return super().__init__(
            option_strings, dest, nargs=1, default="", type=str, **local_kwargs
        )

    def __call__(self, parser, args, values, option_string=None):
        if values[0] not in valid_mpi_types_and_specs.keys():
            raise ValueError("Unrecognized MPI type: {}".format(values[0]))
        print(
            "The following specs will be installed for {} in the Benchpark container:".format(
                values[0]
            )
        )
        print(
            "\n".join(["  {}".format(s) for s in valid_mpi_types_and_specs[values[0]]])
        )
        parser.exit()


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
    root_parser.add_argument(
        "--extra_labels",
        "-l",
        metavar="KEY=VALUE",
        type=str,
        nargs="+",
        action=ExtraLabelAction,
        help="Add extra labels to the container definition",
    )
    root_parser.add_argument(
        "--list_os",
        action=ListOsAction,
        help="If provided, list the available operating systems",
    )
    root_parser.add_argument(
        "--list_mpi",
        action=ListMpiAction,
        help="If provided, list the available types of MPI",
    )
    root_parser.add_argument(
        "--list_mpi_specs",
        action=ListMpiSpecsAction,
        help="If provided, list the available Spack specs that will be installed for the specified MPI",
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
