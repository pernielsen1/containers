import os
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
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s - %(funcName)s() %(message)s') 

# QueueObject class
class QueueObject:
    def __init__(self, name, config):
        self.name = name
        self.config = config
        max_size = config.get('queue_details', {}).get(name, {}).get('max_size', 0)
        logging.debug(f"creating queue {name} with max_size {max_size}")
        self.queue = Queue(maxsize=max_size)

    def put(self, data):
        self.queue.put(data)

    def get(self, timeout):
        try:
            return self.queue.get(timeout=timeout / 1000)
        except:
            return None

# Filter - where the real work is done -  (app communication application not defined yet comes below) 
class Filter:
    def __init__(self, app: any, name:str):
        self.app = app
        self.name = name

    def run(self, message):
        pass
        # This method should be overridden by subclasses

# Message class
class Message:
    def __init__(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8') 
        elif not (isinstance(data, bytes) or isinstance(data, bytearray)):
            raise TypeError("Data must be a string or bytes")
        self.msg = {

            "data_base64": base64.b64encode(data).decode('utf-8'),
            "time_created_ns": time.time_ns()
        }

    def get_data(self):
        return base64.b64decode(self.msg["data_base64"])

    def get_string(self):
        return self.get_data().decode('utf-8')

    def get_json(self):
        return self.msg

class Measurements():
    def __init__(self, name: str, capacity:int = 5):
        self.measurements = []
        self.last_ix = capacity
        self.name = name
        for x in range(capacity):
            self.measurements.append({'start_ns': 0, 'end_ns': 0}) 
        self.reset()
        return

    def add_measurement(self, start_ns:0):
        self.num_measurements += 1
        self.last_ns = time.time_ns()
        if (self.first_ns == 0):
            self.first_ns = start_ns
        if ((self.last_ns - start_ns) > self.max_elapsed):
            self.max_elapsed = self.last_ns - start_ns
            if self.last_ix == len(self.measurements):
                self.last_ix = 0
            self.measurements[self.last_ix] = {'start_ns': start_ns, 'end_ns': self.last_ns}
            self.last_ix += 1

        return 
    
    def reset(self):
        self.max_elapsed = 0
        self.last_ns = 0 
        self.first_ns = 0 
        self.num_measurements = 0

        for item in self.measurements: 
            item = {'start_ns': 0, 'end_ns': 0}
        return
    
    def get_measurements(self):
        return_dict = {'name': self.name, 'first_ns' : self.first_ns, 'last_ns': self.last_ns, 'num_measurements': self.num_measurements, 
                       'top_list': self.measurements }
        return return_dict 
    
# CommunicationApplication class
class CommunicationApplication:
    def __init__(self, config_file):
        # OK vscode - weird.... this should work - need to add the path to the config file
        config_file_path = config_file
        if not os.path.isabs(config_file):
            config_file_path = os.path.join(os.getcwd(), config_file)

        with open(config_file_path, 'r') as f:
            self.config = json.load(f)
        logging.getLogger().setLevel(self.config['log_level'])
        self.name=self.config['name']
        self.filters = {}
        self.queues = {}
        self.threads = []
        self.children = []
        # load filters
        if 'filters' in self.config:
            for filter_name, filter_config in self.config['filters'].items():
                module_name = filter_config['module']
                class_name = filter_config['class']
                try:
                    module = __import__(module_name)
                    filter_class = getattr(module, class_name)
                    filter_obj = filter_class(self, filter_name)
                    self.filters[filter_obj.name] = filter_obj
                    logging.info(f"Filter {filter_name} loaded from {module_name}.{class_name}")
                except Exception as e:
                    logging.error(f"Error loading filter {filter_name}: {e}")

    def start(self):
        command_thread = CommandThread(self, 'command_thread', 'command', self.config['command_port'])
        self.threads.append(command_thread)
        command_thread.start()

        big_mama_thread = BigMamaThread(self, 'big_mama', 'big_mama')
        self.threads.append(big_mama_thread)
        big_mama_thread.start()

        if 'child_apps' in self.config:
            for child_app_name in self.config['child_apps']:
                child_app_thread = GrandMamaThread(self, 'grand_mama', 'grand_mama', child_app_name)
                self.threads.append(child_app_thread)
                child_app_thread.start()

        if 'workers' in self.config:
            for worker_name, worker in self.config['workers'].items():
                t = WorkerThread(self, worker_name, worker['in_queue'],
                                 worker.get('to_queue', None), worker.get('filter_name', None))
                self.threads.append(t)
                t.start()

        if 'routers' in self.config:          
            for router_name, router in self.config['routers'].items():
                t = EstablishConnectionThread(self, router_name, router['type'],
                                            router['socket_to_queue'], router['queue_to_socket'],
                                            router['host'],
                                            router['port'], router.get('filter_name', None))
                self.threads.append(t)
                t.start()

    def stop(self):
        logging.info("Stopping all threads")
        for thread in self.threads:
            thread.active = False
        for thread in self.threads:
            if thread.ident != threading.current_thread().ident:
               thread.join()
        logging.info("All threads stopped")

    def get_filter(self, name):
        return self.filters.get(name, None)

    def add_queue(self, name):
        if name not in self.queues:
            self.queues[name] = QueueObject(name, self.config)
        return self.queues[name]
    
    def get_measurements(self):
        all_measurements = []
        for thread in self.threads:
            if thread.measurements: 
                all_measurements.append(thread.measurements.get_measurements())
 
        return json.dumps(all_measurements)

    def reset_measurements(self):
        for thread in self.threads:
            if thread.measurements:
                thread.measurements.reset() 
    
    def get_threads(self):
        return_dict = {}
        for t in self.threads:
            return_dict[t.native_id] = {'name': t.name, 'active': t.active, 'heartbeat': t.heartbeat, 'class': type(t).__name__ , "state" : t.state}
        return return_dict 
    
    def get_children(self):
        return_dict = {}
        for c in self.children:
            print(c)
            return_dict[c.name] = {'name': c.name}
        print(return_dict)
        return return_dict 
 
# CommunicationThread class
class CommunicationThread(threading.Thread):
    INITIALIZED="Initialized"
    STARTED="Started"
    RUNNING="Running"
    DONE="Done"

    def __init__(self, app, name, queue_name, filter_name=None):
        super().__init__()
        self.app = app
        self.name = name
        self.queue_name = queue_name
        self.filter_name = filter_name
        self.heartbeat = time.time()
        self.active = True
        self.queue = app.add_queue(self.queue_name)
        self.filter = app.get_filter(self.filter_name)
        self.measurements = None # will be overridden in worker thread..
        logging.info(f'App:{self.app.name} initializing {self.name} with queue[{self.queue_name}], filter={self.filter_name}')
        self.state = self.INITIALIZED
    def run(self):
        pass
     
# WorkerThread class
class WorkerThread(CommunicationThread):
    def __init__(self, app, name, queue_name, to_queue_name=None,  filter_name=None):
        super().__init__(app, name, queue_name, filter_name)
        logging.info(f"Adding worker queue[{to_queue_name}]")
        self.to_queue_name = to_queue_name
        self.measurements = Measurements(name, 4)
        if self.to_queue_name is not None:
            self.to_queue = app.add_queue(to_queue_name)

    def run(self):
        self.state=self.RUNNING
        while self.active:
            self.heartbeat = time.time()
            message = self.queue.get(500)
            if message:
                start_ns = time.time_ns()
                logging.debug(f"Worker {self.name} received message {message.get_data()} to queue {self.to_queue_name}")
                # the work =  apply the filter.
                if self.filter is not None:
                    message = self.filter.run(message)
                # and send the message to the to_queue
                if self.to_queue_name is not None:
                    self.to_queue.put(message)
                    logging.debug(f"Worker {self.name} put message {message.get_data()} to queue {self.to_queue.name}")
                self.measurements.add_measurement(start_ns)
        self.state=self.DONE

# SocketReceiverThread class
class SocketReceiverThread(CommunicationThread):
    def __init__(self, app, name, socket, length_field_type, queue_name, filter_name=None):
        super().__init__(app, name, queue_name, filter_name)
        self.socket = socket
        self.length_field_type = length_field_type

    def run(self):
        self.state=self.RUNNING
        logging.info(f'Starting {self.name} receiving from socket sending to queue[{self.queue_name}]')
        while self.active:
            self.heartbeat = time.time()
            try:
                length_field = self.socket.recv(4)
                if self.length_field_type == 'ascii_4':
                    length = int(length_field.decode('ascii'))
                elif self.length_field_type == 'binary_4':
                    length = int.from_bytes(length_field, 'big')
                logging.debug(f'Received length field: {length_field} with length {length}')
                data = self.socket.recv(length)
                message = Message(data)
                if self.filter:
                    message = self.filter.run(message)
                logging.debug(f'{self.name} sending message to queue[{self.queue.name}]: {data}')

                self.queue.put(message)
            except socket.timeout:
            #    print("Didn't receive data! [Timeout 5s]")
                continue
            except Exception as e:
                self.active = False
                logging.error(f'{self.name} had an error {e}')

        self.socket.close()
        logging.info(f"Time to stop {self.name}")
        self.state=self.DONE

# SocketSenderThread class
class SocketSenderThread(CommunicationThread):
    def __init__(self, app, name, socket, length_field_type, queue_name, exit_if_inactive, filter_name=None):
        super().__init__(app, name, queue_name, filter_name)
        self.socket = socket
        self.length_field_type = length_field_type

    def run(self):
        self.state=self.RUNNING
        logging.info(f'Starting {self.name} receiving from queue[{self.queue_name}] sending to socket')

        while self.active:
            try:
                self.heartbeat = time.time()
                message = self.queue.get(500)
                if message:
                    data = message.get_data()
                    length = len(data)
                    if self.filter:
                        message = self.filter.run(message)
                    if self.length_field_type == 'ascii_4':
                        length_field = f"{length:04}".encode('ascii')
                    elif self.length_field_type == 'binary_4':
                        length_field = length.to_bytes(4, 'big')
                    logging.debug(f'Sending length field: {length_field} with data: {data}')
                    self.socket.send(length_field)
                    self.socket.send(data)
            except Exception as e:
                self.active = False
                logging.error(f'Sender {self.name} had an error {e}')

        self.socket.close()
        logging.info(f"Time to stop {self.name}")
        self.state=self.DONE

# BigMamaThread class
class BigMamaThread(CommunicationThread):
    def __init__(self, app, name, queue_name,  filter_name=None):
        super().__init__(app, name, queue_name, filter_name)

    def run(self):
        self.state=self.RUNNING
        while self.active:
            self.heartbeat = time.time()
            for thread in self.app.threads:
                if (time.time() - thread.heartbeat > 30):
                    if thread.state != self.DONE:
                        logging.error(f"Thread {thread.name} is inactive and all will be stopped")
                        self.app.stop()
                    else:
                        if isinstance(thread, EstablishConnectionThread):
                            logging.info("OK that establish connection is all done will join and remove")
                            thread.join()
                            logging.info("OK join ready - remove from list")
                            self.app.threads.remove(thread)
                            logging.info("All done removed from list")
                        else:
                            logging.error(f"Thread {thread.name} reporting done not OK stopping all")
                            self.app.stop()
                # ok if we have wrong thread saying DONE - then we shut down.
            
            command = self.queue.get(15000)   
            if (command):
                text = command.get_string()
                logging.info(f"command {text} received to big_mama")
                if text == 'stop':
                    logging.info(f"stop command received to big_mama")
                    self.app.stop()

        logging.info(f"Time to stop {self.name}")
        self.state=self.DONE

# ConnectThread class
class EstablishConnectionThread(CommunicationThread):
    def __init__(self, app, name, type:str, socket_to_queue, queue_to_socket, host, port, filter_name=None,):
        super().__init__(app, name, name, None)  # no filter for this thread
        self.type = type
        self.socket_to_queue = socket_to_queue
        self.queue_to_socket = queue_to_socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.host = host
        self.port = port
        self.length_field_type = 'ascii_4'
        self.received_filter_name = filter_name

    def run(self):
        self.state=self.RUNNING
        # first part = establish connection outbound or accept client inbound
        if self.type == 'listen':
            self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listen_socket.settimeout(10)  # necessary here or only below ?
            self.listen_socket.bind((self.host, self.port))

        logging.info(f'{self.name} waiting for Establish {self.port} type:{self.type}')
        # waiting to connect to host of for client to connect
        while self.active and self.state == self.RUNNING:
            logging.debug(f'{self.name} waiting for Establish {self.port} type:{self.type}')
            self.heartbeat = time.time()

            try:
                if self.type == 'connect':
                    self.socket.settimeout(10)
                    self.socket.connect((self.host, self.port))
                    logging.info(f'Connected to server {self.name} on port {self.port}')
                    self.state=self.DONE
                elif self.type == 'listen':
                    self.listen_socket.listen(5)  # listen for incoming connections 
                    self.socket, addr  = self.listen_socket.accept()
                    self.socket.settimeout(10)  # still here set socket = client timeout
                    logging.info(f'Client accepted by {self.name} from {addr}')
                    self.listen_socket.close()
                    self.state = self.DONE
                # still here we have a connection
                receiver_thread = SocketReceiverThread(self.app, self.name + '_socket_to_queue', self.socket, self.length_field_type, 
                                                     self.socket_to_queue, self.received_filter_name)
                sender_thread = SocketSenderThread(self.app, self.name + '_queue_to_socket', self.socket, self.length_field_type, 
                                                   self.queue_to_socket, None)
                self.app.threads.append(receiver_thread)
                self.app.threads.append(sender_thread)

                receiver_thread.start()
                sender_thread.start()

            except socket.timeout as e:  # TBD timeout error... nothing to worry abount let it pass
                pass

            except Exception as e:  
                logging.error(f"Error in {self.name} connection: {e}")
                time.sleep(5) # tbd should it be removed - if we get connect error we might as well wait..
                pass    
        self.active =  False


# GrandMamaThread(CommunicationThread) starts a communication app ... 
class GrandMamaThread(CommunicationThread):
    def __init__(self, app, name, queue_name, child_app_name):
        super().__init__(app, name, queue_name)
        self.child_app = CommunicationApplication(child_app_name)
        self.app.children.append(self.child_app)

    def run(self):
        logging.info(f"Starting communication app{self.child_app.name}")
        self.child_app.start()
        self.state=self.RUNNING
        while self.active:
            self.heartbeat = time.time()    
            command = self.queue.get(15000)   
            if (command):
                logging.info(f"command {command} received to grand_mama")

        logging.info(f"Time to stop {self.name}")
        self.state=self.DONE




# CommandThread class
class CommandThread(CommunicationThread):
    def __init__(self, app, name, queue_name, port, filter_name=None):
        super().__init__(app, name, queue_name, filter_name)
        self.app = app
        self.port = port
    def run(self):
        self.state=self.RUNNING
        logging.info(f'command server for {self.name} started on {self.port}')
        server = HTTPServer(('localhost', self.port), CommandHandler)
        server.timeout = 20
        while self.active:
            self.heartbeat = time.time()
            if self.app.config.get("command_debug", False):  # to avoid noise possible to set True if really needing in config file
                logging.debug("Command ready")
            server.handle_request()
        logging.info(f"Time to stop guess I am last man standing {self.name}")
        self.state=self.DONE

# CommandHandler - the actual implementation called when HTTP request is received
class CommandHandler(BaseHTTPRequestHandler):
    def setup(self):
        BaseHTTPRequestHandler.setup(self)
        self.request.settimeout(10)
        self.app = threading.current_thread().app   # ensure we have a link to the communication app easily available.

    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        
    def do_HEAD(self):
        self._set_headers()

    def burst_messages(self, queue_name:str, message:Message, num_messages: int):
        # a thread started when sending messages will put the messages to the queue.
        # the queue has a max_size so when filled it will go slower.
        for i in range  (num_messages):
            self.app.add_queue(queue_name).put(message)

    def send_error(self, error_code, error_text):
        self.send_response(error_code)
        self._set_headers()
        self.wfile.write(json.dumps(error_text).encode())

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(json.loads(body))  # we need to decode the json string twice... why 
            command = data.get('command', None)
            return_data = None
            if command is None:
                self.send_error(400, {"error": "Missing 'command' field"})
                return
            command = command.lower()
            if command not in ['stop', 'stat', 'reset', 'send', 'work', 'debug', 'info', 'ping', 'threads', 'children']:
                self.send_error(400, {"error": f"Invalid command '{command}'"})
                return
            logging.info("command {commend} received")
            if command == 'stop':
                self.app.add_queue('big_mama').put(Message("stop"))

            #    self.app.stop()

            if command == 'debug':
                logging.getLogger().setLevel(10)
                logging.debug("Logging debug after change to debug level")

            if command == 'info':
                logging.getLogger().setLevel(20)

            if command == 'stat':
                return_data = json.dumps(self.app.get_measurements())

            if command == 'reset':
                self.app.reset_measurements()

            if command == 'threads':
                return_data = self.app.get_threads()

            if command == 'children':
                return_data = self.app.get_children()

            if command == 'ping':
                logging.debug("ping - do nothing")

            if command == 'send':
                queue_name = data.get('queue_name', None)
                if (queue_name is None):
                    self.send_error(400, {"error": "Missing 'queue_name' field for 'send' command"})
                    return
                # Check if the queue exists
                if queue_name not in self.app.queues:
                    self.send_error(400, {"error": f"Queue '{queue_name}' does not exist"})
                    return
                # check text is in command 
                text = data.get('text', None)
                if (text is None):
                    self.send_error(400, {"error": "Missing 'text' field for 'send' command"})
                    return
                is_base64 = data.get("is_base64", False)
                if (is_base64):
                    message = Message(base64.b64decode(text.encode("ascii")))
                else:
                    message = Message(text)
              
                num_messages = data.get('num_messages', 1)            
                logging.info(f"sending {text} to {queue_name} {num_messages} times in a seperate thread")
                t1 = threading.Thread(target=self.burst_messages, args=(queue_name, message, num_messages))
                t1.start()
                
            if (command == 'work'):
                data_base64 = data.get('data_base64', None)
                if (data_base64 is None):
                    self.send_error(400, {"error": "Missing 'data_base64' field for 'work' command"})
                    return
                # decode the base64 data, create Message and run the filter
                message = Message(base64.b64decode(data_base64))

                filter_name = data.get('filter_name', None)
                if filter_name is not None:
                    filter_obj = self.app.get_filter(filter_name)
                    if filter_obj is not None:
                        logging.info(f"Applying filter {filter_name} to message {message.get_data()}")
                        message = filter_obj.run(message)
                        return_data = message.get_json()
                            
            self._set_headers()
            self.wfile.write(json.dumps({
                "status": "OK",
                "from:" : self.app.name,
                "command": command, 
                "return_data": return_data 
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
 
# Main function
if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    
    app = CommunicationApplication(config_file)
    app.start()

 
