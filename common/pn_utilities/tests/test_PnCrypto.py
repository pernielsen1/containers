import pn_utilities.PnLogger as PnLogger
import pn_utilities.crypto.PnCrypto as PnCrypto
#-------------------------------
# local tests
#--------------------------------
if __name__ == '__main__':
  my_keys = PnCrypto.PnCryptoKeys()
  log = PnLogger.PnLogger()
  log.info(my_keys.get_keys()) 
  log.info(my_keys.get_key('k3')) 
  log.info(my_keys.get_key('k3xyz')) 
