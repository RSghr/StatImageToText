from PIL import Image
import sys

def process_stat(input_image_path, output_folder):
    # Load the image
    img = Image.open(input_image_path)

    # Slice the image into four 452x745 pixel images
    slices = []
    slice_height = 45

    for i in range(8):  # Slice per stat
        left = 0
        upper = 0
        right = left + img.width
        if i == 0 :
            lower = upper + slice_height
        elif i > 5:
            lower = upper + (i + 1) * slice_height + 25
            upper = upper + 25 + i * slice_height
        else :
            lower = upper + (i + 1) * slice_height + 10
            upper = upper + 10 + i * slice_height
        
        #Crop the slice
        slice_img = img.crop((left, upper, right - 25, lower))

        #Save the slice
        slice_path = f"{output_folder}/Stat_slice_{i}.png"
        slice_img.save(slice_path)
        slices.append(slice_path)

    return slices

def main():
    output_folder = "Result\\Slices"
    #input_image_path = f"{output_folder}/final_0.png"
    input_image_path = sys.argv[1]
    final_images = process_stat(input_image_path, output_folder)
    print("Processing complete. Final images saved:", final_images)

if __name__ == "__main__":
    main()