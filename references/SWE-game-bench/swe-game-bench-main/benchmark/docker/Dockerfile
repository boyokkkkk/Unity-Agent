ARG UNITY_IMAGE_TAG=ubuntu-2019.4.36f1-base-3.2.1
FROM unityci/editor:${UNITY_IMAGE_TAG}

# Re-declare so the value is available after FROM and at runtime.
ARG UNITY_IMAGE_TAG
ENV UNITY_IMAGE_TAG=${UNITY_IMAGE_TAG}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        software-properties-common gnupg gpg-agent git git-lfs xvfb \
        libgconf-2-4 libglu1-mesa libnss3 libatk1.0-0 libxss1 \
    && add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get update \
    && apt-get install -y --no-install-recommends python3.11 python3.11-venv \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --branch v1.1.0 --depth 1 https://github.com/SWE-agent/SWE-agent.git /opt/SWE-agent \
    && python3.11 -m venv /opt/swe-agent-venv \
    && /opt/swe-agent-venv/bin/python -m pip install --upgrade pip \
    && /opt/swe-agent-venv/bin/pip install --no-cache-dir \
        --editable /opt/SWE-agent \
        pandas requests python-dotenv PyYAML

# Bump SWE-agent's setup-phase shell timeout from 120s to 1800s so large
# repos don't time out during git checkout.
RUN sed -i 's|timeout=120,|timeout=1800,|' /opt/SWE-agent/sweagent/environment/swe_env.py

# Bound tool output observations so one oversized dump (e.g. viewing a whole
# directory) can't exceed the model's small input budget. Offload the full text
# to a file in the agent's container and show the model a bounded preview plus a
# grep/sed retrieval hint, instead of head-clipping and losing the rest.
COPY patches/_obs_offload.py /opt/SWE-agent/sweagent/_obs_offload.py
COPY patches/apply_offload_patch.py /tmp/apply_offload_patch.py
RUN /opt/swe-agent-venv/bin/python /tmp/apply_offload_patch.py \
        /opt/SWE-agent/sweagent/agent/agents.py

# Bake a mirror of the benchmark repo into the image so ephemeral (--fresh)
# containers can clone locally in seconds instead of hitting the network.
ARG REPO_URL=""
RUN if [ -n "$REPO_URL" ]; then \
        GIT_LFS_SKIP_SMUDGE=1 git clone --mirror "$REPO_URL" /opt/repo-cache.git; \
    fi

ENV HOME=/tmp
ENV SWE_AGENT_SRC_ROOT=/opt/SWE-agent
ENV SWEAGENT_CMD="/opt/swe-agent-venv/bin/python -m sweagent"
ENV PATH="/opt/swe-agent-venv/bin:${PATH}"
WORKDIR /pipeline

ENTRYPOINT ["tail","-f","/dev/null"]
