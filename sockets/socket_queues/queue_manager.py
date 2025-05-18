#  The abstract object queue_manager which will find redis & apache implementations. -  
#  https://medium.com/@amirm.lavasani/design-patterns-in-python-factory-method-1882d9a06cb4
#
from abc import ABC, abstractmethod
class QueueManager(ABC):
    #--------------------------------------------------------------------------
    # queue_send - low level functions can create unique message number though 
    #              obs takes string as input which is encoded to utf-8 before sending
    #--------------------------------------------------------------------------
    @abstractmethod
    def queue_send(self, queue: str, data : str, message_number: int = None, ttl=3600):
        pass
    #------------------------------------------------------------------------
    # queue_receive - low level function receiving message from queue - 
    #                   obs will decode the data to utf-8
    #--------------------------------------------------------------------------
    @abstractmethod
    def queue_receive(self, queue: str):
        pass

    #------------------------------------------------------------------------
    # send_and_wait - send message and wait for reply - 
    #                   obs will decode the data to utf-8
    #--------------------------------------------------------------------------
    @abstractmethod
    def send_and_wait(self, queue, msg_no, msg, timeout=20):
        pass

    #------------------------------------------------------------------------
    # notify_reply - 
    #--------------------------------------------------------------------------
    @abstractmethod
    def notify_reply(self, data: str, notify_send_ttl_milliseconds = 600):
        pass

    