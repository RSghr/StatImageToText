import pandas as pd
import sys

def merge_excel_mission_to_one_Sheet(mission1, mission2, mission3):
    
    separator = pd.DataFrame([''] * 2)

    # Read the Excel files into DataFrames
    df1 = pd.read_excel(mission1, header=None)
    df2 = pd.read_excel(mission2, header=None)
    df3 = pd.read_excel(mission3, header=None)

    # Merge the DataFrames with separators
    merged_df = pd.concat([df1, separator, df2, separator, df3], ignore_index=True)

    # Save the merged DataFrame to a new Excel file
    output_file = sys.argv[1] + "\\ResultExcel\\All_Operation.xlsx"
    merged_df.to_excel(output_file, index=False, header=False)

if __name__ == "__main__":
    merge_excel_mission_to_one_Sheet(sys.argv[1] + "\\ResultExcel\\Stat_Final_1.xlsx", sys.argv[1] + "\\ResultExcel\\Stat_Final_2.xlsx", sys.argv[1] + "\\ResultExcel\\Stat_Final_3.xlsx")