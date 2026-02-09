import argparse
# https://github.com/hubipe/company-identifiers/tree/master/src/CountryValidators
class modulus:
    definitions = {
        "standard":{"algorithm":"mod11", "weights": [7, 6, 5, 4, 3, 2, 1], "len":0},
        "cpr": {"algorithm":"mod11","weights": [ 4,3,2,7,6,5,4,3,2,1 ], "len":10}     ,
        "cvr": {"algorithm":"mod11","weights": [ 2, 7, 6, 5, 4, 3, 2, 1 ], "len":8},
        "sweorg": {"algorithm":"mod10","weights": None, "len":10},
        "nororg": {"algorithm":"mod11","weights": [ 3, 2, 7, 6, 5, 4, 3, 2, 1 ], "len":9},
        "siren": {"algorithm":"mod10","weights": None, "len":9},
        "che": {"algorithm":"che","weights": [ 5, 4, 3, 2, 7, 6, 5, 4, 1 ], "len":9},
        "ly" : {"algorithm":"ly","weights": [  7, 9, 10, 5, 8, 4, 2, 1 ], "len":8},
        "fn": {"algorithm":"fn","weights": None, "len":7},

        "swebg7": {"algorithm":"mod10","weights": None, "len":7},    
        "swebg8": {"algorithm":"mod10","weights": None, "len":8},

        "kvn": {"algorithm":"mod11","weights": [8, 7, 6, 5, 4, 3, 2, 1], "len":8}
    }
    def __init__(self):
        # TBD
        return

    def calc_modulus11_chkdigit(self, s:str, variant) -> int:
        weights = self.definitions[variant]["weights"]
        if not isinstance(s, str) or not s.isdigit():
            return -1
        i = 0
        res = 0
        for c in s:
            if (i==len(weights)):  # when all weights used start from left again
                i=0
            res += int(c) * weights[i]
            i += 1

        rest = res % 11 
        if (rest == 0):
            return rest
        else: 
            return 11 - rest

    def validate_modulus11(self, s:str, variant) -> int:
        weights = self.definitions[variant]["weights"]
        exp_len = self.definitions[variant]["len"]

        if not isinstance(s, str) or not s.isdigit():
            return False
        if exp_len > 0: 
            if len(s) != exp_len:
                return False
        # still here let's see if mod 11 compliant
        i = 0
        res = 0
        for c in s:
            if (i==len(weights)):  # when all weights used start from left again
                i=0
            res += int(c) * weights[i]
            i += 1
        print(f"var:{variant} weights:{weights} input:{s} res:{res}")
        return res  % 11 == 0

    def validate_modulus11_new(self, s:str, variant) -> int:
        exp_len = self.definitions[variant]["len"]
        if not isinstance(s, str) or not s.isdigit():
            return False
        if exp_len > 0: 
            if len(s) != exp_len:
                return False
        excl_chk_dig = s[0:exp_len - 1]
        exp_chk_dig = int(s[exp_len-1:exp_len])
        chk_dig = self.calc_modulus11_chkdigit(excl_chk_dig, variant)
        return chk_dig == exp_chk_dig
    
    def calc_modulus10(self, s:str):
        
        res = 0
        reverse_digits = s[::-1]
        for i, d in enumerate(reverse_digits):
            n = int(d)
            if i % 2 == 0:  # every second digit from the right (original number)
                n *= 2
                if n > 9:
                    n -= 9
            res += n

        chk_dig = 10 - (res % 10)
        if chk_dig == 10:
            return 0
        else:
            return chk_dig
    
    def validate_modulus10(self, s:str, variant) -> int:
        exp_len = self.definitions[variant]["len"]
        if not isinstance(s, str) or not s.isdigit():
            return False
        if exp_len > 0: 
            if len(s) != exp_len:
                return False
        chk_dig=s[exp_len-1:exp_len]
        excl_chk_dig= s[0:exp_len - 1] 
        res = self.calc_modulus10(excl_chk_dig)
        return res == int(chk_dig)


    def validate_fn(self, s, variant):
        # simplified validation of austrian number 1..6 digits followed by a character (lowercase)
        max_len = self.definitions[variant]["len"]
        if not isinstance(s, str) or len(s) > max_len:
            return False
        chk_char=s[len(s)-1:len(s)]
        digits= s[0:len(s) - 1] 
        if not digits.isdigit() or len(digits) > 6:
            return False
        if chk_char < 'a' or chk_char > 'z':
            return False
        return True        
  
    def calc_chk_digit(self, s, variant):
        return self.calc_modulus11_chkdigit(s, variant)

    def validate_che(self, s, variant):
        s=s.replace('.','') # ignore dot's ...
        che = s[0:4]
        if che !=  'CHE-':  # must start with CHE-
            return False
        digits = s[4:len(s)] # take position after CHE- and to end of string and do a modulus 11
        return self.validate_modulus11(digits, variant)

    def validate_ly(self, s, variant):    # Finnish Ly-number can be missing a leading 0 and we ignore hyphens
        digits=s.replace('-','') # ignore hyphens ...
        if len(digits) == 7:     # don't think it can be shorter than 7 digits who should have one zero added first
            digits = digits.zfill(8)
        return self.validate_modulus11_new(digits, variant)
        
    def validate(self, s, variant):
        algo = self.definitions[variant]["algorithm"]
        if algo == 'mod11':
            return self.validate_modulus11(s, variant)
        if algo == 'mod10':
            return self.validate_modulus10(s, variant)
        if algo == 'fn':
            return self.validate_fn(s, variant)
        if algo == 'che':
            return self.validate_che(s, variant)
        if algo == 'ly':
            return self.validate_ly(s, variant)
        
        print("wrong algo")
        return False          
        


if __name__=="__main__":
    r='validate'
    m_obj = modulus()
    r = m_obj.validate('123456785', 'nororg') # Offical example
    r = m_obj.validate('974760673', 'nororg') # Brönnoy sund 
    
#    r = m_obj.validate('2070742-1', 'ly') # Wärtsila  does not work 
    
#    r = m_obj.validate('1572860-0', 'ly') # test case from google ai. 
#    r = m_obj.validate('112038-9', 'ly')  # Nokia with a missing zero first

#    r = m_obj.validate('CHE-123.456.788', 'che') # Unicef 


#    r = m_obj.validate('784671695', 'siren') # Unicef 
#    r = m_obj.validate('005520135', 'siren') # starts with zero 
    

#    r = m_obj.validate('33282b', 'fn') # FN 72544g (Red Bull GmbH) FN 33282b (OMV Aktiengesellschaft)
#    r = m_obj.validate('123456k', 'fn') # example
#    r = m_obj.validate('56247t', 'fn') #  verfied red bull
#    r = m_obj.validate('180219d', 'fn') # verified ostrischer post

#    r = m_obj.validate('2021005489', 'sweorg')
#    r = m_obj.validate('9912346', 'swebg7')
#    r = m_obj.validate('55555551', 'swebg8')

    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--command", choices=['calculate', 'validate' ])
    parser.add_argument("-v", "--variant", choices=['standard', 'kvn',
                                                    'cpr', 'cvr' ])
    parser.add_argument("-i", "--input")
    args=parser.parse_args()
    r=-1
    m_obj = modulus()
    if args.command == 'calculate':
        r=m_obj.calc_chk_digit(args.input, args.variant)
    if args.command == 'validate':
        r=m_obj.validate(args.input, args.variant)

    print(r)
