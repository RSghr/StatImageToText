import cv2
from PIL import Image
import pytesseract

def save_string_to_file(string_input, file_name="output_.txt"):
    """
    Save the input string to a .txt file in the current directory.
    
    :param string_input: The string to save in the file.
    :param file_name: The name of the output file (default: output.txt).
    """
    try:
        file_name = "OUTPUT_Pengus_Panini_Stella_Engel.txt"
        # Open the file in write mode
        with open(file_name, 'w') as file:
            file.write(string_input)
        print(f"String saved to {file_name} successfully!")
    except Exception as e:
        print(f"An error occurred: {e}")

# Specify Tesseract path (Windows only)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Test OCR
image_path = 'Testing.png'
text = pytesseract.image_to_string(Image.open(image_path))
print("Extracted Text:", text)

save_string_to_file(text)
##############################################################################
#                                                                            #
#It was my first try at convert images to text. Will be deleted down the line#
#                                                                            #
##############################################################################