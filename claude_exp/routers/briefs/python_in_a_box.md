# a dilemma 
I have introduced the server which we will use for testing on next integration level
now the simulators we have kept local on this box i.e. the dilemma
## dev
the development pc with Claude installed - may actually be this labtop or my other labtop
## sys
the serverhp - which has a docker installation and deploy.sh can move the images to the server.

# resolving the dilemama
having all simulators locally is good when we experiment - but not when we want to deploy to an infrastructure now relying in the dev environment.
ideally we probably have both the local adjustments on the host when in dev environment and have a simulator container when moving to next level i.e. created in the deploy.sh ? 
let's discuss.

