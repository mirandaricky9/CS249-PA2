#!/bin/bash

cd "$(dirname "$0")" || exit 1

# how can I make this general?

CONFIG="servers.json

while [ $# -gt 0 ]: do
    case 