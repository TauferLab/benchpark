# Build stage with Spack pre-installed and ready to be used
FROM spack/rockylinux9:0.22.2 AS builder

RUN spack compiler find
## RUN spack external find

# What we want to install and how we want to install it
# is specified in a manifest file (spack.yaml)
RUN mkdir -p /opt/spack-environment && \
set -o noclobber \
&&  (echo spack: \
&&   echo '  specs:' \
&&   echo '  - openmpi@4.1.5 fabrics=ofi' \
&&   echo '  - libfabric fabrics=sockets,tcp,udp,verbs' \
&&   echo '  concretizer:' \
&&   echo '    unify: true' \
&&   echo '  packages:' \
&&   echo '    all:' \
&&   echo '      compiler: [gcc]' \
&&   echo '  config:' \
&&   echo '    template_dirs:' \
&&   echo '    - /Users/ilumsden/llnl/projects/pave/benchpark/docker/base_images/rockylinux9-ompi/templates' \
&&   echo '    install_tree: /opt/software' \
&&   echo '  view: /opt/views/view') > /opt/spack-environment/spack.yaml

# Install the software, remove unnecessary deps
RUN cd /opt/spack-environment && spack env activate . && spack install --fail-fast && spack gc -y

# Strip all the binaries
RUN find -L /opt/views/view/* -type f -exec readlink -f '{}' \; | \
    xargs file -i | \
    grep 'charset=binary' | \
    grep 'x-executable\|x-archive\|x-sharedlib' | \
    awk -F: '{print $1}' | xargs strip

# Modifications to the environment that are necessary to run
RUN cd /opt/spack-environment && \
    spack env activate --sh -d . > activate.sh



# Bare OS image to run the installed executables
FROM docker.io/rockylinux:9

COPY --from=builder /opt/spack-environment /opt/spack-environment
COPY --from=builder /opt/software /opt/software

# paths.view is a symlink, so copy the parent to avoid dereferencing and duplicating it
COPY --from=builder /opt/views /opt/views

RUN { \
      echo '#!/bin/sh' \
      && echo '.' /opt/spack-environment/activate.sh \
      && echo 'exec "$@"'; \
    } > /entrypoint.sh \
&& chmod a+x /entrypoint.sh \
&& ln -s /opt/views/view /opt/view


RUN dnf update -y && dnf install -y epel-release && dnf update -y \
 && dnf install -y git python3-devel python3-pip vim shadow-utils \
 && rm -rf /var/cache/dnf && dnf clean all

ENV LOCAL_USER=jovyan \
    LOCAL_UID=1001 \
    LOCAL_USER_HOME=/home/jovyan

RUN adduser \
    --comment "Default user" \
    --uid ${LOCAL_UID} \
    --home-dir ${LOCAL_USER_HOME} \
    --badname \
    ${LOCAL_USER} && \
    passwd -l ${LOCAL_USER}

COPY --chown=${LOCAL_USER} ./ ${LOCAL_USER_HOME}/benchpark

RUN python3 -m pip install -r ${LOCAL_USER_HOME}/benchpark/requirements.txt

WORKDIR ${LOCAL_USER_HOME}

USER ${LOCAL_USER}

ENV SPACK_ENV_PATH="/opt/view"

RUN echo "export PATH=${LOCAL_USER_HOME}/benchpark/bin:${SPACK_ENV_PATH}/bin:$PATH" >> ${LOCAL_USER_HOME}/.bashrc

RUN source ${LOCAL_USER_HOME}/.bashrc && echo -n "Benchpark version: " && benchpark --version
LABEL "app"="benchpark"
LABEL "mpi"="openmpi"
ENTRYPOINT [ "/entrypoint.sh" ]
CMD [ "/bin/bash" ]

