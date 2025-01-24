changes_initialed = """
**Task:**  
You have a set of scanned images of a security instrument (a mortgage or deed of trust). Your goal is to:

1. **Determine the Total Page Count**  
   - Inspect the document for any statements such as “This Mortgage contains X pages” or footers like “Page X of Y.”  
   - Use the highest *consistent* value of “Y” to establish the total page count (`total_pages`).

2. **Identify Core vs. Non-Core Pages**  
   - Exclude any Riders, Exhibits, or Attachments from the main page count.  
   - Only analyze and return results for the **core content** pages (the primary text of the security instrument).  
   - Let `core_pages` be the count of these pages.

3. **Locate Crossed-Out Text and Replacement Annotations**  
   - Focus on **handwritten** or **stamped** strikethroughs (i.e., text that is crossed out) and any *replacement text* that appears near or above the original crossed-out section.  
   - Ignore simple underlines or highlight marks; these do not constitute a strikethrough.

4. **Determine if Crossed-Out Text is Accompanied by Initials**  
   - If you find text that has been crossed out and replaced and is **also initialed**, record `"Yes"`.  
   - If crossed-out text and replacement annotations are **not** initialed, record `"No"`.  
   - If **no crossed-out text** appears on the page, record `"N/A"`.

5. **Confidence Score**  
   - For each core page, provide a numerical `confidence_score` in the range `[0.0, 1.0]` indicating how certain you are that your assessment (`Yes`, `No`, or `N/A`) is correct.

6. **Summary Note**  
   - Provide a brief explanation (`note`) justifying your determination on each page (e.g., “No visible strikethroughs were found on this page,” or “Text is crossed out with initials in the margin.”).

7. **Return a JSON Object**  
   - Your final output must be returned as valid JSON.  
   - The structure should be as follows:
     ```json
     {
       "crossed-out": {
         "total_pages": "<int>",
         "core_pages": "<int>",
         "results": [
           {
             "image_index": "<int index of core page>",
             "crossed_out_and_replacement_annotations_with_Initials": "<Yes | No | N/A>",
             "confidence_score": "<float>",
             "note": "<brief justification>"
           }
         ]
       }
     }
     ```

"""

# """ 
# Identify crossed-out text and replacement annotations (handwritten or stamped modifications) in all attached scanned images of the security instrument.  
# - **Text with underlines** should not be considered as crossed-out text.  
# - **Return the results in JSON format** for **all images**, with the following structure:  

#   - `"crossed-out"`: An array of results for all images, along with the total image count.  
#     - `"total_images"`: The total number of scanned images analyzed.  
#     - Each entry in the array should include:
#       - `"image_index"`: The index of the scanned image.  
#       - `"crossed_out_and_replacement_annotations"`:  
#         - If crossed-out, annotations and initials are present, value should be `"Yes"`.  
#         - If crossed-out and annotations are present without initials, value should be `"No"`.  
#         - If no crossed-out are present, value should be `"N/A"`.  
#       - `"confidence_score"`: A numerical value between 0 and 1 indicating the confidence in the analysis.  
#       - `"note"`: A brief explanation justifying the selection of the value for `"crossed_out_and_replacement_annotations"`.  

# ---
# ### JSON Format Example:  
# ```json
# {
#   "crossed-out": {
#     "total_images": "<int count of images>",
#     "results": [
#       {
#         "image_index": "<int index of image>",
#         "crossed_out_and_replacement_annotations": "<Yes | No | N/A>",
#         "confidence_score": "<float between 0.0 and 1.0>",
#         "note": "A brief explanation justifying the selection of the value"
#       }
#     ]
#   }
# }
# ```
# """
