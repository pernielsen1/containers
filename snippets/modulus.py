import argparse
# https://github.com/hubipe/company-identifiers/tree/master/src/CountryValidators
class modulus:
    definitions = {
        "standard":{"algorithm":"mod11", "weights": [7, 6, 5, 4, 3, 2, 1], "len":0},
        "cpr": {"algorithm":"mod11","weights": [ 4,3,2,7,6,5,4,3,2,1 ], "len":10}     ,
        "cvr": {"algorithm":"mod11","weights": [ 2, 7, 6, 5, 4, 3, 2, 1 ], "len":8},
        "sweorg": {"algorithm":"mod10","weights": None, "len":10},
        "fn": {"algorithm":"fn","weights": None, "len":7},

        "swebg7": {"algorithm":"mod10","weights": None, "len":7},    
        "swebg8": {"algorithm":"mod10","weights": None, "len":8},

        "kvn": {"algorithm":"mod11","weights": [8, 7, 6, 5, 4, 3, 2, 1], "len":8}
    }
    def __init__(self):
        # TBD
        return
    def calculate_fn_check_char(self, digits:str):
        """
        Calculates the check letter for an Austrian Firmenbuchnummer (FN).
        :param digits: The numeric part of the FN (up to 6 digits) as an integer or string.
        :return: The correct check letter (lowercase).
        """
        # Mapping for Modulus 17 (reminders 0 through 16)
        # Note: Letters C, E, J, N, O, Q, R, U, Z are excluded to avoid confusion.
#        ALPHABET = "abdfghiklmpstvwxy"
        ALPHABET = "abd fghiklmpstvwxy".replace(" ", "")
        ALPHABET = 'abdfghikmpstvwxyz'
        ALPHABET = "abcdeflghikmnpqrstvwxyz"
        ALPHABET = 'abcdefghijkmpqrst'
        ALPHABET = 'abcdefghijkmnpqrst'
        #           01234567890123456
        if not digits.isdigit() or len(digits) > 6:
            raise ValueError("FN digits must be a numeric string of up to 6 characters.")

        # Pad with leading zeros to ensure 6 digits for consistent weighting
        fn_padded = digits.zfill(6)
        
        # Weights applied from right to left: 2, 3, 4, 5, 6, 7
        weights = [7, 6, 5, 4, 3, 2]
#        weights = [6, 4, 14, 15, 10, 1]
        total_sum = 0
        for i in range(6):
            total_sum += int(fn_padded[i]) * weights[i]
        
        # Calculate remainder Modulo 17
        remainder = total_sum % 17
        return ALPHABET[remainder]

    def validate_fn(self, s:str, variant) -> int:
        max_len = self.definitions[variant]["len"]
        if not isinstance(s, str) or len(s) > max_len:
            return False
        chk_char=s[len(s)-1:len(s)]
        excl_chk_char= s[0:len(s) - 1] 
        res = self.calculate_fn_check_char(excl_chk_char)
        return chk_char == res

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



    def calc_chk_digit(self, s, variant):
        return self.calc_modulus11_chkdigit(s, variant)

    def validate(self, s, variant):
        algo = self.definitions[variant]["algorithm"]
        if algo == 'mod11':
            return self.validate_modulus11(s, variant)
        if algo == 'mod10':
            return self.validate_modulus10(s, variant)
        if algo == 'fn':
            return self.validate_fn(s, variant)
        print("wrong algo")
        return False          
        


if __name__=="__main__":
    r='validate'
    m_obj = modulus()
#    r = m_obj.validate('33282b', 'fn') # FN 72544g (Red Bull GmbH) FN 33282b (OMV Aktiengesellschaft)
    r = m_obj.validate('72544g', 'fn') # FN 72544g (Red Bull GmbH) FN 33282b (OMV Aktiengesellschaft)

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
