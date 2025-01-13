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
from prompt.legal import legal_prompt
from prompt.pages import pages_prompt
from prompt.reference import reference_prompt
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
    Images are saved in a unique subdirectory under base_temp_dir, named with 'referenceid'.
    """
    
    # Create a subfolder for this reference ID
    unique_temp_dir = os.path.join(base_temp_dir, str(referenceid))
    pdf_folder_path = os.path.join(pdf_location, pdf_path)
    os.makedirs(unique_temp_dir, exist_ok=True)

    try:
        images = convert_from_path(pdf_folder_path, dpi=350)
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
            image_file = os.path.join(unique_temp_dir, f"page_{i + 1}.png")
            processed_image.save(image_file, "PNG")
            image_paths.append(image_file)

        return image_paths
    except Exception as e:
        print(f"Error converting PDF to images for reference {referenceid}: {e}")
        return []

def load_images_for_reference(referenceid, base_temp_dir=TEMP_IMAGES_DIR):
    """
    Loads all PNG images from the specified reference subfolder.
    """
    ref_folder = os.path.join(base_temp_dir, str(referenceid))
    images = []
    if not os.path.exists(ref_folder):
        print(f"No folder found for reference {referenceid}.")
        return images
    
    for filename in os.listdir(ref_folder):
        if filename.lower().endswith('.png'):
            file_path = os.path.join(ref_folder, filename)
            try:
                img = Image.open(file_path)
                images.append(img)
                print(f"Loaded image: {file_path}")
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

def send_conversation_to_gpt(messages):
    """
    Send the current conversation to GPT-4 and get the assistant's response.
    """
    client = OpenAI()

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
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
from statistics import mean
def get_output_confidence(all_response):
    # Parse each JSON string into a Python dictionary
    parsed_data = [json.loads(item) for item in all_response]

    # Initialize variables to collect required data
    overall_validation_notes = []
    confidence_scores = []
    context_lines = []

    # Initialize the transformed data dictionary
    transformed_data = {
        "BorrowerMatches": None,
        "BorrowerNotes": None,
        "DateMatches": None,
        "DateNotes": None,
        "LoanAmountMatches": None,
        "LoanAmountNotes": None,
        "MaturityDateMatches": None,
        "MaturityDateNotes": None,
        "PropertyAddressMatches": None,
        "PropertyAddressNotes": None,
        "MINMatches": None,
        "MINNotes": None,
        "DocumentNumber": None,
        "Book": None,
        "Page": None,
        "RecordingDate": None,
        "RecordingTime": None,
        "RecordingFee": None,
        "CountyRecorderName": None,
        "CountyName": None,
        "IsDocumentRecorded": None,
        "LegalDescriptionIncluded": None,
        "LegalDescriptionNotes": None,
        "PartiesSigned": None,
        "PartiesSignedNotes": None,
        "TrusteeNameProvided": None,
        "TrusteeNameNotes": None,
        "AllPagesPresent": None,
        "AllPagesPresentNotes": None,
        "ChangesInitialed": None,
        "ChangesInitialedNotes": None,
        "AllRidersPresent": None,
        "MERSRiderPresent": None,
        "AllRidersNotes": None,
        "MERSRiderNotes": None,
        "AllValidationNotes": "",
        "ConfidenceScore": 0.0,
        "ContextLines": []
    }

    # Iterate through each parsed JSON object
    for item in parsed_data:
        # Aggregate Overall Validation Notes
        if "AllValidationNotes" in item and item["AllValidationNotes"].strip():
            overall_validation_notes.append(item["AllValidationNotes"])
        
        # Collect Confidence Scores
        if "ConfidenceScore" in item:
            confidence_scores.append(item["ConfidenceScore"])
        
        # Extract specific fields
        # Borrower and Loan Details
        transformed_data["BorrowerMatches"] = item.get("BorrowerMatches", transformed_data["BorrowerMatches"])
        transformed_data["BorrowerNotes"] = item.get("BorrowerNotes", transformed_data["BorrowerNotes"])
        transformed_data["DateMatches"] = item.get("DateMatches", transformed_data["DateMatches"])
        transformed_data["DateNotes"] = item.get("DateNotes", transformed_data["DateNotes"])
        transformed_data["LoanAmountMatches"] = item.get("LoanAmountMatches", transformed_data["LoanAmountMatches"])
        transformed_data["LoanAmountNotes"] = item.get("LoanAmountNotes", transformed_data["LoanAmountNotes"])
        transformed_data["MaturityDateMatches"] = item.get("MaturityDateMatches", transformed_data["MaturityDateMatches"])
        transformed_data["MaturityDateNotes"] = item.get("MaturityDateNotes", transformed_data["MaturityDateNotes"])
        transformed_data["PropertyAddressMatches"] = item.get("PropertyAddressMatches", transformed_data["PropertyAddressMatches"])
        transformed_data["PropertyAddressNotes"] = item.get("PropertyAddressNotes", transformed_data["PropertyAddressNotes"])
        transformed_data["MINMatches"] = item.get("MINMatches", transformed_data["MINMatches"])
        transformed_data["MINNotes"] = item.get("MINNotes", transformed_data["MINNotes"])
        
        # Recording Stamp Details from Occurrences
        if "Occurrences" in item:
            for occurrence in item["Occurrences"]:
                if "RecordingStamp" in occurrence:
                    recording_stamp = occurrence["RecordingStamp"]
                    transformed_data["DocumentNumber"] = recording_stamp.get("DocumentNumber", transformed_data["DocumentNumber"])
                    transformed_data["Book"] = recording_stamp.get("Book", transformed_data["Book"])
                    transformed_data["Page"] = recording_stamp.get("Page", transformed_data["Page"])
                    transformed_data["RecordingDate"] = recording_stamp.get("RecordingDate", transformed_data["RecordingDate"])
                    transformed_data["RecordingTime"] = recording_stamp.get("RecordingTime", transformed_data["RecordingTime"])
                    transformed_data["RecordingFee"] = recording_stamp.get("RecordingFee", transformed_data["RecordingFee"])
                    transformed_data["CountyRecorderName"] = recording_stamp.get("CountyRecorderName", transformed_data["CountyRecorderName"])
                    transformed_data["CountyName"] = recording_stamp.get("CountyName", transformed_data["CountyName"])
                    transformed_data["IsDocumentRecorded"] = recording_stamp.get("IsDocumentRecorded", transformed_data["IsDocumentRecorded"])
                
                # Collect Context Lines
                if "ContextLines" in occurrence:
                    for context in occurrence["ContextLines"]:
                        text = context.get("text", "").strip()
                        if text:
                            context_lines.append(text)
        
        # Legal and Riders Information
        transformed_data["LegalDescriptionIncluded"] = item.get("LegalDescriptionIncluded", transformed_data["LegalDescriptionIncluded"])
        transformed_data["LegalDescriptionNotes"] = item.get("LegalDescriptionNotes", transformed_data["LegalDescriptionNotes"])
        transformed_data["PartiesSigned"] = item.get("PartiesSigned", transformed_data["PartiesSigned"])
        transformed_data["PartiesSignedNotes"] = item.get("PartiesSignedNotes", transformed_data["PartiesSignedNotes"])
        transformed_data["TrusteeNameProvided"] = item.get("TrusteeNameProvided", transformed_data["TrusteeNameProvided"])
        transformed_data["TrusteeNameNotes"] = item.get("TrusteeNameNotes", transformed_data["TrusteeNameNotes"])
        transformed_data["AllRidersPresent"] = item.get("AllRidersPresent", transformed_data["AllRidersPresent"])
        transformed_data["MERSRiderPresent"] = item.get("MERSRiderPresent", transformed_data["MERSRiderPresent"])
        transformed_data["AllRidersNotes"] = item.get("AllRidersNotes", transformed_data["AllRidersNotes"])
        transformed_data["MERSRiderNotes"] = item.get("MERSRiderNotes", transformed_data["MERSRiderNotes"])
        
        # Page and Corrections Validation
        if "PageValidation" in item:
            transformed_data["AllPagesPresent"] = item["PageValidation"].get("AllPagesPresent", transformed_data["AllPagesPresent"])
            transformed_data["AllPagesPresentNotes"] = item["PageValidation"].get("AllPagesPresentNotes", transformed_data["AllPagesPresentNotes"])
        if "CorrectionsValidation" in item:
            transformed_data["ChangesInitialed"] = item["CorrectionsValidation"].get("ChangesInitialed", transformed_data["ChangesInitialed"])
            transformed_data["ChangesInitialedNotes"] = item["CorrectionsValidation"].get("ChangesInitialedNotes", transformed_data["ChangesInitialedNotes"])
        
        # Collect Context Lines if present outside Occurrences
        # (In the provided data, ContextLines are only within Occurrences)
        # If needed, add similar extraction here
        
    # Combine all Overall Validation Notes
    transformed_data["AllValidationNotes"] = " ".join(overall_validation_notes)

    # Calculate the average Confidence Score
    if confidence_scores:
        transformed_data["ConfidenceScore"] = round(mean(confidence_scores), 2)

    # Add collected Context Lines
    transformed_data["ContextLines"] = context_lines

    # Optional: Remove None values for cleaner output
    # transformed_data_cleaned = {k: v for k, v in transformed_data.items() if v is not None and v != ""}

    # Output the transformed data as a JSON string with indentation for readability
    print(json.dumps(transformed_data, indent=4))

    return transformed_data, transformed_data["ConfidenceScore"]
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
        system_messages = reference_prompt.replace('{Borrower}', borrower)\
                                        .replace('{MIN}', str(min_number))\
                                        .replace('{Note_Date}', note_date)\
                                        .replace('{Maturity_Date}', maturity_date)\
                                        .replace('{Loan_Amount}', str(loan_amount))\
                                        .replace('{Property_Address}', property_address)

        # Start conversation with system + user (images)
        conversation = [
            {"role": "system", "content": system_messages},
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
        all_response = []
        # ------------- STEP 5: FIRST GPT RESPONSE (INITIAL) -------------
        print(f"Sending initial request to GPT-4 for reference {referencenumber}...")
        initial_response = send_conversation_to_gpt(conversation)
        all_response.append(initial_response)
        # Add the assistant response to the conversation history
        conversation.append({"role": "assistant", "content": initial_response})

        # ------------- STEP 6: PREPARE ADDITIONAL PROMPTS -------------
        # Example: identity_stamp modifies the template with note_date
        identity_stamp = identitystamp.replace('{SecurityInstrumentDate}', note_date)

        # Define your additional prompts
        additional_prompts = [
            identity_stamp,
            legal_prompt,
            pages_prompt
        ]

        # ------------- STEP 7: SEND EACH ADDITIONAL PROMPT -------------
        final_output = ""
        overall_conf = 0.0
        for i, prompt in enumerate(additional_prompts):
            # Add user prompt
            conversation.append({"role": "user", "content": prompt})

            # Get GPT's response
            response = send_conversation_to_gpt(conversation)
            # Add assistant's response to the conversation
            conversation.append({"role": "assistant", "content": response})
            all_response.append(response)
            # If this is the last prompt, parse the final JSON
        final_output, overall_conf = get_output_confidence(all_response)
        # ------------- STEP 8: CLEAN UP TEMP IMAGES FOR THIS REFERENCE -------------
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
            "output": final_output,
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
            df = pd.read_excel(file_path)
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

