import os
import pandas as pd
import sys

def add_headers_to_excel(folder_path):
    # Define the header columns
    header_columns = [
        "KILLS",
        "ACCURACY",
        "SHOTS FIRED",
        "SHOTS HIT",
        "DEATH",
        "STIMS USED",
        "ACCIDENTALS",
        "SAMPLES EXTRACTED"
    ]

    # Loop through all files in the folder
    for file_name in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file_name)

        # Process only Excel files
        if file_name.endswith('.xlsx') or file_name.endswith('.xls'):
            # Read the spreadsheet without headers
            df = pd.read_excel(file_path, header=None)

            # Check if the number of columns matches the header length
            if len(df.columns) != len(header_columns):
                print(f"Skipping {file_name}: Column count mismatch.")
                continue

            # check if the spreadshet already has headers
            if df.iloc[0].tolist() == header_columns:
                print(f"Skipping {file_name}: Headers already present.")
            else:
                # Add the header columns
                df.columns = header_columns

                # Save the file back with headers
                df.to_excel(file_path, index=False)
                print(f"Headers added to {file_name}.")

# Define the input folder
input_folder = sys.argv[1]

# Run the function
add_headers_to_excel(input_folder)

print("Headers have been added to all applicable files.")