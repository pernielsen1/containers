
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
#---------------------------------------------------------------------

class PnLogger(logging.Logger):
  def __init__(self, name = None, level=logging.NOTSET):
    if (name == None):
       name = Path(__file__).stem

    super().__init__(name, level)
    # create formatting object
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    # add a file out 
    fh = logging.FileHandler(name + ".log")
    fh.setLevel(level)
    fh.setFormatter(formatter)
    self.addHandler(fh)
    # add output to console - would be possible to have different levels in console and file... hmm
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(formatter)
    self.addHandler(ch)

#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
    log = PnLogger(level=logging.INFO)
    log.info("started logging")
    log.info("stopped logging")
    log.error("ups")

