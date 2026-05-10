import pandas as pd
import json
import os
module_path = os.path.dirname(os.path.abspath(__file__))
df =  pd.read_excel(module_path + '/' + 'XJustiz.xlsx')
# df['key'] = df.apply(self.clean_key, axis=1)  # remove the ( and . etc)
dict_xjustiz = pd.Series(df.value.values,index=df.key).to_dict()
with open(module_path + '/' + 'XJustiz.json', 'w') as f:
    json.dump(dict_xjustiz, f)
print(dict_xjustiz)
