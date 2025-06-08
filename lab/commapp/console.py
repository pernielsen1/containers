import os
import json
import requests
import sys
import base64
import logging
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

server_url = 'localhost'
port = 8070

# inheritance from HTTP-server let's us store an object where we have the data - the console_app
class ConsoleHTTPServer(HTTPServer):
    def __init__(self, console_app, server, port, command_handler):
        super().__init__((server, port), command_handler)
        self.console_app = console_app    
        print(self.console_app.processes)
        print("after")
class ConsoleApp():
    def __init__(self, config_file="console.json"):
        super().__init__()
        config_file_path = config_file
        if not os.path.isabs(config_file):
            config_file_path = os.path.join(os.getcwd(), config_file)
        with open(config_file_path, 'r') as f:
            self.config = json.load(f)
        self.name = self.config['name']
 
        # list all config files in config dir
        self.processes={}
        for f in os.listdir(self.config['config_dir']): 
            full_name = self.config['config_dir'] + '/' + f
            if os.path.isfile(full_name):
                with open(full_name, 'r') as x:
                    process_dir = json.load(x)
                    name = process_dir.get('name', None)
                    server = process_dir.get('server', None)
                    command_port = process_dir.get('command_port', 0)
                    if name != None and server != None and  port != 0:
                        url = 'http://' + server + ':' + str(command_port) 
                        self.processes[process_dir.get('name','Not Found')]= {"description": 
                                        process_dir.get('description', None), 
                                        "server": server, 'command_port': command_port, 
                                        "url": url} 
                        
        self.port = port
        self.active = True
        run_server = True
        
        if run_server:
            logging.info(f'starting console server on {self.port}')
            server = ConsoleHTTPServer(self, 'localhost', self.port, RequestHandler)
            server.timeout = 20
            while self.active:
                self.heartbeat = time.time()
                logging.debug("Console ready")
                server.handle_request()
        
        logging.info(f"Time to stop guess I am last man standing {self.name}")

class RequestHandler(BaseHTTPRequestHandler):
    def setup(self):
        BaseHTTPRequestHandler.setup(self)
        self.request.settimeout(10)
        print(self.server.console_app)
        self.console_app = self.server.console_app
    def _set_headers(self, type:str):
        self.send_response(200)
        if (type == 'json'):
            self.send_header('Content-type', 'application/json')
        if (type == 'html'):
            self.send_header('Content-type', 'text/html')

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
            data = json.loads(json.loads(body))  # we need to decode the json string twice... why 
            command = data.get('command', None)
            return_data = None
            if command is None:
                self.send_error(400, {"error": "Missing 'command' field"})
                return
            command = command.lower()
            if command not in ['stop', 'stat', 'reset', 'send', 'work', 'debug', 'info']:
                self.send_error(400, {"error": f"Invalid command '{command}'"})
                return

            if command == 'stop':
                logging.info("Stop command received")
                self.app.stop()

                            
            self._set_headers()
            self.wfile.write(json.dumps({
                "status": "OK",
                "from:" : self.app.name,
                "command": command, 
                "return_data": return_data 
            }).encode())

        except json.JSONDecodeError:
            self.send_response(400)
            self._set_headers('json')
            self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())

        except Exception as e:
            logging.exception("Error handling POST request")
            self.send_response(500)
            self._set_headers('json')
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_GET(self):
        logging.info("received" + str(self.path))
        self._set_headers('html')
        page_start ="<html><head><title>Hello World</title></head><body>"
        page_body = "A text"
        page_end =  "</body></html>"
        # msg = "<html><head><title>Hello World</title></head><body>a_text</body></html>"

        if self.path.startswith('/processes'):
            page_body=page_body + " you called me with:" + self.path
            process_name = self.path.split('/')[-1]
            if (process_name == 'processes'):
                page_body =  page_body + " you want to see all processes"
            else:
                url = self.console_app.processes[process_name].get('url', 'What ?')
                description = self.console_app.processes[process_name].get('description', 'What ?')
                page_body = page_body + " you want to see " + process_name + ' ' + description + " url" + url

        host_uri ="http://localhost:" + str(port) 
        if self.path.startswith('/index') or self.path == '/':
            page_body =  page_body + " you want to see main menu"
            for process_name in self.console_app.processes:
                #   <a href="url">link text</a>
                page_body +=f'<br><a href={host_uri}/processes/{process_name}>{process_name}</a>'
                print(page_body)

        page = page_start + page_body + page_end 
        self.wfile.write(bytes(page, 'UTF-8'))

     
#        if self.path.startswith('/processes'):
#            queue_name = self.path.split('/')[-1]
#
#        else:
#            self.send_response(404)
#            self.end_headers()

#-----------------------------------------------
def send_request(port, command, queue_name:str=None, data:any =None, num_messages:int = 1):
    post_url = "http://" + server_url + ":" + str(port) 
    is_base64 = False
    if isinstance(data, bytes) or isinstance(data, bytearray):
        is_base64 = True
        text = base64.b64encode(data).decode("ascii")
    else:  # text is already string   
        text = data

    if (command == 'send'):
        msg = {
            "command": command,
            "queue_name": queue_name,
            "is_base64": is_base64,
            "text": text,
            "num_messages": num_messages    
        }
    else: 
        msg = {
            "command": command,
        }
    
    json_msg = json.dumps(msg)
    try:
        response = requests.post(post_url, json=json_msg)
    
        print(response)
        if (response.status_code != 200):
            print("Error: " + str(response.status_code) + " " + response.text)
            return
        # stilll here
        if (command == 'stat'): 
            do_stat(response.json())
        else:
            print(response.json())
    except requests.exceptions.ConnectionError as errc:
           print(f'So there was no luck with {post_url} gracefully exiting')
           print ("Error Connecting:",errc)
       
    # Maybe set up for a retry, or continue in a retry loop
    except requests.exceptions.RequestException as e:
        print("will that didn't work out exiting")
        raise Exception(e)

#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    console = ConsoleApp()