import argparse
import os
import json
# https://github.com/hubipe/company-identifiers/tree/master/src/CountryValidators
class modulus:
    def __init__(self):
        self.clean_table = str.maketrans('.-',"  ")
        # load the Xjustiz - json and clean the keys
        module_path = os.path.dirname(os.path.abspath(__file__))
        with open(module_path + '/' + 'XJustiz.json') as json_file:
            temp = json.load(json_file)
        self.dict_xjustiz={}
        for key, item in temp.items():
            clean_key = self.clean_str(key)
            self.dict_xjustiz[clean_key] = item
        # the variants of calculations input dictionary
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
            "CH_COMPANY_ID": {"algorithm":self.validate_modulus11,"name":"Che",
                    "weights": [ 5, 4, 3, 2, 7, 6, 5, 4, 1 ],  "len":9, "before_list": ['CHE']},
            "FI_COMPANY_ID" : {"algorithm":self.validate_ly,"name":"LY - business ID",
                "weights": [  7, 9, 10, 5, 8, 4, 2, 1 ], "len":8},
            "AT_COMPANY_ID": {"algorithm":self.validate_fn,"name":"FN",
                "weights": None, "min_len":1, "len":7, 'after_allowed':True},
            "DE_COMPANY_ID": {"algorithm":self.validate_germany,"name":"Germany HRB, HRA etc",
               "weights": None, "min_len":3, "len":6, "before_list": ['HRA', 'HRB'], 'after_allowed':True},
            "NL_COMPANY_ID": {"algorithm":self.validate_modulus11, "name":"KVN",
                    "weights": [8, 7, 6, 5, 4, 3, 2, 1], "len":8},
            "PL_COMPANY_ID": {"algorithm":self.validate_just_numeric, "name":"KRS",
                     "len":10},
            "IE_COMPANY_ID": {"algorithm":self.validate_just_numeric, "name":"CRO",
                     "min_len": 3, "len":6 },

            "ES_COMPANY_ID": {"algorithm":self.validate_modulus10,"name":"Spanish NIF",
               "weights": None, "len":8, "before_list": ['A', 'B', 'C', 'F', 'G', 'N', 'W']},


            "PT_COMPANY_ID": {"algorithm":self.validate_modulus11, "name":"NIPC",
                    "weights": [ 9, 8, 7, 6, 5, 4, 3, 2], "len":9},
      
            "SE_BG7": {"algorithm":self.validate_modulus10,"name":"Bankgiro 7 digits",
                    "weights": None, "len":7},    
            "SE_BG8": {"algorithm":self.validate_modulus10, "name":"Bankgiro 8 digits",
                    "weights": None, "len":8},
            "standard":{"algorithm":self.validate_modulus11, "name":"standard",
                        "weights": [7, 6, 5, 4, 3, 2, 1], "len":0}
        }
        return

    def clean_str(self,s:str) -> str:
        s = s.translate(self.clean_table)
        return  s.replace(' ','')

    def create_result_error(self, error:str, result={}):
        result['validation_result'] = False
        result['error'] = error
        return result

    def create_result_ok(self, result={}):
        result['validation_result'] = True
        return result

    def calc_modulus11_check_digit(self, s:str, variant) -> int:
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
        if rest == 0 or rest == 1:
            return 0
        else: 
            return 11 - rest
    
    def calc_modulus10_check_digit(self, s:str, variant=None) -> int:
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

    def validate_modulus(self, s:str, variant, calc_function):
        result = self.get_before_number_after(s, variant)
        if result['validation_result'] == False:
            return result
        result['check_digit'] = calc_function(result['excl_chk_dig'], variant)
        if (result['check_digit'] == result['expected']):
            return self.create_result_ok(result)
        else:
            return self.create_result_error('Wrong modulus 11 check digit', result)
         
    def validate_modulus11(self, s:str, variant):
        return self.validate_modulus(s, variant, self.calc_modulus11_check_digit)
    
    def validate_modulus10(self, s:str, variant):
        return self.validate_modulus(s, variant, self.calc_modulus10_check_digit)

    def validate_just_numeric(self, s:str, variant):
        return self.get_before_number_after(s, variant)


    def validate_fn(self, s, variant):
        # simplified validation of austrian number 1..6 digits followed by a character (lowercase)
        result = self.get_before_number_after(s, variant)
        if result['validation_result'] == False:
            return result
        if len(result['after']) != 1 or result['after'] < 'a' or result['after'] > 'z':
            return self.create_result_error('check char not between a and z', result)
        # still her all good
        return self.create_result_ok(result)
    
    def get_before_number_after(self, s, variant):
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
        # Validations - initially set to all good
        after_allowed = self.definitions[variant].get('after_allowed', False)
        before_list = self.definitions[variant].get('before_list', None)
        max_len = self.definitions[variant].get('len', 0)  
        min_len = self.definitions[variant].get('min_len', -1)
        if len(result['number']) != max_len and  min_len == -1:
            return self.create_result_error('Length of number does not match fixed number', result)
        if len(result['number']) > max_len or len(result['number']) < min_len:
            return self.create_result_error('Length of number not between min and max', result)
        if before_list == None and len(result['before']) > 0:
            return self.create_result_error('Length of before > 0 and empty before_list', result)
        if before_list != None and result['before'] not in before_list:
            return self.create_result_error('The before string is not in allowed before_list', result)
        if len(result['after']) > 0 and after_allowed == False:
            return self.create_result_error('The after string is not empty', result)
        # still ehre all good
        num_len = len(result['number'])
        result['excl_chk_dig']= result['number'][0:num_len  - 1] 
        result['expected'] = int(result['number'][num_len-1:num_len])
        return self.create_result_ok(result)

    def validate_germany(self, s, variant):
        result = self.get_before_number_after(s, variant)
        if result['validation_result'] == False:
            return result
        result['XJustiz_code'] = self.dict_xjustiz.get(result['after'], None)
        if result['XJustiz_code'] == None:
            return self.create_result_error("Invalid XJustis code", result)
        # still here all good 
        return self.create_result_ok(result)
        

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
        return self.validate(s, country_code + '_' + 'COMPANY_ID')

if __name__=="__main__":
    m_obj = modulus()
    r = m_obj.validate_COMPANY_ID('A28123453', 'ES') # Offical example

#    r = m_obj.validate_COMPANY_ID('1234567890', 'PL') # Offical example
    print(r)
    r = m_obj.validate_germany(m_obj.clean_str('HRB-1234 Aachen'), 'DE_COMPANY_ID') # Offical example
    x = m_obj.clean_str('Bad Homburg v.d.H.')
    print(x)
    print(m_obj.dict_xjustiz[x])
    print(m_obj.dict_xjustiz['Aachen'])
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
    parser.add_argument("-v", "--variant", choices=['standard', 'kvn',                                                    'cpr', 'cvr' ])
    parser.add_argument("-i", "--input")
    args=parser.parse_args()
    r=-1
    m_obj = modulus()
    if args.command == 'calculate':
        r=m_obj.calc_chk_digit(args.input, args.variant)
    if args.command == 'validate':
        r=m_obj.validate(args.input, args.variant)
