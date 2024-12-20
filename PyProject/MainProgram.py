
import subprocess

__name__ = "__main__"
#__name__ = "__IMGSETUP__"
#__name__ = "__IMGTOSTAT__"
#__name__ = "__IMGTOTEXT__"
#__name__ = "__TEXTTOEXCEL__"


Img_Path = "Deploy1\\Pengus_Panini_Stella_Engel_3.PNG"

Slice_Path = "Result\\Slices\\final_"
Stat_Path = "Result\\Slices\\Stat_slice_"
Text_Folder = "Result\\Attendee"

def full_process():
    subprocess.run(['python', 'ImageSetup.py', Img_Path])

    for i in range(4):
        subprocess.run(['python', 'StatIsolation.py', Slice_Path + str(i) + ".png"])
        for j in range(8):
            subprocess.run(['python', 'ImageToText.py', Stat_Path + str(j) + ".png", Text_Folder + str(i), str(i), str(j)])
        subprocess.run(['python', 'TxtToExcel.py', str(i)])
        subprocess.run(['python', 'ExcelIntoOne.py', str(i)])

if __name__ == "__main__":
    full_process()

if __name__ == "__IMGSETUP__":
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
