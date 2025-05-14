#!/bin/bash
# gnome-terminal  --tab --working-directory ~/containers -e 'bash -c "title xo1;bash"'
gnome-terminal  --tab --working-directory ~/containers -e 'bash -c "echo -ne "\033]0;/bin/foo\007";bash"'


function title() {
    # Set terminal tab title. Usage: title "new tab name"
    prefix=${PS1%%\\a*}                  # Everything before: \a
    search=${prefix##*;}                 # Eeverything after: ;
    esearch="${search//\\/\\\\}"         # Change \ to \\ in old title
    PS1="${PS1/$esearch/$@}"             # Search and replace old with new
}
export -f title



echo -ne "\033]0;/bin/foo\007"
echo -ne "\033]0;/bin/foo\007"

# gnome-terminal --tab -t "Docker" --working-directory="$BASE_DIR/backend" -- \
#  zsh -is eval "docker-compose up"
# gnome-terminal --tab -t "Backend" --working-directory="$BASE_DIR/backend" -- \
#  zsh -is eval "npm start"
#gnome-terminal --tab -t "Frontend" --working-directory="$BASE_DIR/frontend" -- \
#  zsh -is eval "npm start"
#gnome-terminal --tab -t "Git" --working-directory="$BASE_DIR"
# EOF
