import cv2
import pytesseract
import numpy as np
import sys
from pytesseract import Output

# Set up Tesseract executable path (change this to your Tesseract path if necessary)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def convert_non_white_to_black(image_path, output_path="Result\\Attendee" + sys.argv[3] + "\\output_image.png"):
    """
    Converts all non-white pixels in an image to black.

    :param image_path: Path to the input image.
    :param output_path: Path to save the processed image.
    """
    # Load the image
    image = cv2.imread(image_path)

    # Define the lower and upper bounds for "white" in BGR format
    lower_bound = np.array([0, 175, 175], dtype=np.uint8)
    upper_bound = np.array([255, 255, 255], dtype=np.uint8)

    # Create a mask for pixels that are "white"
    white_mask = cv2.inRange(image, lower_bound, upper_bound)

    # Create an output image where non-white pixels are black
    output_image = cv2.bitwise_and(image, image, mask=white_mask)

    # Save the processed image
    cv2.imwrite(output_path, output_image)


def preprocess_image(image_path):
    """
    Preprocess the image for better OCR accuracy using OpenCV.
    
    :param image_path: Path to the input image.
    :return: Preprocessed image ready for OCR.
    """
    convert_non_white_to_black(image_path)

    # Read the image in grayscale
    image = cv2.imread("Result\\Attendee" + sys.argv[3] + "\\output_image.png", cv2.IMREAD_GRAYSCALE)

    # Resize the image (optional, improves OCR for small images)
    #image = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    # Apply Gaussian Blur to reduce noise
    #image = cv2.GaussianBlur(image, (5, 5), 0)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 2))
    image = cv2.morphologyEx(image, cv2.MORPH_CLOSE, kernel)

    # Apply thresholding for binarization
    _, image = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    return image

def extract_text_with_tesseract(image):
    """
    Perform OCR using Tesseract on the preprocessed image.
    
    :param image: Preprocessed image.
    :return: Extracted text.
    """
    # Use Tesseract to extract text
    text = pytesseract.image_to_string(image, lang='eng')
    return text

def main(image_path):
    # Step 1: Preprocess the image
    preprocessed_image = preprocess_image(image_path)

    # Step 2: Save the preprocessed image for debugging (optional)
    cv2.imwrite("Result\\Attendee" + sys.argv[3] + "\\preprocessed_image.png", preprocessed_image)

    custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789%'

    # Step 3: Extract text with Tesseract
    #extracted_text = extract_text_with_tesseract(preprocessed_image)
    _, thresholded = cv2.threshold(preprocessed_image, 150, 255, cv2.THRESH_BINARY)
    extracted_text = pytesseract.image_to_string(thresholded, config=custom_config)

    # Step 4: Output the extracted text
    print("Extracted Text:")
    print(extracted_text)
    
    save_string_to_file(extracted_text)

def save_string_to_file(string_input, file_name="output_.txt"):
    """
    Save the input string to a .txt file in the current directory.
    
    :param string_input: The string to save in the file.
    :param file_name: The name of the output file (default: output.txt).
    """
    try:
        file_name = "Result\\Attendee" + sys.argv[3] + "\\OUTPUT_Test.txt"
        # Open the file in write mode
        with open(file_name, 'w') as file:
            file.write(string_input)
        print(f"String saved to {file_name} successfully!")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    # Input image path
    image_path = sys.argv[1]  # Replace with your image path
    #image_path = "Testing.png"
    main(image_path)