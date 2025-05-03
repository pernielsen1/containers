# !interpreter [optional-arg]
# -*- coding: utf-8 -*-

"""
This contains sample code on REDIS load test with locust using python.
It has following operations for Redis data-types: String,List,Set,Hash,Sorted Set
"""

# Built-in/Generic Imports
import json
import random
import time
import redis
from locust import User, events, task, tag
import datetime

__author__ = "Manoj Singh"


host_name = "localhost"
port_no = 6379
password = "pn_password"
class RedisClient(object):
    def __init__(self, host=host_name, port=port_no):
        self.rc = redis(host=host, port=port, password=password)
    
    def set_query_string(self, key, command='SET'):
        result = None
        bid_price = random.randint(47238, 57238)
        redis_response = {'bids': bid_price}
        start_time = time.time()
        try:
            result = self.rc.set(key, json.dumps(redis_response))
            if not result:
                result = ''
        except Exception as e:
            total_time = int((time.time() - start_time) * 1000)
            events.request_failure.fire(request_type=command, name=key, response_time=total_time, exception=e)
        else:
            total_time = int((time.time() - start_time) * 1000)
            length = len(str(result))
            events.request_success.fire(request_type=command, name=key, response_time=total_time,
                                        response_length=length)
        return result

    def get_query_string(self, key, command='ARQC'):
        result = None
        start_time = time.time()
        try:
            result = self.rc.get(key)
            if not result:
                result = ''
        except Exception as e:
            total_time = int((time.time() - start_time) * 1000)
            events.request_failure.fire(request_type=command, name=key, response_time=total_time, exception=e)
        else:
            total_time = int((time.time() - start_time) * 1000)
            length = len(str(result))
            events.request_success.fire(request_type=command, name=key, response_time=total_time,
                                        response_length=length)
        return result



class RedisLocust(User):
    def __init__(self, *args, **kwargs):
        super(RedisLocust, self).__init__(*args, **kwargs)
        self.client = RedisClient()

    @task
    @tag("ARQC")
    def string_operations(self):
        self.client.set_query_string("string_set_operation")
        self.client.get_query_string("string_get_operation")

