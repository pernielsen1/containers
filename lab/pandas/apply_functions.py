import pandas as pd

def add_two_columns(row):
    result = [row['x'] * 2, row['y']*3]
    return result

def add_dict(row):
    res={}
    res['a'] = 2 * row['x']
    res['b'] = 7 * row['x']
    return pd.Series(res)

def do_it():
    df = pd.DataFrame({"x": [1,2,3],"y":[5,6,7]})
    print(df)
    df[['z', 'w']] = df.apply(add_two_columns, axis=1, result_type='expand')
    print(df)
    df[['xx', 'xxx']] = df.apply(add_dict, axis=1, result_type='expand')
    print(df)


#--------------------------------
if __name__ == '__main__':
    do_it()
    