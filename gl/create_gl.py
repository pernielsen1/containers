import os
import json
from openpyxl import workbook
from openpyxl import load_workbook
import xlsxwriter
import pandas as pd
from datetime import datetime
# dir_name = "/mnt/c/users/perni/OneDrive/Documents/Häggeboda/gl"

class accounting():
    def __init__(self, config_file="config.json"):
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        self.output_file = self.config['out_dir'] + "/" + "gl_output.xlsx"

        self.wb = load_workbook(filename=self.output_file)
        self.file_name = self.config['in_dir'] + "/" + "gl.xlsx"
        self.reports = pd.read_excel(self.file_name, sheet_name="rapporter")
        self.reports = self.reports.rename(columns={'beskrivning':'rapport_beskrivning'})


    def run(self):
        accounts =  pd.read_excel(self.file_name, sheet_name="konti")
        accounts =  accounts[['konto', 'beskrivning', 'konto_typ']]  # don't take the formula fields 
        accounts =  accounts.rename(columns={'beskrivning':'konto_beskrivning'})

        account_types =  pd.read_excel(self.file_name, sheet_name="konto_typer")
        account_types = account_types[['konto_typ', 'beskrivning', 'klass']] # don't take the formula fields
        account_types = account_types.rename(columns={'beskrivning':'konto_typ_beskrivning'})

        accounts = accounts.merge(account_types, how='inner', 
                    left_on='konto_typ', right_on='konto_typ', indicator=False)
        classes = pd.read_excel(self.file_name, sheet_name="klasser")
        classes = classes[['klass', 'beskrivning', 'rapport_id']]
        classes = classes.rename(columns={'beskrivning':'klass_beskrivning'})
       
        accounts = accounts.merge(classes, how='inner', 
                    left_on='klass', right_on='klass', indicator=False)
       
        accounts = accounts.merge(self.reports, how='inner', 
                    left_on='rapport_id', right_on='rapport_id', indicator=False)
       
        postings_all =  pd.read_excel(self.file_name, sheet_name="posteringer")
        postings_open = postings_all.query('ver_nr == 0') # opening balances
        postings = postings_all.query('ver_nr != 0')  # this year
        # create opening balance per account    
        account_open_balance = postings_open.groupby(by=['konto']).agg(
            opening_balance = ('belopp', 'sum'),
        )
        # movement opening balance per account    
        account_movements = postings.groupby(by=['konto']).agg(
            movement = ('belopp', 'sum'),
        )
        # outer join not all accounts will have open balance or movements
        balances = account_open_balance.merge(account_movements, how='outer', 
                                                   left_on='konto', right_on='konto', 
                                                   indicator=True)
        balances= balances.fillna({'opening_balance':0,'movement':0})
        balances['closing_balance'] = balances['opening_balance'] + balances['movement']
#        balances = balances.query('konto < 2999')
        # remove those who have 0 in all... !2
        # balances = balances.query('(opening_balance != 0) | (movement != 0) | (closing_balance !=0)')
        # add the account description
        balances = balances[['opening_balance', 'movement', 'closing_balance']]
        balances = accounts.merge(balances, how="left", 
                                            left_on='konto', right_on='konto', 
                                            indicator = True) 
        balances = balances.fillna({'opening_balance':0,'movement':0, 'closing_balance':0})      
        balances = balances.sort_values(['klass', 'konto_typ', 'konto'])
        balances = balances[['rapport_id', 'rapport_beskrivning', 'sheet_name',
                                        'klass', 'klass_beskrivning', 
                                       'konto_typ', 'konto_typ_beskrivning',
                                       'konto', 'konto_beskrivning',
                                       'opening_balance', 'movement', 'closing_balance'
     
                            ]]
        self.balance_report_to_excel(balances, 'BS')
        self.balance_report_to_excel(balances, 'RS')
        self.balance_report_to_excel(balances, 'ALL')  # balance list
        
        self.verifikation_to_excel(postings)
        self.wb.save(self.output_file)
        print("all done - workbook ready")
    
    # self.to_excel(post_enriched)
    # creates the "Balance sheet"
    def write_line(self, ws, r, text, konto=None, opening=None, movement=None):
        if konto is not None:
            ws.cell(row=r+1, column=1).value = konto
        ws.cell(row=r+1, column=2).value= text
        if (opening is not None):
            ws.cell(row=r+1, column=3).value= opening
            ws.cell(row=r+1, column=4).value = movement
            ws.cell(row=r+1, column=5).value = opening + movement
        return r+1

       
    def balance_report_to_excel(self, in_df, report_id):
        str_query = f'(rapport_id=="{report_id}")'
        this_report = self.reports.query(str_query).iloc[0]
        sheet_name  = this_report['sheet_name']

        if (report_id == 'ALL'): 
            df = in_df.copy(deep=True)
        else:
            df = in_df.query(str_query).copy(deep=True)
       
#        ws = self.wb.add_worksheet(sheet_name)
        ws = self.wb[sheet_name]
        headings = ["konto", "Text", "Ing balans", "Perioden", "Utg Balans" ]
        col = 1
        for item in headings:
            ws.cell(row=1, column=col).value=item
            col += 1
        self.write_dashes(ws, 1, len(headings), '=')

        r = 2
        prv_klass = 0     
        cur_klass_beskrivning = ''
        tot_klass_opening = 0
        tot_klass_movement = 0

        prv_konto_typ = 0
        cur_konto_typ_beskrivning = ''
        tot_konto_typ_opening = 0
        tot_konto_typ_movement = 0 
        
        for index, row in df.iterrows():
            col = 0
            # write summaries if break
            if (row['konto_typ'] != prv_konto_typ):
                tot_klass_opening += tot_konto_typ_opening
                tot_klass_movement += tot_konto_typ_movement
                if (prv_konto_typ != 0):
                    if report_id != 'ALL':
                        r = self.write_line(ws, r, "S: A " + cur_konto_typ_beskrivning, None, 
                                        tot_konto_typ_opening, tot_konto_typ_movement)
                    tot_konto_typ_opening = 0
                    tot_konto_typ_movement = 0

            if (row['klass'] != prv_klass):
                if (prv_klass != 0):  # write klass summary 
                    r = self.write_line(ws, r, "S: A " + cur_klass_beskrivning, None,
                                     tot_klass_opening, tot_klass_movement)
                    tot_klass_opening = 0
                    tot_klass_movement = 0
                    r += 1 # make a blank iine
            
            # write headings if we are on new i.e. a break
            if row['klass'] != prv_klass:
                prv_klass = row['klass']
                cur_klass_beskrivning = row['klass_beskrivning']
                if report_id != 'ALL':
                    r = self.write_line(ws, r, cur_klass_beskrivning)
                else:
                    r = self.write_dashes(ws, r, len(headings), '-') 
               
            if row['konto_typ'] != prv_konto_typ:
                prv_konto_typ = row['konto_typ']
                cur_konto_typ_beskrivning = row['konto_typ_beskrivning']
                if report_id != 'ALL':
                    r = self.write_line(ws, r, cur_konto_typ_beskrivning)
    
            opening = row['opening_balance']
            movement = row['movement']
            if (opening != 0 or movement != 0):
                r=self.write_line(ws, r, row['konto_beskrivning'], row['konto'], row['opening_balance'], row['movement'])
                tot_konto_typ_opening += opening
                tot_konto_typ_movement += movement

        # write last summary 
        if (report_id != 'ALL'):
            r = self.write_line(ws, r, "S: A " + cur_konto_typ_beskrivning,  None,
                        tot_konto_typ_opening, tot_konto_typ_movement)
        
        r = self.write_line(ws, r, "S: A " + cur_klass_beskrivning, None,  
                       tot_klass_opening, tot_klass_movement)
    def write_dashes(self, ws, r, num_cols, dash_char):
        dashes= "'" + 10 * dash_char
        for col in range(num_cols): 
            ws.cell(row=r+1, column=col+1).value= dashes
        return r + 1

    def verifikation_to_excel(self, df):
        ws = self.wb['verifikationslista']
        headings = ["ver", "konto ks", "Text", "Debet", "Kredit" ]
        col = 0
        for item in headings:
            ws.cell(row=1, column=col+1).value = item
            col += 1
        r = self.write_dashes(ws, 1, len(headings),"=")

        cur_ver_nr = 0
        for index, row in df.iterrows():
            if cur_ver_nr != row['ver_nr']:
                if cur_ver_nr != 0:
                    r = self.write_dashes(ws, r, len(headings), '-')
                cur_ver_nr = row['ver_nr']
                ws.cell(row=r+1, column=1).value = row['ver_nr']
                posting_date = row['dato']
                posting_date_str = posting_date.strftime('%y%m%d')
                ws.cell(row=r+1, column=2).value = posting_date_str  
                ws.cell(row=r+1, column=3).value = row['beskrivning']
                r += 1

            ws.cell(row=r+1, column=2).value = row['konto']
            ws.cell(row=r+1, column=3).value = row['konto_beskrivning']
            if  row['belopp'] < 0:
                ws.cell(row=r+1, column=5).value = row['belopp']  # credit
            else:
                ws.cell(row=r+1, column=4).value = row['belopp']  # debit
            r += 1

        r = self.write_dashes(ws, r+1, len(headings), '-')

                
if __name__ == '__main__':
    accounting_obj = accounting("config.json")
    accounting_obj.run()
    