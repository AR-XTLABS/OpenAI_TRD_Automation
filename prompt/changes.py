changes_initialed ="""
Analyze the attached document image to identify the following elements:

1) DETECT CROSSED-OUT TEXT:
   - Identify any words, phrases, or lines that appear to be crossed out or struck through.
   - Capture the crossed-out content exactly as written before the mark.

2) DETECT INITIALS NEAR CROSSED-OUT TEXT:
   - Scan immediately adjacent areas (above, below, or to the side) for any initials that appear in or around the location of the crossed-out text.
   - Ignore borrower or notary signatures that do not serve as an initial for the crossed-out text validation.
   - If initials are found, capture "Yes"; if none are present in the vicinity, capture "No" (if you are certain they are not present) or "None" if uncertain.

3) DETECT REPLACEMENT TEXT:
   - Look for handwritten or stamped text that appears directly beneath, above, or adjacent to the crossed-out text.
   - Identify that replacement text if it clearly substitutes the crossed-out content.

4) NOTE YOUR CONFIDENCE:
   - Provide a numeric "confidence_score" (ranging from 0.0 to 1.0) indicating your overall certainty of completeness and accuracy in the extraction. 
   - If you are certain you have captured all crossed-out text, initials, and replacements accurately, set it close to 1.0. If unsure, lower the score accordingly.

5) OUTPUT FORMAT IN JSON:
   - Return the extracted information in the following JSON structure:
     {
       "crossed_Out_Text": "Crossed Out Text Here",
       "initialed": "<Yes | No | None>",
       "crossed_Out_replacement_Text": "Replacement Text Here",
       "confidence_score": 0.0
     }

6) HIGH CONFIDENCE REQUIREMENT:
   - Only provide non-empty fields ("crossed_Out_Text", "initialed", "crossed_Out_replacement_Text") if you are 100% confident in their correctness. 
   - Otherwise, if you have any uncertainty, leave those fields empty (e.g., "None") and ensure the "confidence_score" reflects your uncertainty.

"""