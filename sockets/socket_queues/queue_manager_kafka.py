#  redis_queue_manager -  
#  interfaces to redis and implements the low level queue_send amd queue_receive
import json
import pn_utilities.logger.PnLogger as PnLogger
from message import Message
from confluent_kafka import Producer, Consumer, KafkaException

log = PnLogger.PnLogger()

class QueueManagerKafka():
    def __init__(self, host='localhost', port=9092, client_id="no_name"):
        self.bootstrap_servers = host + ":" + str(port)
        self.client_id = client_id
        log.info("Createing kafkaqueue manager bothstrap_servers:" + conf['bootstrap.servers'] ) 
        conf = {'bootstrap.servers': 'host1:9092,host2:9092',
                'client.id': client_id}
        self.producer = Producer(conf)


    #------------------------------------------------------------
    # Delivery callback function
    # . can be used to send and wait....
    #------------------------------------------------------------
    def delivery_report(self, err, msg):
        if err is not None:
            print(f"❌ Delivery failed for record {msg.key()}: {err}")
        else:
            print(f"✅ Record successfully produced to {msg.topic()} [{msg.partition()}] at offset {msg.offset()}")

    #--------------------------------------------------------------------------
    # queue_send - low level functions can create unique message number though 
    #              obs takes string as input which is encoded to utf-8 before sending
    #--------------------------------------------------------------------------
    def queue_send(self, queue: str, data : str, message_number: int = None, ttl=3600):
        if (message_number != None): 
            message_id = str(message_number)
        else:
            if (self.queues_message_number.get(queue, None) == None):
                self.queues_message_number[queue] = 0   # first time send - initialize the 

        self.queues_message_number[queue] = self.queues_message_number[queue] + 1
        message_id = str(self.queues_message_number[queue]) 

        message_dict = json.loads(data)
        message_dict['message_id'] = message_id
        send_str = json.dumps(message_dict)
        
        self.producer.produce(topic=queue, key=message_id, value=send_str, callback=self.delivery_report)
        self.producer.flush()

        
    #------------------------------------------------------------------------
    # queue_receive - low level function receiving message from queue - 
    #                   obs will decode the data to utf-8
    #--------------------------------------------------------------------------
    def queue_receive(self, queue: str):
        conf_consumer = {
            'bootstrap.servers': self.bootstrap_servers, 
            'group.id': queue,
            'auto.offset.reset': 'earliest'  # Start from the beginning if no offset is committed
        }
        consumer = Consumer(conf_consumer)
        topic = queue
        consumer.subscribe([topic])
        log.info(f"📥 Listening for messages on topic '{topic}'... Press Ctrl+C to stop.\n")
        try:
            while True:
                msg = consumer.poll(timeout=1.0)  # Wait for message or timeout
                if msg is None:
                    continue
                if msg.error():
                    raise KafkaException(msg.error())
                else:
                    log.debug(f"✅ Received message: key={msg.key().decode('utf-8') if msg.key() else None}, "
                        f"value={msg.value().decode('utf-8')}, "
                        f"partition={msg.partition()}, offset={msg.offset()}")
                    
        except KeyboardInterrupt:
            print("\n🛑 Stopping consumer...")
        finally:
            consumer.close()



    

# Subscribe to the topic





    def send_and_wait(self, queue, msg_no, msg, timeout=20):
        log.error("Not implemented yet in kafka")

    #------------------------------------------------------------------------
    # notify_reply - 
    #--------------------------------------------------------------------------
    def notify_reply(self, data: str, notify_send_ttl_milliseconds = 600):
        log.error("Not implemented yet in kafka")
       
#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    my_RQM =  QueueManagerKafka(host='localhost', port=9092)
    from message import Message
    my_message = Message('stat')
    my_RQM.queue_send('crypto',my_message.get_json())
