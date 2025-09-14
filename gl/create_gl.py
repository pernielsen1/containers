
import json
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import numbers
from datetime import datetime

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
        verifications = pd.read_excel(self.file_name, sheet_name='verifikationer')       
        verifications = verifications[['ver_nr', 'dato', 'beskrivning']]
        postings_all =  pd.read_excel(self.file_name, sheet_name="posteringer")
        postings_all = postings_all[['ver_nr', 'lin', 'konto', 'belopp']] 
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
                                       'opening_balance', 'movement', 'closing_balance']]
        self.transfer_last_year(verifications, postings_all, balances)
        self.df_to_excel(verifications, 'verifications')   
        self.df_to_excel(postings_all, 'postings_all')   
      
        # self.add_verification(verifications, '2024-12-31', 'transfer last year')
        result = self.calculate_result(balances)
        # add data like text and date from verifications
        postings = postings.merge(verifications,  how="left", 
                                            left_on='ver_nr', right_on='ver_nr', 
                                            indicator = False) 
        postings = postings.merge(accounts, how="left",
                                            left_on='konto', right_on='konto', 
                                            indicator = False) 
                                   
        self.balance_report_to_excel(balances, 'BS')
        self.balance_report_to_excel(balances, 'RS')
        self.balance_report_to_excel(balances, 'ALL')  # balance list
        self.gl_report_to_excel(balances, postings, 'GL')  # GL
        
        self.verifikation_to_excel(postings)
        self.wb.save(self.output_file)
        print("all done - workbook ready")

    def transfer_last_year(self, verifications, postings_all, balances):
        # find balance for last years result
        last_year_result = balances.query('konto == 2098').iloc[0]['closing_balance']

        new_ver_nr, verifications = self.add_verification(verifications, '2024-12-31', 'transfer')
        postings_all.loc[len(postings_all)] = [new_ver_nr, 1, 2099, -last_year_result]
        postings_all.loc[len(postings_all)] = [new_ver_nr, 1, 2098, +last_year_result]
        return verifications, postings_all
    
    def add_verification(self, verifications, date_str, text:str):
        new_ver_nr = 1 + verifications.agg({'ver_nr' : ['max']}).iloc[0]['ver_nr']
        ver_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        verifications.loc[len(verifications)] = [new_ver_nr, ver_date, text]
        print(verifications)
        return new_ver_nr, verifications

    def df_to_excel(self, df, sheet_name):
        ws = self.add_or_get_ws(sheet_name)
        col = 1
        for column in df.columns:
            ws.cell(row=1, column = col).value = column
            col += 1
        cur_row = 2
        for index, row in df.iterrows():
            col = 1
            for column in df.columns:
                ws.cell(row=cur_row, column=col).value = row[column]
                col += 1
            cur_row += 1


        
    def write_line(self, ws, r, text, konto=None, opening=None, movement=None):
        if konto is not None:
            ws.cell(row=r+1, column=1).value = konto
        ws.cell(row=r+1, column=2).value= text
        if (opening is not None):
            ws.cell(row=r+1, column=3).value= opening
            ws.cell(row=r+1, column=4).value = movement
            ws.cell(row=r+1, column=5).value = opening + movement
        return r+1

    def write_dashes(self, ws, r, num_cols, dash_char):
        for col in range(num_cols): 
            f = "=REPT(" + '"' + dash_char + '"' + ',' + '10' + ')'
            ws.cell(row=r, column=col+1).value = f
        return r + 1

    def write_heading(self, ws, r, headings):
        col = 1
        for item in headings:
            ws.cell(row=r, column=col).value=item
            col += 1
        self.write_dashes(ws, r+1, len(headings), '=')
        return r + 2
    
    def add_or_get_ws(self, sheet_name, clear=True):
        if sheet_name in self.wb.sheetnames: 
            ws = self.wb[sheet_name]
        else:
            ws = self.wb.create_sheet(sheet_name)
        if clear:
            ws.delete_rows(1, ws.max_row) # clear the sheet.
        return ws 
    
    def gl_report_to_excel(self, balances, verifications, report_id):
        this_report = self.reports.query(f'(rapport_id=="{report_id}")').iloc[0]
        ws = self.add_or_get_ws(this_report['sheet_name'])
        headings = ["konto", "Text", "Ing balans", "Perioden", "Utg Balans" ]
        cur_row = self.write_heading(ws,1,headings)
        for index, row in balances.iterrows():
            ws.cell(row=cur_row, column=1).value = 'Ing Balance'
            ws.cell(row=cur_row, column=2).value = row['konto']
            ws.cell(row=cur_row, column=3).value = row['konto_beskrivning']
            ws.cell(row=cur_row, column=4).value = row['opening_balance']
            cur_row += 1
            strqry = f"konto=={row['konto']}"
            postings = verifications.query(strqry)
            for ver_index, ver_row in postings.iterrows():
                ws.cell(row=cur_row, column=2).value = ver_row['beskrivning']
                ws.cell(row=cur_row, column=3).value = ver_row['belopp']
                cur_row += 1

            ws.cell(row=cur_row, column=1).value = 'Utg Balance'
            ws.cell(row=cur_row, column=4).value = row['closing_balance']
            cur_row += 1
            cur_row = self.write_dashes(ws, cur_row, len(headings),'-')

#                r=self.write_line(ws, r, row['konto_beskrivning'], row['konto'], row['opening_balance'], row['movement'])
            
    def calculate_result(self, df_balances):
        result_df = df_balances.query('rapport_id=="RS"').agg({'movement' : ['sum']})
        result = result_df.iloc[0]['movement']

        return result

    def balance_report_to_excel(self, in_df, report_id):
        str_query = f'(rapport_id=="{report_id}")'
        this_report = self.reports.query(str_query).iloc[0]
        ws = self.add_or_get_ws(this_report['sheet_name'])

        if (report_id == 'ALL'): 
            df = in_df.copy(deep=True)
        else:
            df = in_df.query(str_query).copy(deep=True)

        headings = ["konto", "Text", "Ing balans", "Perioden", "Utg Balans" ]
        r = self.write_heading(ws, 1, headings)

        prv_klass = 0     
        cur_klass_beskrivning = ''
        tot_klass_opening = 0
        tot_klass_movement = 0

        prv_konto_typ = 0
        cur_konto_typ_beskrivning = ''
        tot_konto_typ_opening = 0
        tot_konto_typ_movement = 0 
        
        for index, row in df.iterrows():
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
#                else:
#                    r = self.write_dashes(ws, r, len(headings), '-') 
               
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
    
    def verifikation_to_excel(self, df):
        ws = self.wb['verifikationslista']
        headings = ["ver", "konto ks", "Text", "Debet", "Kredit" ]
        col = 0
        r = self.write_heading(ws, 1, headings)

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

            ws.cell(row=r, column=2).value = row['konto']
            ws.cell(row=r, column=3).value = row['konto_beskrivning']
            if  row['belopp'] < 0:
                ws.cell(row=r+1, column=5).value = row['belopp']  # credit
            else:
                ws.cell(row=r+1, column=4).value = row['belopp']  # debit
            r += 1

        r = self.write_dashes(ws, r, len(headings), '-')

                
if __name__ == '__main__':
    accounting_obj = accounting("config.json")
    accounting_obj.run()
    