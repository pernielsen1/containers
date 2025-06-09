import os
import json
import requests
import base64
import logging
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import iso8583
from iso_spec import test_spec


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
                    if name != None and server != None and  command_port != 0:
                        url = 'http://' + server + ':' + str(command_port) 
                        self.processes[process_dir.get('name','Not Found')]= {"description": 
                                        process_dir.get('description', None), 
                                        "server": server, 'command_port': command_port, 
                                        "url": url} 
                        

        self.server = self.config['server']
        self.port = self.config['port']
        self.active = True
        run_server = True
        
        if run_server:
            logging.info(f'starting console server on {self.port}')
            server = ConsoleHTTPServer(self, self.server, self.port, RequestHandler)
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
        self.console_app = self.server.console_app
        self.host_uri = "http://" + self.console_app.server + ":" +  str(self.console_app.port) 

        self.routes = {
            'index': self.do_index, 
            '': self.do_index, 
            'statistics': self.get_statistics, 
            'reset': self.do_reset, 
            'testcases' : self.run_test,
            'processes' : self.get_process 
        }


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

    def run_command(self, process_name, msg):
        url = self.console_app.processes[process_name].get('url', 'What ?')
        description = self.console_app.processes[process_name].get('description', 'What ?')
        result = ""
        json_msg = json.dumps(msg)
        try:
            response = requests.post(url, json=json_msg)
            if (response.status_code != 200):
                return "Error: " + str(response.status_code) + " " + response.text
            # still here all good
            if msg['command'] == 'stat':
                result = f'stats: retrieved from {url} for {description}'
                result += do_stat(response.json())
            if msg['command'] in ('send', 'reset'):
                result += f"Command {msg['command']} successfull !"
            return result

        except requests.exceptions.ConnectionError as errc:
            return f'So there was no luck with {url} gracefully exiting'
        # Maybe set up for a retry, or continue in a retry loop
        except requests.exceptions.RequestException as e:
            return "well that didn't work out exiting" + str(e)
    #-----------------------------------------
    # the different routes 
    #------------------------------------------
    def do_reset(self, process_name):
        if process_name is None:
            return " you want to reset all testcases"
        else:
            return self.run_command(process_name,{ "command": "reset"})
    #
    def get_statistics(self, process_name):
        return self.run_command(process_name,{ "command": "stat"})

    def get_process(self, process_name):
        url = self.console_app.processes[process_name].get('url', 'What ?')
        description = self.console_app.processes[process_name].get('description', 'What ?')
        return "you want to see " + process_name + ' ' + description + " url" + url


    def run_test(self, test_case):
        if (test_case is None):
            return "You want to see all test cases"

        process_name = self.console_app.test_case_file['test_process_name']
        url = self.console_app.processes[process_name].get('url', 'What ?')
        queue_name = self.console_app.test_case_file['test_process_queue_name']
        num_messages = 1
        result = f'trying to send {test_case} to {process_name} on {url}<br>'
            # build the iso message             
        iso_message_raw, encoded = iso8583.encode(self.console_app.test_cases[test_case]['iso_message'], test_spec)
        text = base64.b64encode(iso_message_raw).decode("ascii")
        msg = {
                "command": "send",
                "queue_name": queue_name,
                "is_base64": True,
                "text": text,
                "num_messages": num_messages    
        }
        return result + self.run_command(process_name, msg)


    def do_index(self,key):
        index_page =  "<h2>Processes</h2>"
        process_table = "<table><tr><th>process</th><th>statistics</th><th>reset</th></tr>" 
        for process_name in self.console_app.processes:
            process_table += "<tr>"
            process_table += f'<td><a href={self.host_uri}/processes/{process_name}>{process_name}</td>'
            process_table += f'<td><a href={self.host_uri}/statistics/{process_name}>stats for {process_name}</a></td>'
            process_table += f'<td><a href={self.host_uri}/reset/{process_name}>reset for {process_name}</a></td>'
            process_table += "</tr>"

        process_table +='</table>'
        index_page += process_table

        index_page += "<h2>test cases</h2>"        
        testcase_table = "<table><tr><th>test cases</th></tr>" 
        for test_case in self.console_app.test_cases:
            testcase_table += "<tr>"
            testcase_table +=f'<td><a href={self.host_uri}/testcases/{test_case}>{test_case}</a></td>'
            testcase_table += "</tr>"
        testcase_table +='</table>'
        return index_page + testcase_table
#--------------------------
# do_GET - the main traffic control
#---------------------------
    def do_GET(self):
        self._set_headers('html')  
        home_buttom_html = f'<a href="{self.host_uri}"><button>to the main page</button></a>'
        page_start ="<html><head><title>Commapp console</title></head><body>"
        css = "<style>table, th, td {  border: 1px solid black;}</style>"
        page_body = "<h1>commapp console</h1>"
        page_end =  "</body></html>"
  
        route = self.path.split('/')[+1]
        function = self.routes.get(route, None)
        if function is not None:
            key = self.path.split('/')[-1]
            page_body += function(key)
            
        page_body += "<h1>bottom<h1>"
        page = page_start + css + page_body + home_buttom_html + page_end 
        self.wfile.write(bytes(page, 'UTF-8'))


def do_stat(json_response):
    NANO_TO_SECONDS = 1000000000
    return_data_str = json_response['return_data']
    return_data_threads = json.loads(json.loads(return_data_str))
    res = "<table><tr><th>process</th><th>start</th><th>end</th><th>num msg</th><th>elapsed</th><th>avg pr sec</th></tr>"
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
        res += f'<tr><td>{name}</td><td>{first_ns_str}</td><td>{last_ns_str}</td><td>{num_measurements}</td><td>{elapsed/NANO_TO_SECONDS:.2f}</td><td>{average_sec:.4f}</td></tr>' 
    res += "</table>"
    return res


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    console = ConsoleApp()