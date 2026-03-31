import pandas as pd

def do_it():
    df1 = pd.DataFrame({'k': ['k1','k2','k3'], 'desc':['text1', 'text2', 'text3']})
    df2 = pd.DataFrame({'k2': ['k1','k3','k4'], 'desc':['text2_1', 'text2_3', 'text2_4']})
    df_res = df1.merge(df2, how = 'left', left_on = 'k', right_on = 'k2',
                       suffixes = ('_a', '_b'), indicator = 'merge_res'
            )
    print(df_res)
    # those two columns which can be NaN we set to a default value
    columns = ['k2', 'desc_b'] 
    df_res[columns] = df_res[columns].fillna('_')   
    print(df_res)
    # merge and select only some columns and discard the index in one go
    df_res = df1.merge(df2, how = 'left', left_on = 'k', right_on = 'k2',
                       suffixes = ('_a', '_b'), indicator = 'merge_res'
    )[['k', 'desc_b']]     
    print(df_res)
#--------------------------------
if __name__ == '__main__':
    do_it()
    