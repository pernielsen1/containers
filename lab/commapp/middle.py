import sys
import logging
from communication_app import CommunicationApplication, Filter, MessageString

def upper_filter(message):
    logging.info(f"upper filter received message: {message.get_json()}")
    return MessageString(message.get_data().decode('utf-8').upper())

# Main function
if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    
    app = CommunicationApplication(config_file)
    app.add_filter(Filter('upper', upper_filter))
    app.start()
