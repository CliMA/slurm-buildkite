FROM docker.io/nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install system deps + Buildkite agent dependencies
RUN apt-get update && apt-get install -y \
    wget curl git openssh-server \
    apt-transport-https gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Buildkite agent
RUN curl -fsSL https://keys.openpgp.org/vks/v1/by-fingerprint/32A37959C2FA5C3C99EFBC32A79206696452D198 \
    | gpg --dearmor -o /usr/share/keyrings/buildkite-agent-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/buildkite-agent-archive-keyring.gpg] \
    https://apt.buildkite.com/buildkite-agent stable main" \
    > /etc/apt/sources.list.d/buildkite-agent.list && \
    apt-get update && apt-get install -y buildkite-agent && \
    rm -rf /var/lib/apt/lists/*

# Install Julia
ARG JULIA_VERSION=1.11.8
ENV PATH="/root/.juliaup/bin:${PATH}"
RUN curl -fsSL https://install.julialang.org | sh -s -- -y && juliaup add ${JULIA_VERSION} && juliaup default ${JULIA_VERSION}
# TODO: set Julia artifacts (Base.set_depot_path())

WORKDIR /app

# SSH setup
RUN mkdir /var/run/sshd && \
    echo "PermitRootLogin yes" >> /etc/ssh/sshd_config && \
    echo "PasswordAuthentication no" >> /etc/ssh/sshd_config

EXPOSE 22

COPY start.sh /start.sh
RUN chmod +x /start.sh
CMD ["/start.sh"]
