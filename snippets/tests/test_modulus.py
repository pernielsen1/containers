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
      self.assertEqual(self.m_obj.validate_COMPANY_ID('68750110', 'NL'), True)
      self.assertEqual(self.m_obj.validate_COMPANY_ID('68750119', 'NL'), False)
      self.assertEqual(self.m_obj.validate_COMPANY_ID('6875011', 'NL'), False)
      self.assertEqual(self.m_obj.validate_COMPANY_ID('687A0110', 'NL'), False)
 
  def test_cvr(self):
      print("xyz")
      # https://gist.github.com/henrik/daf364fb7e22b3b10cad
      # Search for real CVRs, to see examples: https://datacvr.virk.dk/data/
      # E.g. 35408002, 30715063.

      self.log.info("testing cvr")
      self.assertEqual(self.m_obj.validate_COMPANY_ID('35408002', 'DK'), True)
      self.assertEqual(self.m_obj.validate_COMPANY_ID('35408009', 'DK'), False)
      self.assertEqual(self.m_obj.validate_COMPANY_ID('3540800', 'DK'), False)
      self.assertEqual(self.m_obj.validate_COMPANY_ID('354A8009', 'DK'), False)
 
  def test_sweorg(self):
        print("org")
        self.log.info("testing org")
        self.assertEqual(self.m_obj.validate_COMPANY_ID('2021005489', 'SE'), True) # skatteverket
        self.assertEqual(self.m_obj.validate_COMPANY_ID('202100548', 'SE'), False)
        self.assertEqual(self.m_obj.validate_COMPANY_ID('2021005487', 'SE'), False)
        self.assertEqual(self.m_obj.validate_COMPANY_ID('2021A05489', 'SE'), False)
        self.assertEqual(self.m_obj.validate('9912346', 'SE_BG7'), True) # from bg https://www.bankgirot.se/globalassets/dokument/anvandarmanualer/10-modul.pdf
        self.assertEqual(self.m_obj.validate('55555551', 'SE_BG8'), True) # from bg example

  def test_fn(self):
        print("fn")
        self.log.info("testing fn - firmen buch number")
        self.assertEqual(self.m_obj.validate_COMPANY_ID('33282b', 'AT'), True) # 
        self.assertEqual(self.m_obj.validate_COMPANY_ID('56247t', 'AT'), True) # 
        self.assertEqual(self.m_obj.validate_COMPANY_ID('80219d', 'AT'), True) # 

  def test_siren(self):  # France
        self.assertEqual(self.m_obj.validate_COMPANY_ID('784671695', 'FR'), True) # Unicef 
        self.assertEqual(self.m_obj.validate_COMPANY_ID('005520135', 'FR'), True) # starts with zero 
        self.assertEqual(self.m_obj.validate_COMPANY_ID('78467169', 'FR'), False) # to short
        self.assertEqual(self.m_obj.validate_COMPANY_ID('78A467169', 'FR'), False) # letter 
        self.assertEqual(self.m_obj.validate_COMPANY_ID('', 'FR'), False) # Empty 
        
  def test_che(self):  # France
        self.assertEqual(self.m_obj.validate_COMPANY_ID('CHE-123.456.788', 'CH'), True) # OK 
        self.assertEqual(self.m_obj.validate_COMPANY_ID('CHe-123.456.788', 'CH'), False) # Is case sensitive 
        self.assertEqual(self.m_obj.validate_COMPANY_ID('CHX-123.456.788', 'CH'), False) # CHE not CHX 
        self.assertEqual(self.m_obj.validate_COMPANY_ID('CHE-123456788', 'CH'), True) # ok with no dots  
        self.assertEqual(self.m_obj.validate_COMPANY_ID('CHE-123456A88', 'CH'), False) # not numeric
        self.assertEqual(self.m_obj.validate_COMPANY_ID('CHE-12345688', 'CH'), False) # Wromg len        
        self.assertEqual(self.m_obj.validate_COMPANY_ID('CHE-123456789', 'CH'), False) # Wromg chk didit not 9 but 8 is the result       
        
  def test_ly(self): # finland
        self.assertEqual(self.m_obj.validate_COMPANY_ID('1572860-0', 'FI'), True)   # Nokia with a missing zero first
        self.assertEqual(self.m_obj.validate_COMPANY_ID('15728600', 'FI'), True)   # OK without the hyphen 
        self.assertEqual(self.m_obj.validate_COMPANY_ID('112038-9', 'FI'), True)   # Nokia with a missing zero first
        self.assertEqual(self.m_obj.validate_COMPANY_ID('12038-9', 'FI'), False)    # Wrong len
        self.assertEqual(self.m_obj.validate_COMPANY_ID('1A1138-9', 'FI'), False)    # Alfa in 

  def test_nororg(self): # Norway
        self.assertEqual(self.m_obj.validate_COMPANY_ID('123456785', 'NO'), True)   # Offical example
        self.assertEqual(self.m_obj.validate_COMPANY_ID('974760673', 'NO'), True)   # Brönnoysund
        self.assertEqual(self.m_obj.validate_COMPANY_ID('12345678', 'NO'), False)   # Wrong len
        self.assertEqual(self.m_obj.validate_COMPANY_ID('1A2345678', 'NO'), False)   # not digits

  def test_germany(self): # Germany
        self.assertEqual(self.m_obj.validate_COMPANY_ID('HRB-1234 Aachen', 'DE') , True)   # Offical example
        self.assertEqual(self.m_obj.validate_COMPANY_ID('HRx-1234 Aachen', 'DE') , False)   # Not HRB, HRA

  def test_poland(self): # Poland
        self.assertEqual(self.m_obj.validate_COMPANY_ID('1234567890', 'PL') , True)   # Offical example
        self.assertEqual(self.m_obj.validate_COMPANY_ID('123', 'PL') , False)   # Not HRB, HRA

  def test_portugal(self): # Portucal
        self.assertEqual(self.m_obj.validate_COMPANY_ID('510 123 457', 'PT') , True)   # Offical example
        self.assertEqual(self.m_obj.validate_COMPANY_ID('500 000 000', 'PT') , True)   # Offical example
        self.assertEqual(self.m_obj.validate_COMPANY_ID('123', 'PT') , False)   # Not HRB, HRA

  def test_ireland(self): # Ireland
        self.assertEqual(self.m_obj.validate_COMPANY_ID('123260', 'IE') , True)   # Offical example
        self.assertEqual(self.m_obj.validate_COMPANY_ID('83424', 'IE') , True)   # Offical example
        self.assertEqual(self.m_obj.validate_COMPANY_ID('1234567', 'IE') , False)   # To Long
        self.assertEqual(self.m_obj.validate_COMPANY_ID('12', 'IE') , False)   # To short

  def test_spain(self): # Ireland
        self.assertEqual(self.m_obj.validate_COMPANY_ID('A28123453', 'ES') , True)   # Offical example
        self.assertEqual(self.m_obj.validate_COMPANY_ID('A123456789', 'IE') , False)   # To Long
   
  
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
