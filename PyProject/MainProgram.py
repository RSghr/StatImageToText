
import subprocess
import os
import sys
import time

__name__ = "__main__"
#__name__ = "__IMGSETUP__"
#__name__ = "__IMGTOSTAT__"
#__name__ = "__IMGTOTEXT__"
#__name__ = "__TEXTTOEXCEL__"

#Slice_Path = "Result\\Slices\\final_"
#Stat_Path = "Result\\Slices\\Stat_slice_"
#Text_Folder = "Result\\Attendee"
ProcessStart = time.time()
ProcessEnd = time.time()

def full_process(mission_id, Img_Path, folder_name):

    Slice_Path = os.path.join(folder_name, "Result\\Slices\\final_")
    Stat_Path = os.path.join(folder_name, "Result\\Slices\\Stat_slice_")
    Text_Folder = os.path.join(folder_name, "Result\\Attendee")

    Img_Path = Img_Path + str(mission_id) + ".PNG"
    ProcessStart = time.time()
    subprocess.run(['python', 'ImageSetup.py', Img_Path, str(mission_id), folder_name])
    ProcessEnd = time.time()
    time_elapsed = ProcessEnd - ProcessStart
    print(f"ImageSetup elapsed: {time_elapsed:.2f} seconds.")

    for i in range(4):
        ProcessStart = time.time()
        subprocess.run(['python', 'StatIsolation.py', Slice_Path + str(i) + ".png", folder_name])
        ProcessEnd = time.time()
        time_elapsed = ProcessEnd - ProcessStart
        print(f"StatIsolation elapsed: {time_elapsed:.2f} seconds.")
        
        for j in range(8):
            ProcessStart = time.time()
            subprocess.run(['python', 'ImageToText.py', Stat_Path + str(j) + ".png", Text_Folder + str(i), str(i), str(j), folder_name])
            ProcessEnd = time.time()
            time_elapsed = ProcessEnd - ProcessStart
            print(f"ImageToText elapsed: {time_elapsed:.2f} seconds.")
        
        ProcessStart = time.time()
        subprocess.run(['python', 'TxtToExcel.py', str(i), folder_name])
        ProcessEnd = time.time()
        time_elapsed = ProcessEnd - ProcessStart
        print(f"TxtToExcel elapsed: {time_elapsed:.2f} seconds.")
        
        ProcessStart = time.time()
        subprocess.run(['python', 'ExcelIntoOne.py', str(i), str(mission_id), folder_name])
        ProcessEnd = time.time()
        time_elapsed = ProcessEnd - ProcessStart
        print(f"ExcelIntoOne elapsed: {time_elapsed:.2f} seconds.")

if __name__ == "__main__":

    _, _, files = next(os.walk(sys.argv[1]))
    file_count = len(files)

    Img_Path = os.path.join(sys.argv[1], sys.argv[2])

    for i in range(file_count):
        full_process(i + 1, Img_Path, sys.argv[1])
    
    ProcessStart = time.time()
    subprocess.run(['python', 'OperationToSheet.py', sys.argv[1]])
    ProcessEnd = time.time()
    time_elapsed = ProcessEnd - ProcessStart
    print(f"OperationToSheet elapsed: {time_elapsed:.2f} seconds.")    

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
