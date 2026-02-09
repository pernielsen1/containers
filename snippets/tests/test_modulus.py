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
        self.assertEqual(self.m_obj.validate('2021005489', 'sweorg'), True) # skatteverket
        self.assertEqual(self.m_obj.validate('202100548', 'sweorg'), False)
        self.assertEqual(self.m_obj.validate('2021005487', 'sweorg'), False)
        self.assertEqual(self.m_obj.validate('2021A05489', 'sweorg'), False)
        self.assertEqual(self.m_obj.validate('9912346', 'swebg7'), True) # from bg https://www.bankgirot.se/globalassets/dokument/anvandarmanualer/10-modul.pdf
        self.assertEqual(self.m_obj.validate('55555551', 'swebg8'), True) # from bg example

  def test_fn(self):
        print("fn")
        self.log.info("testing fn - firmen buch number")
        self.assertEqual(self.m_obj.validate('33282b', 'fn'), True) # 
        self.assertEqual(self.m_obj.validate('56247t', 'fn'), True) # 
        self.assertEqual(self.m_obj.validate('80219d', 'fn'), True) # 

  def test_siren(self):  # France
        self.assertEqual(self.m_obj.validate('784671695', 'siren'), True) # Unicef 
        self.assertEqual(self.m_obj.validate('005520135', 'siren'), True) # starts with zero 
        self.assertEqual(self.m_obj.validate('78467169', 'siren'), False) # to short
        self.assertEqual(self.m_obj.validate('78A467169', 'siren'), False) # letter 
        self.assertEqual(self.m_obj.validate('', 'siren'), False) # Empty 
        
  def test_che(self):  # France
        self.assertEqual(self.m_obj.validate('CHE-123.456.788', 'che'), True) # OK 
        self.assertEqual(self.m_obj.validate('CHe-123.456.788', 'che'), False) # Is case sensitive 
        self.assertEqual(self.m_obj.validate('CHX-123.456.788', 'che'), False) # CHE not CHX 
        self.assertEqual(self.m_obj.validate('CHE-123456788', 'che'), True) # ok with no dots  
        self.assertEqual(self.m_obj.validate('CHE-123456A88', 'che'), False) # not numeric
        self.assertEqual(self.m_obj.validate('CHE-12345688', 'che'), False) # Wromg len        
        self.assertEqual(self.m_obj.validate('CHE-123456789', 'che'), False) # Wromg chk didit not 9 but 8 is the result       
        
  def test_ly(self): # finland
        self.assertEqual(self.m_obj.validate('1572860-0', 'ly'), True)   # Nokia with a missing zero first
        self.assertEqual(self.m_obj.validate('15728600', 'ly'), True)   # OK without the hyphen 
        self.assertEqual(self.m_obj.validate('112038-9', 'ly'), True)   # Nokia with a missing zero first
        self.assertEqual(self.m_obj.validate('12038-9', 'ly'), False)    # Wrong len
        self.assertEqual(self.m_obj.validate('1A1138-9', 'ly'), False)    # Alfa in 

  
# Österreichische Post AG	250328t	High digit count
# Red Bull GmbH	56247k	Five-digit number
# Erste Group Bank AG	33209m	Common retail bank FN
# OMV AG	93308v	Short digit sequence
# Raiffeisen Bank International	121075t	Six-digit number
 

  @classmethod
  def tearDownClass(cls):
      cls.log.info("in tear down")


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  unittest.main()
