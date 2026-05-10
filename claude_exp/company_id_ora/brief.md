# Oracle installation
## build container spec
in current directory start_oracle.sh will start up a container running a oracle express server.
what I need is a compose.yaml 
where an oracle user is created found in environment variable $PN_MYSQL_USER and password as defined in environment variable $PB_MYSQL_PASSWORD.
  
## part 2
the current setup works - what I need now is a persistent data volume in the host.
it should point to existing directory ~/db_data/oracle
also write a short python script connecting to database with the user $PN_MYSQL_USER and password $PN_MYSQL_PASSWORD

and a problem with pga_aggregate_limit oracle variable - which basically creates the situation that we cannot runt the oracle in docker and vscode at the same time on this machine. 
performance is not interesting on this machine it is a development box.
come up with a good value enabling me to run vscode and the oracle server in a docker box at the same time.
and set the variable when the oracle server is started in the docker container

