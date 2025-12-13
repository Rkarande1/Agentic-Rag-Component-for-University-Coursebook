import json
import os
import chromadb
from chromadb.utils import embedding_functions

# 1. SETUP CHROMA DB
# We use a persistent local database in the "chroma_db" folder.
DB_PATH = "data/chroma_db"
client = chromadb.PersistentClient(path=DB_PATH)

# 2. SETUP EMBEDDINGS
# We use the SentenceTransformerEmbeddingFunction used by ChromaDB
# This automatically downloads "all-MiniLM-L6-v2"
emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

# 3. HELPER: CREATE OR GET COLLECTION
def get_or_create_collection(name):
    try:
        # Delete if exists to ensuring clean indexing
        try: client.delete_collection(name); print(f"Deleted existing collection: {name}")
        except: pass
        
        return client.create_collection(name=name, embedding_function=emb_fn)
    except Exception as e:
        print(f"Error creating collection {name}: {e}")
        return None

# 4. INDEXING FUNCTIONS
def index_file(collection_name, json_path, doc_type):
    if not os.path.exists(json_path):
        print(f"Skipping {json_path} (File not found)")
        return

    print(f"Indexing {json_path} into '{collection_name}'...")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    collection = get_or_create_collection(collection_name)
    if not collection: return

    ids, documents, metadatas = [], [], []

    for idx, item in enumerate(data):
        # Create a unique ID
        item_id = f"{doc_type}_{idx}"
        
        # Prepare content and metadata
        # We need to flatten the item to string for the "document" 
        
        # Strategy: Embed the "Content" but store "Metadata"
        if doc_type == "module":
            # For modules, embed Name + Content + Learning Outcomes
            text = f"Module ID: {item.get('module_id', '')}\n"
            text += f"Module Name: {item.get('module_name', '')}\n"
            text += f"Type: {item.get('type', 'Module')}\n"
            convenor = item.get('Module Convenor  Professor / Lecturer', '')
            if convenor:
                text += f"Lecturer: {convenor}\n"
            text += f"Outcomes: {item.get('learning_outcomes', '')}\n"
            text += f"Content: {item.get('course_content', '')}"
            meta = {
                "source": item.get("source_file", "unknown"),
                "title": f"{item.get('module_name', 'Unknown Module')} ({item.get('module_id', '')})", # Standardize TITLE
                "type": item.get("type", "Module"),
                "module_id": item.get("module_id", "N/A")
            }
        
        elif doc_type == "regulation":
            # For regulations, embed Title + Content
            text = f"Section: {item.get('section_title', '')}\n"
            text += f"Content: {item.get('content', '')}"
            meta = {
                "source": item.get("source_file", "unknown"),
                "title": item.get("section_title", "Regulation Section"), # Standardize TITLE
                "type": item.get("type", "Regulation")
            }
        
        elif doc_type == "elective":
            # Electives are simple
            text = f"Elective: {item.get('module_name', '')}\n"
            text += f"Professor: {item.get('professor', '')}\n"
            text += f"Language: {item.get('language', '')}"
            meta = {
                "source": item.get("source_file", "unknown"),
                "title": item.get("module_name", "Unknown Elective"), # Standardize TITLE
                "type": "Elective",
                "professor": item.get("professor", "N/A")
            }
        
        else:
            text = str(item)
            meta = {"source": "unknown", "title": "Unknown Item"}

        # Store structured data as string in metadata too (so we can retrieve it)
        # ChromaDB metadata must be str, int, float, bool. No lists/dicts.
        # We'll store the full JSON string in a "json_data" field
        meta["json_data"] = json.dumps(item, ensure_ascii=False)

        ids.append(item_id)
        documents.append(text)
        metadatas.append(meta)

    # ADD IN BATCHES (chroma handles it, but good practice)
    if ids:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)
        print(f"--> Added {len(ids)} documents.")

# 5. MAIN
if __name__ == "__main__":
    
    # --- 1. UNIFIED MODULES COLLECTION ---
    # We will combine Master Modules, Bridge Modules, and Electives into ONE "modules" collection.
    print("\n--- Building Unified 'modules' Collection ---")
    
    # A. Reset Collection
    try: client.delete_collection("modules"); print("Deleted old 'modules' collection.")
    except: pass
    modules_col = client.create_collection("modules", embedding_function=emb_fn)
    
    # B. Index Master & Bridge Modules
    # Reuse the add_to_existing helper logic
    def add_json_to_col(col, json_path, dtype):
        if not os.path.exists(json_path): 
            print(f"File not found: {json_path}")
            return
            
        print(f"Indexing {json_path}...")
        with open(json_path, "r", encoding="utf-8") as f: data = json.load(f)
        
        ids, docs, metas = [], [], []
        for i, item in enumerate(data):
            # 1. PRELIMINARY NOTES (Bridge)
            if item.get("type") == "preliminary_notes":
                content_val = item.get("content", "")
                content_str = str(content_val) if not isinstance(content_val, dict) else "\n".join([f"{k}: {v}" for k,v in content_val.items()])
                
                text = f"Title: Preliminary Notes (Bridge)\nContent: {content_str}"
                meta = {
                    "source": item.get("source_file", "Bridge Course Catalogue"),
                    "title": "Preliminary Notes (Bridge)",
                    "id": "prelim_notes",
                    "type": "Note",
                    "json_data": json.dumps(item, ensure_ascii=False)
                }
                item_id = f"{dtype}_{i}_prelim"
            
            # 2. ELECTIVES
            elif dtype == "elective":
                text = f"Module: {item.get('module_name', '')}\n"
                text += "Type: Elective Module\n"
                text += f"Professor: {item.get('professor', '')}\n"
                text += f"Language: {item.get('language', '')}"
                meta = {
                    "source": item.get("source_file", "unknown"),
                    "title": item.get("module_name", "Unknown Elective"),
                    "type": "Elective",
                    "professor": item.get("professor", "N/A"),
                    "json_data": json.dumps(item, ensure_ascii=False)
                }
                item_id = f"{dtype}_{i}_{item.get('module_name', 'x')}"

            # 3. STANDARD MODULES (Master/Bridge)
            else:
                text = f"Module ID: {item.get('module_id', '')}\n"
                text += f"Module Name: {item.get('module_name', '')}\n"
                text += f"Type: {item.get('type', 'Module')}\n"
                
                convenor = item.get('Module Convenor  Professor / Lecturer', '')
                if convenor: text += f"Lecturer: {convenor}\n"
                
                text += f"Credits: {item.get('credits', '0')} ECTS\n"
                text += f"Semester: {item.get('semester', 'Unknown')}\n"
                text += f"Outcomes: {item.get('learning_outcomes', '')}\n"
                text += f"Content: {item.get('course_content', '')}\n"
                
                prereq = item.get('Prerequistes', item.get('Prerequisites', ''))
                if prereq: text += f"Prerequisites: {prereq}\n"
                
                if 'assessment' in item: text += f"Assessment: {item['assessment'].get('details', '')}"
                
                meta = {
                    "source": item.get("source_file", "unknown"),
                    "title": item.get('module_name', 'Unknown Module'),
                    "id": item.get("module_id", "N/A"),
                    "type": "Module",
                    "json_data": json.dumps(item, ensure_ascii=False)
                }
                item_id = f"{dtype}_{i}_{item.get('module_id', 'x')}"
            
            ids.append(item_id)
            docs.append(text)
            metas.append(meta)
            
        if ids: 
            col.add(ids=ids, documents=docs, metadatas=metas)
            print(f"--> Added {len(ids)} items.")

    # Execute Indexing
    add_json_to_col(modules_col, "data/master_modules.json", "master")
    add_json_to_col(modules_col, "data/bridge_modules.json", "bridge")
    add_json_to_col(modules_col, "data/electives.json", "elective") # Merged!

    # --- 2. REGULATIONS COLLECTION ---
    print("\n--- Indexing Regulations ---")
    index_file("regulations", "data/regulations.json", "regulation")

    print("\nIndex built successfully in 'data/chroma_db'!")
