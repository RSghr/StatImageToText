
import subprocess
import os
import sys
import time
import logging

__name__ = "__main__"
#__name__ = "__IMGSETUP__"
#__name__ = "__IMGTOSTAT__"
#__name__ = "__IMGTOTEXT__"
#__name__ = "__TEXTTOEXCEL__"

ProcessStart = time.time()
ProcessEnd = time.time()

logging.basicConfig(filename='Log.txt', level=logging.DEBUG, format='')

def Log_Print(data):
    logging.info(data)
    print(data)

def full_process(mission_id, Img_Path, folder_name):

    #Define Relative folders
    Slice_Path = os.path.join(folder_name, "Result\\Slices\\final_")
    Stat_Path = os.path.join(folder_name, "Result\\Slices\\Stat_slice_")
    Text_Folder = os.path.join(folder_name, "Result\\Attendee")

    #Selecting image to process
    Img_Path = Img_Path + str(mission_id) + ".PNG"

    #formatting the image to be processed
    ProcessStart = time.time()
    subprocess.run(['python', 'ImageSetup.py', Img_Path, str(mission_id), folder_name])
    ProcessEnd = time.time()
    time_elapsed = ProcessEnd - ProcessStart
    Log_Print(f"ImageSetup elapsed: {time_elapsed:.2f} seconds.")

    for i in range(4):

        #Slicing the stats Found in \Slices
        ProcessStart = time.time()
        subprocess.run(['python', 'StatIsolation.py', Slice_Path + str(i) + ".png", folder_name])
        ProcessEnd = time.time()
        time_elapsed = ProcessEnd - ProcessStart
        Log_Print(f"StatIsolation elapsed: {time_elapsed:.2f} seconds.")
        
        #Convert from Image to Text
        for j in range(8):
            ProcessStart = time.time()
            subprocess.run(['python', 'ImageToText.py', Stat_Path + str(j) + ".png", Text_Folder + str(i), str(i), str(j), folder_name])
            ProcessEnd = time.time()
            time_elapsed = ProcessEnd - ProcessStart
            Log_Print(f"ImageToText elapsed: {time_elapsed:.2f} seconds.")
        
        #Concat Text to Spreadsheet
        ProcessStart = time.time()
        subprocess.run(['python', 'TxtToExcel.py', str(i), folder_name])
        ProcessEnd = time.time()
        time_elapsed = ProcessEnd - ProcessStart
        Log_Print(f"TxtToExcel elapsed: {time_elapsed:.2f} seconds.")
        
        #Concat the whole mission in a single Spreadsheet (4 lines)
        ProcessStart = time.time()
        subprocess.run(['python', 'ExcelIntoOne.py', str(i), str(mission_id), folder_name])
        ProcessEnd = time.time()
        time_elapsed = ProcessEnd - ProcessStart
        Log_Print(f"ExcelIntoOne elapsed: {time_elapsed:.2f} seconds.")

if __name__ == "__main__":

    #Check how many files exist in the folder
    _, _, files = next(os.walk(sys.argv[1]))
    file_count = len(files)

    Img_Path = os.path.join(sys.argv[1], sys.argv[2])

    #Image to spreadsheet for each image detected.
    for i in range(file_count):
        ProcessStart = time.time()
        full_process(i + 1, Img_Path, sys.argv[1])
        ProcessEnd = time.time()
        time_elapsed = ProcessEnd - ProcessStart
        Log_Print(f"full_process elapsed: {time_elapsed:.2f} seconds.")    
    
    ProcessStart = time.time()
    subprocess.run(['python', 'OperationToSheet.py', sys.argv[1], sys.argv[2]])
    ProcessEnd = time.time()
    time_elapsed = ProcessEnd - ProcessStart
    Log_Print(f"OperationToSheet elapsed: {time_elapsed:.2f} seconds.")    


#NOT USED ANYMORE - IT IS NOT UP TO DATE WITH THE CURRENT STRUCTURE
if __name__ == "__IMGSETUP__":
    Img_Path = "Deploy6\\Eight_Jullox_Pengus_Janus_1.png"
    subprocess.run(['python', 'ImageSetup.py', Img_Path])

if __name__ == "__IMGTOSTAT__":
    for i in range(4):
        subprocess.run(['python', 'StatIsolation.py', Slice_Path + str(i) + ".png"])

if __name__ == "__IMGTOTEXT__":
    for i in range(4):
        subprocess.run(['python', 'StatIsolation.py', Slice_Path + str(i) + ".png"])
        for j in range(8):
            subprocess.run(['python', 'ImageToText.py', Stat_Path + str(j) + ".png", Text_Folder + str(i), str(i), str(j)])

if __name__ == "__TEXTTOEXCEL__":
    for i in range(4):
        subprocess.run(['python', 'TxtToExcel.py'])
    subprocess.run(['python', 'ExcelIntoOne.py'])
