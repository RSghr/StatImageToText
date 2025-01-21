import pandas as pd
import sys

def insert_txt_into_spreadsheet(txt_files, output_excel):
    """
    Inserts the content of text files into an Excel spreadsheet.

    Args:
        txt_files (list of str): List of paths to the text files.
        output_excel (str): Path to the output Excel file.
    """
    # Dictionary to store file content
    data = []

    # Read each file and add content to the dictionary
    for file in txt_files:
        try:
            with open(file, 'r') as f:
                data.append([line.strip() for line in f.readlines()])
        except Exception as e:
            print(f"Error reading {file}: {e}")
            return

    max_columns = max(len(row) for row in data)

    # Normalize rows to have the same number of columns
    normalized_data = [row + [''] * (max_columns - len(row)) for row in data]

    # Convert to DataFrame
    dataframe = pd.DataFrame(normalized_data)

    # Save DataFrame to Excel
    try:
        dataframe.to_excel(output_excel, index=False, header=False, engine='openpyxl')
    except Exception as e:
        print(f"Error writing to Excel file: {e}")

if __name__ == "__main__":
    
    for i in range(4):
        txt_files = []
        output_excel = sys.argv[2] + "\\ResultExcel\\output_" + str(i) + ".xlsx"
        for j in range (8):
            txt_files.append(sys.argv[2] + "\\Result\\Attendee" + str(i) + "\\OUTPUT_Test_" + str(j) + ".txt")
        insert_txt_into_spreadsheet(txt_files, output_excel)
