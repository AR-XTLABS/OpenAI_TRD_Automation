import json
import http.client, urllib.request, urllib.parse, urllib.error
import os
import time

# API_KEY =  os.environ['api_key']#"cc4cae2ff9b549398d002398edc3e07b"
# ENDPOINT = os.environ['urlvision']#"https://xtvision.cognitiveservices.azure.com/"

API_KEY =  "cc4cae2ff9b549398d002398edc3e07b"
ENDPOINT = "https://xtvision.cognitiveservices.azure.com/"

# Define thresholds for grouping
vertical_threshold = 80  # Max vertical distance for lines in the same paragraph/neighbor group
horizontal_threshold = 120  # Maximum horizontal distance between lines in the same group
stamp_vertical_threshold = 5


def azure_to_opencv_bbox(azure_bbox):
    # Extract the x and y coordinates
    x_coords = azure_bbox[0::2]  # Get every second element starting at 0 (x1, x2, x3, x4)
    y_coords = azure_bbox[1::2]  # Get every second element starting at 1 (y1, y2, y3, y4)

    # Calculate the top-left corner coordinates
    x_min = min(x_coords)
    y_min = min(y_coords)

    # Calculate width and height
    width = max(x_coords) - x_min
    height = max(y_coords) - y_min

    # Return the OpenCV bounding box [x, y, w, h]
    return [round(x_min*300), round(y_min*300), round(width*300), round(height*300)]

# Helper function to merge two bounding boxes
def merge_bounding_boxes(box1, box2):
    x_min = min(box1[0], box2[0])
    y_min = min(box1[1], box2[1])
    x_max = max(box1[0] + box1[2], box2[0] + box2[2])
    y_max = max(box1[1] + box1[3], box2[1] + box2[3])
    return [x_min, y_min, x_max - x_min, y_max - y_min]

# # Helper function to determine if boxes are on the same line
def are_on_same_line_threshold(box1, box2, v_threshold):
    bottom1 = box1[1] + box1[3]
    bottom2 = box2[1] + box2[3]
    return abs(box1[1] - box2[1]) < v_threshold or abs(bottom1 - bottom2) < v_threshold

# # Helper function to check if two boxes are aligned (left or right)
def are_aligned_threshold(box1, box2, h_threshold):
    return abs(box1[0] - box2[0]) < h_threshold

# Process left and right side elements individually
def process_side_group(text_elements, current_side_group,vertical_threshold,horizontal_threshold):
    for element in text_elements:
        current_box = element['boundingBox']
        
        if (current_side_group and 
            (are_on_same_line_threshold(current_side_group[-1]['boundingBox'], current_box, vertical_threshold) or
             (are_aligned_threshold(current_side_group[-1]['boundingBox'], current_box, horizontal_threshold) and
              abs(current_side_group[-1]['boundingBox'][1] + current_side_group[-1]['boundingBox'][3] - current_box[1]) < vertical_threshold * 2))):
            current_side_group[-1]['line'].append(element['line'])
            current_side_group[-1]['boundingBox'] = merge_bounding_boxes(current_side_group[-1]['boundingBox'], current_box)
        else:
            current_side_group.append({'line': [element['line']], 'boundingBox': current_box})

    return current_side_group

# Helper function to determine if boxes are on the same line
def are_on_same_line(box1, box2):
    bottom1 = box1[1] + box1[3]
    bottom2 = box2[1] + box2[3]
    return abs(box1[1] - box2[1]) < 3 or abs(bottom1 - bottom2) < 3

# Helper function to check if two boxes are aligned (left or right)
def are_aligned(box1, box2):
    return abs(box1[0] - box2[0]) < 2

# Process left and right side elements individually
def process_same_line(text_elements, current_side_group):
    for element in text_elements:
        current_box = element['boundingBox']
        
        if (current_side_group and 
            (are_on_same_line(current_side_group[-1]['boundingBox'], current_box) or
             (are_aligned(current_side_group[-1]['boundingBox'], current_box) and
              abs(current_side_group[-1]['boundingBox'][1] + current_side_group[-1]['boundingBox'][3] - current_box[1]) < 4))):
            current_side_group[-1]['line'].append(element['line'])
            current_side_group[-1]['boundingBox'] = merge_bounding_boxes(current_side_group[-1]['boundingBox'], current_box)
        else:
            current_side_group.append({'line': [element['line']], 'boundingBox': current_box})

    return current_side_group
# Function to check if two bounding boxes overlap
def do_boxes_overlap(box1, box2):
    return not (box1[0] > box2[0] + box2[2] or  # box1 is right to box2
                box1[0] + box1[2] < box2[0] or  # box1 is left to box2
                box1[1] > box2[1] + box2[3] or  # box1 is below box2
                box1[1] + box1[3] < box2[1])    # box1 is above box2

# Function to merge overlapping bounding boxes within a group
def merge_overlapping_boxes(grouped_elements):
    merged_group = []
    while grouped_elements:
        current_element = grouped_elements.pop(0)
        current_box = current_element['boundingBox']
        merged = False
        for merged_element in merged_group:
            if do_boxes_overlap(merged_element['boundingBox'], current_box):
                merged_element['line'] += current_element['line'] # Merge lines
                merged_element['boundingBox'] = merge_bounding_boxes(merged_element['boundingBox'], current_box) # Merge bounding boxes
                merged = True
                break
        if not merged:
            merged_group.append(current_element)
    return merged_group

def merge_lines(text_elements, y_threshold=30):
    merged_lines = []
    current_line = {'line': [], 'boundingBox': []}

    for element in text_elements:
        current_box = element['boundingBox']
        current_y = (current_box[1] + current_box[3]) / 2

        if not current_line['line']:
            current_line['line'].extend(element['line'])
            current_line['boundingBox'] = current_box
        else:
            prev_box = current_line['boundingBox']
            prev_y = (prev_box[1] + prev_box[3]) / 2

            if abs(prev_y - current_y) <= y_threshold:
                current_line['line'].extend(element['line'])
                current_line['boundingBox'] = merge_bounding_boxes(prev_box, current_box)
            else:
                merged_lines.append(current_line)
                current_line = {'line': element['line'], 'boundingBox': current_box}

    if current_line['line']:
        merged_lines.append(current_line)

    return merged_lines

def merge_group_box(box, max_y, max_x):
	if not  box:
		return [],[]
	text_elements = box
	text_elements.sort(key=lambda x:x['boundingBox'][1])

	new_text_elements = [item for item in  text_elements if item['boundingBox'][1] < round(max_y/2.5) or   item['boundingBox'][1] > max_y-round(max_y/2.5)]
	middle_text_elemets = [item for item in  text_elements if item['boundingBox'][1] > round(max_y/2.5) and   item['boundingBox'][1] < max_y-round(max_y/2.5)]
	middle_same_line = process_same_line(middle_text_elemets, [])

	page_width = max([el['boundingBox'][0] + el['boundingBox'][2] for el in new_text_elements])
	middle_of_page = page_width / 2
	# # Separate elements into left and right based on middle_of_page
	left_elements = [el for el in new_text_elements if el['boundingBox'][0] < middle_of_page]
	right_elements = [el for el in new_text_elements if el['boundingBox'][0] >= middle_of_page]

	# # Sort the elements within each side by vertical position
	left_elements.sort(key=lambda x: x['boundingBox'][1])
	right_elements.sort(key=lambda x: x['boundingBox'][1])

	# Group left and right side elements based on vertical/horizontal threshold
	left_side_group = process_side_group(left_elements, [],stamp_vertical_threshold,horizontal_threshold)
	right_side_group = process_side_group(right_elements, [],stamp_vertical_threshold,horizontal_threshold)
	all_side_groups = right_side_group + left_side_group + middle_same_line
	# all_side_groups.sort(key=lambda x:x['boundingBox'][1])
	combined_group = merge_overlapping_boxes(all_side_groups)
	# combined_group.sort(key=lambda x:x['boundingBox'][1])
	stamplines = [{"line":" ".join(group['line']),"boundingBox": group['boundingBox']} for group in combined_group]
	return stamplines

def call_vision(content):
    headers = {
			# Request headers
			'Content-Type': 'application/octet-stream',
			'Ocp-Apim-Subscription-Key': API_KEY,
		}
    params = urllib.parse.urlencode({
        # Request parameters
        'language': 'en'
        # ,'pages':page
    })
    try:

        conn = http.client.HTTPSConnection('centralindia.api.cognitive.microsoft.com')
        conn.request("POST", "/vision/v3.2/read/analyze?%s" % params, content, headers)
        response = conn.getresponse()
        data = response.headers['operation-location']
        
        operationId = (data.split("/"))[-1]
       
        conn.close()
    except Exception as e:
            print(f"error --> {e}")

    headers = {
        # Request headers
        'Ocp-Apim-Subscription-Key': API_KEY,
    }
    
    params = urllib.parse.urlencode({
    })

		
    try:
        data = None
        conn = http.client.HTTPSConnection('centralindia.api.cognitive.microsoft.com')
        url =f'/vision/v3.2/read/analyzeResults/{operationId}?%s'
        while True:
            conn.request("GET",  url % params, "{body}", headers)
            response = conn.getresponse()
            data = json.loads(response.read().decode())
            if data["status"] == "succeeded":
                break
            conn.close()
            time.sleep(5)

        if data:
            
            for i, text_result in enumerate(data["analyzeResult"]["readResults"]):
                box = []
                __lines = text_result["lines"]
                max_y = round(text_result["height"] * 300)
                max_x = round(text_result["width"] * 300)
                for _i, line in enumerate(__lines):
                    _box = azure_to_opencv_bbox(line["boundingBox"])
                    if _box:
                        box.append({"line":line["text"],"boundingBox":_box})
                stamplines = merge_group_box(box,max_y,max_x)
                if stamplines:
                    _text = "\n".join([item['line'] for item in stamplines])
                    return _text
        return ""
    except Exception as e:
        print(f"error -> {e}")
        