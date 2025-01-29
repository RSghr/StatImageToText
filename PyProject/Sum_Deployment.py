import os
import pandas as pd

def sum_and_convert_to_line(file_path, output_file):
    # Read the Excel file
    df = pd.read_excel(file_path, header=None)  # No headers assumed

    # Check if the sheet has exactly 8 columns
    if len(df.columns) != 8:
        raise ValueError(f"The sheet must have exactly 8 columns, but it has {len(df.columns)}.")

    # Sum each column vertically
    column_sums = [
        df.iloc[:, i].sum() if i != 1 else None for i in range(len(df.columns))
    ]

    # Remove the skipped column from the results
    column_sums = [value for value in column_sums if value is not None]

    # Convert the sums into a single column DataFrame
    column_df = pd.DataFrame(column_sums, columns=["Sum"])

    # Convert the sums into a single column DataFrame
    column_df = pd.DataFrame(column_sums, columns=["Sum"])

    # Save the result as a single column in an Excel file
    column_df.to_excel(output_file, header=False, index=False)

    print(f"Summed columns have been converted into a line and saved to {output_file}.")

# Input file and output file paths
input_file = "All_Operation_Output\\INPUT YOU DEPLOYMENT HERE.xlsx"  # Replace with your input file path
output_file = "Treated_Sheet\\summed_line.xlsx"  # Replace with your desired output file path

# Run the function
sum_and_convert_to_line(input_file, output_file)
