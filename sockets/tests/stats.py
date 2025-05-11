#-----------------------------------------------------
# articles on the test patterns
#-----------------------------------------------------
import sys
import pn_utilities.logger.PnLogger as PnLogger
log = PnLogger.PnLogger()
#--------------------------------------------------------------
# so we need to cheat a little and add the socket_queues directory to path
# to find the redis_queue manage obj - ... 
sys.path.insert(0, '../socket_queues')
#--------------------------------------------------------
from redis_queue_manager import RedisQueueManager
from message import CommandMessage

my_RQM =  RedisQueueManager(host='localhost', port=6479, password='pn_password')

command=' '
to_queue = 'crypto_async'
while command != 'X':
  print("current queue is " + to_queue + " enter command\n")
  print("")
  print("f filterstat no reset")
  print("F filterstat RESET")
  print("s send stop")
  print("c change queue name")
  print("X end this program")
  command = input("Enter command")
  if (command == 'f'):
    my_message = CommandMessage('filter_stat', reset='no', key='the_key')
    my_RQM.queue_send(to_queue,my_message.get_json())
  if (command == 'F'):
    my_message = CommandMessage('filter_stat', reset='yes', key='the_key')
    my_RQM.queue_send(to_queue,my_message.get_json())
  if (command == 's'):  
    my_message = CommandMessage('stop', reset='yes', key='the_key')
    my_RQM.queue_send(to_queue,my_message.get_json())
  if (command == 'c'):
    to_queue = input("New queue_name:\n")
   
