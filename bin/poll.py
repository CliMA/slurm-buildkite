#!/usr/bin/env python3
import logging
# setup root logger
logger = logging.Logger('poll')
handler = logging.StreamHandler()
# For debug statements: handler.setLevel(logging.DEBUG)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

import os

# Which poller implementation to run: 'rest' (default) polls the Buildkite
# builds REST API and requires a user API token; 'metrics' polls the agent
# Metrics API and requires only a cluster agent token. Each mode lives in its
# own module (rest_poll.py / metrics_poll.py), imported lazily here so that
# rest_poll's eager user-token requirement is never hit when running in
# metrics-only mode.
BUILDKITE_POLL_MODE = os.environ.get('BUILDKITE_POLL_MODE', 'rest')

try:
    if BUILDKITE_POLL_MODE == 'metrics':
        import metrics_poll as poll_impl
    else:
        import rest_poll as poll_impl
    poll_impl.run(logger)
except Exception:
    logger.error(f"Caught exception during {BUILDKITE_POLL_MODE} poll", exc_info=True)
