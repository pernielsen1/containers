# ui to monitor
in reality the ui is now the monitor of the other actors so rename to monitor
## stop actor
it shall be possible to start a single actor - right now we only have start all
## total messages since start
we have 30 and 60 seconds add a "since start" counter for all actors.
## kill monitor
the monitor should be possible to stop with a post command
## kill monitor script
a bash kill_monitor.sh script which starts with post a stop command to the monitor - then checking that the unix process stops - if it doesn't after 30 seconds - do a hard kill


