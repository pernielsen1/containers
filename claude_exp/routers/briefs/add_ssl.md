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

# let's go crazy
ssl in every connection crypto_host, downstream and all implementations python, java, cpp 

# let's go ssl all in also for performance test
i.e. ssl is now the default setting and we can set it to false if we want a debugging new partner

# java upgrade 
seems my java version is rather old - let's upgrade to newest version both on host and in docker images - give me a upgrade_java_20260814.sh script and I will run it on both labtops


# minor issues 
on java startup i get
WARNING: A terminally deprecated method in sun.misc.Unsafe has been called
WARNING: sun.misc.Unsafe::objectFieldOffset has been called by com.google.common.util.concurrent.AbstractFuture$UnsafeAtomicHelper (file:/usr/share/maven/lib/guava.jar)
WARNING: Please consider reporting this to the maintainers of class com.google.common.util.concurrent.AbstractFuture$UnsafeAtomicHelper
WARNING: sun.misc.Unsafe::objectFieldOffset will be removed in a future release
