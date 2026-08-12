# time to add the ssl layer   
make a plan and ask questions 
## certificates
1: one certificate for the crypto_host connection
2: one certificate for the downstream host 
3: one certificate per upstream connection 
## config
in the router config the necessary certificates should be named including whether sss_active true/false for the three necessary connections crypto_host, downstream and upstream 

## creating certificates
make a python script create_certificate.py on host creating self signed certificates needed. 
I will run it manually. 

# implementation
first implement the ssl layer in the python implementations - i.e. simulators and router_py - keep config_host as configured with ssl_active = false

