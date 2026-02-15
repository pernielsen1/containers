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
      self.assertEqual(self.m_obj.validate_legal('68750110', 'NL'), True)
      self.assertEqual(self.m_obj.validate_legal('68750119', 'NL'), False)
      self.assertEqual(self.m_obj.validate_legal('6875011', 'NL'), False)
      self.assertEqual(self.m_obj.validate_legal('687A0110', 'NL'), False)
 
  def test_cvr(self):
      print("xyz")
      # https://gist.github.com/henrik/daf364fb7e22b3b10cad
      # Search for real CVRs, to see examples: https://datacvr.virk.dk/data/
      # E.g. 35408002, 30715063.

      self.log.info("testing cvr")
      self.assertEqual(self.m_obj.validate_legal('35408002', 'DK'), True)
      self.assertEqual(self.m_obj.validate_legal('35408009', 'DK'), False)
      self.assertEqual(self.m_obj.validate_legal('3540800', 'DK'), False)
      self.assertEqual(self.m_obj.validate_legal('354A8009', 'DK'), False)
 
  def test_sweorg(self):
        print("org")
        self.log.info("testing org")
        self.assertEqual(self.m_obj.validate_legal('2021005489', 'SE'), True) # skatteverket
        self.assertEqual(self.m_obj.validate_legal('202100548', 'SE'), False)
        self.assertEqual(self.m_obj.validate_legal('2021005487', 'SE'), False)
        self.assertEqual(self.m_obj.validate_legal('2021A05489', 'SE'), False)
        self.assertEqual(self.m_obj.validate('9912346', 'SE_BG7'), True) # from bg https://www.bankgirot.se/globalassets/dokument/anvandarmanualer/10-modul.pdf
        self.assertEqual(self.m_obj.validate('55555551', 'SE_BG8'), True) # from bg example

  def test_fn(self):
        print("fn")
        self.log.info("testing fn - firmen buch number")
        self.assertEqual(self.m_obj.validate_legal('33282b', 'AT'), True) # 
        self.assertEqual(self.m_obj.validate_legal('56247t', 'AT'), True) # 
        self.assertEqual(self.m_obj.validate_legal('80219d', 'AT'), True) # 

  def test_siren(self):  # France
        self.assertEqual(self.m_obj.validate_legal('784671695', 'FR'), True) # Unicef 
        self.assertEqual(self.m_obj.validate_legal('005520135', 'FR'), True) # starts with zero 
        self.assertEqual(self.m_obj.validate_legal('78467169', 'FR'), False) # to short
        self.assertEqual(self.m_obj.validate_legal('78A467169', 'FR'), False) # letter 
        self.assertEqual(self.m_obj.validate_legal('', 'FR'), False) # Empty 
        
  def test_che(self):  # France
        self.assertEqual(self.m_obj.validate_legal('CHE-123.456.788', 'CH'), True) # OK 
        self.assertEqual(self.m_obj.validate_legal('CHe-123.456.788', 'CH'), False) # Is case sensitive 
        self.assertEqual(self.m_obj.validate_legal('CHX-123.456.788', 'CH'), False) # CHE not CHX 
        self.assertEqual(self.m_obj.validate_legal('CHE-123456788', 'CH'), True) # ok with no dots  
        self.assertEqual(self.m_obj.validate_legal('CHE-123456A88', 'CH'), False) # not numeric
        self.assertEqual(self.m_obj.validate_legal('CHE-12345688', 'CH'), False) # Wromg len        
        self.assertEqual(self.m_obj.validate_legal('CHE-123456789', 'CH'), False) # Wromg chk didit not 9 but 8 is the result       
        
  def test_ly(self): # finland
        self.assertEqual(self.m_obj.validate_legal('1572860-0', 'FI'), True)   # Nokia with a missing zero first
        self.assertEqual(self.m_obj.validate_legal('15728600', 'FI'), True)   # OK without the hyphen 
        self.assertEqual(self.m_obj.validate_legal('112038-9', 'FI'), True)   # Nokia with a missing zero first
        self.assertEqual(self.m_obj.validate_legal('12038-9', 'FI'), False)    # Wrong len
        self.assertEqual(self.m_obj.validate_legal('1A1138-9', 'FI'), False)    # Alfa in 

  def test_nororg(self): # Norway
        self.assertEqual(self.m_obj.validate_legal('123456785', 'NO'), True)   # Offical example
        self.assertEqual(self.m_obj.validate_legal('974760673', 'NO'), True)   # Brönnoysund
        self.assertEqual(self.m_obj.validate_legal('12345678', 'NO'), False)   # Wrong len
        self.assertEqual(self.m_obj.validate_legal('1A2345678', 'NO'), False)   # not digits

  def test_germany(self): # Germany
        self.assertEqual(self.m_obj.validate_legal('HRB-1234 Aachen', 'DE') , True)   # Offical example
        self.assertEqual(self.m_obj.validate_legal('HRx-1234 Aachen', 'DE') , False)   # Not HRB, HRA
   
  
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
