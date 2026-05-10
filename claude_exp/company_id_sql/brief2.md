we are in a container defined by the Dockerfile and docker-compose.yml
it implements a mysql, python and claude instanse with a few python requirements
propose a plan for 
1: update Dockerfile & docker-compose to add a oracle database with same users and passwords we use for mysql
plus add python support for selecting mysql or oracle.
the dockers containers are build outside this so 
provide script build.sh and startx.sh 
2: re