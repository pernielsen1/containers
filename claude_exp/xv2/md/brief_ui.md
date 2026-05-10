# UI
make a plan for building a user interface.
let's discuss if extra packages are needed in the venv - if so I will install.

create a ui front end which makes it possible to control all actors.
the ui-front will find the information by looking a config.json's in the directory structure
all actors exposes stop and stats - which should be accessible in the ui
in addition the upstream_host also allows for upload a csv file with test cases and start which starts running the test cases.
when choosing upload it should be possible to choose a local csv file with test cases.

## update
I am on a windows PC but this venv is running in wsl. 
when choosing a file it will default to my windows directories - I want it to default to the root of this project within the wsl

## cleaning
cleaning a bit - create directory test_csv_files and move all csv files used to this directory - make that directory the default for the ui

## regression test
we have moved files around etc - please make a regression test of the whole solution excluding the ui part.

# ui part two
when running ui.sh - I get a lot of messages in my console GET /api/status HTTP etc... how can I avoid that when i have sent ui.sh to run in the back ground 
