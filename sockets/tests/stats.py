#-----------------------------------------------------
# articles on the test patterns
#-----------------------------------------------------
import os
import sys
import json
import pn_utilities.logger.PnLogger as PnLogger
log = PnLogger.PnLogger()
#--------------------------------------------------------------
# so we need to cheat a little and add the socket_queues directory to path
# to find the redis_qyeye manage obj - ...
abspath = os.path.abspath(__file__)
dname = os.path.dirname(abspath)
os.chdir(dname)
sys.path.insert(0, '../socket_queues')
dname = os.path.dirname(abspath) 

#--------------------------------------------------------
from redis_queue_manager import RedisQueueManager
from message import CommandMessage


class StatClass():

  def __init__(self, config_file="TEST.json"):
    log.info("loading config file:" + config_file + " in dir:" + os.getcwd())
    with open(config_file, 'r') as file:
      self.config = json.loads(file.read())
    self.RQM = RedisQueueManager(host=self.config['message_broker']['host'], 
                port = self.config['message_broker']['port'], 
                password = self.config['message_broker']['password']) 
    self.filter_stat   = self.config['filter_stat']

  def the_menu(self):
    command=' '
    while command != 'X':
      to_queue = self.filter_stat
      print("current queue is " + to_queue + " enter command\n")
      print("")
      print("f filterstat no reset")
      print("F filterstat RESET")
      print("s send stop")
      print("c change queue name")
      print("X end this program")
      command = input("Enter command")
      if (command == 'f'):
        message = CommandMessage('filter_stat', reset='no', key='the_key')
        self.RQM.queue_send(to_queue,message.get_json())
      if (command == 'F'):
        message = CommandMessage('filter_stat', reset='yes', key='the_key')
        self.RQM.queue_send(to_queue, message.get_json())
      if (command == 's'):  
        message = CommandMessage('stop', reset='yes', key='the_key')
        self.queue_send(to_queue , message.get_json())
      if (command == 'c'):
        to_queue = input("New queue_name:\n")
   

#--------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  stat_class = StatClass()
  stat_class.the_menu()

