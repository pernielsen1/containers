import os
import logging
from communication_app import Message, Filter, QueueObject, CommunicationApplication   

class FilterUpper(Filter):
    def __init__(self, app:CommunicationApplication , name:str):
        super().__init__(app, name)

    def run(self, message):
        if (self.app is not None):
            print(":" + self.app.name)
            logging.debug(f'I am in {self.app.name}')
        logging.info(f"upper filter received message: {message.get_json()}")
        return Message(message.get_string().upper())

class FilterEcho(Filter):
    def __init__(self, app:CommunicationApplication , name:str):
        super().__init__(app, name)
        # Add the queue to the application - if not already there
        if 'to_middle' not in self.app.queues:
            logging.debug('Creating new queue to_middle')
            self.app.queues['to_middle'] = QueueObject('to_middle', self.app.config)
       
        
    def run(self, message):
        if (self.app is not None):
            logging.debug(f'I am in {self.app.name}')
        logging.info(f"echo filter received message: {message.get_json()}")
        out_message = Message(message.get_string() + " and return")
        self.app.queues['to_middle'].put(out_message)
        return message

# Main function
if __name__ == "__main__":
    print("current dir" + os.getcwd())
    logging.getLogger().setLevel(logging.DEBUG)

    filter_upper  = FilterUpper(CommunicationApplication("middle.json"), 'upper')
    msg = Message('Hello, World!')
    msg_upper = filter_upper.run(msg)
    print(msg_upper.get_string())

    filter_echo = FilterEcho(CommunicationApplication('backend.json'), 'echo')
    msg_echo = filter_echo.run(msg)
    print(msg_echo.get_string())    
    print("End of simple_filters.py")   