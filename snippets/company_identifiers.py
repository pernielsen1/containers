""" company_identifiers: class validating company identifiers and VAT-id's primarily in Europe

    variations of check digit calculations stored in definitions.
    main access via validate_COMPANY_id and validate_VAT_ID
    for test convinience also exists in .bool variations.
    
"""

import argparse
import os
import json

class company_identifiers:
    def __init__(self):
        self.clean_table = str.maketrans('.-()',"    ")
        # load the Xjustiz - json and clean the keys
        module_path = os.path.dirname(os.path.abspath(__file__))
        with open(module_path + '/' + 'XJustiz.json') as json_file:
            temp = json.load(json_file)
        self.dict_xjustiz={}
        for key, item in temp.items():
            clean_key = self.clean_str(key)
            self.dict_xjustiz[clean_key] = item

        self.dict_xjustiz_to_name={}  # build dictionary to provide the correctly edited name
        for key, item in temp.items():
            self.dict_xjustiz_to_name[item] = '(' + key + ')'
            
        # TBD - comment in start 
        self.definitions = {
            "DK_COMPANY_ID": {"algorithm":self.validate_modulus11, "country":"DK", "name":"CVR" ,
                        "weights": [ 2, 7, 6, 5, 4, 3, 2, 1 ], "len":8},
            "NO_COMPANY_ID": {"algorithm":self.validate_modulus11, "country":"NO", "name":"Organisationsnummer", "len":9, 
                        "weights": [ 3, 2, 7, 6, 5, 4, 3, 2, 1 ]},
            "CH_COMPANY_ID": {"algorithm":self.validate_modulus11, "country":"CH", "name":"Che", "len":9,
                        "weights": [ 5, 4, 3, 2, 7, 6, 5, 4, 1 ],   "before_list": ['CHE']},
            "CH_VAT_ID": {"algorithm": self.validate_vat_std, "number_algorithm":self.validate_modulus11,
                          "country":"CH","name":"Che", "len":9, "weights": [ 5, 4, 3, 2, 7, 6, 5, 4, 1 ]},
            "FI_COMPANY_ID" : {"algorithm":self.validate_modulus11,"country":"FI", "name":"LY - business ID", "len":8,
                        "zfill_len":8,  "weights": [  7, 9, 10, 5, 8, 4, 2, 1 ]},
            "GR_COMPANY_ID" : {"algorithm":self.validate_modulus11,"country":"GR", "name":"AFM", "len": 9,
                        "weights": [  256, 128, 64, 32, 16, 8, 4, 2], "return_rest": True, "return_10":0},
            "RO_COMPANY_ID" : {"algorithm":self.validate_modulus11,"country":"RO", "name":"CUI/CIF", "len": 10,
                        "weights": [  7, 5, 3, 2, 1, 7, 5, 3, 2], "mult10": True, "zfill_len":10,
                         "return_rest": True, "return_10":0},
            "DE_COMPANY_ID": {"algorithm":self.validate_germany,"name":"Germany HRB, HRA etc", 
                              "country":"DE", "min_len":3, "len":6, 
                              "before_list": ['HRA', 'HRB', 'GnR', 'GsR', 'VR', 'PR'], 'after_allowed':True},
            "GB_COMPANY_ID": {"algorithm":self.validate_great_britain,"name":"UK SC, FC, etcc", 
                              "country":"GB", "min_len":6, "len":8, 
                              "before_list": ['SC', 'FC', '']},

            # TBD add modulus 89 ? 
            "DE_VAT_ID": {"algorithm":self.validate_vat_std, "number_algorithm":self.validate_just_numeric, "country":"DE", "name":"Germany VAT", "len":9},
            "NL_COMPANY_ID": {"algorithm":self.validate_just_numeric, "country":"NL", "name":"KVN",  "len":8},
            "ES_COMPANY_ID": {"algorithm":self.validate_modulus10, "country":"ES", "name":"Spanish NIF", "len":8, 
                        "before_list": ['A', 'B', 'C', 'F', 'G', 'N', 'W']},
            "ES_VAT_ID": {"algorithm":self.validate_vat_std, "number_algorithm":self.validate_modulus10, "country":"ES",
                          "name":"Spanish NIF", "len":8,
                        "before_list_TBD": ['ESA', 'ESB', 'ESC', 'ESF', 'ESG', 'ESN', 'ESW']}, 
            "PT_COMPANY_ID": {"algorithm":self.validate_modulus11, "country":"PT","name":"NIPC", "len":9, 
                        "weights": [ 9, 8, 7, 6, 5, 4, 3, 2]},
            "PT_VAT_ID": {"algorithm":self.validate_vat_std, "number_algorithm":self.validate_modulus11, 
                          "country":"PT", "name":"NIPC", "len":9, 
                        "weights": [ 9, 8, 7, 6, 5, 4, 3, 2]},
            "CZ_COMPANY_ID": {"algorithm":self.validate_modulus11, "country":"CZ", "name":"ICO", "len":8, 
                        "weights": [ 8, 7, 6, 5, 4, 3, 2], "check_digit_for_0":1},
            "LU_COMPANY_ID": {"algorithm":self.validate_just_numeric, "country":"LU", "name":"LU RCS", "min_len":4, "len":6, 
                        "before_list": ['B','']},
            "LV_COMPANY_ID": {"algorithm":self.validate_modulus11, "country":"LV", "name":"", "len":11, 
                        "weights": [ 1, 3, 9, 10, 5, 8, 4, 2, 1, 6], 'check_digit_for_1':1},
            "LT_COMPANY_ID": {"algorithm":self.validate_modulus11, "country":"LT", "name":"Legal identity code", "len":9, 
                        "weights": [  1, 2, 3, 4, 5, 6, 7, 8 ],  "weights_round2": [ 3, 4, 5, 6, 7, 8, 9, 1 ], 
                         "return_rest": True },
            "EE_COMPANY_ID": {"algorithm":self.validate_modulus11, "country":"EE", "name":"Legal identity code", "len":8, 
                        "weights": [  1, 2, 3, 4, 5, 6, 7 ],  "weights_round2": [ 3, 4, 5, 6, 7, 8, 9 ], 
                         "return_rest": True },
            "BG_COMPANY_ID": {"algorithm":self.validate_modulus11, "country":"BG","name":"UIC", "len":9, 
                        "weights": [  1, 2, 3, 4, 5, 6, 7, 8 ],  "weights_round2": [ 3, 4, 5, 6, 7, 8, 9, 10 ], 
                         "return_rest": True },
            "IT_COMPANY_ID": {"algorithm":self.validate_italy, "country":"IT","name":"Partita IVA", "len":11} ,
            "BE_COMPANY_ID": {"algorithm":self.validate_modulus97, "country":"BE","name":"Ondernemingsnummer", "len":10},
            "BE_VAT_ID": {"algorithm":self.validate_vat_std, "number_algorithm":self.validate_modulus97, 
                          "country":"BE", "name":"Ondernemingsnummer", "len":10},
            "SE_COMPANY_ID": {"algorithm":self.validate_modulus10, "country":"SE","name":"Organisationsnummer", "len":10,
                                "mask":"%s%s%s%s%s%s-%s%s%s%s"},    

            "FR_COMPANY_ID": {"algorithm":self.validate_modulus10, "country":"FR","name":"Siren", "len":9},
            "PL_COMPANY_ID": {"algorithm":self.validate_just_numeric, "country":"PL","name":"KRS", "len":10},
            "HU_COMPANY_ID": {"algorithm":self.validate_just_numeric, "country":"HU","name":"Adoszam", "len":10},
            "IE_COMPANY_ID": {"algorithm":self.validate_just_numeric, "country":"IE", "name":"CRO", "min_len": 3, "len":6 },
            "US_COMPANY_ID": {"algorithm":self.validate_just_numeric, "country":"UA","name":"EIN",  "len":9 },
            "US_VAT_ID": {"algorithm": self.validate_vat_std, "number_algorithm":self.validate_just_numeric, "country":"US","name":"EIN",  "len":9 },
            "MX_COMPANY_ID": {"algorithm":self.validate_mx, "country":"MX","name":"RFC",  "len":12},
            "AT_COMPANY_ID": {"algorithm":self.validate_fn,"country":"AT","name":"FN",  "min_len":1, "len":7,
                              "before_list":["FB", "FN", "ZVR", ""], 'after_allowed':True},
            "AT_VAT_ID": {"algorithm":self.validate_vat_std, "number_algorithm":self.validate_just_numeric, "country":"AT","name":"ATU",  
                          "len":8, "before_list":["ATU", ""]},

            "SE_BG": {"algorithm":self.validate_modulus10, "country":"SE","name":"Bankgiro", "min_len":7, "len":8},
            "DK_NATURAL": {"algorithm":self.validate_modulus11, "country":"DK","name":"CPR",
                        "weights": [ 4,3,2,7,6,5,4,3,2,1 ], "len":10}, 
            "standard":{"algorithm":self.validate_modulus11, "country":"","name":"standard", "len":0,
                        "weights": [7, 6, 5, 4, 3, 2, 1] }
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

    def calc_modulus11_remainder(self, s, weights, variant):
        i = 0
        res = 0
        for c in s:
            if (i==len(weights)):  # when all weights used start from left again
                i=0
            res += int(c) * weights[i]
            i += 1
        # some variations on what to return when rest is 0 and 1
        mult10=variant.get('mult10', False)
        if mult10:
            res = res * 10
        return  res % 11 

    def calc_modulus11_check_digit(self, s:str, variant) -> int:
        return_rest = variant.get('return_rest', False)
        rest = self.calc_modulus11_remainder(s, variant["weights"], variant)
        # special for the Latvia and estonian do two rounds... 
        if rest == 10:
            round2 = variant.get("weights_round2", None)
            if round2 != None:
                rest = self.calc_modulus11_remainder(s, round2, variant)
                if rest == 10:
                    return 0
            return_10 = variant.get("return_10", None)
            if return_10 != None:
                return return_10     
        if return_rest:
            return rest
        # some variations on what to return when rest is 0 and 1
        if rest == 0: 
            return variant.get('check_digit_for_0', 0)
        if rest == 1:
            return variant.get('check_digit_for_1', 0)
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

    def validate_italy(self, s:str, variant):
        result = self.get_before_number_after(s, variant)
        if result['validation_result'] == False:
            return result
        i=1
        res = 0
        for c in result['excl_chk_dig']:
            if i % 2 == 0:  # even
                x = int(c) * 2
                if x > 9:
                    x = x - 9
                res += x
            else:
                res += int(c)
            i += 1
        result['res'] = res
        result['check_digit'] = (10 - (res % 10)) % 10
        if (result['check_digit'] == result['expected']):
            return self.create_result_ok(result)
        else:
            return self.create_result_error('Wrong modulus 11 check digit', result)
        
    def validate_modulus97(self, s:str, variant):
        result = self.get_before_number_after(s, variant)
        if result['validation_result'] == False:
            return result
        result['first8'] = int(result['number'][0:8])  # first 8 digits - already validated a numeric string
        result['last2'] = int(result['number'][8:10])
        result['remainder'] = result['first8'] % 97
        result['mod97'] = 97 - result['remainder']
        result['validation_result'] = result['last2'] == result['mod97']
        return result
    
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
        after_allowed = variant.get('after_allowed', False)
        before_list = variant.get('before_list', None)
        max_len = variant.get('len', 0)  
        min_len = variant.get('min_len', -1)
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
        else:
            # still here all good create an edited name also
            result['edited_name'] = ( result['before'] + ' ' + result['number'] + ' ' +
                                     self.dict_xjustiz_to_name[result['XJustiz_code']] ) 
     
        return self.create_result_ok(result)

    def validate_great_britain(self, s, variant):
        result = self.get_before_number_after(s, variant)
        if result['validation_result'] == False:
            return result
        if (len(result['number']) == 6 and len(result['before']) == 2) or len(result['number']) == 8:
            return self.create_result_ok(result)
        else: # bad
            return self.create_result_error("GB wrong len")
        
        
    def validate_vat_std(self, s, variant):
        result = self.get_before_number_after(s, variant)
        result['var_cntry'] = variant['country']
        if (result['before'][0:2] != result['var_cntry']):
            return self.create_result_error('country code not valid', result)
        # now validate the number with company id variant
        number_algo = variant.get('number_algorithm', None)
        if number_algo == None:  # no further validation just the number in correct lenght from above
            return self.create_result_ok(result)
        else:
            return number_algo(result['number'], variant)        

    def validate_mx(self, s, variant):
        result={}
        if len(s) != 12:
            return self.create_result_error("wrong len must be 12")
        result['YYMMDD'] = s[3:9]    
        if result['YYMMDD'].isdigit() == False:
            return self.create_result_error("not numeric YYMMDD")   
        result['HOMOCLAVE'] = s[9:11]
        return self.create_result_ok(result)

    def validate(self, in_str, variant_name):
        variant = self.definitions.get(variant_name, None)
        if  variant == None:
            return {'validation_result':False, 'error':'Algorithm not found'}
        s = self.clean_str(in_str)
        zfill_len = variant.get('zfill_len', 0)
        if zfill_len > 0:
            s = s.zfill(zfill_len)
        return variant["algorithm"](s, variant)

    def validate_bool(self, s, variant_name) -> bool:
        res = self.validate(s, variant_name)
        return res['validation_result']

    def validate_COMPANY_ID(self, s, country_code):
        result =  self.validate(s, country_code + '_COMPANY_ID') 
        if result['validation_result']: 
            if result.get('edited_name', None) == None:
                variant = self.definitions[country_code + '_COMPANY_ID']
                mask = variant.get('mask', None)
                if mask == None:
                    result['edited_name'] = s
                else:
                    result['edited_name'] = mask % tuple(result['number'])

        return result            

    def validate_VAT_ID(self, s, country_code):
        variant = self.definitions.get(country_code + '_VAT_ID', None)
        if variant != None:
            return self.validate(s, country_code + '_VAT_ID')
        else:
            variant = self.definitions.get(country_code + '_COMPANY_ID', None)
            if variant == None:
                return self.create_result_error("VAT-ID no country algorithm available")

            result = self.get_before_number_after(s, variant)
            result['var_cntry'] = variant['country']
            if (result['before'][0:2] != result['var_cntry']):
                 return self.create_result_error('country code not valid', result)
            return variant['algorithm'](result['number'], variant)        


    def validate_COMPANY_ID_bool(self, s, country_code):
        return self.validate_bool(s, country_code + '_COMPANY_ID')

    def validate_VAT_ID_bool(self, s, country_code):
        result = self.validate_VAT_ID(s, country_code)
        return result['validation_result']

if __name__=="__main__":
    m_obj = company_identifiers()
#    r = m_obj.validate_VAT_ID_bool('NO123456785', 'NO')
    r = m_obj.validate_COMPANY_ID('HRB-1234 Aachen', 'DE')
    print(r)

#    r = m_obj.validate_COMPANY_ID('2021005489', 'SE')

#    r = m_obj.validate_COMPANY_ID('0001590082', 'RO')
#    r = m_obj.validate_COMPANY_ID('01590082', 'RO')

#     r = m_obj.validate_COMPANY_ID('094014298', 'GR')
#   r = m_obj.validate_COMPANY_ID('12870491-2-41', 'HU')  
#   r = m_obj.validate_VAT_ID('BG12870491-2-41', 'HU')  
#    r = m_obj.validate_COMPANY_ID('ABC680524P76', 'MX')
#    r = m_obj.validate_COMPANY_ID('131468980', 'BG') # 
#    r = m_obj.validate_COMPANY_ID('111111118', 'LT') # 
#    r = m_obj.validate_COMPANY_ID('10345833', 'EE') # 
#    r = m_obj.validate_COMPANY_ID('200000017', 'LT') # 


#    r = m_obj.validate_COMPANY_ID('20000001', 'LT') # 
#    r = m_obj.validate_COMPANY_ID('188659752', 'LT') # 
#    r = m_obj.validate_COMPANY_ID('300060819', 'LT') # 
# 188659752
# 300060819
    print(r)
#   r = m_obj.validate_VAT_ID('ATU12345678', 'AT') # 
#    r = m_obj.validate_COMPANY_ID('40003032949', 'LV') # Offical example
#    r = m_obj.validate_VAT_ID('BE0403.019.261', 'BE')
#    r = m_obj.validate_VAT_ID('IT01533030480', 'IT')
#    r = m_obj.validate_VAT_ID('ESA28123453', 'ES') # Offical example

#    r = m_obj.validate_COMPANY_ID('01533030480', 'IT')
    
#    r = m_obj.validate_COMPANY_ID('19871234569', 'LU') 
#    r = m_obj.validate_COMPANY_ID('25596641', 'CZ')
#    r = m_obj.validate_COMPANY_ID('0403.019.261', 'BE')
#    r = m_obj.validate_COMPANY_ID_bool('A28123453', 'ES') # Offical example
#    r = m_obj.validate_COMPANY_ID_bool('1234567890', 'PL') # Offical example
#    r = m_obj.validate_germany(m_obj.clean_str('HRB-1234 Aachen'), 'DE_COMPANY_ID') # Offical example
#    x = m_obj.clean_str('Bad Homburg v.d.H.')
#    print(x)
#    print(m_obj.dict_xjustiz[x])
#    print(m_obj.dict_xjustiz['Aachen'])
#    print(r)
#    r = m_obj.validate_COMPANY_ID_bool('123456785', 'NO') # Offical example
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
    m_obj = company_identifiers()
    if args.command == 'calculate':
        r=m_obj.calc_chk_digit(args.input, args.variant)
    if args.command == 'validate':
        r=m_obj.validate(args.input, args.variant)
