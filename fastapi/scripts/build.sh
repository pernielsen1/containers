#!/bin/bash
# https://www.datacamp.com/tutorial/set-up-and-configure-mysql-in-docker
# https://fastapi.tiangolo.com/tutorial/first-steps/
step=20
# step 10 build the sql container
if [ $step -eq 10 ]
then
    echo "Build the SQL container - pulling mysql:latest and creating /host/mysql + /host/var according to Dockerfile"
    # the little point . after the dockere build -t is important.... 
    docker build -t mysql .
#    docker pull mysql:latest
    docker images
    step=20
fi
# step 20 
if [ $step -eq 20 ]
then
    echo "in step 20" 
    # https://www.datacamp.com/tutorial/set-up-and-configure-mysql-in-docker
    CONTAINER=test-mysql
    HOST_DATA=$HOME/container_data
    mkdir $HOST_DATA
    mkdir $HOST_DATA/mysql_data

    HOST_PATH="$HOME/containers/mysql/"
 
    CONTAINER_PATH="/host/mysql"
    CONTAINER_DATA_PATH="/host/var"
    MY_USER="my_user"
    MY_PASSWORD="password"
    # if container already exists we stop container and remove it
    docker stop $CONTAINER
    docker rm $CONTAINER
    # if trouble shooting remove the -d option then the output is shown
    echo $CONTAINER_PATH
    echo $HOST_PATH
    docker run --name $CONTAINER -p 12345:3306 \
               --mount type=bind,source=$HOST_PATH,target=$CONTAINER_PATH \
               --mount type=bind,source=$HOST_DATA,target=$CONTAINER_DATA_PATH \
               -e MYSQL_ROOT_PASSWORD=$MY_PASSWORD  -e MYSQL_USER=$MY_USER -e MYSQL_PASSWORD=$MY_PASSWORD \
               -d mysql 
               
    docker ps
    # wait for mysql to be ready for action
    docker exec  test-mysql bash -c $CONTAINER_PATH/scripts/wait_mysql.sh
    # run the init_mysql script (creates the test_db database)
    docker exec $CONTAINER bash -c "mysql -u root -p$MY_PASSWORD <$CONTAINER_PATH/scripts/init_mysql.sql"
    docker exec -it $CONTAINER bash
    step=20
fi

