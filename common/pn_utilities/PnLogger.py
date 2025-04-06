
import logging
from pathlib import Path
#---------------------------------------------------------------
# 
# combined these two
# https://stackoverflow.com/questions/14058453/making-python-loggers-output-all-messages-to-stdout-in-addition-to-log-file
# https://medium.com/@emanueleorecchio/crafting-your-custom-logger-in-python-a-step-by-step-guide-0824bfd9b939
# 
# the object needs to be installed into the virtual environments
# https://stackoverflow.com/questions/15031694/installing-python-packages-from-local-file-system-folder-to-virtualenv-with-pip
# this file will be in the containers/pn_utilities directory and used from containers/myvenv 
#  
# assuming cd-ed to the myenv directory 
# source bin/activate 
# pip install ../pn_utilities
# and then it could eb used with 
# from pn_utilities import PnLogg 
# 
# https://packaging.python.org/en/latest/tutorials/packaging-projects/
# at present pn_utilities have empty __init__.py and empty setup.py and a filled pyproject.toml
# https://pkiage.hashnode.dev/creating-a-local-python-package-in-a-virtual-environment
#
#  Singleton version:
# https://github.com/priyankmishraa/linkedin-posts/blob/main/logging-singleton/main.py
#---------------------------------------------------------------------

class PnLogger:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
            cls._instance.setup_logger()
        return cls._instance

    def setup_logger(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        self.logger.addHandler(ch)
        fh = logging.FileHandler(__name__ + ".log")
 #       fh.setLevel(level)
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)
  
    def info(self, message):
        self.logger.info(message)
    def error(self, message):
        self.logger.error(message)
    def warning(self, message):
        self.logger.warning(message)
    def debug(self, message):
        self.logger.debug(message)
        
        


class PnLoggerOld(logging.Logger):
  def __init__(self, name = None, level=logging.NOTSET):
    if (name == None):
       name = Path(__file__).stem

    super().__init__(name, level)
    # create formatting object
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    # add a file out 
    self.fh = logging.FileHandler(name + ".log")
    self.fh.setLevel(level)
    self.fh.setFormatter(formatter)
    self.addHandler(self.fh)
    # add output to console - would be possible to have different levels in console and file... hmm
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(formatter)
    self.addHandler(ch)

  #----------------------------------------------
  # release the file handle
  #----------------------------------------------  
  def __del__(self):
    self.removeHandler(self.fh)
    self.fh.close()
#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    log = PnLogger(level=logging.INFO)
    log.info("started logging")
    log.info("stopped logging")
    log.error("ups")

