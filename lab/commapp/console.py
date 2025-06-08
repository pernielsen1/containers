import os
import json
import requests
import sys
import base64
import logging
import time
from datetime import datetime

from http.server import BaseHTTPRequestHandler, HTTPServer

server_url = 'localhost'
port = 8070

# inheritance from HTTP-server let's us store an object where we have the data - the console_app
class ConsoleHTTPServer(HTTPServer):
    def __init__(self, console_app, server, port, command_handler):
        super().__init__((server, port), command_handler)
        self.console_app = console_app    
       
class ConsoleApp():
    def __init__(self, config_file="console.json"):
        super().__init__()
        config_file_path = config_file
        if not os.path.isabs(config_file):
            config_file_path = os.path.join(os.getcwd(), config_file)
        with open(config_file_path, 'r') as f:
            self.config = json.load(f)
        with open(self.config['test_case_file'], 'r') as f:
            self.test_case_file = json.load(f)
        self.test_cases = self.test_case_file['tests']

#        print(self.test_cases)      
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
    #----------------------------------------------------
    #
    #----------------------------------------------------
    def get_statistics(self, process_name):
        url = self.console_app.processes[process_name].get('url', 'What ?')
        description = self.console_app.processes[process_name].get('description', 'What ?')
        msg = { "command": "stat"}
        json_msg = json.dumps(msg)
        try:
            response = requests.post(url, json=json_msg)
            print(response)
            if (response.status_code != 200):
                return "Error: " + str(response.status_code) + " " + response.text
            # still here all good
            result = f'stats: retrieved from {url} for {description}'
            result += do_stat(response.json())
            return result

        except requests.exceptions.ConnectionError as errc:
            return f'So there was no luck with {url} gracefully exiting'
        # Maybe set up for a retry, or continue in a retry loop
        except requests.exceptions.RequestException as e:
            return "well that didn't work out exiting" + str(e)

#--------------------------
# do_GET - the main traffic control
#---------------------------
    def do_GET(self):
        logging.info("received" + str(self.path))
        # TBD find from server... 
        host_uri ="http://localhost:" + str(port) 

        self._set_headers('html')
        page_start ="<html><head><title>Commapp console</title></head><body>"
        page_body = "<h1>commapp console</h1>"
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

        if self.path.startswith('/statistics'):
            process_name = self.path.split('/')[-1]
            if (process_name == 'statistics'):
                page_body =  page_body + " you want to see statistics for all processes"
            else:
                page_body += self.get_statistics(process_name)

        if self.path.startswith('/testcases'):
            test_case = self.path.split('/')[-1]
            if (test_case == 'testcases'):
                page_body =  page_body + " you want to see all testcases"
            else:
                page_body += " you want to executre" + test_case

        if self.path.startswith('/index') or self.path == '/':
            page_body =  page_body + "<h2>Processes</h2>"
            process_table = "<table><tr><th>process</th><th>statistics</th></tr>" 
            for process_name in self.console_app.processes:
                #   <a href="url">link text</a>
                process_table += "<tr>"
                process_table += f'<td><a href={host_uri}/processes/{process_name}>{process_name}</td>'
                process_table += f'<td><a href={host_uri}/statistics/{process_name}>stats for {process_name}</a></td>'
                process_table += "</tr>"
            process_table +='</table>'
            page_body += process_table

            page_body += "<h2>test cases</h2>"
            testcase_table = "<table><tr><th>test cases</th></tr>" 
            for test_case in self.console_app.test_cases:
                testcase_table += "<tr>"
                testcase_table +=f'<td><a href={host_uri}/testcases/{test_case}>{test_case}</a></td>'
                process_table += "</tr>"
            page_body += testcase_table

        page = page_start + page_body + page_end 
        self.wfile.write(bytes(page, 'UTF-8'))


def do_stat(json_response):
    NANO_TO_SECONDS = 1000000000
    return_data_str = json_response['return_data']
    return_data_threads = json.loads(json.loads(return_data_str))
    res = ""
    for thread_stat in return_data_threads:
        first_ns  = thread_stat['first_ns']
        last_ns  = thread_stat['last_ns']
        elapsed = last_ns - first_ns 
        num_measurements = thread_stat['num_measurements']
        if num_measurements == 0:
            average_sec = 0 
        else:
            average_sec = (elapsed / num_measurements)/ NANO_TO_SECONDS
          
        name  = thread_stat['name']
        first_ns_str = datetime.fromtimestamp(first_ns/NANO_TO_SECONDS).strftime('%H:%M:%S.%f')
        last_ns_str = datetime.fromtimestamp(last_ns/NANO_TO_SECONDS).strftime('%H:%M:%S.%f')
        res += f'<br>{name} start {first_ns_str} end {last_ns_str} {num_measurements} elapsed:{elapsed/NANO_TO_SECONDS:.2f} average per sec: {average_sec:.4f}' 
    return res



#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    console = ConsoleApp()