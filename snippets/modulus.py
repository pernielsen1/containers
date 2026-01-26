import argparse

class modulus:
    definitions = {
        "standard":{"algorithm":"mod11", "weights": [7, 6, 5, 4, 3, 2, 1], "len":0},
        "cpr": {"algorithm":"mod11","weights": [ 4,3,2,7,6,5,4,3,2,1 ], "len":10}     ,
        "cvr": {"algorithm":"mod11","weights": [ 2, 7, 6, 5, 4, 3, 2, 1 ], "len":8},
        "sweorg": {"algorithm":"mod10","weights": None, "len":10},
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

    def validate_modulus10(self, s:str, variant) -> int:
        print("modulu10")
        exp_len = self.definitions[variant]["len"]
        if not isinstance(s, str) or not s.isdigit():
            return False
        if exp_len > 0: 
            if len(s) != exp_len:
                return False
        res = 0
        reverse_digits = s[::-1]
        for i, d in enumerate(reverse_digits):
            n = int(d)
            if i % 2 == 1:  # every second digit from the right (original number)
                n *= 2
                if n > 9:
                    n -= 9
            res += n
        print(f"mod10 var:{variant} input:{s} res:{res}")

        return res % 10 == 0



    def calc_chk_digit(self, s, variant):
        return self.calc_modulus11_chkdigit(s, variant)

    def validate(self, s, variant):
        algo = self.definitions[variant]["algorithm"]
        if algo == 'mod11':
            return self.validate_modulus11(s, variant)
        if algo == 'mod10':
            return self.validate_modulus10(s, variant)
        print("wrong algo")
        return False          
        


if __name__=="__main__":
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
