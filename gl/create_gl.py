import os
import xlsxwriter
import pandas as pd
dir_name = "/mnt/c/users/perni/OneDrive/Documents/Häggeboda/gl"

def do_it():
    file_name = dir_name + "/" + "gl.xlsx"
    postings =  pd.read_excel(file_name, sheet_name="posteringer")
    print(postings)
    accounts =  pd.read_excel(file_name, sheet_name="konti")
    print(accounts)
    post_enriched = postings.merge(accounts, how='left', left_on='konto', right_on='konto',
                                   indicator=True)
    print(post_enriched)
    output_file = dir_name + "/" + "gl_output.xlsx"
    wb = xlsxwriter.Workbook(output_file)
    ws = wb.add_worksheet()
    
    headings = post_enriched.columns.tolist()
    col = 0
    for item in headings:
        ws.write(0, col, item)
        col += 1
    r = 0
    for index, row in post_enriched.iterrows():
        col = 0
        r += 1
        ws.write(r, 0,   row['konto'])
        ws.write(r, 1, row['belopp'])

    wb.close()

if __name__ == '__main__':
    do_it()
