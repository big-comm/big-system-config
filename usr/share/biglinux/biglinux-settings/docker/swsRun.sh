#!/bin/bash

dockerComposeAddress="$HOME/Docker/SWS/docker-compose.yml"

# check current status
if [ "$1" == "check" ]; then
  if docker compose ls 2>/dev/null | grep -F -- "$dockerComposeAddress" | grep -q running; then
      echo "true"
  else
      echo "false"
  fi

# change the state
elif [ "$1" == "toggle" ]; then
  state="$2"
  if [ "$state" == "true" ]; then
    docker compose -f "$dockerComposeAddress" up -d
    exitCode=$?
    exit $exitCode
  else
    docker compose -f "$dockerComposeAddress" down
    exitCode=$?
    exit $exitCode
  fi
fi
