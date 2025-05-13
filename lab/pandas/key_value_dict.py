import pandas as pd

#------------------------------------------------------------------------------------------
# https://sqlryan.com/2022/02/converting-two-column-dataframe-to-a-dictionary-in-python/
#------------------------------------------------------------------------------------------
def load_excel_to_dict(file_name):
    df =  pd.read_excel(file_name)
    return pd.Series(df.value.values,index=df.key).to_dict()


#--------------------------------
if __name__ == '__main__':
    dir_name = "/mnt/c/users/perni/OneDrive/Documents/PythonTest/lab"
    file_name = dir_name + "/" + "keys_and_values.xlsx"
    dict = load_excel_to_dict(file_name)
    print(dict)
    print("dict of k1:" + dict['k1'])
