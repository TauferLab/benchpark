# Copyright 2023 Lawrence Livermore National Security, LLC and other
# Benchpark Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: Apache-2.0

from benchpark.system import System
from benchpark.directives import variant


class Oci(System):


    def initialize(self):
        super().initialize()
        self.scheduler = "flux"
        # TODO: do we need to set attributes sys_cores_per_node and/or sys_mem_per_node?
        self.sys_cores_per_node = 10

    def generate_description(self, output_dir):
        super().generate_description(output_dir)

        sw_description = pathlib.Path(output_dir) / "software.yaml"

        with open(sw_description, "w") as f:
            f.write(self.sw_description())


    def compiler_configs(self):
        compilers = Oci.resource_location / "compilers"

        selections = []
        selections.append(compilers / "gcc" / "00-gcc-11-compilers.yaml")

        return selections


    def sw_description(self):
        """This is somewhat vestigial, and maybe deleted later. The experiments
        will fail if these variables are not defined though, so for now
        they are still generated (but with more-generic values).
        """
        return """\
software:
  packages:
    default-compiler:
      pkg_spec: gcc
    default-mpi:
      pkg_spec: openmpi
    compiler-gcc:
      pkg_spec: gcc
"""

