import sys
import logging
from communication_app import CommunicationApplication, Filter, Message
def upper_filter(message):
    logging.debug(f"upper filter receivd message: {message.get_json()}")
    return Message(message.get_string().upper())

# Main function
if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    
    app = CommunicationApplication(config_file)
    app.add_filter(Filter('upper', upper_filter))
    app.start()
