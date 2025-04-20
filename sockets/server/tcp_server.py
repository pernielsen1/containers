#--------------------------------------------------------------------------
# tcp_server:  listen on port - establishes connection
# reads messages i.e. reads length field + message and forwards message to 
# message broker.. 
# -------------------------------------------------------------------------
import socket
import json
import pn_utilities.logger.PnLogger as PnLogger
log = PnLogger.PnLogger()

#-------------------------------------------------------------------
# 
#-------------------------------------------------------------------
class TcpServer():
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)
    # the init load the config file to dict config.
    def __init__(self, config_file=""):
        if (config_file == ""):
            config_file = "config.json"
        with open(config_file, 'r') as file:
            self.config = json.loads(file.read())    
        self.go_server()
    def go_server(self):
       port = self.config['port']
       host = self.config['host']

       log.info('Starting server on:' + host + ' on port:' + str(port))
       with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
          s.bind((host, port))
          s.listen()
          conn, addr = s.accept()
          with conn:
            print(f"Connected by {addr}")
            while True:
              len_field = conn.recv(4)
              if (len(len_field) < 4):
                 print("we received less than 4 time to exit")
                 return 
              
              print(len_field)
              log.info("got len field:" + str(len_field))
              len_int = int(len_field)
              data = conn.recv(len_int)
              log.info("received:" + str(data))
              reply = "hello:" + data.decode("utf-8")
              reply_byte_data = reply.encode("utf-8")
              reply_len=len(reply_byte_data)
              reply_len_str = f"{reply_len:04d}"
              log.info("sending reply len:" + reply_len_str)
              conn.sendall(reply_len_str.encode("utf-8"))
              conn.sendall(reply_byte_data)
#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  my_server = TcpServer()
