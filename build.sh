#!/bin/sh
# Compile the Swift helper into bin/phonectl. Needs only the Xcode command line tools.
set -e
cd "$(dirname "$0")"
mkdir -p bin
swiftc -O -parse-as-library helper/phonectl.swift -o bin/phonectl
echo "built bin/phonectl"
