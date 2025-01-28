import os
import pandas as pd

def sum_and_concatenate(folder_path, output_file):
    # Create an empty DataFrame to store the concatenated results
    concatenated_df = pd.DataFrame()

    # Loop through all files in the folder
    for file_name in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file_name)

        # Process only Excel files
        if file_name.endswith('.xlsx') or file_name.endswith('.xls'):
            # Read the spreadsheet
            df = pd.read_excel(file_path, header=None)

            # Sum each column vertically, skipping the second column (index 1)
            column_sums = [
                pd.to_numeric(df.iloc[:, i].astype(str).str.replace(",", ""), errors='coerce').sum()
                if i != 1 else None for i in range(len(df.columns))
            ]

            # Remove the skipped column from the results
            column_sums = [value for value in column_sums if value is not None]

            # Convert the sums into a single column DataFrame
            column_df = pd.DataFrame(column_sums, columns=[file_name])

            # Concatenate the column_df to the right of concatenated_df
            concatenated_df = pd.concat([concatenated_df, column_df], axis=1)

    # Add the new column with the specified values
    new_column = [
        "KILLS",
        "SHOTS FIRED",
        "SHOTS HIT",
        "DEATH",
        "STIMS USED",
        "ACCIDENTALS",
        "SAMPLES EXTRACTED"
    ]
    concatenated_df.insert(0, "Metrics", new_column)

    # Save the concatenated DataFrame to an Excel file
    concatenated_df.to_excel(output_file, header=True, index=False)
    print(f"All spreadsheets have been processed, summed, and concatenated into {output_file}.")

# Input folder and output file paths
input_folder = "All_Operation_Output"  # Replace with your folder path
output_file = "Treated_Sheet\\summed_and_concatenated.xlsx"  # Replace with your desired output file path

# Run the function
sum_and_concatenate(input_folder, output_file)