import os
import json
import xlsxwriter
import pandas as pd
# dir_name = "/mnt/c/users/perni/OneDrive/Documents/Häggeboda/gl"

class accounting():
    def __init__(self, config_file="config.json"):
        with open(config_file, 'r') as f:
            self.config = json.load(f)


    def run(self):
        file_name = self.config['dir'] + "/" + "gl.xlsx"
        postings =  pd.read_excel(file_name, sheet_name="posteringer")
        print(postings)
        accounts =  pd.read_excel(file_name, sheet_name="konti")
        print(accounts)
        post_enriched = postings.merge(accounts, how='left', left_on='konto', right_on='konto',
                                    indicator=True)
        post_enriched  =post_enriched.sort_values(by=['konto', 'dato'])
        print(post_enriched)
    
    # self.to_excel(post_enriched)
    def to_excel(self, df):
        output_file = self.config['dir'] + "/" + "gl_output.xlsx"
        wb = xlsxwriter.Workbook(output_file)
        ws = wb.add_worksheet()
        
        headings = df.columns.tolist()
        col = 0
        for item in headings:
            ws.write(0, col, item)
            col += 1
        r = 0
        for index, row in df.iterrows():
            col = 0
            r += 1
            ws.write(r, 0,   row['konto'])
            ws.write(r, 1, row['belopp'])

        wb.close()


if __name__ == '__main__':
    accounting_obj = accounting("config.json")
    accounting_obj.run()
    