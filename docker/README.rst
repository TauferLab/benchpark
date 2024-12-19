Requirements
============

* Python3.8+
* Docker

Local Usage
===========

This section assumes that you are not using the registry image (not yet created).

It also assumes that you have docker installed on your system.

Build Base Image
----------------

You can build the base OCI/Docker image for Benchpark with the following
commands. Note that this command must be run from the root directory of Benchpark.

First git clone the repository (and checkout the correct branch).
Activate a python 3.8+ environment.

.. code-block:: bash

    cd benchpark 
    . setup-env.sh

    benchpark containerize rockylinux:9 openmpi -o benchpark.dockerfile

    docker build -f benchpark.dockerfile -t benchpark_base .


Run Base Image
--------------

You can run the base OCI/Docker image for Benchpark with the following command:

.. code-block:: bash

    docker run --rm -it -v </host/results/path>:</container/results/path> --name benchpark_container benchpark_base


Initialize the Benchpark System
--------------

To initialize the system for the OCI/Docker container run:

.. code-block:: bash

    cd benchpark
    benchpark system init --dest=oci-system oci

Initialize/Setup a Single Node Experiment
--------------

.. code-block:: bash
    
    benchpark experiment init --dest=kripke-test kripke +single_node +openmp
    benchpark setup kripke-test/ oci-system/ </container/results/path>/workspace/

This comand will list a set of addional commands that may differ slightly on your image, examples listed below. 
Execute the prompted commands to run an experiment.

.. code-block:: bash

    . /home/jovyan/benchpark/workspace/setup.sh
    ramble --disable-progress-bar --workspace-dir /home/jovyan/benchpark/workspace/kripke_test/Oci-ec4b246/workspace workspace setup
    ramble --disable-progress-bar --workspace-dir /home/jovyan/benchpark/workspace/kripke_test/Oci-ec4b246/workspace on
