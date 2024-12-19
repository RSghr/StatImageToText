
import subprocess

Img_Path = "Deploy1\\Pengus_Panini_Stella_Engel_2.PNG"

Slice_Path = "Result\\Slices\\final_"
Text_Folder = "Result\\Attendee"


subprocess.run(['python', 'ImageSetup.py', Img_Path])

for i in range(4):
    subprocess.run(['python', 'ImageToText.py', Slice_Path + str(i) + ".png", Text_Folder + str(i), str(i)])