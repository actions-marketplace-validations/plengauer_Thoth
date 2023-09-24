#!/bin/bash
set -e
export SHELL=$1
export OTEL_BASH_CONSOLE_EXPORTER=TRUE
for file in $(find . -iname 'test_*.sh'); do
  echo "running $file"
  $SHELL $file || (echo "FAILED" && exit 1)
done
echo "ALL TESTS SUCCESSFUL"
