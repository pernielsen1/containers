#-----------------------------------------------------
# articles on the test patterns
# https://docs.python.org/3/library/unittest.html

#--------------------------------------------------------
# START OF DIRTY
# OK this is dirty .. we will go directy to the package in the source instead of the installed version of pn_utilities.
# 
#import sys, os
#sys.path.insert(0, '../..')
# 
import os
import sys
import inspect

currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0, parentdir) 

# END OF DIRTY
#----------------------------------------------------------
#  

import unittest
import json
import logging
from modulus import modulus
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s - %(message)s %(funcName)s()') 

#-------------------------------------------------------------------
# 
#-------------------------------------------------------------------
class test_moudulus(unittest.TestCase):
 
  @classmethod
  def setUpClass(cls):
      logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s - %(message)s %(funcName)s()') 
      cls.log = logging.Logger(__name__)

      cls.log.info("setUp starting")
      cls.m_obj = modulus()
      cls.log.info("setUp completed starting tests")    

  def test_kvn(self):
      print("xyz")
      self.log.info("testing kvn")
      self.assertEqual(self.m_obj.validate('68750110', 'kvn'), True)
      self.assertEqual(self.m_obj.validate('68750119', 'kvn'), False)
      self.assertEqual(self.m_obj.validate('6875011', 'kvn'), False)
      self.assertEqual(self.m_obj.validate('687A0110', 'kvn'), False)
 
  def test_cvr(self):
      print("xyz")
      # https://gist.github.com/henrik/daf364fb7e22b3b10cad
      # Search for real CVRs, to see examples: https://datacvr.virk.dk/data/
      # E.g. 35408002, 30715063.

      self.log.info("testing kvn")
      self.assertEqual(self.m_obj.validate('35408002', 'cvr'), True)
      self.assertEqual(self.m_obj.validate('35408009', 'cvr'), False)
      self.assertEqual(self.m_obj.validate('3540800', 'cvr'), False)
      self.assertEqual(self.m_obj.validate('354A8009', 'cvr'), False)
 
  def test_sweorg(self):
        print("org")
        self.log.info("testing org")
        self.assertEqual(self.m_obj.validate('5590002742', 'sweorg'), True)
        
  @classmethod
  def tearDownClass(cls):
      cls.log.info("in tear down")


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  unittest.main()
