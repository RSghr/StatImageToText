import pandas as pd
import sys

def merge_excel_sheets_to_one_row(excel_files, output_excel):
    """
    Merges the content of multiple Excel files into one file, adding each file's content as a new row.

    Args:
        excel_files (list of str): List of paths to the Excel files.
        output_excel (str): Path to the output Excel file.
    """
    # List to store each file's content as a DataFrame row
    data_rows = []

    for file in excel_files:
        try:
            # Read the content of the Excel file
            df = pd.read_excel(file, engine='openpyxl', header=None)
            # Flatten the content into a single row and add it to the list
            data_rows.append(df.values.flatten().tolist())
        except Exception as e:
            print(f"Error reading {file}: {e}")
            return

    # Create a DataFrame from the rows
    merged_df = pd.DataFrame(data_rows)

    # Save the DataFrame to a new Excel file
    try:
        merged_df.to_excel(output_excel, index=False, header=False, engine='openpyxl')
        print(f"Merged data has been written to {output_excel}")
    except Exception as e:
        print(f"Error writing to Excel file: {e}")

if __name__ == "__main__":
    # List of Excel files to merge
    excel_files = []
    for i in range(4):
        excel_files.append("ResultExcel\\output_" + str(i) + ".xlsx")
    # Output file path
    output_excel = "ResultExcel\\Stat_Final.xlsx"

    # Call the function to merge the files
    merge_excel_sheets_to_one_row(excel_files, output_excel)
