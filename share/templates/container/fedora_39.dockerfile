{% extends "container/Dockerfile" %}
{% block build_stage %}
RUN spack compiler find
{{ super() }}
{% endblock %}
{% block final_stage %}
{{ super() }}
ENV LOCAL_USER=jovyan \
    LOCAL_UID=1001 \
    LOCAL_USER_HOME=/home/jovyan

RUN useradd \
    -c "Default user" \
    -u ${LOCAL_UID} \
    -d ${LOCAL_USER_HOME} \
    -m \
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
{% endblock %}
