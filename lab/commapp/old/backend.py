import sys
import logging
from communication_app import CommunicationApplication, Filter, Message


def echo_filter(message):
    # A simple filter that echoes the message back a bit of cheating... .
    logging.debug(f"Echo filter received message: {message.get_json()}")
    out_message = Message(message.get_string() + " and return")
    app.queues['to_middle'].put(out_message)
    return message


# Main function
if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    
    app = CommunicationApplication(config_file)
#    app.add_filter(Filter('echo', echo_filter))
    app.start()
