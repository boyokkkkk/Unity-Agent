#!/bin/bash
# Long-lived container entrypoint: activate the mounted Unity license, then
# idle so the CLI can docker-exec evaluation runs into the container.

bash "$(dirname "$0")/activate_license.sh"

tail -f /dev/null
