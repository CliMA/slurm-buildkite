FROM docker.io/nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install system deps + Buildkite agent dependencies
RUN apt-get update && apt-get install -y \
    wget curl git openssh-server \
    apt-transport-https gnupg \
    tmux vim htop less rsync \
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
ENV PATH="/root/.juliaup/bin:${PATH}"
RUN curl -fsSL https://install.julialang.org | sh -s -- -y \
    && juliaup add 1.10.10 \
    && juliaup add 1.11.7 \
    && juliaup add 1.12.6 \
    && juliaup default 1.12.6

WORKDIR /clima

# Install VS Code CLI for tunnel support
RUN curl -Lk 'https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64' \
    --output /tmp/vscode_cli.tar.gz && \
    tar -xf /tmp/vscode_cli.tar.gz -C /usr/local/bin && \
    rm /tmp/vscode_cli.tar.gz

# SSH setup
RUN mkdir /var/run/sshd && \
    echo "PermitRootLogin yes" >> /etc/ssh/sshd_config && \
    echo "PasswordAuthentication no" >> /etc/ssh/sshd_config

EXPOSE 22

COPY start.sh /start.sh
COPY install-clima-artifacts.sh /usr/local/bin/install-clima-artifacts.sh
COPY clima-artifacts-profile.sh /etc/profile.d/clima-artifacts.sh
# Pick up the profile in non-login interactive shells too (docker exec, vscode).
# Also make bash history append-safe across concurrent shells and persist via
# /root/.bash_history (which start.sh symlinks to /workspace when available).
RUN { \
        echo '[ -f /etc/profile.d/clima-artifacts.sh ] && . /etc/profile.d/clima-artifacts.sh'; \
        echo 'shopt -s histappend'; \
        echo 'HISTSIZE=10000'; \
        echo 'HISTFILESIZE=20000'; \
        echo 'PROMPT_COMMAND="history -a${PROMPT_COMMAND:+; $PROMPT_COMMAND}"'; \
    } >> /etc/bash.bashrc

COPY clima-artifacts.tsv /etc/clima-artifacts.tsv

RUN chmod +x /start.sh /usr/local/bin/install-clima-artifacts.sh
CMD ["/start.sh"]
