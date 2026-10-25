# Build the native kernel once for the deployment platform. No compiler at runtime.
FROM python:3.11-slim AS native-builder
RUN apt-get update && apt-get install -y --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY research/build_native.py ./research/build_native.py
COPY research/native/cfr.cpp ./research/native/cfr.cpp
RUN python research/build_native.py --output /opt/poker/native/libpoker_cfr.so

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    POKER_RESEARCH_NATIVE_LIB=/opt/poker/native/libpoker_cfr.so
# The bounded subprocess monitor uses ps; the compiled kernel needs libstdc++.
RUN apt-get update && apt-get install -y --no-install-recommends procps libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY research ./research
COPY --from=native-builder /opt/poker/native /opt/poker/native
# Verify the real isolated calculation in the final image, without a DB or secrets.
RUN python -m research.verify_packaged
# Keep one process: room sockets, timers, live tables and solver queue have one owner.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --ws-max-size 16384 --no-access-log"]
