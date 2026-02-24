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

# TBD - is there actually a check digit on the first 8 for Hungary ?
# TBD - validate is date for the mexican

 

import unittest
import json
import logging
from company_identifiers import company_identifiers
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
      cls.m_obj = company_identifiers()
      cls.log.info("setUp completed starting tests")    

  def test_netherland(self): # netherlands
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('68750110', 'NL'), True)
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('6875011', 'NL'), False)
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('6875011', 'NL'), False)
      self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('687A0110', 'NL'), False)
      self.assertEqual(self.m_obj.validate_VAT_ID_bool('NL68750110', 'NL'), True)
 
  def test_denmark(self):
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

  def test_austria(self):
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('33282b', 'AT'), True) # 
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('56247t', 'AT'), True) # 
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('80219d', 'AT'), True) # 
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('FN 80219d', 'AT'), True) # 
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('FN 80219d', 'AT'), True) # 
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('FB 80219d', 'AT'), True) # 
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('ZVR80219d', 'AT'), True) # 
    self.assertEqual(self.m_obj.validate_VAT_ID_bool('ATU12345678', 'AT'), True) # 

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
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('B112.11', 'LU') , True)   # AI google example
#        self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('92345678902', 'LU') , True)   # OECD example
        # Result: Remainder 0 results in check digit 0 or 2 depending on specific tax office rounding, but commonly matches 2 in practice for certain registry series.      
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('12345', 'LU') , True)   # 
    self.assertEqual(self.m_obj.validate_VAT_ID_bool('LUB1234', 'LU') , True) # why is false not correct ?   

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

  def test_lithuania(self): #  Lthuania
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('124110246', 'LT'), True)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('200000017', 'LT'), True)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('124110241', 'LT'), False)  
    self.assertEqual(self.m_obj.validate_VAT_ID_bool('LT200000017', 'LT'), True)  

  def test_estonia(self): #  Estonia
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('10345833', 'EE'), True)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('80352598', 'EE'), True)  
    self.assertEqual(self.m_obj.validate_VAT_ID_bool('EE80352598', 'EE'), True)  

  def test_bulgaria(self): #  Bulgaria
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('131468980', 'BG'), True)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('131468981', 'BG'), False)  
    self.assertEqual(self.m_obj.validate_VAT_ID_bool('BG131468980', 'BG'), True)  

  def test_hungary(self): 
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('12870491-2-4', 'HU'), True)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('12870491-2-41', 'HU'), False)  

  def test_mexico(self): 
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('ABC680524P76', 'MX'), True)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('ABCD80524P76', 'MX'), False)  
    self.assertEqual(self.m_obj.validate_VAT_ID_bool('MXABCD80524P76', 'MX'), False)  

  def test_greece(self): 
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('094014298', 'GR'), True)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('094014290', 'GR'), False)  

  def test_slovenia(self): 
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('5022305400', 'SI'), True)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('50223053', 'SI'), False)  

  def test_romania(self): 
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('J/AB/12345/1999', 'RO'), True)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('J/AB/125/1999', 'RO'), True)  

  def test_slovakia(self): 
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('12345678', 'SK'), True)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('1234567', 'SK'), False)  

  def test_great_britain(self): 
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('12345678', 'GB'), True)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('SC123456', 'GB'), True)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('FC123566', 'GB'), True)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('FC12356', 'GB'), False)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('SC12356', 'GB'), False)  
    self.assertEqual(self.m_obj.validate_COMPANY_ID_bool('412356', 'GB'), False)  


  @classmethod
  def tearDownClass(cls):
      cls.log.info("in tear down")


#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  unittest.main()
