FROM ubuntu:22.04

ARG HTTP_PROXY
ARG HTTPS_PROXY
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    software-properties-common \
    wget \
    build-essential \
    libssl-dev \
    zlib1g-dev \
    libffi-dev \
    binutils \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y python3.13 python3.13-dev python3.13-venv \
    && rm -rf /var/lib/apt/lists/*

RUN wget https://bootstrap.pypa.io/get-pip.py && python3.13 get-pip.py && rm get-pip.py && apt-get remove -y --purge python3-blinker python3-flask

WORKDIR /build

COPY requirements.txt .
RUN python3.13 -m pip install --no-cache-dir -r requirements.txt

CMD ["/bin/bash"]
