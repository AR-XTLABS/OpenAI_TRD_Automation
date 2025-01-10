
import datetime
import os
import openpyxl
import pyodbc
import io
import base64
import cv2
import numpy as np
from pdf2image import convert_from_path
from PIL import Image
from openai import OpenAI
import pandas as pd
import json
from prompt.identity_stamp import identitystamp
from prompt.changes import changes_prompt
from prompt.legal import legal_prompt
from prompt.pages import pages_prompt
from prompt.reference import reference_prompt
from prompt.rider import riders_prompt
from prompt.score import Score_prompt

# Constants
TEMP_IMAGES_DIR = "temp_images"
server = 'your_server_name'
database = 'your_database_name'
username = 'your_username'
password = 'your_password'
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


# def update_excel_file(output_path, row_data, sheet_name):
#     # Standardize row_data column names
#     standardized_row_data = {key.lower(): value for key, value in row_data.items()}
    
#     if os.path.exists(output_path):
#         with pd.ExcelWriter(output_path, mode="a", engine="openpyxl", if_sheet_exists="overlay") as writer:
#             try:
#                 # Read the sheet
#                 existing_df = pd.read_excel(output_path, sheet_name=sheet_name)

#                 # Standardize column names
#                 existing_df.columns = existing_df.columns.str.strip().str.lower()
#                 reference_column = "referencenumber"

#                 # Check if the column exists
#                 if reference_column not in existing_df.columns:
#                     print(f"Column '{reference_column}' not found in the sheet. Initializing new DataFrame.")
#                     updated_df = pd.DataFrame([standardized_row_data])
#                 else:
#                     # Check if the reference number already exists
#                     if standardized_row_data["referencenumber"] in existing_df[reference_column].values:
#                         # Update the row
#                         existing_df.loc[
#                             existing_df[reference_column] == standardized_row_data["referencenumber"], :
#                         ] = pd.DataFrame([standardized_row_data])
#                         updated_df = existing_df
#                     else:
#                         # Append the new row
#                         row_df = pd.DataFrame([standardized_row_data])
#                         row_df = row_df.reindex(columns=existing_df.columns, fill_value=None)
#                         updated_df = pd.concat([existing_df, row_df], ignore_index=True)
#             except ValueError:
#                 print(f"Sheet '{sheet_name}' not found. Creating new sheet.")
#                 # If the sheet does not exist, create a new one with standardized columns
#                 updated_df = pd.DataFrame([standardized_row_data])

#             # Write back to the same sheet
#             updated_df.to_excel(writer, sheet_name=sheet_name, index=False)
#     else:
#         print(f"File '{output_path}' not found. Creating new file and initializing sheets.")
#         with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
#             auto_submit_df = pd.DataFrame(columns=row_data.keys())
#             need_review_df = pd.DataFrame(columns=row_data.keys())
#             auto_submit_df.to_excel(writer, sheet_name="Auto Submit", index=False)
#             need_review_df.to_excel(writer, sheet_name="Need to Review", index=False)

#         update_excel_file(output_path, row_data, sheet_name)

def insert_file_tracking(file_name):


    # Create the connection string
    connection_string = f'DRIVER={{SQL Server}};SERVER={server};DATABASE={database};UID={username};PWD={password}'

    try:
        # Connect to the database
        connection = pyodbc.connect(connection_string)
        cursor = connection.cursor()

        # SQL query to insert data into the table
        insert_query = """
            INSERT INTO dbo.tbl_excel_tracking (output_excel, createtimestamp, isread)
            VALUES (?, ?, ?)
        """

        # Parameters to be inserted
        params = (file_name, datetime.datetime.now(), 1)  # '1' for TRUE in BIT column

        # Execute the query
        cursor.execute(insert_query, params)

        # Commit the transaction
        connection.commit()

        # Close the cursor and connection
        cursor.close()
        connection.close()

        print(f"Inserted file name {file_name} into the database successfully.")

    except Exception as e:
        print(f"An error occurred: {e}")





def update_excel_file(folder_path, file_name, row_data, sheet_name):
    """
    Updates or creates an Excel file in the specified folder with the given data and sheet name.
    
    Args:
        folder_path (str): Path to the folder where the Excel file will be stored.
        file_name (str): Name of the Excel file.
        row_data (dict): Data to be added or updated in the Excel file.
        sheet_name (str): Name of the sheet to update.
    """
    # Ensure the folder exists
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
    
    # Construct the full path to the Excel file
    output_path = os.path.join(folder_path, file_name)
    
    # Standardize row_data column names
    standardized_row_data = {key.lower(): value for key, value in row_data.items()}
    
    if os.path.exists(output_path):
        with pd.ExcelWriter(output_path, mode="a", engine="openpyxl", if_sheet_exists="overlay") as writer:
            try:
                # Read the sheet
                existing_df = pd.read_excel(output_path, sheet_name=sheet_name)

                # Standardize column names
                existing_df.columns = existing_df.columns.str.strip().str.lower()
                reference_column = "referencenumber"

                # Check if the column exists
                if reference_column not in existing_df.columns:
                    print(f"Column '{reference_column}' not found in the sheet. Initializing new DataFrame.")
                    updated_df = pd.DataFrame([standardized_row_data])
                else:
                    # Check if the reference number already exists
                    if standardized_row_data["referencenumber"] in existing_df[reference_column].values:
                        # Update the row
                        existing_df.loc[
                            existing_df[reference_column] == standardized_row_data["referencenumber"], :
                        ] = pd.DataFrame([standardized_row_data])
                        updated_df = existing_df
                    else:
                        # Append the new row
                        row_df = pd.DataFrame([standardized_row_data])
                        row_df = row_df.reindex(columns=existing_df.columns, fill_value=None)
                        updated_df = pd.concat([existing_df, row_df], ignore_index=True)
            except ValueError:
                print(f"Sheet '{sheet_name}' not found. Creating new sheet.")
                # If the sheet does not exist, create a new one with standardized columns
                updated_df = pd.DataFrame([standardized_row_data])

            # Write back to the same sheet
            updated_df.to_excel(writer, sheet_name=sheet_name, index=False)
    else:
        print(f"File '{output_path}' not found. Creating new file and initializing sheets.")
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            auto_submit_df = pd.DataFrame(columns=row_data.keys())
            need_review_df = pd.DataFrame(columns=row_data.keys())
            auto_submit_df.to_excel(writer, sheet_name="Auto Submit", index=False)
            need_review_df.to_excel(writer, sheet_name="Need to Review", index=False)

        update_excel_file(folder_path, file_name, row_data, sheet_name)

        


# 5. Main Function
def main():
    input_folder = "input_excel"
    output_folder_path = "outputs"

    # List all Excel files in the folder
    excel_files = [f for f in os.listdir(input_folder) if f.endswith(('.xls', '.xlsx'))]

    # Process each Excel file one by one
    for excel_file in excel_files:
        file_path = os.path.join(input_folder, excel_file)
        print(f"Processing file: {file_path}")

        # Read the Excel file
        df = pd.read_excel(file_path)
        response_list = []
        sheet_name =""
        for index, row in df.iterrows():
            # Access specific columns by name
            projectids = row['projectid']
            referenceid = row['referencenumber']
            documenttype = row['documenttype']
            pdf_path = row['pdf_path']
            borrower = row['borrower']
            loan_amount = row['amount']
            property_address = row['propertyaddress']
            note_date = row['notedate']
            min_number = row['minnumber']
            maturity_date = row['maturitydate']
            pdf_path = r""+pdf_path
            output_folder_path = r"outputs"

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

            # Use f-string formatting to replace the placeholders with actual values
            system_messages = reference_prompt.replace('{Borrower}',borrower).replace('{MIN}',str(min_number))\
            .replace('{Note_Date}',note_date).replace('{Maturity_Date}',maturity_date).replace('{Loan_Amount}',str(loan_amount)).replace('{Property_Address}',property_address)

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

            print("\nInitial Response from GPT-4:\n", initial_response)
            # response_list.append(initial_response)
            identity_stamp = identitystamp.replace('{SecurityInstrumentDate}',note_date)
            # Step 7: Additional User Prompts (Up to 5)
            additional_prompts = [
                identity_stamp,
                # stamp_prompt,
                legal_prompt,
                pages_prompt,
                changes_prompt,
                riders_prompt,
                Score_prompt
            ]
            length = len(additional_prompts)
            for i, prompt in enumerate(additional_prompts, start=1):
            
                conversation.append({"role": "user", "content": prompt})

                # Get GPT's Response
                response = send_conversation_to_gpt(conversation)
                conversation.append({"role": "assistant", "content": response})

                print(f"Response to Prompt {i}:\n{response}")
                
                if i == length:
                    response = json.loads(response)
                    output = response['MergedResponse']
                    OverallConfidence = response['OverallConfidence']

                    # Determine the sheet name
                    sheet_name = "Need to Review" if OverallConfidence < 0.9 else "Auto Submit"

                    # Prepare row data for the sheet
                    row_data = {
                        "ProjectId": projectids,
                        "ReferenceNumber": referenceid,
                        "DocumentType": documenttype,
                        "Output": output,
                        "OverallConfidence": OverallConfidence,
                    }
                    response_list.append(row_data)
                    
                                
            try:
                if os.path.exists(TEMP_IMAGES_DIR):
                    for file_name in os.listdir(TEMP_IMAGES_DIR):
                        file_path = os.path.join(TEMP_IMAGES_DIR, file_name)
                        # Check if it's a file before deleting
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                            print(f"Deleted file: {file_path}")
                    print("All files have been deleted successfully.")
                else:
                    print(f"The folder '{TEMP_IMAGES_DIR}' does not exist.")
            except Exception as e:
                print(f"An error occurred: {e}")
            print("\nAll prompts processed. Conversation history complete.")
            
        
        current_datetime = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_name = f"{excel_file}_output_{current_datetime}.xlsx"
        for item in response_list:
            update_excel_file(output_folder_path, file_name, item, sheet_name)
        print(f"Excel file has been updated: {file_name}")
        insert_file_tracking(file_name)
if __name__ == "__main__":
    main()
