#!/bin/sh
# Checkout-local short command; no installed alias or environment setup required.
suites_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
PYTHONPATH="$suites_dir/src${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m portfolio_suites "$@"
