#  message - defines the Message object
# 
import time
import json
import pn_utilities.logger.PnLogger as PnLogger

log = PnLogger.PnLogger()

class Message():
    def __init__(self, payload: str):
        self.message_dict = {}
        self.message_dict['payload'] = payload
        self.message_dict['create_time_ns'] = time.time_ns() 
        self.message_dict['receive_time_ns'] = 0
        self.message_dict['send_time_ns'] = 0
        self.message_dict['message_id'] = ''
        return

    def get_json(self):
        return json.dumps(self.message_dict)

class CommandMessage(Message):
    def __init__(self, commmand: str, key: str = None, reset:str = None):
        self.command_dict = {}
        self.command_dict['command'] = commmand
        if (key != None):
            self.command_dict['key'] = key
        if (reset != None):
            self.command_dict['reset'] = reset
        command_json  = json.dumps(self.command_dict)
        super().__init__(command_json)

class Measurement():
    
    def __init__(self):
        self.measure_time_ns = 0
        self.start_time_ns = 0
        self.elapsed = 0

class Measurements():
    
    def __init__(self, capacity:int = 5):
        self.measurements = []
        self.capacity = capacity
        self.last_ix = capacity
        self.max_elapsed = 0
        self.first_measurement_ns = 0
        for x in range(self.capacity):
            self.measurements.append(Measurement())
        self.reset()
        
    def add_measurement(self, data_json: str,  start_time_ns: int  = None):
        just_now = time.time_ns()
    #    print("DATAJSON" + data_json)
        message_dict = json.loads(data_json)
        if (start_time_ns == None):
            start_time_ns = message_dict['create_time_ns']
        elapsed = just_now - start_time_ns
        self.num_measurements += 1
        self.last_measurement_ns = just_now
        self.total_elapsed_ns += elapsed
        
        if (self.first_measurement_ns == 0):
            self.first_measurement_ns = just_now
        
        if (elapsed > self.max_elapsed):
            self.last_ix +=1 
            if (self.last_ix >= self.capacity):
                self.last_ix = 0

            self.measurements[self.last_ix].start_time_ns = start_time_ns
            self.measurements[self.last_ix].measure_time_ns = just_now
            self.measurements[self.last_ix].elapsed = just_now - start_time_ns

    def reset(self): 
        self.first_measurement_ns = 0
        self.last_measurement_ns = 0
        self.num_measurements = 0 
        self.total_elapsed_ns = 0

        for x in range(self.capacity):
            self.measurements[x].measure_time_ns = 0
            self.measurements[x].start_time_ns = 0
            self.measurements[x].elapsed = 0
            self.max_elapsed = 0
        
    def print_stat(self, reset = False):
        NANO_TO_SECONDS = 1000000000
        for x in range(self.capacity):
            measure_time_ns = self.measurements[x].measure_time_ns
            seconds = measure_time_ns // NANO_TO_SECONDS
            time_str = time.strftime("%Y%m%d %H:%M:%S", time.localtime(seconds)) 
            log.info("time:" + str(self.measurements[x].measure_time_ns) + " " + time_str + " elapsed:" + str(self.measurements[x].elapsed / NANO_TO_SECONDS) )
        
        total_measurement_ns = self.last_measurement_ns - self.first_measurement_ns
        total_measurement_secs = total_measurement_ns / NANO_TO_SECONDS
        if (self.num_measurements > 0):
            log.info("Total measurements: " + str(self.num_measurements)+ " total_elapsed secs:" + str(total_measurement_secs) + 
                                                " avg:" + str(total_measurement_secs/self.num_measurements) +
                                                " per/sec:" + str(self.num_measurements/total_measurement_secs))
            
            log.info("Total avg elapsed:" + str((self.total_elapsed_ns/self.num_measurements)/NANO_TO_SECONDS))
        if (reset):
            self.reset()