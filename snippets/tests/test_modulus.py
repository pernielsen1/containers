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

  def test_nl(self): # netherlands
      print("xyz")
      self.log.info("testing kvn")
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('68750110', 'NL'), True)
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('68750119', 'NL'), False)
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('6875011', 'NL'), False)
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('687A0110', 'NL'), False)
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('NL68750110', 'NL'), True)
 
  def test_denmark(self):
      print("xyz")
      # https://gist.github.com/henrik/daf364fb7e22b3b10cad
      # Search for real CVRs, to see examples: https://datacvr.virk.dk/data/
      # E.g. 35408002, 30715063.

      self.log.info("testing cvr")
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('35408002', 'DK'), True)
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('35408009', 'DK'), False)
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('3540800', 'DK'), False)
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('354A8009', 'DK'), False)
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('DK354A8009', 'DK'), False)
 
  def test_sweden(self):
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('2021005489', 'SE'), True) # skatteverket
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('202100548', 'SE'), False)
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('2021005487', 'SE'), False)
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('2021A05489', 'SE'), False)
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('SE2021005489', 'SE'), True) # skatteverket
      self.assertEqual(self.m_obj.validate_bool('9912346', 'SE_BG'), True) # from bg https://www.bankgirot.se/globalassets/dokument/anvandarmanualer/10-modul.pdf
      self.assertEqual(self.m_obj.validate_bool('55555551', 'SE_BG'), True) # from bg example

  def test_fn(self):
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('33282b', 'AT'), True) # 
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('56247t', 'AT'), True) # 
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('80219d', 'AT'), True) # 

  def test_france(self):  # France
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('784671695', 'FR'), True) # Unicef 
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('005520135', 'FR'), True) # starts with zero 
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('78467169', 'FR'), False) # to short
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('78A467169', 'FR'), False) # letter 
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('', 'FR'), False) # Empty 
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('FR784671695', 'FR'), True) # Unicef 
        
  def test_che(self):  # France
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('CHE-123.456.788', 'CH'), True) # OK 
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('CHe-123.456.788', 'CH'), False) # Is case sensitive 
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('CHX-123.456.788', 'CH'), False) # CHE not CHX 
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('CHE-123456788', 'CH'), True) # ok with no dots  
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('CHE-123456A88', 'CH'), False) # not numeric
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('CHE-12345688', 'CH'), False) # Wromg len        
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('CHE-123456789', 'CH'), False) # Wromg chk didit not 9 but 8 is the result       
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('CH123.456.788', 'CH'), True) # OK 
        
  def test_finland(self): # finland
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('1572860-0', 'FI'), True)   # Nokia with a missing zero first
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('15728600', 'FI'), True)   # OK without the hyphen 
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('112038-9', 'FI'), True)   # Nokia with a missing zero first
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('12038-9', 'FI'), False)    # Wrong len
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('1A1138-9', 'FI'), False)    # Alfa in 
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('FI15728600', 'FI'), True)   # Nokia with a missing zero first

  def test_norway(self): # Norway
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('123456785', 'NO'), True)   # Offical example
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('974760673', 'NO'), True)   # Brönnoysund
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('12345678', 'NO'), False)   # Wrong len
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('1A2345678', 'NO'), False)   # not digits
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('NO123456785', 'NO'), True)   # Offical example

  def test_germany(self): # Germany
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('HRB-1234 Aachen', 'DE') , True)   # Offical example
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('HRx-1234 Aachen', 'DE') , False)   # Not HRB, HRA
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('DE123456789', 'DE') , True)   # Offical example
 
  def test_poland(self): # Poland
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('1234567890', 'PL') , True)   # Offical example
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('123', 'PL') , False)   # Not HRB, HRA
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('PL1234567890', 'PL') , True)   # Offical example

  def test_portugal(self): # Portucal
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('510 123 457', 'PT') , True)   # Offical example
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('500 000 000', 'PT') , True)   # Offical example
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('PT510 123 457', 'PT') , True)   # Offical example
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('123', 'PT') , False)   # Not HRB, HRA

  def test_ireland(self): # Ireland
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('123260', 'IE') , True)   # Offical example
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('83424', 'IE') , True)   # Offical example
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('1234567', 'IE') , False)   # To Long
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('12', 'IE') , False)   # To short
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('IE123260', 'IE') , True)   # Offical example

  def test_spain(self): # Ireland
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('A28123453', 'ES') , True)   # Offical example
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('ESA28123453', 'ES') , True)   # Offical example
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('A123456789', 'IE') , False)   # To Long
  
  def test_belgium(self): # Belgium
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('0403.019.261', 'BE') , True)   # AI google example
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('0403.019.262', 'BE') , False)   # Wrong digit
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('BE0403.019.261', 'BE') , True)   # AI google example
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('BA0403.019.261', 'BE') , False)   # AI google example
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('BE0403.019.262', 'BE') , False)   # AI google example
   
  def test_czech(self): # Czechia  TBD more edge cases in test for 1 in rest
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('25596641', 'CZ') , True)   # AI google example
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('25596640', 'CZ') , False)   # Wrong digit
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('CZ25596641', 'CZ') , True)   # AI google example

  def test_luxembourg(self): # Luxembourg  TBD more edge cases in test for 1 in rest
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('19871234569', 'LU') , True)   # AI google example
#        self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('92345678902', 'LU') , True)   # OECD example
        # Result: Remainder 0 results in check digit 0 or 2 depending on specific tax office rounding, but commonly matches 2 in practice for certain registry series.      
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('19871234568', 'LU') , False)   # Wrong digit
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('LU19871234569', 'LU') , True)   # AI google example

  def test_italy(self): # Italy a variant of luhn 
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('01533030480', 'IT') , True)   # AI google example
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('01533030484', 'IT') , False)   # Wrong digit
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('IT01533030480', 'IT') , True)   # AI google example

  def test_us(self): # us just number 01-1234567 
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('01-1234567', 'US') , True)   
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('01-123456', 'US') , False)   
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('US01-1234567', 'US') , True)   

  def test_latvia(self): #  Latvia
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('40003032949', 'LV') , True)   
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('40003032944', 'LV') , False)   
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('LV40003032949', 'LV') , True)   

#    Tier 1 Calculation:
#        Multiply the first 7 digits by weights 1, 2, 3, 4, 5, 6, 7 respectively.
#        Sum the products and calculate the remainder of the sum divided by 11 (Sum % 11).
#        If the remainder is less than 10, it is the check digit.
#    Tier 2 Calculation (if Tier 1 remainder is 10):
#        If the first calculation yields a remainder of 10, repeat the process with new weights: 3, 4, 5, 6, 7, 8, 9.
#        Sum these products and calculate the remainder divided by 11.
#        If this second remainder is less than 10, it is the check digit.
#        If the second remainder is still 10, the check digit is 0. 

#Structure and Official Verification
#
#    Length: Exactly 8 digits.
#    First Digit: Indicates the entity type (e.g., 1 for companies, 8 for non-profits, 7 for government agencies).
#    Official Search: You can verify if a specific code is currently active and assigned to a legal entity via the Estonian e-Business Register (Äriregister).
#    VAT Numbers: If checking a VAT ID (format EE + 9 digits), the first 8 digits are usually the registry code, and the 9th is a separate checksum verifiable via the European VIES system. 
# Lithuania
# Check Digit Calculation Rules
# The check digit is calculated based on the first 8 digits of the company code: 
#
#    Weights: Each of the first 8 digits is multiplied by a weight ranging from 1 to 8, respectively.
#        Digit 1 × 1
#        Digit 2 × 2
#        Digit 3 × 3
#        Digit 4 × 4
#        Digit 5 × 5
#        Digit 6 × 6
#        Digit 7 × 7
#        Digit 8 × 8
#    Summation: The results of these multiplications are summed together.
#    Modulo 11: The sum is divided by 11 to find the remainder.
#    Result: The remainder is the 9th check digit.
#    Exception: If the remainder is 10, a new, unused 8-digit code must be used, or a different weight set (3, 4, 5, 6, 7, 8, 9, 1) is applied in some legacy systems to ensure the check digit is less than 10. 
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
