import os
import pandas as pd
import subprocess

def create_header(folder_path):
    subprocess.run(['python', 'Add_Header.py', folder_path])

def sum_columns_in_folder(folder_path, output_file):
    # Create an empty dictionary to store column-wise sums
    column_sums = {}

    # Loop through all files in the folder
    for file_name in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file_name)
        
        # Process only Excel files
        if file_name.endswith('.xlsx') or file_name.endswith('.xls'):  
            # Read the spreadsheet
            df = pd.read_excel(file_path)

            # Iterate through each column by position (except column B, which is index 1)
            for i, col in enumerate(df.columns):
                if i != 1:  # Skip column B (index 1)
                    if col not in column_sums:
                        column_sums[col] = 0  # Initialize if column not already in dictionary
                    column_sums[col] += pd.to_numeric(df[col], errors='coerce').sum(skipna=True)  # Add sum, skipping NaN values



    # Create a DataFrame from the column sums
    output_df = pd.DataFrame(list(column_sums.items()), columns=['Column', 'Sum'])


    # Write the output to a single spreadsheet
    output_df.to_excel(output_file, index=False)

# Define the input folder and output file
input_folder = "All_Operation_Output"
output_file = "Treated_Sheet\\Column_Sums.xlsx"

# Run the function
create_header(input_folder)
sum_columns_in_folder(input_folder, output_file)  


print(f"Column sums have been written to {output_file}")
