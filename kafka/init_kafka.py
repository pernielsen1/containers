import os
import json
import pn_utilities.logger.PnLogger as PnLogger
# from kafka.admin import KafkaAdminClient
from confluent_kafka.admin import AdminClient, NewTopic
log = PnLogger.PnLogger()

class InitKafka():
    def __init__(self, config_file: str):
        with open(config_file, 'r') as file:
            self.config = json.loads(file.read())

        bootstrap_servers = self.config['message_broker']['host'] + ":" + str(self.config['message_broker']['kafka_port'] )
        conf = {'bootstrap.servers': bootstrap_servers}
        self.admin_client = AdminClient(conf)
 
    def delete_queue(self, queue):
        # topic new topic in list constructor ? 
        topics_to_delete = []
        topics_to_delete.append (NewTopic(queue))
        log.info("Deleting queue:" + queue)
        self.admin_client.delete_topics(topics_to_delete)
        log.info("Listing after delete of:" + queue)
        self.list_topics()

    def create_queue(self, queue, replace = False):
        if ( queue == 'debug'):
            log.info("Not creating the special debug queue")
        else:
            if (self.topic_exists(queue)):
                if (replace == False):
                    log.info("Not creating queue it already exists and replace is False")
                    return
                else:
                    self.delete_queue(queue)
            # Still here new topic or we hava deleted
            log.info("creating topic " + queue)
            new_topics = []
            new_topics.append (NewTopic(queue, num_partitions = 2))
            self.admin_client.create_topics(new_topics)

    def list_topics(self):
        topic_list = self.admin_client.list_topics(timeout=10)
        # Iterate through topics and print details
        for topic_name, topic_metadata in topic_list.topics.items():
            log.info(f"Topic: {topic_name} " + f"Partitions: {len(topic_metadata.partitions)}")
# TBD
# https://stackoverflow.com/questions/50110075/how-to-create-topic-in-kafka-with-python-kafka-admin-client
# 
    def topic_exists(self, topic):
        topic_list = self.admin_client.list_topics(timeout=10)
        if topic_list.topics.get(topic, None) == None:
            return False
        else:
            return True

    def do_config(self, replace=False):
        log.info("connected listing topics before")
        self.list_topics()
        setup = self.config['setup']
        if (setup == 'queue_worker'):
            self.list_topics()
            recv_queue = self.config['queue_worker']['recv_queue']
            send_queue = self.config['queue_worker']['send_queue']
            self.create_queue(recv_queue, replace)
            self.create_queue(send_queue, replace)
            self.list_topics()
        if (setup == 'socket_to_queues'):
            if (self.config['client']['type'] == 'queue'):
                log.info("Client is queue - creating topics = queues")
                self.create_queue(self.config['client']['recv_queue'], replace)
                self.create_queue(self.config['client']['send_queue'], replace)

            if (self.config['server']['type'] == 'queue'):
                log.info("Server is queue - creating topics = queues")
                self.create_queue(self.config['server']['recv_queue'], replace)
                self.create_queue(self.config['server']['send_queue'], replace)

        
def do_config_dir(dir: str, replace: bool = False):
    for x in os.listdir(dir):
        # Prints only text file present in My Folder
        if (os.path.isfile(dir + "/" + x)):
        #   print("we will process:" + x)
           ic_obj = InitKafka(dir + "/" + x)
           ic_obj.do_config(replace)

if __name__ == '__main__':
    print("cwd" + os.getcwd())
    dir = "sockets/socket_queues/configs"
    file = "WORKER1.json"
    file = "CLIENT.json"
   
    config_file = dir + "/" + file
    replace  = False
    ic_obj = InitKafka(config_file)
    ic_obj.do_config(replace)
    do_config_dir(dir, replace)
    