import os
import json
import requests
import base64
import logging
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
  
# import iso8583
# from iso_spec import test_spec
from iso8583_utils import Iso8583Utils

NANO_TO_SECONDS = 1000000000


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
        self.iso8583_utils = Iso8583Utils("iso8583_utils.json")
 
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
            "index": {"text":"index", "function" :self.do_index, "menu": "index", "data_func": None}, 
            "": {"text" : "index", "function": self.do_index, "menu" : "index", "data_func": None},

            'processes' : {"text": "{key}", "function": self.get_process, "menu": "processes", "data_func" : self.get_link}, 
            "statistics": {"text": "show stats", "function": self.get_statistics, "menu": "processes", "data_func": self.get_link}, 
            "reset": {"text": "reset stats", "function": self.do_reset, "menu": "processes", "data_func": self.get_link}, 
            "stop": {"text": "stop", "function": self.do_stop, "menu": "processes", "data_func": self.get_link}, 
            'status' : {"text": "status", "function": self.get_process, "menu": "processes", "data_func" : self.get_status}, 

            "testcases" : {"text": "test cases", "function": self.run_test, "menu" : "testcases", "data_func": self.get_link},
            "testcases_multi" : {"text": "multiple tests", "function": self.run_multiple_tests, "menu" : "testcases", "data_func": self.get_link},

            "children" : {"text": "{key}", "function": self.run_child, "menu" : "children", "data_func": self.get_link},
            "children_name" : {"text": "name", "function": None, "menu" : "children", "data_func": self.get_link}

        }

    def run_child():
        print("run chlld")
        return

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
        print(f"running {process_name} {msg}")
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
            if msg['command'] in ('send', 'reset', 'work'):
                result += f"Command {msg['command']} successfull !"
            if msg['command'] in ('threads', 'ping', 'children'):
                result = response.json()
    

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
            return " you want to reset all processes - not implemented"
        else:
            return self.run_command(process_name,{ "command": "reset"})
    
    def do_stop(self, process_name):
        if process_name is None:
            return " you want to stop all processes - not implemented"
        else:
            return self.run_command(process_name,{ "command": "stop"})

    #
    def get_statistics(self, process_name):
        return self.run_command(process_name,{ "command": "stat"})

    def get_process(self, process_name):
        url = self.console_app.processes[process_name].get('url', 'What ?')
        description = self.console_app.processes[process_name].get('description', 'What ?')
        res = "you want to see " + process_name + ' ' + description + " url:" + url
        threads = self.run_command(process_name,{ "command": "threads"})
        res += "<table><tr><th>name</th><th>heartbeat</th><th>active</th><th>class</th><th>native_id</th><th>state</th></tr>"
        for key, t in threads['return_data'].items():
            heartbeat_str = datetime.fromtimestamp(t['heartbeat']).strftime('%H:%M:%S.%f')
            res += f'<tr><td>{t['name']}</td><td>{heartbeat_str}</td><td>{t['active']}</td><td>{t['class']}</td><td>{key}</td><td>{t['state']}</td></tr>' 

        res += "</table>"
        return res

    # do a ping and see if we get a result OK 
    def check_ping(self, process_name):
        result =  self.run_command(process_name,{ "command": "ping"})
        heartbeat= time.time()  
        heartbeat_str = datetime.fromtimestamp(heartbeat).strftime('%H:%M:%S.%f')
        if isinstance(result, dict):
            color="green"
            text="OK " + heartbeat_str 
        else:
            color="red"
            text = "Failed " + heartbeat_str + str(result)

        return f'<p style="color:{color}">{text}</p>'

    def run_multiple_tests(self, test_case_key):
        parms_dict = parse_qs(urlparse(self.path).query)  # the possible parms after the ? as dict
        num_cases_tuple = parms_dict.get("num_cases", None)
        if num_cases_tuple is not None:
            num_cases = int(num_cases_tuple[0])
            if num_cases > 0:
                print("time to execute")
                return(self.run_test(test_case_key, num_cases))

        page = f'<br>You want to run {test_case_key} multiple times'
        url = self.host_uri + "/testcases_multi/"  # i.t. this URI probably possible to get easier
        url = self.host_uri + self.path 
        page +=f'<form action="{url}" method="get">'
        page += '<label for="num_cases">Number of times to run</label>'
        page +=  '<input type="text" id="num_cases" name="num_cases" placeholder="0" required />'
        page += '<button type="submit">Submit</button>'
        page += '</form>'
        return page
    
    def run_test(self, test_case, num_messages:int= 1):
        if (test_case is None):
            return "You want to see all test cases"

        process_name = self.console_app.test_case_file['test_process_name']
        url = self.console_app.processes[process_name].get('url', 'What ?')
        queue_name = self.console_app.test_case_file['test_process_queue_name']
        result = f'trying to send {test_case} to {process_name} on {url}<br>'
        # build the iso message   
        iso_message_raw = self.console_app.iso8583_utils.build_iso_msg(test_case)                  
#        iso_message_raw, encoded = iso8583.encode(self.console_app.test_cases[test_case]['iso_message'], test_spec)
        text = base64.b64encode(iso_message_raw).decode("ascii")
        msg = {
                "command": "work",
                "queue_name": queue_name,
                "is_base64": True,
                "text": text,
                "data_base64": text,
                "num_messages": num_messages    
        }
        return result + self.run_command(process_name, msg)

    def get_link(self, process_name, key, item): 
        return  f'<td><a href={self.host_uri}/{key}/{process_name}>{item['text']}</td>'.replace("{key}", process_name)
  
    def get_status(self, process_name, key, item):
        return f'<td>{self.check_ping(process_name)}</td>'

    # build a menu - table - based on routes - known    
    def build_menu(self, menu_name, key_dict):
        menu = f'<h2>{menu_name}</h2>'
        menu += "<table><tr>" 
        for key, item in self.routes.items():
            if (item['menu'] == menu_name):
                menu += f'<th>{item['text']}</th>'
        menu += "</tr>"
        for key in key_dict:
            menu += "<tr>"
            for route_key, item in self.routes.items():
                if (item['menu'] == menu_name):
                    # run the data func for the item and get a link or status in return
                    menu += item['data_func'](key, route_key, item)
            menu += "</tr>"
        menu += '</table>'
        return menu

    # build the main page - link of processes and test cases
    def do_index(self,key):
        process_table = self.build_menu("processes", self.console_app.processes)
        testcase_table = self.build_menu("testcases", self.console_app.test_cases) 
        children_table = self.get_children("grand_mama")

        return children_table + process_table + testcase_table 

    def get_children(self, process_name):
        ret_dict = self.run_command(process_name,{ "command": "children"})
        if isinstance(ret_dict, dict):
            ret_data = ret_dict.get('return_data', None)
            if ret_data is not None:
                return self.build_menu("children", ret_data)
        #Still here = not good 
        return "<BR>Error getting children info" + str(ret_dict)


#-----------------------------------
# do_GET - the main traffic control
#-----------------------------------
    def do_GET(self):
        self._set_headers('html')  
        home_buttom_html = f'<a href="{self.host_uri}"><button>to the main page</button></a>'
        page_start ="<html><head><title>Commapp console</title></head><body>"
    #    page_start +='<link rel="icon" type="image/x-icon" href="/images/favicon.ico">'
        css = "<style>table, th, td {  border: 1px solid black;}</style>"
        page_body = "<h1>commapp console</h1>"
        page_end =  "</body></html>"
        # the route is the start of the path simple app only one level so far
        route_str = self.path.split('/')[+1]
        route = self.routes.get(route_str, None)
        if route is not None:
            function = route['function']
            path =  urlparse(self.path).path
            key =  path.split('/')[-1] # a potential key is the last path of the part before parms
            page_body += function(key)
        else:
            if (route_str != 'favicon.ico'):
                logging.error(f"did not find route for {route_str}")
        page_body += "<h1>bottom<h1>"
        page = page_start + css + page_body + home_buttom_html + page_end 
        self.wfile.write(bytes(page, 'UTF-8'))

#-----------------------------------
# do_POST  - just send to do_GET that should work
#-----------------------------------
    def do_POST(self):
        print(self.headers)
        self.do_GET()

def do_stat(json_response):
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