import sys
from communication_app import CommunicationApplication


# Main function
if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'config.json'

    app = CommunicationApplication(config_file)
    app.start()
