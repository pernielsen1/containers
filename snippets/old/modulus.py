import argparse
import os
# https://github.com/hubipe/company-identifiers/tree/master/src/CountryValidators
import pandas as pd
class modulus:
    def __init__(self):
        self.clean_table = str.maketrans('.-',"  ")
        module_path = os.path.dirname(os.path.abspath(__file__))
        df =  pd.read_excel(module_path + '/' + 'XJustiz.xlsx')
        df['key'] = df.apply(self.clean_key, axis=1)  # remove the ( and . etc)
        self.dict_xjustiz = pd.Series(df.value.values,index=df.key).to_dict()
#        print(dict_xjustiz['Aachen'])
        self.definitions = {
            "DK_NATURAL": {"algorithm":self.validate_modulus11, "name":"CPR",
                        "weights": [ 4,3,2,7,6,5,4,3,2,1 ], "len":10}     ,
            "DK_COMPANY_ID": {"algorithm":self.validate_modulus11, "name":"CVR",
                        "weights": [ 2, 7, 6, 5, 4, 3, 2, 1 ], "len":8},
            "SE_COMPANY_ID": {"algorithm":self.validate_modulus10, "name":"Organisationsnummer",
                        "weights": None, "len":10},
            "NO_COMPANY_ID": {"algorithm":self.validate_modulus11,"name":"Organisationsnummer",
                        "weights": [ 3, 2, 7, 6, 5, 4, 3, 2, 1 ], "len":9},
            "FR_COMPANY_ID": {"algorithm":self.validate_modulus10,"name":"Siren", 
                    "weights": None, "len":9},
            "CH_COMPANY_ID": {"algorithm":self.validate_che,"name":"Che",
                    "weights": [ 5, 4, 3, 2, 7, 6, 5, 4, 1 ], "len":9},
            "FI_COMPANY_ID" : {"algorithm":self.validate_ly,"name":"LY - business ID",
                "weights": [  7, 9, 10, 5, 8, 4, 2, 1 ], "len":8},
            "AT_COMPANY_ID": {"algorithm":self.validate_fn,"name":"FN",
                "weights": None, "len":7},
            "DE_COMPANY_ID": {"algorithm":self.validate_germany,"name":"Germany HRB, HRA etc",
               "weights": None, "len":0},
            "NL_COMPANY_ID": {"algorithm":self.validate_modulus11, "name":"KVN",
                    "weights": [8, 7, 6, 5, 4, 3, 2, 1], "len":8},
            "SE_BG7": {"algorithm":self.validate_modulus10,"name":"Bankgiro 7 digits",
                    "weights": None, "len":7},    
            "SE_BG8": {"algorithm":self.validate_modulus10, "name":"Bankgiro 8 digits",
                    "weights": None, "len":8},
            "standard":{"algorithm":self.validate_modulus11, "name":"standard",
                        "weights": [7, 6, 5, 4, 3, 2, 1], "len":0}
        }
        return
    def clean_key(self, row) -> str:
        return self.clean_str(row['key'])
    
    def clean_str(self,s:str) -> str:
        s = s.translate(self.clean_table)
        return  s.replace(' ','')

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

    def validate_modulus11(self, s:str, variant):
        result = {}
        exp_len = self.definitions[variant]["len"]
        if not isinstance(s, str) or not s.isdigit():
            return {'validation_result':False, 'error':'not string or digits'}
        if exp_len > 0 and len(s) != exp_len:
            return {'validation_result':False, 'error':'wrong length'}
        result['excl_chk_dig'] = s[0:exp_len - 1]
        result['expected'] = int(s[exp_len-1:exp_len])
        result['check_digit'] = self.calc_modulus11_chkdigit(result['excl_chk_dig'], variant)
        if (result['check_digit'] == result['expected']):
            result['validation_result'] = True
        else:
            result['validation_result'] = False
            result['error'] = 'Wrong modulus 11 check digit'
   
        return result 
    
    def calc_modulus10(self, s:str) -> int:
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
    
    def validate_modulus10(self, s:str, variant):
        exp_len = self.definitions[variant]["len"]
        if not isinstance(s, str) or not s.isdigit():
            return {'validation_result':False, 'error':'not string or digits'}
        if exp_len > 0 and len(s) != exp_len:
            return {'validation_result':False, 'error':'wrong length'}
        result = {}
        result['excl_chk_dig']= s[0:exp_len - 1] 
        result['expected'] = int(s[exp_len-1:exp_len])
#        res = self.calc_modulus10(result['excl_chk_dig'])
        result['check_digit'] = self.calc_modulus10(result['excl_chk_dig'])
        if (result['check_digit'] == result['expected']):
            result['validation_result'] = True
        else:
            result['validation_result'] = False
            result['error'] = 'Wrong modulus 11 check digit'

        return result

    def validate_fn(self, s, variant):
        # simplified validation of austrian number 1..6 digits followed by a character (lowercase)
        max_len = self.definitions[variant]["len"]
        if not isinstance(s, str) or len(s) > max_len:
            return {'validation_result':False, 'error':'wrong len'}
        chk_char=s[len(s)-1:len(s)]
        digits= s[0:len(s) - 1] 
        if not digits.isdigit() or len(digits) > 6:
            return {'validation_result':False, 'error':'not string or digits'}
        if chk_char < 'a' or chk_char > 'z':
            return {'validation_result':False, 'error':'check char not between a and z'}
        
        return {'validation_result':True}
        
  
    def calc_chk_digit(self, s, variant):
        return self.calc_modulus11_chkdigit(s, variant)

    def validate_che(self, s, variant):  # dot's and hyphens removed before call
        if s[0:3] !=  'CHE':  # must start with CHE
            return {'validation_result':False, 'error':'Does not start with CHE'}

        digits = s[3:len(s)] # take position after CHE and to end of string and do a modulus 11
        return self.validate_modulus11(digits, variant)

    def get_before_number_after(self, s):
        result={'before':'', 'number':'', 'after':''}
        i=0
        while i<len(s) and s[i].isdigit() == False:
            result['before'] += s[i]
            i += 1
        while i<len(s) and s[i].isdigit() == True:
            result['number'] += s[i]
            i += 1
        while i<len(s):
            result['after'] += s[i]
            i += 1
        return result

    def validate_germany(self, s, variant):
        result = self.get_before_number_after(s)
        if result['before'] not in ['HRB', 'HRA']:
            return {'validation_result':False, 'error':'Does not start with HRB, HRA'}
        if not result['number'].isdigit():
            return {'validation_result':False, 'error':'The number is not digits'}
        result['XJustiz_code'] = self.dict_xjustiz.get(result['after'], None)
        if result['XJustiz_code'] == None:
            result['validation_result'] = False
            result['error']  = "Invalid XJustis code"
        # still here all good 
        result['validation_result'] = True
        return result
        
    def validate_germany_old(self, s, variant):
        result = {}
        result['type'] = s[0:3]
        if result['type'] not in ['HRB', 'HRA']:
            return {'validation_result':False, 'error':'Does not start with HRB, HRA'}
        result['number'] =  ""
        i = 3
        while s[i].isdigit():
            result['number'] += s[i]
            i += 1  
        result['court_name'] = ""
        while i<len(s):
            result['court_name'] += s[i]
            i += 1
        # find the XJustis if it is there
        result['XJustiz_code'] = self.dict_xjustiz.get(result['court_name'], None)
        # optimistic
        if not result['number'].isdigit():
            return {'validation_result':False, 'error':'The number is not digits'}
        if len(result['number']) < 1 or len(result['number']) > 5:
            return {'validation_result':False, 'error':'The number is not digits'}
        if result['XJustiz_code'] == None:
            result['validation_result'] = False
            result['error']  = "Invalid XJustis code"
        
        # still here all good 
        result['validation_result'] = True
        return result

    def validate_ly(self, s, variant):    # Finnish Ly-number can be missing a leading 0 and we ignore hyphens
        if len(s) == 7:     # don't think it can be shorter than 7 digits who should have one zero added first
            s = s.zfill(8)
        return self.validate_modulus11(s, variant)
        
    def validate(self, s, variant):
        s = self.clean_str(s)         # clean up the string
        if  self.definitions.get(variant, None) == None:
            return {'validation_result':False, 'error':'Algorithm not found'}
        algo = self.definitions[variant]["algorithm"]
        res = algo(s, variant)
        return res['validation_result']

    def validate_COMPANY_ID(self, s, country_code):
        return self.validate(s, country_code + '_' + 'LEGAL')

if __name__=="__main__":
    r='validate'
    m_obj = modulus()
    r = m_obj.validate_germany(m_obj.clean_str('HRB-1234 Aachen'), 'DE_COMPANY_ID') # Offical example
    print("Here we go")
    print(r)
#    r = m_obj.validate_COMPANY_ID('123456785', 'NO') # Offical example
#    r = m_obj.validate('974760673', 'NO_COMPANY_ID') # Brönnoy sund 
    
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
