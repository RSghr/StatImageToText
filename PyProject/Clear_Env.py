import os

__name__ == "__main__"

def clear_folder(folder_path):
    """
    Clears a folder of .png, .txt, and .xlsx files.

    Args:
        folder_path (str): Path to the folder to be cleared.
    """
    try:
        # List all files in the folder
        for file_name in os.listdir(folder_path):
            # Build the full file path
            file_path = os.path.join(folder_path, file_name)

            # Check if it's a file and has the specified extension
            if os.path.isfile(file_path) and file_name.lower().endswith(('.png', '.txt', '.xlsx')):
                # Remove the file
                os.remove(file_path)
                print(f"Deleted: {file_path}")
    except Exception as e:
        print(f"Error clearing folder: {e}")

#folder_path = "Result"
#folder_path = "ResultExcel"
folder_path = "All"

if folder_path == "Result":
    for i in range(4):
        clear_folder(folder_path + "\\Attendee" + str(i))
    clear_folder(folder_path + "\\Slices")

elif folder_path == "ResultExcel":
    clear_folder(folder_path)

else:
    folder_path = "Result"
    for i in range(4):
        clear_folder(folder_path + "\\Attendee" + str(i))
    clear_folder(folder_path + "\\Slices")

    folder_path = "ResultExcel"
    clear_folder(folder_path)