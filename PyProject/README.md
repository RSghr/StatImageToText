STATS TO TEXT

Just launch MainProgram.py and it will create the slices, and text in each attendee folder (attendee 0 is the host)

It's still being tuned.

Deploy 1 2 and 3 in order to get more testing data.

Archive is just old stuff or files I'd like to keep for now and delete later.

I have to write a whole setup with the pip commands and such.

you need to get ocr_env in your project.

MainProgram.py :

__main__
    Excecute the whole project.
__IMGSETUP__
    Creates an image for each helldiver
__IMGTOSTAT__
    Convert each image into separated image for each stat (from Kills to Samples extracted)
__IMGTOTEXT__
    Converts each stat into a text file that contains the stat.
    Returns "0" if the script does not recognize the text and is empty. (Could be changed to -1, but 0 is good as it usually fails to convert 0 in text)
__TEXTTOEXCEL__
    Gathers all the stats into one spreadsheet, alongside one for each helldiver.

You can just comment the mode you want.

Clear_Env.py :

The script deletes all .png .txt and .xlsx

__Result__
    Clear the result folder
__ResultExcel__
    Clear the ResultExcel folder
__All__
    Clear the whole project