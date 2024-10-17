.. note::

    If running on an M series Mac, you should add :code:`--platform linux/arm64`
    to all the Docker commands below. If you don't you may experience odd errors and/or
    performance degradation.

Local Usage
===========

This section assumes that you are not using the registry image (not yet created).

Build Base Image
----------------

You can build the base OCI/Docker image for Benchpark with the following
command. Note that this command must be run from the root directory of Benchpark.

.. code-block:: bash

    docker build -t benchpark_base -f ./docker/Dockerfile.base .

Run Base Image
--------------

You can run the base OCI/Docker image for Benchpark with the following command:

.. code-block:: bash

    docker run --rm -it --name benchpark_base benchpark_base
