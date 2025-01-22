changes_initialed ="""
Create a detailed analysis of a document snippet containing loan information. 
Identify any handwritten or stamped modifications, specifically focusing on crossed-out text and replacement annotations. 
Look for initials that may indicate approval of changes. 
Include a confidence score for the accuracy of the modifications identification. 

Provide the output in JSON format with the following keys:
- `"crossed_out_and_replacement_annotations"`: 
  - If crossed-out, annotations and initials are present, value should be `"Yes"`.
  - If crossed-out and annotations are present without initials, value should be `"No"`.
  - If no crossed-out and annotations are present, value should be `"N/A"`.

- `"confidence_score"`: A numerical value indicating the confidence in the analysis.

- `"note"`: A brief explanation justifying the selection of the value for `"crossed_out_and_replacement_annotations"`.

```json
{
  "crossed_out_and_replacement_annotations": "< Yes | No | N/A >",
  "confidence_score": "<float between 0 and 1>",
  "note": "<brief explanation>"
}
```
"""
