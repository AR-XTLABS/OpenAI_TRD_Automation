import datetime
import os
import pyodbc
import io
import base64
import cv2
import numpy as np
import pandas as pd
import json
import shutil
from PIL import Image
from pdf2image import convert_from_path
import concurrent.futures
from prompt.identity_stamp import identitystamp
from prompt.message import systemmessage
from prompt.changes import changes_initialed
from openai import OpenAI

# ---------------- CONFIGURATION ----------------
# Replace with your actual credentials and paths
SERVER = 'YOUR_SERVER'
DATABASE = 'YOUR_DATABASE'
USERNAME = 'YOUR_USERNAME'
PASSWORD = 'YOUR_PASSWORD'

# GPT or OpenAI key (if needed)
os.environ["OPENAI_API_KEY"] = "YOUR_OPENAI_API_KEY_HERE"

INPUT_FOLDER = "input_excel"       # Folder where .xls or .xlsx files are read
OUTPUT_FOLDER = "outputs"          # Folder to store final output Excel
TEMP_IMAGES_DIR = "temp_images"    # Base directory for storing reference subfolders
PDF_FOLDER = ""
MAX_WORKERS = 5                    # Number of parallel threads (rows processed in parallel)
# ------------------------------------------------

def get_connection():
    """
    Returns a pyodbc connection to SQL Server.
    """
    connection_string = (
        f'DRIVER={{SQL Server}};'
        f'SERVER={SERVER};'
        f'DATABASE={DATABASE};'
        f'UID={USERNAME};'
        f'PWD={PASSWORD}'
    )
    return pyodbc.connect(connection_string)

def create_tables():
    """
    Creates (if not exists) the tables:
      - tbl_excel_tracking
      - tbl_processing_result
    with the required schema.
    """
    create_tracking_table = """
    IF NOT EXISTS (
        SELECT * FROM sysobjects
        WHERE name='tbl_excel_tracking' AND xtype='U'
    )
    CREATE TABLE tbl_excel_tracking (
        id INT IDENTITY(1,1) PRIMARY KEY,
        excel_name VARCHAR(255),
        createtimestamp DATETIME DEFAULT GETDATE(),
        isread BIT DEFAULT 0
    );
    """

    create_processing_table = """
    IF NOT EXISTS (
        SELECT * FROM sysobjects
        WHERE name='tbl_processing_result' AND xtype='U'
    )
    CREATE TABLE tbl_processing_result (
        id INT IDENTITY(1,1) PRIMARY KEY,
        tracking_id INT NOT NULL,
        projectid VARCHAR(50),
        referencenumber VARCHAR(50),
        documenttype VARCHAR(100),
        pdf_path VARCHAR(500),
        borrower VARCHAR(255),
        amount DECIMAL(18,2),
        propertyaddress VARCHAR(500),
        notedate VARCHAR(50),
        minnumber VARCHAR(50),
        maturitydate VARCHAR(50),
        output TEXT,
        overallconfidence FLOAT,
        FOREIGN KEY (tracking_id) REFERENCES tbl_excel_tracking(id)
    );
    """

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(create_tracking_table)
        cursor.execute(create_processing_table)
        conn.commit()

def insert_excel_tracking_record(file_name: str) -> int:
    """
    Inserts a new record into tbl_excel_tracking with the given file name.
    Returns the newly inserted record ID (tracking_id).
    """
    query = """
        INSERT INTO tbl_excel_tracking (excel_name, isread)
        OUTPUT INSERTED.id
        VALUES (?, 0)
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (file_name,))
        new_id = cursor.fetchone()[0]
        conn.commit()
    print(f"Inserted '{file_name}' into tbl_excel_tracking with ID = {new_id}")
    return new_id

def update_tracking_isread(tracking_id: int):
    """
    Sets isread = 1 for the given tracking_id in tbl_excel_tracking.
    """
    query = """
        UPDATE tbl_excel_tracking
        SET isread = 1
        WHERE id = ?
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (tracking_id,))
        conn.commit()
    print(f"Updated tbl_excel_tracking.isread = 1 for ID = {tracking_id}")

def insert_processing_result(
    tracking_id: int,
    projectid: str,
    referencenumber: str,
    documenttype: str,
    pdf_path: str,
    borrower: str,
    amount: float,
    propertyaddress: str,
    notedate: str,
    minnumber: str,
    maturitydate: str,
    output: str,
    overallconfidence: float
):
    """
    Inserts a single row's processing result into tbl_processing_result.
    """
    query = """
        INSERT INTO tbl_processing_result (
            tracking_id,
            projectid,
            referencenumber,
            documenttype,
            pdf_path,
            borrower,
            amount,
            propertyaddress,
            notedate,
            minnumber,
            maturitydate,
            output,
            overallconfidence
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (
            tracking_id,
            projectid,
            referencenumber,
            documenttype,
            pdf_path,
            borrower,
            amount,
            propertyaddress,
            notedate,
            minnumber,
            maturitydate,
            output,
            overallconfidence
        ))
        conn.commit()


def convert_pdf_to_images(pdf_path, referenceid, base_temp_dir=TEMP_IMAGES_DIR, pdf_location=PDF_FOLDER):
    """
    Convert a PDF to images with preprocessing for better OCR accuracy.
    Images are saved in a unique subdirectory under base_temp_dir,
    named using 'referenceid'. Additional denoising and dot-noise
    removal techniques are applied to improve text clarity.
    """
    # Create a subfolder for this reference ID
    unique_temp_dir = os.path.join(base_temp_dir, str(referenceid))
    pdf_folder_path = os.path.join(pdf_location, pdf_path)
    os.makedirs(unique_temp_dir, exist_ok=True)

    try:
        # Increase DPI for clearer images
        images = convert_from_path(pdf_folder_path, dpi=350)
        image_paths = []

        for i, image in enumerate(images):
            # Convert PIL Image to OpenCV format
            # opencv_image = np.array(image)

            # # 1) Convert to grayscale
            # gray = cv2.cvtColor(opencv_image, cv2.COLOR_RGB2GRAY)

            # # 2) Use a mild median blur to reduce salt-and-pepper noise
            # gray = cv2.medianBlur(gray, 3)

            # # 3) Binarize using Otsu's Threshold
            # _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

            # # 4) Morphological opening to remove small black specks
            # #    (especially helpful for scanned dot-noise artifacts)
            # kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            # opened = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_open, iterations=1)

            # # 5) Optionally, morphological closing can be used to fill small
            # #    white holes within black text regions (uncomment if needed)
            # # kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            # # cleaned = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel_close, iterations=1)
            # # final_image = cleaned
            # #
            # # If you do not need closing, simply use:
            # final_image = opened

            # Convert back to PIL Image for saving
            # processed_image = Image.fromarray(final_image)

            # Save the processed image
            image_file = os.path.join(unique_temp_dir, f"page_{i + 1}.png")
            image.save(image_file, "PNG")
            image_paths.append(image_file)

        return image_paths
    except Exception as e:
        print(f"Error converting PDF to images for reference {referenceid}: {e}")
        return []

def load_images_for_reference(referenceid, base_temp_dir=TEMP_IMAGES_DIR):
    """
    Loads all PNG images from the specified reference subfolder, renames them
    with the format 'page_{i + 1}.png' where i is the index of the image,
    and sorts them numerically.
    """
    ref_folder = os.path.join(base_temp_dir, str(referenceid))
    images = []
    if not os.path.exists(ref_folder):
        print(f"No folder found for reference {referenceid}.")
        return images
    
    image_files = [f for f in os.listdir(ref_folder) if f.lower().endswith('.png')]
    if not image_files:
        print(f"No PNG images found in folder {ref_folder}.")
        return images

    # Sort files by the numeric value extracted from the filenames
    image_files.sort(key=lambda x: int(x.split('_')[1].split('.')[0]))

    # Load and rename images
    for i, filename in enumerate(image_files):
        file_path = os.path.join(ref_folder, filename)
        try:
            img = Image.open(file_path)
            images.append(img)
        except Exception as e:
            print(f"Error loading image {file_path}: {e}")
    
    return images


def cleanup_temp_images_for_reference(referenceid, base_temp_dir=TEMP_IMAGES_DIR):
    """
    Deletes all PNG files in the subfolder for a given reference ID.
    Then removes the reference subfolder if empty.
    """
    ref_folder = os.path.join(base_temp_dir, str(referenceid))

    if not os.path.exists(ref_folder):
        print(f"The folder '{ref_folder}' does not exist.")
        return


    try:
        shutil.rmtree(ref_folder)
        print(f"Successfully removed the directory: {ref_folder}")
    except Exception as e:
        print(f"Error while cleaning up temporary files for reference: {e}")

def encode_image(image):
    """
    Convert a PIL image to a base64-encoded string.
    """
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def send_conversation_to_gpt(messages, _model="gpt-4o-mini"):
    """
    Send the current conversation to GPT-4 and get the assistant's response.
    """
    client = OpenAI()

    try:
        response = client.chat.completions.create(
            model= _model,
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


def get_output_confidence(all_response):

    # Parse each JSON string into a Python dictionary
    parsed_data = [json.loads(item) for item in all_response]

    # Initialize variables to collect required data
    confidence_scores = []

    # Initialize the transformed data dictionary
    transformed_data = {
        "borrower_validation": None,
        "borrower_notes": None,
        "note_date_validation": None,
        "note_date_notes": None,
        "loan_amount_validation": None,
        "loan_amount_notes": None,
        "maturity_date_validation": None,
        "maturity_date_notes": None,
        "property_address_validation": None,
        "property_address_notes": None,
        "min_validation": None,
        "min_notes": None,
        "document_number": None,
        "book_volume": None,
        "page_number": None,
        "recording_date": None,
        "recording_time": None,
        "recording_fee": None,
        "recorder_clerk_name": None,
        "county_name": None,
        "isdocumentrecorded": None,
        "legal_description_present": None,
        "legal_description_notes": None,
        "borrower_signatures_present": None,
        "borrower_signatures_notes": None,
        "trustee_name_present": None,
        "trustee_name_notes": None,
        "riders_present": None, 
        "riders_notes": None, 
        "mers_rider_present": None,
        "mers_rider_notes": None,
        "page_validation": None,
        "page_validation_notes": None,
        "correction_validation": None,
        "correction_validation_notes": None,
        "document_type":None,
        "property_state":None,
        "confidence_score": 0.0,
    }

    required_keys = {"document_number", "recording_date", "book_volume", "page_number", "recording_fee"}

    # Process each response and map data to transformed_data
    for response in parsed_data:
        if 'loan_data_validation' in response:
            loan_data = response['loan_data_validation']
            transformed_data['borrower_validation'] = loan_data['borrower_validation']['outcome']
            transformed_data['borrower_notes'] = loan_data['borrower_validation']['notes']
            transformed_data['note_date_validation'] = loan_data['note_date_validation']['outcome']
            transformed_data['note_date_notes'] = loan_data['note_date_validation']['notes']
            transformed_data['loan_amount_validation'] = loan_data['loan_amount_validation']['outcome']
            transformed_data['loan_amount_notes'] = loan_data['loan_amount_validation']['notes']
            transformed_data['maturity_date_validation'] = loan_data['maturity_date_validation']['outcome']
            transformed_data['maturity_date_notes'] = loan_data['maturity_date_validation']['notes']
            transformed_data['property_address_validation'] = loan_data['property_address_validation']['outcome']
            transformed_data['property_address_notes'] = loan_data['property_address_validation']['notes']
            transformed_data['min_validation'] = loan_data['min_validation']['outcome']
            transformed_data['min_notes'] = loan_data['min_validation']['notes']
        
        

        if required_keys <= response.keys():

            transformed_data['document_number'] = response.get('document_number', '')
            transformed_data['book_volume'] = response.get('book_volume', '')
            transformed_data['page_number'] = response.get('page_number', '')
            transformed_data['recording_date'] = response.get('recording_date', '')
            transformed_data['recording_time'] = response.get('recording_time', '')
            transformed_data['recording_fee'] = response.get('recording_fee', '')
            transformed_data['recorder_clerk_name'] = response.get('recorder_clerk_name', '')
            transformed_data['county_name'] = response.get('county_name', '')

            if (response.get('recording_date') and response.get('document_number')) or \
            ((response.get('recording_date') or response.get('document_number')) and response.get('book_volume') and response.get('page_number')):
                transformed_data['isdocumentrecorded'] = True
            else:
                transformed_data['isdocumentrecorded'] = False

        if 'document_review' in response:
            doc_review = response['document_review']
            transformed_data['document_type'] = doc_review.get('document_type', '')
            transformed_data['legal_description_notes'] = doc_review.get('legal_description_notes', '')
            transformed_data['legal_description_present'] = doc_review.get('legal_description_present', '')
            transformed_data['borrower_signatures_present'] = doc_review.get('borrower_signatures_present', '')
            transformed_data['borrower_signatures_notes'] = doc_review.get('borrower_signatures_notes', '')
            transformed_data['trustee_name_present'] = doc_review.get('trustee_name_present', 'N/A')
            transformed_data['trustee_name_notes'] = doc_review.get('trustee_name_notes', '')
            transformed_data['property_state'] = doc_review.get('property_state', '')
        
        if 'page_validation' in response:
            page_validation = response['page_validation']
            transformed_data['page_validation'] = page_validation.get('status', '')
            transformed_data['page_validation_notes'] = page_validation.get('details', {}).get('notes', '')

        if 'rider_analysis' in response:
            if response['rider_analysis']:
                rider_analysis = [item for item in response['rider_analysis'] if 'mers' not in item['rider_name'].lower()]
                yes = [item for item in rider_analysis if 'yes' == item['status'].lower()]
                no = [item for item in rider_analysis if 'no' == item['status'].lower()]
                na = [item for item in rider_analysis if 'n/a' == item['status'].lower()]
                if len(yes) + len(na) == len(rider_analysis):
                    transformed_data['riders_present'] = 'Yes'
                    transformed_data['riders_notes'] = ''
                elif any(no):
                    transformed_data['riders_present'] = 'No'
                    transformed_data['riders_notes'] = 'incomplete/ missing'
                elif len(na) == len(rider_analysis):
                    transformed_data['riders_present'] = 'N/A'
                    transformed_data['riders_notes'] = 'unchecked'

                
                if transformed_data['property_state'].lower() in ['montana', 'oregon', 'washington']:
                    mers_rider_analysis = [item for item in response['rider_analysis'] if 'mers' in item['rider_name'].lower()]
                    yes = [item for item in mers_rider_analysis if 'yes' not in item['status'].lower()]
                    no = [item for item in mers_rider_analysis if 'no' not in item['status'].lower()]
                    if any(yes):
                        transformed_data['mers_rider_present'] = 'Yes'
                        transformed_data['mers_rider_notes'] = ''
                    elif any(no):
                        transformed_data['mers_rider_present'] = 'No'
                        transformed_data['mers_rider_notes'] = 'incomplete/ missing'
                else:
                    transformed_data['mers_rider_present'] = 'N/A'
                    transformed_data['mers_rider_notes'] = 'Not present'    
            else:
                transformed_data['riders_present'] = 'N/A'
                transformed_data['riders_notes'] = 'unchecked'

                if transformed_data['property_state'].lower() not in ['montana', 'oregon', 'washington']:
                    transformed_data['mers_rider_present'] = 'N/A'
                    transformed_data['mers_rider_notes'] = 'unchecked'
                else:
                    transformed_data['mers_rider_present'] = 'No'
                    transformed_data['mers_rider_notes'] = 'incomplete/ missing'   

        if 'crossed_out_and_replacement_annotations' in response:
            transformed_data['correction_validation'] = response['crossed_out_and_replacement_annotations']
            transformed_data['correction_validation_notes'] = response['note']
               
            
        if 'confidence_score' in response:
            confidence_scores.append(float(response.get('confidence_score', 0.0)))

    # Calculate average confidence score
    avg_confidence_score = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0
    transformed_data['confidence_score'] = avg_confidence_score

    return transformed_data, avg_confidence_score


def gpt_system_message(system_message,encoded_images):
    conversation = [
            {"role": "system", "content": system_message},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}",
                            "detail": "high"
                        },
                    } for base64_image in encoded_images
                ],
            },
        ]
    _response = send_conversation_to_gpt(conversation)
    return _response

def gpt_identity_stamp(identity_stamp, encoded_images):
    if len(encoded_images) > 4:
        first_two = encoded_images[:2]  # First 2 elements
        last_two = encoded_images[-2:]  # Last 2 elements
        middle = encoded_images[2:-2]  # Middle elements

        # Concatenate first two, reimaged middle, and last two
        _encoded_images =  first_two + last_two + middle 

    for base64_image in _encoded_images:
        conversation = [
            {"role": "system", "content": identity_stamp},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}",
                            "detail": "high"
                        },
                    }
                ],
            },
        ]
        _response = send_conversation_to_gpt(conversation, _model="gpt-4o")
        if _response: 
            __res = json.loads(_response)
            if "document_number" and "recording_date" and "book_volume" and\
                  "page_number" and "recording_fee" and "confidence_score" in  __res\
                and (__res["document_number"] or __res["recording_date"]) and __res["county_name"]\
                    and __res["recorder_clerk_name"]:
                return _response
    return "No valid response received"

def gpt_crossed_Out_and_initiale(crossed_Out_and_initiale, encoded_images):
    conversation = [
            {"role": "system", "content": crossed_Out_and_initiale},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}",
                            "detail": "high"
                        },
                    } for base64_image in encoded_images
                ],
            },
        ]

    _response = send_conversation_to_gpt(conversation, _model="gpt-4o")
    if _response:
        return  _response 
    return {}

def process_single_row(row, tracking_id):
    """
    Processes a single row: convert PDF to images, send images to GPT for multiple prompts,
    parse the final JSON, and returns a dictionary of results to insert into the database.
    """
    try:
        # ------------- EXTRACT ROW DATA -------------
        projectid = row.get('projectid', '')
        referencenumber = row.get('referencenumber', '')
        documenttype = row.get('documenttype', '')
        pdf_path = row.get('pdf_path', '')
        borrower = row.get('borrower', '')
        amount_str = str(row.get('amount', 0.0)) if isinstance(row.get('amount', 0.0), str) else row.get('amount', 0.0)
        loan_amount = float(str(amount_str).replace(',', ''))
        # loan_amount = float(str(row.get('amount', 0.0).replace(',','')))  # ensure float
        property_address = row.get('propertyaddress', '')
        note_date = row.get('notedate', '')
        min_number = row.get('minnumber', '')
        maturity_date = row.get('maturitydate', '')

        # ------------- STEP 1: CONVERT PDF -> IMAGES -------------
        image_paths = convert_pdf_to_images(pdf_path, referenceid=referencenumber)
        if not image_paths:
            print(f"No images were generated from the PDF for reference {referencenumber}.")
            return None
        return {}
        # ------------- STEP 2: LOAD IMAGES -------------
        images = load_images_for_reference(referencenumber)
        if not images:
            print(f"No images found in the subfolder for reference {referencenumber}.")
            return None

        # ------------- STEP 3: ENCODE IMAGES -------------
        encoded_images = [encode_image(img) for img in images]

        # ------------- STEP 4: BUILD INITIAL CONVERSATION -------------
        # For instance, use 'reference_prompt' as your first system message 
        # (or build a dynamic system prompt yourself).
        # Example placeholders:
        print(f'reference number --> {referencenumber}')
        all_response = []
        system_message = systemmessage.replace('{in_borrower}', borrower)\
                                        .replace('{in_min}', str(min_number))\
                                        .replace('{in_note_date}', note_date)\
                                        .replace('{in_maturity_date}', maturity_date)\
                                        .replace('{in_loan_amount}', str(loan_amount))\
                                        .replace('{in_property_address}', property_address)

        _response = gpt_system_message(system_message,encoded_images)
        all_response.append(_response)

        # ------------- STEP 6: PREPARE ADDITIONAL PROMPTS -------------
        # Example: identity_stamp modifies the template with note_date
        identity_stamp = identitystamp.replace('in_note_date', json.dumps({"note_date":note_date}))
        _response = gpt_identity_stamp(identity_stamp,encoded_images)
        all_response.append(_response)

        _response = gpt_crossed_Out_and_initiale(changes_initialed,encoded_images)
        all_response.append(_response)

        # print(all_response)
        final_output, overall_conf = get_output_confidence(all_response)

        # # ------------- STEP 8: CLEAN UP TEMP IMAGES FOR THIS REFERENCE -------------
        cleanup_temp_images_for_reference(referencenumber)

        # ------------- STEP 9: RETURN RESULTS -------------
        return {
            "tracking_id": tracking_id,
            "projectid": projectid,
            "referencenumber": referencenumber,
            "documenttype": documenttype,
            "pdf_path": pdf_path,
            "borrower": borrower,
            "amount": loan_amount,
            "propertyaddress": property_address,
            "notedate": note_date,
            "minnumber": min_number,
            "maturitydate": maturity_date,
            "output": json.dumps(final_output),
            "overallconfidence": overall_conf
        }

    except Exception as e:
        print(f"Error processing row for reference {row.get('referencenumber', 'N/A')}: {e}")
        return None

def main():
    # 1) Ensure tables exist
    create_tables()

    # 2) Fetch list of already tracked Excel files from tbl_excel_tracking
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT excel_name FROM tbl_excel_tracking")
            tracked_files = [row.excel_name for row in cursor.fetchall()]
        print(f"Tracked Excel files: {tracked_files}")
    except Exception as e:
        print(f"Error fetching tracked Excel files: {e}")
        tracked_files = []

    # 3) List all Excel files in INPUT_FOLDER
    if not os.path.exists(INPUT_FOLDER):
        print(f"Input folder '{INPUT_FOLDER}' does not exist. Please create it and add Excel files.")
        return

    all_excel_files = [f for f in os.listdir(INPUT_FOLDER) if f.endswith(('.xls', '.xlsx'))]
    if not all_excel_files:
        print(f"No Excel files found in '{INPUT_FOLDER}'. Exiting.")
        return

    # 4) Filter out Excel files that are already tracked
    excel_files_to_process = [f for f in all_excel_files if f not in tracked_files]
    if not excel_files_to_process:
        print("No new Excel files to process. Exiting.")
        return

    print(f"Excel files to process: {excel_files_to_process}")

    for excel_file in excel_files_to_process:
        # 5) Insert record into tbl_excel_tracking
        tracking_id = insert_excel_tracking_record(excel_file)

        # 6) Read the Excel file
        file_path = os.path.join(INPUT_FOLDER, excel_file)
        print(f"\nReading Excel file: {file_path}")
        try:
            df = pd.read_excel(file_path,dtype=str)
        except Exception as e:
            print(f"Error reading Excel file {file_path}: {e}")
            continue

        row_dicts = df.to_dict(orient="records")

        # 7) Process rows in parallel (thread pool)
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_row = {executor.submit(process_single_row, row, tracking_id): row for row in row_dicts}
            for future in concurrent.futures.as_completed(future_to_row):
                res = future.result()
                if res is not None:
                    results.append(res)

        # 8) Insert results into tbl_processing_result
        for r in results:
            insert_processing_result(
                tracking_id=r["tracking_id"],
                projectid=r["projectid"],
                referencenumber=r["referencenumber"],
                documenttype=r["documenttype"],
                pdf_path=r["pdf_path"],
                borrower=r["borrower"],
                amount=r["amount"],
                propertyaddress=r["propertyaddress"],
                notedate=r["notedate"],
                minnumber=r["minnumber"],
                maturitydate=r["maturitydate"],
                output=json.dumps(r["output"]),
                overallconfidence=r["overallconfidence"]
            )

        # 9) Build two lists for "Auto Submit" and "Need to Review"
        auto_submit = []
        need_review = []
        for r in results:
            if r["overallconfidence"] < 0.9:
                need_review.append(r)
            else:
                auto_submit.append(r)

        # 10) Create DataFrames
        df_auto = pd.DataFrame(auto_submit)
        df_review = pd.DataFrame(need_review)

        # 11) Create a unique name for the output Excel
        current_datetime = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_file_name = f"{os.path.splitext(excel_file)[0]}_output_{current_datetime}.xlsx"
        output_path = os.path.join(OUTPUT_FOLDER, output_file_name)

        # 12) Ensure output folder exists
        if not os.path.exists(OUTPUT_FOLDER):
            os.makedirs(OUTPUT_FOLDER)
            print(f"Created output folder '{OUTPUT_FOLDER}'.")

        # 13) Write both sheets
        try:
            with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
                if not df_auto.empty:
                    df_auto.to_excel(writer, sheet_name="Auto Submit", index=False)
                if not df_review.empty:
                    df_review.to_excel(writer, sheet_name="Need to Review", index=False)
            print(f"Created output Excel: {output_path}")
        except Exception as e:
            print(f"Error writing output Excel file '{output_path}': {e}")

        # 14) Update tbl_excel_tracking.isread = 1
        update_tracking_isread(tracking_id)

    print("\nAll new Excel files have been processed.")

# --------------------- ENTRY POINT ---------------------
if __name__ == "__main__":
    main()

