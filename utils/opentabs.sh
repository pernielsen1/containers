#!/bin/bash
gnome-terminal --title "Containers" --tab --working-directory ~/containers
gnome-terminal --title "Containers" --tab --working-directory ~/containers/common
gnome-terminal --title "Containers" --tab --working-directory ~/containers/sockets

# gnome-terminal --tab -t "Docker" --working-directory="$BASE_DIR/backend" -- \
#  zsh -is eval "docker-compose up"
# gnome-terminal --tab -t "Backend" --working-directory="$BASE_DIR/backend" -- \
#  zsh -is eval "npm start"
#gnome-terminal --tab -t "Frontend" --working-directory="$BASE_DIR/frontend" -- \
#  zsh -is eval "npm start"
#gnome-terminal --tab -t "Git" --working-directory="$BASE_DIR"
# EOF
