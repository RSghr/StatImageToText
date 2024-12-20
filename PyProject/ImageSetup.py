from PIL import Image
import sys

def process_image(input_image_path, output_folder):
    # Load the image
    img = Image.open(input_image_path)

    # Resize the image to 1818x745 pixels
    resized_img = img.resize((1818, 745))

    # Save resized image (optional, for debugging)
    resized_img.save(f"{output_folder}\\resized_image.png")

    # Slice the image into four 452x745 pixel images
    slices = []
    slice_width = 450
    slice_height = 450

    for i in range(4):  # Slice vertically
        left = i * slice_width
        upper = 150
        right = left + slice_width
        lower = upper + slice_height
        
        #Crop the slice
        slice_img = resized_img.crop((left, upper, right, lower))

        #Save the slice
        slice_path = f"{output_folder}/slice_{i}.png"
        slice_img.save(slice_path)
        slices.append(slice_path)

    # Process each slice to take only the first sliceNumberStat pixels from the right
    sliceNumberStat = 150

    final_images = []
    for idx, slice_path in enumerate(slices):
        slice_img = Image.open(slice_path)

        # Calculate cropping area for the rightmost sliceNumberStat pixels
        slice_width, slice_height = slice_img.size
        left = slice_width - sliceNumberStat
        upper = 0
        right = slice_width
        lower = slice_height

        # Crop the rightmost sliceNumberStat pixels
        cropped_img = slice_img.crop((left, upper, right, lower))

        # Save the cropped image
        final_path = f"{output_folder}\\final_{idx}.png"
        cropped_img.save(final_path)
        final_images.append(final_path)

    return final_images

def main():
    input_image_path = sys.argv[1]
    output_folder = "Result\\Slices"
    final_images = process_image(input_image_path, output_folder)
    print("Processing complete. Final images saved:", final_images)

if __name__ == "__main__":
    main()