#!/bin/sh
# Name: KOReader
# Author: KOReader Team
# DontUseFBInk

[ -f /mnt/us/koreader/koreader.sh ] || exit 1
cd /mnt/us || exit 1
export UNPACK_DIR=/mnt/us
exec /bin/sh /mnt/us/koreader/koreader.sh --asap
