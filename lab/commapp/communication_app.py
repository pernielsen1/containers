# OK a little challenge can you make a Java version of the following python program ? 

import sys
import json
import socket
import threading
import time
import base64
import logging

from queue import Queue
from http.server import BaseHTTPRequestHandler, HTTPServer

# Setup logging
logging.basicConfig(level=logging.INFO)

# QueueObject class
class QueueObject:
    def __init__(self, name, config):
        self.name = name
        self.config = config
        self.queue = Queue()

    def put(self, data):
        self.queue.put(data)

    def get(self, timeout):
        try:
            return self.queue.get(timeout=timeout / 1000)
        except:
            return None

# Message class
class Message:
    def __init__(self, data):
        self.msg = {
            "data_base64": base64.b64encode(data).decode('utf-8'),
            "time_created_ns": time.time_ns()
        }

    def get_data(self):
        return base64.b64decode(self.msg["data_base64"])

    def get_json(self):
        return self.msg

    def get_create_ns(self):
        return self.msg["time_created_ns"]

# MessageString class
class MessageString(Message):
    def __init__(self, string):
        super().__init__(string.encode('utf-8'))

    def get_string(self):
        return self.get_data().decode('utf-8')

# Filter class
class Filter:
    def __init__(self, name, run_function):
        self.name = name
        self.run_function = run_function

    def run(self, message):
        return self.run_function(message)

    def get_name(self):
        return self.name

# CommunicationApplication class
class CommunicationApplication:
    def __init__(self, config):
        self.config = config
        self.filters = {}
        self.queues = {}
        self.threads = []
    
    def stop(self):
        logging.info("Stopping all threads")
        for thread in self.threads:
            thread.active = False
        for thread in self.threads:
            thread.join()
        logging.info("All threads stopped")

    def add_filter(self, filter_obj):
        self.filters[filter_obj.get_name()] = filter_obj

    def get_filter(self, name):
        return self.filters.get(name, None)

    def add_queue(self, name):
        if name not in self.queues:
            self.queues[name] = QueueObject(name, self.config)
        return self.queues[name]

# CommunicationThread class
class CommunicationThread(threading.Thread):
    def __init__(self, name, queue_name, exit_if_inactive, filter_name=None):
        super().__init__()
        self.name = name
        self.queue_name = queue_name
        self.exit_if_inactive = exit_if_inactive
        self.filter_name = filter_name
        self.heartbeat = time.time()
        self.active = True
        self.queue = app.add_queue(self.queue_name)
        self.filter = app.get_filter(self.filter_name)

    def run(self):
        while self.active:
            self.heartbeat = time.time()
            time.sleep(0.5)
    

# SocketReceiverThread class
class SocketReceiverThread(CommunicationThread):
    def __init__(self, name, socket, length_field_type, queue_name, exit_if_inactive, filter_name=None):
        super().__init__(name, queue_name, exit_if_inactive, filter_name)
        self.socket = socket
        self.length_field_type = length_field_type

    def run(self):
        logging.info(f'Starting {self.name} receiving from socket sending to {self.queue_name}')
        while self.active:
            self.heartbeat = time.time()
            try:
                length_field = self.socket.recv(4)
                if self.length_field_type == 'ascii_4':
                    length = int(length_field.decode('ascii'))
                elif self.length_field_type == 'binary_4':
                    length = int.from_bytes(length_field, 'big')
                data = self.socket.recv(length)
                message = Message(data)
                if self.filter:
                    message = self.filter.run(message)
                logging.debug(f'{self.name} sending message to queue: {data}')

                self.queue.put(message)
            except:
                pass
            time.sleep(0.5)

# SocketSenderThread class
class SocketSenderThread(CommunicationThread):
    def __init__(self, name, socket, length_field_type, queue_name, exit_if_inactive, filter_name=None):
        super().__init__(name, queue_name, exit_if_inactive, filter_name)
        self.socket = socket
        self.length_field_type = length_field_type

    def run(self):
        logging.info(f'Starting {self.name} receiving from {self.queue_name}')

        while self.active:
            self.heartbeat = time.time()
            message = self.queue.get(500)
            if message:
                data = message.get_data()
                logging.debug(f'{self.name} sending message to socket: {data}')

                length = len(data)
                if self.filter:
                    message = self.filter.run(message)
                if self.length_field_type == 'ascii_4':
                    length_field = f"{length:04}".encode('ascii')
                elif self.length_field_type == 'binary_4':
                    length_field = length.to_bytes(4, 'big')
                self.socket.send(length_field)
                self.socket.send(data)
            time.sleep(0.5)

# BigMamaThread class
class BigMamaThread(CommunicationThread):
    def __init__(self, name, queue_name, exit_if_inactive, filter_name=None):
        super().__init__(name, queue_name, exit_if_inactive, filter_name)

    def run(self):
        while self.active:
            self.heartbeat = time.time()
            for thread in app.threads:
                if time.time() - thread.heartbeat > 30:
                    if thread.exit_if_inactive:
                        thread.active = False
                        logging.warning(f"Thread {thread.name} is inactive and will be stopped.")
            time.sleep(1.5)

# ConnectThread class
class EstablishConnectionThread(CommunicationThread):
    def __init__(self, name, type:str, socket_to_queue, queue_to_socket, port, exit_if_inactive, filter_name=None):
        super().__init__(name, name, exit_if_inactive, filter_name)
        self.type = type
        self.socket_to_queue = socket_to_queue
        self.queue_to_socket = queue_to_socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.port=port
        self.length_field_type = 'ascii_4'

    def run(self):
        # first part = establish connection outbound or accept client inbound
        self.socket.settimeout(10)
        if self.type == 'connect':
            self.socket.connect(('localhost', self.port))
        if self.type == 'listen':
            self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listen_socket.bind(('localhost', self.port))
            self.listen_socket.listen(10)  # max backlog of 10... not really needed.. 
        connection_ready = False
        while self.active and connection_ready is False:
            logging.debug(f'{self.name} waiting for Establish {self.port} type:{self.type}')
            self.heartbeat = time.time()

            try:
                if self.type == 'connect':
                    self.socket.connect(('localhost', self.port))
                    connection_ready = True
                    logging.info(f'Connected to server {self.name} on port {self.port}')
                if self.type == 'listen':
                    self.socket, addr  = self.listen_socket.accept()
                    connection_ready = True
                    logging.info(f'Client accepted by {self.name} from {addr}')

                # still here we have a connection
                receiver_thread = SocketReceiverThread(self.socket_to_queue, self.socket, self.length_field_type, 
                                                       'from_client', True, self.socket_to_queue)
                sender_thread = SocketSenderThread(self.queue_to_socket, self.socket, self.length_field_type, 
                                                   'to_client', True, self.queue_to_socket)

                app.threads.append(receiver_thread)
                app.threads.append(sender_thread)

                receiver_thread.start()
                sender_thread.start()

            except:
                pass

        while self.active:
            self.heartbeat = time.time()
            command = self.queue.get(500)
            if command and command.get_string() == 'stop':
                self.active = False
                self.receiver_thread.active = False
                self.sender_thread.active = False

# CommandThread class
class CommandThread(CommunicationThread):
    def __init__(self, name, queue_name, port, exit_if_inactive, filter_name=None):
        super().__init__(name, queue_name, exit_if_inactive, filter_name)
        self.port = port
    def run(self):
        logging.info(f'command server started on {self.port}')
        server = HTTPServer(('localhost', self.port), CommandHandler)
        server.timeout = 5
        while self.active:
            self.heartbeat = time.time()
            logging.debug("Command ready")
            server.handle_request()

class CommandHandler(BaseHTTPRequestHandler):
    def setup(self):
        BaseHTTPRequestHandler.setup(self)
        self.request.settimeout(10)

    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        
    def do_HEAD(self):
        self._set_headers()

    def send_error(self, error_code, error_text):
        self.send_response(error_code)
        self._set_headers()
        self.wfile.write(json.dumps(error_text).encode())

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)  

            data = json.loads(data) # we need to decode the json string twice... why

            command = data.get('command', None)
            if command is None:
                self.send_error(400, {"error": "Missing 'command' field"})
                return
            command = command.lower()
            if command not in ['stop', 'stat', 'reset', 'send']:
                self.send_error(400, {"error": f"Invalid command '{command}'"})
                return

            if command == 'stop':
                logging.info("Stop command received")
                app.stop()

                
            if command == 'send':
               queue_name = data.get('queue_name', None)
               if (queue_name is None):
                    self.send_error(400, {"error": "Missing 'queue_name' field for 'send' command"})
                    return

                # Check if the queue exists
               if queue_name not in app.queues:
                    self.send_error(400, {"error": f"Queue '{queue_name}' does not exist"})
                    return
                # check text is in command 
               text = data.get('text', None)
               if (text is None):
                    self.send_error(400, {"error": "Missing 'text' field for 'send' command"})
                    return

               logging.info(f"sending {text} to {queue_name}")
               message = MessageString(text)
               app.add_queue(queue_name).put(message)

            self.send_response(200)
            self._set_headers()
            self.wfile.write(json.dumps({
                "status": "OK",
                "command": command
            }).encode())

        except json.JSONDecodeError:
            self.send_response(400)
            self._set_headers()
            self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
        except Exception as e:
            logging.exception("Error handling POST request")
            self.send_response(500)
            self._set_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())



    def do_GET(self):
        logging.info("received" + str(self.path))
        last_part =  self.path.split('/')[-1]


        if self.path.startswith('/command/stop'):
            queue_name = self.path.split('/')[-1]
            message = MessageString('stop')
            app.add_queue(queue_name).put(message)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'Command received')
        else:
            self.send_response(404)
            self.end_headers()

# Main function
if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    with open(config_file, 'r') as f:
        config = json.load(f)

    logging.getLogger().setLevel(config['log_level'])
    
    app = CommunicationApplication(config)
    command_thread = CommandThread('command_thread', 'command', config['CommandPort'], True)
    app.threads.append(command_thread)
    command_thread.start()

    big_mama_thread = BigMamaThread('big_mama', 'big_mama', True)
    app.threads.append(big_mama_thread)
    big_mama_thread.start()
    for router_name, router in config['routers'].items():
        t = EstablishConnectionThread(router_name, router['type'], 
            router['socket_to_queue'], router['queue_to_socket'],
            router['port'], True)
        app.threads.append(t)
        t.start()

# curl http://localhost:8009
#{"received": "ok", "hello": "world"}

#curl --data "{\"this\":\"is a test\"}" --header "Content-Type: application/json" http://localhost:8009
# {"this": "is a test", "received": "ok"}
