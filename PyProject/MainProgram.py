
import subprocess
import os

__name__ = "__main__"
#__name__ = "__IMGSETUP__"
#__name__ = "__IMGTOSTAT__"
#__name__ = "__IMGTOTEXT__"
#__name__ = "__TEXTTOEXCEL__"

Slice_Path = "Result\\Slices\\final_"
Stat_Path = "Result\\Slices\\Stat_slice_"
Text_Folder = "Result\\Attendee"

def full_process(mission_id, Img_Path):

    Img_Path = Img_Path + str(mission_id) + ".PNG"
    subprocess.run(['python', 'ImageSetup.py', Img_Path, str(mission_id)])

    for i in range(4):
        subprocess.run(['python', 'StatIsolation.py', Slice_Path + str(i) + ".png"])
        for j in range(8):
            subprocess.run(['python', 'ImageToText.py', Stat_Path + str(j) + ".png", Text_Folder + str(i), str(i), str(j)])
        subprocess.run(['python', 'TxtToExcel.py', str(i)])
        subprocess.run(['python', 'ExcelIntoOne.py', str(i), str(mission_id)])

if __name__ == "__main__":

    _, _, files = next(os.walk("Deploy5\\"))
    file_count = len(files)

    Img_Path = "Deploy6\\Eight_Jullox_Pengus_Janus_"

    for i in range(file_count):
        full_process(i + 1, Img_Path)
    subprocess.run(['python', 'OperationToSheet.py'])

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
