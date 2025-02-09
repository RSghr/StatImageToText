import subprocess
import os
import shutil
import re
import time
import datetime
from PIL import Image
import logging

# Define the base folder where the images are located
base_folder = "MASS_DEPLOY"
output_folder = "Mass Deploy Sorted"

log_file = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


if os.path.exists('Log.txt'):
    os.rename('Log.txt', "Log_" + log_file + ".log")

logging.basicConfig(filename='Log.txt', level=logging.DEBUG, format='')

def Log_Print(data):
    logging.info(data)
    logging.error(data)
    print(data)

# Create output folder if it doesn't exist
if not os.path.exists(output_folder):
    os.makedirs(output_folder)

# Regular expression to match the file pattern
pattern = re.compile(r"^(([a-zA-Z0-9]+_[a-zA-Z0-9]+_[a-zA-Z0-9]+_[a-zA-Z0-9]+)_\d+)(?: - [^\\/]+)?\.(png|jpg|jpeg)$", re.IGNORECASE)

# Dictionary to group files by their main prefix
grouped_files = {}

#Delete the uploader name
def delete_Uploader():
    for file_name in os.listdir(base_folder):
        if " - " in file_name and file_name.endswith(".png"):
            parts = file_name.split(" - ")
            name_part = parts[0]
            new_name = f"{name_part}.png"
            old_path = os.path.join(base_folder, file_name)
            new_path = os.path.join(base_folder, new_name)
            os.rename(old_path, new_path)


#Convert all pictures into PNG
for file_name in os.listdir(base_folder):
    file_path = os.path.join(base_folder, file_name)

    # Check if it is a file
    if os.path.isfile(file_path):
        # Split the file name and extension
        base_name, ext = os.path.splitext(file_name)

        # Only proceed for image files
        if ext.lower() in [".jpg", ".jpeg", ".bmp", ".tiff", ".gif", ".webp"] or ext == ".PNG":
            try:
                # Open the image file
                with Image.open(file_path) as img:
                    # Convert the image to RGB (to avoid issues with formats like .gif or .tiff)
                    img = img.convert("RGB")

                    # Define the output file path
                    output_file_path = os.path.join(base_folder, f"{base_name}.png")

                    # Save the image as .png
                    img.save(output_file_path, "PNG")  

                    # Delete the original file
                    os.remove(file_path) 
            except Exception as e:
                Log_Print(f"Failed to convert {file_name}: {e}")

delete_Uploader()

# Iterate through files in the base folder
for file_name in os.listdir(base_folder):
    
    file_path = os.path.join(base_folder, file_name)

    # Check if it is a file
    if os.path.isfile(file_path):
        match = pattern.match(file_name)

        if match:
            full_prefix, main_prefix, ext = match.groups()
            # Add the file to the group based on its main prefix
            if main_prefix not in grouped_files:
                grouped_files[main_prefix] = []
            grouped_files[main_prefix].append(file_path)

#Create directories for each deployment detected
def Create_Directory():
    for main_prefix, files in grouped_files.items():
        folder_name = os.path.join(output_folder, main_prefix)
        folder_Result = os.path.join(folder_name, "Result")
        folder_Excel = os.path.join(folder_name, "ResultExcel")

        # Create a folder for the group if it doesn't exist
        if not os.path.exists(folder_name):
            os.makedirs(folder_name)
            os.makedirs(folder_Result)
            for i in range(4):
                folder_Attendee = os.path.join(folder_Result, "Attendee" + str(i))
                os.makedirs(folder_Attendee)
            folder_Slice = os.path.join(folder_Result, "Slices")
            os.makedirs(folder_Slice)
            os.makedirs(folder_Excel)

        # Copy files into the group folder
        for file_path in files:
            shutil.copy(file_path, folder_name)
    
    if not os.path.exists("All_Operation_Output"):
        os.makedirs("All_Operation_Output")

# Copy grouped files into their respective folders
Create_Directory()

Log_Print("Files have been sorted and copied successfully.")

ProcessStartOverall = time.time()
    
for folder_name in os.listdir(output_folder):
    folder_path = os.path.join(output_folder, folder_name)

    # Check if it is a directory
    if os.path.isdir(folder_path):
        # Launch MainProgram.py with the folder and name as arguments
        try:
            Log_Print("Processing Operation : " + folder_name)
            folder_name = folder_name + "_"
            ProcessStart = time.time()
            subprocess.run(["python", "MainProgram.py", folder_path, folder_name], check=True)
            ProcessEnd = time.time()
            time_elapsed = ProcessEnd - ProcessStart
            Log_Print(f"MainProgram elapsed: {time_elapsed:.2f} seconds.")   

        except subprocess.CalledProcessError as e:
            Log_Print(f"Error while processing folder '{folder_name}': {e}")
ProcessEnd = time.time()
time_elapsed = ProcessEnd - ProcessStartOverall
Log_Print(f"Deploy_Manager elapsed: {time_elapsed:.2f} seconds.")   

Log_Print("All folders have been processed.")