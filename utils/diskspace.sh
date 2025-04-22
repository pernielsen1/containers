#!/bin/bash
du --max-depth=1 $1 | sort -r -k1,1n
# sudo journalctl --vacuum-size=100M
# sudo snap set system refresh.retain=2


