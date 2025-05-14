#!/bin/bash
# used by opentabs.
prefix=${PS1%%\\a*}                  # Everything before: \a
search=${prefix##*;}                 # Eeverything after: ;
esearch="${search//\\/\\\\}"         # Change \ to \\ in old title
export PS1="${PS1/$esearch/$@}"             # Search and replace old with new
bash
