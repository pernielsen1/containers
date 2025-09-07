import os
import json
import xlsxwriter
import pandas as pd
# dir_name = "/mnt/c/users/perni/OneDrive/Documents/Häggeboda/gl"

class accounting():
    def __init__(self, config_file="config.json"):
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        output_file = self.config['out_dir'] + "/" + "gl_output.xlsx"
        self.wb = xlsxwriter.Workbook(output_file)
       

    def run(self):
        file_name = self.config['in_dir'] + "/" + "gl.xlsx"
        accounts =  pd.read_excel(file_name, sheet_name="konti")
        accounts =  accounts[['konto', 'beskrivning', 'konto_typ']]  # don't take the formula fields 
        accounts =  accounts.rename(columns={'beskrivning':'konto_beskrivning'})

        account_types =  pd.read_excel(file_name, sheet_name="konto_typer")
        account_types = account_types[['konto_typ', 'beskrivning', 'klass']] # don't take the formula fields
        account_types = account_types.rename(columns={'beskrivning':'konto_typ_beskrivning'})

        accounts = accounts.merge(account_types, how='inner', 
                    left_on='konto_typ', right_on='konto_typ', indicator=False)
        classes = pd.read_excel(file_name, sheet_name="klasser")
        classes = classes[['klass', 'beskrivning', 'rapport_id']]
        classes = classes.rename(columns={'beskrivning':'klass_beskrivning'})
       
        accounts = accounts.merge(classes, how='inner', 
                    left_on='klass', right_on='klass', indicator=False)
        reports = pd.read_excel(file_name, sheet_name="rapporter")
        reports = reports.rename(columns={'beskrivning':'rapport_beskrivning'})
       
        accounts = accounts.merge(reports, how='inner', 
                    left_on='rapport_id', right_on='rapport_id', indicator=False)
       
        postings_all =  pd.read_excel(file_name, sheet_name="posteringer")
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
        balances = balances.query(
            '(opening_balance != 0) | (movement != 0) | (closing_balance !=0)')
        # add the account description
        balances = balances[['opening_balance', 'movement', 'closing_balance']]
        balances = balances.merge(accounts, how='inner', 
                                            left_on='konto', right_on='konto', 
                                            indicator = True) 
     
        balances = balances.sort_values(['klass', 'konto_typ', 'konto'])
        balances = balances[['rapport_id', 'rapport_beskrivning', 'sheet_name',
                                        'klass', 'klass_beskrivning', 
                                       'konto_typ', 'konto_typ_beskrivning',
                                       'konto', 'konto_beskrivning',
                                       'opening_balance', 'movement', 'closing_balance'
     
                            ]]
        self.balance_report_to_excel(balances, 'BS')
        self.balance_report_to_excel(balances, 'RS')
   
        self.wb.close()
        print("all done - workbook ready")
    
    # self.to_excel(post_enriched)
    # creates the "Balance sheet"
    def write_line(self, ws, r, konto, text, opening, movement):
        if (konto != 0):
            ws.write(r, 0, konto)
        ws.write(r, 1, text)
        ws.write(r, 2, opening)
        ws.write(r, 3, movement)
        ws.write(r, 4, opening + movement)

    def balance_report_to_excel(self, in_df, report_id):
        str_query = f'(rapport_id=="{report_id}")'
        df = in_df.query(str_query).copy(deep=True)
        first_row = df.iloc[0]
        sheet_name  = first_row['sheet_name']
        ws = self.wb.add_worksheet(sheet_name)
        headings = ["konto", "Text", "Ing balans", "Perioden", "Utg Balans" ]
        col = 0
        for item in headings:
            ws.write(0, col, item)
            dashes = "'======"
            ws.write(1, col, dashes)
            col += 1
        # assets tilgångar
        r = 2
        cur_klass_beskrivning = ''
        prv_klass = 0     
        tot_klass_opening = 0
        tot_klass_movement = 0 
        prv_konto_typ = 0
        cur_konto_typ_beskrivning = ''

        tot_konto_typ_opening = 0
        tot_konto_typ_movement = 0 
        for index, row in df.iterrows():
            col = 0
            r += 1
            # write summaries if break
            if (row['konto_typ'] != prv_konto_typ):
                if (prv_konto_typ != 0):
                    self.write_line(ws, r, 0, "S: A" + cur_konto_typ_beskrivning, 
                                     tot_konto_typ_opening, tot_konto_typ_movement)
                    r+= 1
                    tot_konto_typ_opening = 0
                    tot_konto_typ_movement = 0

            if (row['klass'] != prv_klass):
                if (prv_klass != 0):  # write klass summary 
                    self.write_line(ws, r, 0, "S: A" + cur_klass_beskrivning, 
                                     tot_klass_opening, tot_klass_movement)
                    r += 1
                    tot_klass_opening = 0
                    tot_klass_movement = 0
            # write headings if we are on new i.e. a break
            if row['klass'] != prv_klass:
                prv_klass = row['klass']
                cur_klass_beskrivning = row['klass_beskrivning']
                ws.write(r, 0, cur_klass_beskrivning)
                r += 1 
            
            if row['konto_typ'] != prv_konto_typ:
                prv_konto_typ = row['konto_typ']
                cur_konto_typ_beskrivning = row['konto_typ_beskrivning']
                ws.write(r, 0, cur_konto_typ_beskrivning)
                r += 1 
            self.write_line(ws, r, row['konto'], row['konto_beskrivning'], row['opening_balance'], row['movement'])
            tot_klass_opening += row['opening_balance']
            tot_klass_movement += row['movement']
            tot_konto_typ_opening += row['opening_balance']
            tot_konto_typ_movement += row['movement']
        # write last summary 
        self.write_line(ws, r, 0, "S: A" + cur_konto_typ_beskrivning, 
                       tot_konto_typ_opening, tot_konto_typ_movement)
        self.write_line(ws, r, 0, "S: A" + cur_klass_beskrivning, 
                       tot_klass_opening, tot_klass_movement)

     

if __name__ == '__main__':
    accounting_obj = accounting("config.json")
    accounting_obj.run()
    