import argparse
definitions = {
    "standard":{"weights": [7, 6, 5, 4, 3, 2, 1], "len":0},
    "cpr": {"weights": [ 4,3,2,7,6,5,4,3,2,1 ], "len":10}     ,
    "cvr": {"weights": [ 2, 7, 6, 5, 4, 3, 2 ], "len":8},   
    "kvn": {"weights": [8, 7, 6, 5, 4, 3, 2, 1], "len":8}
}

def calc_modulus11_chkdigit(s:str, variant) -> int:
    weights = definitions[variant]["weights"]
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

def validate_modulus11(s:str, variant) -> int:
    weights = definitions[variant]["weights"]
    exp_len = definitions[variant]["len"]
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

    return res  % 11 == 0

def calc_chk_digit(s, variant):
    return calc_modulus11_chkdigit(s, variant)

def validate(s, variant):
    return validate_modulus11(s, variant)


if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--command", choices=['calculate', 'validate' ])
    parser.add_argument("-v", "--variant", choices=['standard', 'kvn',
                                                    'cpr', 'cvr' ])
    parser.add_argument("-i", "--input")
    args=parser.parse_args()
    r=-1
    if args.command == 'calculate':
        r=calc_chk_digit(args.input, args.variant)
    if args.command == 'validate':
        r=validate_modulus11(args.input, args.variant)

    print(r)
