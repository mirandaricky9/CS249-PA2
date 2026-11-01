#!/bin/bash
# Starts every server listed in the config as its own background process.
# Usage: ./run.sh --config servers.json

cd "$(dirname "$0")" || exit 1

CONFIG="servers.json"
while [ $# -gt 0 ]; do
    case "$1" in
        --config) CONFIG="$2"; shift 2 ;;
        *) echo "Usage: $0 --config <file>" >&2; exit 1 ;;
    esac
done

# Read the server ids using python from the config instead of hardcoding A B C to make it more general
IDS=$(python3 -c 'import json, sys; print(" ".join(s["id"] for s in json.load(open(sys.argv[1]))["servers"]))' "$CONFIG") || {
    echo "Could not read server ids from $CONFIG" >&2; exit 1; }

PIDS=()
cleanup() {
    echo "Stopping servers: ${PIDS[*]}"
    kill "${PIDS[@]}" 2>/dev/null
    wait
    exit 0
}
trap cleanup INT TERM

for id in $IDS; do
    python3 -u server.py --config "$CONFIG" --id "$id" &
    PIDS+=($!)
    echo "Started server $id (pid $!)"
done

# Wait for all servers; keeps running if one (e.g. C in the demo) is killed
wait