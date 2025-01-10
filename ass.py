
import os

import io
import base64
import cv2
import numpy as np
from pdf2image import convert_from_path
from PIL import Image
from openai import OpenAI

# Constants
TEMP_IMAGES_DIR = "temp_images"

# 1. PDF to Image Conversion
def convert_pdf_to_images(pdf_path, temp_dir=TEMP_IMAGES_DIR):
    """
    Convert a PDF to images with preprocessing for better OCR accuracy.
    Images are saved in the specified temp directory.
    """
    try:
        images = convert_from_path(pdf_path, dpi=350)
        os.makedirs(temp_dir, exist_ok=True)
        image_paths = []

        for i, image in enumerate(images):
            # Preprocess image with OpenCV
            opencv_image = np.array(image)
            gray = cv2.cvtColor(opencv_image, cv2.COLOR_RGB2GRAY)
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

            # Save the processed image
            processed_image = Image.fromarray(thresh)
            image_file = os.path.join(temp_dir, f"page_{i + 1}.png")
            processed_image.save(image_file, "PNG")
            image_paths.append(image_file)

        return image_paths
    except Exception as e:
        print(f"Error converting PDF to images: {e}")
        return []

# 2. Load Images
def load_images_from_folder(folder_path):
    """
    Load all PNG images from a specified folder into a list of PIL Images.
    """
    images = []
    for filename in os.listdir(folder_path):
        if filename.lower().endswith('.png'):
            try:
                img = Image.open(os.path.join(folder_path, filename))
                images.append(img)
                print(f"Loaded image: {filename}")
            except Exception as e:
                print(f"Error loading image {filename}: {e}")
    return images

# 3. Encode Images as Base64
def encode_image(image):
    """
    Convert a PIL image to a base64-encoded string.
    """
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

# 4. Send Conversation to GPT-4
def send_conversation_to_gpt(messages):
    """
    Send the current conversation to GPT-4 and get the assistant's response.
    """
    client = OpenAI()

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=1,
            response_format={
                            "type": "json_object"
                            }
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error communicating with GPT: {e}")
        return "An error occurred while processing your request."

from prompt.identity_stamp import identitystamp
from prompt.stamp import stamp_prompt
from prompt.changes import changes_prompt
from prompt.legal import legal_prompt
from prompt.pages import pages_prompt
from prompt.reference import reference_prompt
from prompt.rider import riders_prompt
from prompt.score import Score_prompt

# 5. Main Function
def main():
    # Input: Path to PDF
    pdf_path = r"C:\Users\sriram.bhavadish\Downloads\CC8020122PC_16002305611327_Recorded Mortgage.pdf"

    # Step 1: Convert PDF to Images
    image_paths = convert_pdf_to_images(pdf_path)
    if not image_paths:
        print("No images were generated from the PDF. Exiting.")
        return

    # Step 2: Load Images
    images = load_images_from_folder(TEMP_IMAGES_DIR)
    if not images:
        print("No images found in the temporary directory. Exiting.")
        return

    # Step 3: Encode Images
    encoded_images = [encode_image(img) for img in images]

    # Step 4: Prepare System Prompt
    
    # Define the values for each reference field
    borrower = "Boris feldman"
    min_number = "100719100024547224"
    note_date = "06/14/2023"
    maturity_date = "04/01/2054"
    loan_amount = "430500"
    property_address = "7403 Durham Avenue , North Bergen Nj 07047"

    # Use f-string formatting to replace the placeholders with actual values
    system_messages = reference_prompt.replace('{Borrower}',borrower).replace('{MIN}',min_number)\
    .replace('{Note_Date}',note_date).replace('{Maturity_Date}',maturity_date).replace('{Loan_Amount}',loan_amount).replace('{Property_Address}',property_address)

    # Step 5: Initialize Conversation
    conversation = [
        {
            "role": "system",
            "content": system_messages},
        {
            "role": "user",
            "content": [
                *[
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}",
                            "detail": "high"  # or "low", "auto" as per your need
                        },
                    } for base64_image in encoded_images
                ]
            ],
        }
    ]

    # Step 6: Send Initial Request
    print("Sending initial request to GPT-4...")
    initial_response = send_conversation_to_gpt(conversation)
    conversation.append({"role": "assistant", "content": initial_response})

    # print("\nInitial Response from GPT-4:\n", initial_response)
    identity_stamp = identitystamp.replace('{SecurityInstrumentDate}',note_date)
    # Step 7: Additional User Prompts (Up to 5)
    additional_prompts = [
        identity_stamp,
        legal_prompt,
        pages_prompt,
        changes_prompt,
        riders_prompt,
        Score_prompt
    ]

    for i, prompt in enumerate(additional_prompts, start=1):
       
        conversation.append({"role": "user", "content": prompt})

        # Get GPT's Response
        response = send_conversation_to_gpt(conversation)
        conversation.append({"role": "assistant", "content": response})

        print(f"Response to Prompt {i}:\n{response}")

    print("\nAll prompts processed. Conversation history complete.")
    os.removedirs(TEMP_IMAGES_DIR)

if __name__ == "__main__":
    main()
