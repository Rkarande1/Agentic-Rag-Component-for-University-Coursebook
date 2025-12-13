# -----------------------------------------------------------------------------
# PDF EXTRACTION SCRIPT
# -----------------------------------------------------------------------------

import pdfplumber
import re
import json
import sys
import os

# Ensure UTF-8 output to avoid Windows encoding errors
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')

#Global Clean Text
def clean_text(text, is_header=False):
    if not text: return ""
    if is_header:
        # Headers shouldn't end with colons or stars
        return text.replace('\u2022', '').strip(" :*\n\r\t")
    # Join broken lines (hyphenation at end of line)
    text = re.sub(r'-\n\s*', '', text)
    # Turn all newlines into spaces for flow
    text = text.replace('\n', ' ')
    # Remove superscript footnote markers 
    text = re.sub(r'[¹²³⁴⁵⁶⁷⁸⁹⁰]', '', text)
    # Standardize bullet points
    text = text.replace('\u2022', '- ')
    return " ".join(text.split())

# Helper: Parse Combined Metadata (Used by Bridge and optionally Master)
# Sometimes the PDF puts "Location  English  3 sem  Winter" all in one line.

def parse_combined_metadata(value):
    """Parses the 'Location Language...' combined string."""
    val_clean = value.replace('\n', ' ').strip()
    
    # Regex for: Location, Language, Duration, Frequency, [Participants]
    
    pattern = (
        r'(?P<Location>.*?)\s+'
        r'(?P<Language>(?:English|German|Deutsch)(?:(?:, |/)(?:English|German|Deutsch))?)\s+'
        r'(?P<Duration>.*?semester)\s+'
        r'(?P<Frequency>.*?semester)'
        r'(?:\s+(?P<Participants>.*))?$'
    )
    match = re.search(pattern, val_clean, re.IGNORECASE)
    
    if match:
        return {k: v.strip() for k, v in match.groupdict().items() if v}
    
    # Fallback: Split by double spaces if regex fails.
    # This assumes the PDF uses visual spacing (double space) to separate columns.
    parts = [p.strip() for p in re.split(r'\s{2,}', val_clean) if p.strip()]
    if len(parts) >= 4:
        res = {
            "Location": parts[0], "Language": parts[1],
            "Duration": parts[2], "Frequency": parts[3]
        }
        if len(parts) > 4: res["Max. Number of Participants"] = parts[4]
        return res
    return None

# ==========================================
# 1. EXTRACT BRIDGE COURSE CATALOGUE 
# ==========================================
def extract_bridge_course_catalogue(pdf_path):
    extracted_data = []
    all_lines = []

    # A. READ & LINEARIZE
    # Using pdfplumber to get exact word positions.
    # PDFs don't really have "lines", just floating words. We have to reconstruct lines based on 'top' coordinate.
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                words = page.extract_words(keep_blank_chars=True, extra_attrs=["fontname", "size"])
                # Sort words order: Top-to-bottom, Left-to-right
                words.sort(key=lambda w: (w['top'], w['x0']))
                if not words: continue
                
                # Group words into lines if they are on roughly the same Y-axis (within 3px)
                current_line, lines = [words[0]], []
                for w in words[1:]:
                    if abs(w['top'] - current_line[-1]['top']) < 3: current_line.append(w)
                    else: lines.append(current_line); current_line = [w]
                lines.append(current_line)
                
                for line in lines:
                    all_lines.append({
                        "words": line,
                        "text": " ".join([w['text'] for w in line]),
                        "page": i + 1
                    })
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")
        return []

    # B. PROCESS STREAM
    # We iterate through the linearized text.
    prelim_data, prelim_active, prelim_captured = {}, False, False
    prelim_topic, prelim_header_size = None, 0
    
    for idx, line_obj in enumerate(all_lines):
        text = line_obj['text']
        words = line_obj['words']
        
        # --- Preliminary Notes Handling ---
        # Capture the intro before the actual modules start
        if "preliminary notes" in text.lower() and not prelim_captured and not prelim_active:
            prelim_active = True
            prelim_header_size = words[0]['size']
            continue
        if prelim_active:
            # Detect end of preliminary notes (start of real modules or section change)
            is_end = (abs(words[0]['size'] - prelim_header_size) < 0.5 and len(text) > 5) or ("Modules" in text and words[0]['size'] > 14)
            if is_end:
                prelim_active = False
                if prelim_data:
                    extracted_data.append({"type": "preliminary_notes", "source_file": "Bridge Course Catalogue", "content": prelim_data})
                    prelim_captured = True
            else:
                if "Bold" in words[0]['fontname']:
                    topic = clean_text(text, is_header=True)
                    if topic: prelim_topic = topic; prelim_data[prelim_topic] = ""
                else:
                    if not prelim_topic: prelim_topic = "General"; prelim_data[prelim_topic] = ""
                    prelim_data[prelim_topic] += " " + clean_text(text)
            continue

        # --- Module Handling ---
        # HEURISTIC: Find module IDs (e.g., "140P", "INF123")
        possible_ids = re.findall(r'\b[A-Z0-9]{2,5}\b', text)
        blacklist = ["ECTS", "TYPE", "KIND", "CODE", "PROF", "EXAM", "SWS", "ASPO", "NOTE", "MODUL", "MODULE", "AND", "FOR", "THE", "WITH", "ID"]
        valid_id = next((pid for pid in possible_ids if pid not in blacklist and not re.match(r'^\d+$', pid)), None)
        
        if valid_id:
            # Double check if the previous line say "Module ID"
            is_module = False
            for back in range(1, 3):
                if idx - back >= 0 and ("Module ID" in all_lines[idx-back]['text'] or "Modul-ID" in all_lines[idx-back]['text']):
                    is_module = True; break
            
            if is_module:
                module = {"type": "Bridge Module", "source_file": "Bridge Course Catalogue", "module_id": valid_id}
                
                # Name (Scan Up)
                # We look backwards to find the Big Bold Title.
                name_parts = []
                for back in range(idx - back - 1, -1, -1):
                    prev = all_lines[back]
                    if "Modules" in prev['text'] and prev['words'][0]['size'] > 14: break # Safety stop
                    if "Preliminary notes" in prev['text']: break
                    # Title is usually larger font or bold
                    if (prev['words'][0]['size'] > 11 or "Bold" in prev['words'][0]['fontname']):
                        if "created" in prev['text'].lower() or re.match(r'^\d+\s*$', prev['text']): continue
                        cleaned = re.sub(r'[^\w\s\-\(\)\.,&äöüÄÖÜß]', '', prev['text']).strip()
                        if cleaned: name_parts.insert(0, cleaned)
                    else:
                        if name_parts: break # Stop if we hit normal text
                module['module_name'] = clean_text(" ".join(name_parts))

                # Metadata Window
                # Grab the next 15 lines to scan for ECTS, semester, etc.
                window = "\n".join([l['text'] for l in all_lines[idx:idx+15]])
                ects = re.search(r'(\d+)\s*ECTS', window)
                module['credits'] = int(ects.group(1)) if ects else 0
                module['semester'] = 'Summer' if re.search(r'summer', window, re.I) else 'Winter' if re.search(r'winter', window, re.I) else 'Flexible'

                # Content Scan 
                # We iterate forward until we hit the next Module ID or end of file.
                learning_lines, content_lines, ass_buffer = [], [], []
                current_section, dynamic_meta, curr_meta_key, in_ass = "metadata", {}, None, False

                for fwd in range(idx + 1, len(all_lines)):
                    fwd_line = all_lines[fwd]
                    fwd_txt = fwd_line['text']
                    if ("Module ID" in fwd_txt or "Modul-ID" in fwd_txt) and len(fwd_txt) < 100: break # Next module starts
                    
                    # Identify Sections
                    if re.search(r'Method of Ass.*ment|Modulprüfungen|Prüfungsform', fwd_txt, re.I): in_ass = True; current_section = "assessment"; continue
                    if in_ass:
                        if any(x in fwd_txt.lower() for x in ["type of", "prüfungsform", "type/scope"]): continue
                        if fwd_txt.strip().startswith("*") or "refer to" in fwd_txt: in_ass = False; continue
                        if "Learning Outcomes" in fwd_txt: in_ass = False; current_section = "learning"; continue
                        if "Course Content" in fwd_txt: in_ass = False; current_section = "content"; continue
                        ass_buffer.append(fwd_txt); continue

                    if "Learning Outcomes" in fwd_txt: current_section = "learning"; continue
                    if "Course Content" in fwd_txt: current_section = "content"; continue
                    if "Teaching Material" in fwd_txt: current_section = "material"; continue

                    if current_section == "metadata":
                        is_bold = "Bold" in fwd_line['words'][0]['fontname']
                        if is_bold:
                            # Key-Value pair on same line logic
                            key_p, val_p = [], []
                            is_k = True
                            for w in fwd_line['words']:
                                if "Bold" in w['fontname'] and is_k: key_p.append(w['text'])
                                else: is_k = False; val_p.append(w['text'])
                            k_txt, v_txt = clean_text(" ".join(key_p), True), clean_text(" ".join(val_p))
                            
                            # HEURISTIC: If "key" is too long (likely a bold sentence) or contains commas (list), treat as value
                            if len(k_txt) > 50 or "," in k_txt:
                                if curr_meta_key:
                                    dynamic_meta[curr_meta_key] += " " + k_txt + " " + v_txt
                            else:
                                if k_txt: curr_meta_key = k_txt; dynamic_meta[curr_meta_key] = v_txt
                        elif curr_meta_key:
                            dynamic_meta[curr_meta_key] += " " + clean_text(fwd_txt)
                    elif current_section == "learning": learning_lines.append(fwd_txt)
                    elif current_section == "content": content_lines.append(fwd_txt)

                module.update(dynamic_meta)
                module['learning_outcomes'] = clean_text("\n".join(learning_lines))
                module['course_content'] = clean_text("\n".join(content_lines))
                raw_ass = "\n".join(ass_buffer).replace("Präs", "Prj").replace("Pr\u00e4s", "Prj")
                if raw_ass: module['assessment'] = {'details': clean_text(raw_ass)}

                # Parser Logic for Combined keys (Location/Language/etc)
                final_module = {}
                for k, v in module.items():
                    if "Location" in k and "Language" in k and "Participant" in k:
                        parsed = parse_combined_metadata(v)
                        if parsed: final_module.update(parsed)
                        else: final_module[k] = v
                    elif "Location" in k and "Language" in k and "Duration" in k:
                         parsed = parse_combined_metadata(v)
                         if parsed: final_module.update(parsed)
                         else: final_module[k] = v
                    else:
                        final_module[k] = v
                
                extracted_data.append(final_module)

    return extracted_data

# ==========================================
# 2. EXTRACT MASTER COURSE CATALOGUE (Standard)
# ==========================================
# This is basically the same logic as Bridge, but the PDF structure is slightly different.
def extract_master_course_catalogue(pdf_path):
    extracted_data = []
    all_lines = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                words = page.extract_words(keep_blank_chars=True, extra_attrs=["fontname", "size"])
                words.sort(key=lambda w: (w['top'], w['x0']))
                if not words: continue
                current_line, lines = [words[0]], []
                for w in words[1:]:
                    if abs(w['top'] - current_line[-1]['top']) < 3: current_line.append(w)
                    else: lines.append(current_line); current_line = [w]
                lines.append(current_line)
                for line in lines:
                    all_lines.append({
                        "words": line, "text": " ".join([w['text'] for w in line]), "page": i + 1
                    })
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")
        return []

    for idx, line_obj in enumerate(all_lines):
        text = line_obj['text']
        
        # Master modules usually have 4-letter codes (e.g. "ROBO")
        possible_ids = re.findall(r'\b[A-Z]{4}\b', text)
        valid_id = next((pid for pid in possible_ids if pid not in ["ECTS", "TYPE", "KIND", "CODE", "PROF", "EXAM", "SWS", "ASPO", "NOTE"]), None)
        
        if valid_id and any("Module ID" in all_lines[idx-b]['text'] for b in range(1, 3) if idx-b >= 0):
            module = {"type": "Master Module", "source_file": "Master Course Catalogue", "module_id": valid_id}
            
            # Simple name extraction (scan up 2 lines)
            name_parts = []
            for back in range(idx - 2, -1, -1):
                prev = all_lines[back]
                if "Classification" in prev['text'] or "Module ID" in prev['text']: continue
                if (prev['words'][0]['size'] > 11 or "Bold" in prev['words'][0]['fontname']) and "Required modules" not in prev['text']:
                    name_parts.insert(0, prev['text'])
                else:
                    if name_parts: break
            module['module_name'] = clean_text(" ".join(name_parts))

            window = "\n".join([l['text'] for l in all_lines[idx:idx+15]])
            ects = re.search(r'(\d+)\s*ECTS', window)
            module['credits'] = int(ects.group(1)) if ects else 0
            module['semester'] = 'Summer' if re.search(r'summer', window, re.I) else 'Winter' if re.search(r'winter', window, re.I) else 'Flexible'

            learning, content, ass_buf = [], [], []
            curr_sec, curr_meta_key, in_ass = "metadata", None, False
            dynamic_meta = {}

            # Processing the sections again.
            for fwd in range(idx + 1, len(all_lines)):
                fwd_line = all_lines[fwd]
                fwd_txt = fwd_line['text']
                if ("Module ID" in fwd_txt or "Modul-ID" in fwd_txt) and len(fwd_txt) < 100: break
                
                if re.search(r'Method of Ass.*ment|Modulprüfungen|Prüfungsform', fwd_txt, re.I): in_ass = True; curr_sec = "assessment"; continue
                if in_ass:
                    if any(x in fwd_txt.lower() for x in ["type of", "prüfungsform", "type/scope"]): continue
                    if fwd_txt.strip().startswith("*") or "refer to" in fwd_txt: in_ass = False; continue
                    if "Learning Outcomes" in fwd_txt: in_ass = False; curr_sec = "learning"; continue
                    if "Course Content" in fwd_txt: in_ass = False; curr_sec = "content"; continue
                    ass_buf.append(fwd_txt); continue

                if "Learning Outcomes" in fwd_txt: curr_sec = "learning"; continue
                if "Course Content" in fwd_txt: curr_sec = "content"; continue
                if "Teaching Material" in fwd_txt: curr_sec = "material"; continue

                if curr_sec == "metadata":
                    is_bold = "Bold" in fwd_line['words'][0]['fontname']
                    if is_bold:
                        key_p, val_p = [], []
                        is_k = True
                        for w in fwd_line['words']:
                            if "Bold" in w['fontname'] and is_k: key_p.append(w['text'])
                            else: is_k = False; val_p.append(w['text'])
                        k_txt, v_txt = clean_text(" ".join(key_p), True), clean_text(" ".join(val_p))
                        
                        if len(k_txt) > 50 or "," in k_txt:
                            if curr_meta_key:
                                dynamic_meta[curr_meta_key] += " " + k_txt + " " + v_txt
                        else:
                            if k_txt: curr_meta_key = k_txt; dynamic_meta[curr_meta_key] = v_txt
                    elif curr_meta_key:
                        dynamic_meta[curr_meta_key] += " " + clean_text(fwd_txt)
                elif curr_sec == "learning": learning.append(fwd_txt)
                elif curr_sec == "content": content.append(fwd_txt)

            module.update(dynamic_meta)
            module['learning_outcomes'] = clean_text("\n".join(learning))
            module['course_content'] = clean_text("\n".join(content))
            if ass_buf: module['assessment'] = {'details': clean_text("\n".join(ass_buf).replace("Präs", "Prj"))}
            
            final_module = {}
            for k, v in module.items():
                if "Location" in k and "Language" in k and "Duration" in k:
                    parsed = parse_combined_metadata(v)
                    if parsed: final_module.update(parsed)
                    else: final_module[k] = v
                else:
                    final_module[k] = v
            extracted_data.append(final_module)

    return extracted_data

# ==========================================
# 3. EXTRACT REGULATIONS
# ==========================================
# We want to find the bold headers (Start of Section)
# and then grab everything under it until the next bold header.
def extract_regulations(pdf_path):
    extracted_data = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            all_lines = []
            # We only care about the first 8 pages usually, afterwards it's just appendix/tables.
            for i, page in enumerate(pdf.pages[:8]): 
                words = page.extract_words(keep_blank_chars=True, extra_attrs=["fontname", "size"])
                words.sort(key=lambda w: (w['top'], w['x0']))
                if not words: continue
                current_line, lines = [words[0]], []
                for w in words[1:]:
                    if abs(w['top'] - current_line[-1]['top']) < 3: current_line.append(w)
                    else: lines.append(current_line); current_line = [w]
                lines.append(current_line)
                for line in lines:
                    all_lines.append({"words": line, "text": " ".join([w['text'] for w in line]), "page": i + 1})
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")
        return []

    current_section = None
    last_line_was_header = False
    
    for idx, line_obj in enumerate(all_lines):
        text = line_obj['text']
        words = line_obj['words']
        
        #Headers are Bold and either 11pt or 12pt (ish)
        is_bold = "Bold" in words[0]['fontname']
        font_size = words[0]['size']
        is_header_size = abs(font_size - 11.04) < 0.1 or abs(font_size - 12.00) < 0.1
        is_header = is_bold and is_header_size
        clean_line = clean_text(text)

        if is_header and clean_line:
            # Hard stop if we hit the appendix
            if "Appendix 1" in clean_line: break
            
            # If the previous line was ALSO a header, it's probably a multi-line title.
            if last_line_was_header and current_section:
                current_section["section_title"] += " " + clean_line
            else:
                current_section = {
                    "type": "regulation_section",
                    "source_file": "Study and Examination Regulations",
                    "section_title": clean_line,
                    "content": ""
                }
                extracted_data.append(current_section)
            last_line_was_header = True
        else:
            # Append Content
            if current_section:
                if current_section["content"]: current_section["content"] += " " + clean_text(text)
                else: current_section["content"] = clean_text(text)
            last_line_was_header = False

    return extracted_data

# ==========================================
# 4. EXTRACT ELECTIVES (Dynamic Table)
# ==========================================
# This scans a table. But tables change every semester.
# So we dynamically look for the "Master AI" column instead of hardcoding index 5.
def extract_electives_dynamic(pdf_path):
    extracted_data = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if len(table) < 2: continue
                    # Default assumptions about column indices 
                    idxs = {
                        "sose": 0, "title_eng": 2, "language": 3,
                        "professor": 4, "ects": 7, "mai_filter": 11
                    }
                    
                    # SCAN HEADER
                    header_row = table[0]
                    for i, cell in enumerate(header_row):
                        if cell:
                            norm = cell.replace('\n', ' ').lower()
                            if "artificial" in norm and "intelligence" in norm and "mai" in norm:
                                idxs["mai_filter"] = i; break
                    
                    # ITERATE ROWS
                    for row in table[1:]:
                        if len(row) <= idxs["mai_filter"]: continue
                        # Check if "Master AI" column has "WPM" (Wahlpflichtmodul = Elective)
                        mai_cell = row[idxs["mai_filter"]]
                        if mai_cell and "WPM" in mai_cell:
                            def get_col(idx): return row[idx] if idx is not None and len(row) > idx and row[idx] else ""
                            raw_sose = get_col(idxs["sose"])
                            title = get_col(idxs["title_eng"])
                            language = get_col(idxs["language"])
                            professor = get_col(idxs["professor"])
                            ects = get_col(idxs["ects"])
                            availability = "Winter"
                            if raw_sose and ("yes" in raw_sose.lower() or "ja" in raw_sose.lower()): availability = "Summer"
                            
                            entry = {
                                "type": "Elective Module",
                                "source_file": "Electives Overview",
                                "module_name": title.replace('\n', ' ').strip(),
                                "availability": availability,
                                "language": language.replace('\n', ' ').strip(),
                                "ects": ects.replace('\n', '').strip(),
                                "professor": professor.replace('\n', ' ').strip()
                            }
                            extracted_data.append(entry)
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")
        return []
    return extracted_data

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    if not os.path.exists("data"):
        os.makedirs("data")
        print("Created 'data' directory.")

    # 1. BRIDGE MODULES
    print("Extracting Bridge Modules...")
    bridge_data = extract_bridge_course_catalogue("Bridge Course Catalogue Master Artificial Intelligence for Industrial Applications.pdf")
    with open("data/bridge_modules.json", "w", encoding="utf-8") as f:
        json.dump(bridge_data, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(bridge_data)} items to data/bridge_modules.json")

    # 2. MASTER MODULES
    print("Extracting Master Modules...")
    master_data = extract_master_course_catalogue("Course Catalogue Master Artificial Intelligence for Industrial Applications.pdf")
    with open("data/master_modules.json", "w", encoding="utf-8") as f:
        json.dump(master_data, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(master_data)} items to data/master_modules.json")

    # 3. REGULATIONS
    print("Extracting Regulations...")
    reg_data = extract_regulations("Study and Examination Regulations Master Artificial Intelligence for Industrial Applications of 16.02.2023(347 KB).pdf")
    with open("data/regulations.json", "w", encoding="utf-8") as f:
        json.dump(reg_data, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(reg_data)} items to data/regulations.json")

    # 4. ELECTIVES
    print("Extracting Electives...")
    elec_data = extract_electives_dynamic("Overview Compulsory Elective Modules for Artificial Intelligence for Industrial Applications(93 KB).pdf")
    with open("data/electives.json", "w", encoding="utf-8") as f:
        json.dump(elec_data, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(elec_data)} items to data/electives.json")

    print("\nData preparation complete!")
