#  The abstract object queue_manager which will find redis & apache implementations. -  
#  https://medium.com/@amirm.lavasani/design-patterns-in-python-factory-method-1882d9a06cb4
#
import json
import pn_utilities.logger.PnLogger as PnLogger
from queue_manager_redis import QueueManagerRedis
from queue_manager_kafka import QueueManagerKafka

log = PnLogger.PnLogger()

def create_queue_manager(config_dict = None, config_file="config.json"):
    if (config_dict != None):
        config = config_dict
    else:
        log.info("Loading config dict for create_queue_manager using config file:" + config_file)
        with open(config_file, 'r') as file:
            config = json.loads(file.read())


    queue_manager_type = config['message_broker'].get("type", None) 
    if (queue_manager_type == None or queue_manager_type == "redis"):   
        log.info("creating redis queue manager in create_queue_manager")
        return QueueManagerRedis(host=config['message_broker']['host'], 
                                port = config['message_broker']['redis_port'], 
                                password = config['message_broker']['password']) 
    if (queue_manager_type == "kafka"):
       return QueueManagerKafka(host=config['message_broker']['host'], 
                                port = config['message_broker']['kafka_port']) 
 
    # still here unknown value 
    raise ValueError("queue_manager" + str(queue_manager_type) + " not implemented yet")

