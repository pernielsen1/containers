# a java router in a container
this file is in subdirectory briefs of where the project root for exists the xv6 directory.
in general ask questions and make a plan before building.
I expect a few iterartions before we hit the "go" button.
the build_router_input_v2.md contains spec for building a router in python operating in the workstation environment (WSL)
next jobs are however to do it in java
## build a java container with necessary included dependencies,
docker exists in this environment
create a container capable of java development - all source/config files etc needs to be mapped to this directory structure.
I need to be able to edit files using vscode here.
I need a local run script in root start.sh which start the container and stop.sh which ends it

## implement the router
the router (in python - however) is described in build_router_input_v2.md
the router requires iso8583 support - suggest appropriate standard jars for handling these including preferred solution(s) with argumentation.
the simulators requires crypto support - I would argue that standard java is good enough if not explain why.
obs there are comments on how to port to C++ - we may later end so stick to this restriction - it should still be portable to c++ at least for performance critical parts.



