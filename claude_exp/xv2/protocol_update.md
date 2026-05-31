# iso8583 complete protocol
make a plan for updating the implementation with the following.
## implement advice 0120/0130
0120 works like a 0100 but the difference is it contains a f39 and f38 - the decision has already been taken.
the only correct answer is 0130 with F39=00 i.e. approved - external decision has been obeyed.
a 0120 it replied with a 0130 reply.
## implement advice 0420/0430
is basically a commmand to revert an earlier request / action. 
accept the message and forward it in a simulator perspective just accept i.e. F39 = 00

# and finally let's make a documentation
## I need a documentation but let us work with layout
I am not sure of the level of details we need so give me questions and let is agree on a plan.
I need a compressed layout describing how one partner is running including tue connected simulators.
make a proposal in md format for the documentation.md file 



