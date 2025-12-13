import chromadb
from chromadb.utils import embedding_functions
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 1. SETUP CHROMA & EMBEDDINGS

DB_PATH = "data/chroma_db"
client = chromadb.PersistentClient(path=DB_PATH)

# Using 'all-MiniLM-L6-v2' 
emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

# 2. SETUP LLM (Ollama)
llm = ChatOllama(model="llama3")

# 3. ROUTER CHAIN

router_prompt = ChatPromptTemplate.from_template("""
You are a routing agent for a University RAG system.
Classify the user's query into one of the following categories:
- "modules": Questions about courses, electives, credits, learning outcomes, professors, languages, or bridge modules. (Keywords: detailed, content, prerequisites, 140P, ROS, virtual reality, deep learning, etc.)
- "regulations": Questions about rules, exams, failure policies, thesis, grading, or legal stuff.
- "other": General chatter or out of scope.

CRITICAL RULE: 
If the user's query mentions "elective module" or "elective", classify it as "modules" (since they are in the same database).

Return ONLY the category name (lowercase).

Query: {question}
Category:
""")
# pipeline: Prompt -> LLM -> String Parser.
router_chain = router_prompt | llm | StrOutputParser()

# 4. SEARCH FUNCTIONS
def query_collection(col_name, query, n_results=3):
    try:
        col = client.get_collection(name=col_name, embedding_function=emb_fn)
        results = col.query(query_texts=[query], n_results=n_results)
        
        
        # Format: "Source (ID): Content" so the LLM knows WHERE the info came from.
        docs = results['documents'][0]
        metas = results['metadatas'][0]
        
        context_parts = []
        for i, (d, m) in enumerate(zip(docs, metas)):
            
            title = m.get('title', m.get('id', 'Unknown'))
            source = m.get('source', 'Unknown Source')
            src_str = f"{title} | {source}"
            context_parts.append(f"--- [CHUNK {i+1}] (Source: {src_str}) ---\n{d}\n")
        
        return "\n".join(context_parts)
    except Exception as e:
        # If the collection doesn't exist or crashes,  return empty.
        return ""

# 5. GENERATOR CHAIN
#Some Questions may not use the whole exact words for a Module or other Fields but mean the same thing.
generator_prompt = ChatPromptTemplate.from_template("""
You are a helpful assistant for the Master's Program in AI.
Answer the user's question using ONLY the context provided below.
If the answer is not in the context, say "I don't have that information in my documents."
Do not make up facts. 


CRITICAL INSTRUCTION:
1. Partial Name Matches: 
   - If the User's Query Module Name is a substring or close variation of a retrieved module's name (e.g. User: "Virtual Reality" -> Context: "Selected Topics of Augmented & Virtual Reality"), you SHOULD answer the question for the retrieved module.
   - EXCEPTION: If the names are identical or substantively the same (ignoring case/punctuation), DO NOT stick to the disclaimer rule. Just answer directly.
   - OTHERWISE (if they are significantly different), you MUST start by clarifying: "I don't have information strictly for '[User Name]', but I have information for '[Retrieved Name]'."
   - Then, provide the requested info.

2. Distinct Concepts: 
   - Be careful with terms that look similar but mean different things (e.g. "Deep Learning" vs "Deep Reinforcement Learning").
   - If the user asks for "Deep Learning" and you only found "Deep Reinforcement Learning", state: "I don't have info for 'Deep Learning', but I have info for 'Deep Reinforcement Learning'..." and then you may provide info for the latter if relevant.

3. Missing Fields: 
   - If the user asks for a specific field (e.g. "Prerequisites") and it is NOT in the context for the module, state: "The documents do not specify any [Field] for [Module Name]." (Do not make up 'None' unless the prerequisites are not present for that module).

4. Reply format:
   - Do not talk about which chunks have which information (e.g. don't say "It's mentioned in [CHUNK 1]"), just answer the question.

Context:
{context}

Question: {question}

Answer:
""")
generator_chain = generator_prompt | llm | StrOutputParser()

# 6. MAIN RAG FLOW
def run_rag(question):
    print(f"\nUser: {question}")
    
    # A. ROUTE
    print(f"\n--- 1. ROUTING (Model: {llm.model}) ---")
    
    category = router_chain.invoke({"question": question}).strip().lower()
    

    if ":" in category: category = category.split(":")[-1].strip()
    print(f"Decision: {category}")
    
    context = ""
    
    # B. RETRIEVE
    # Based on the category, we hit the specific Chroma collection.
    # Note: 'electives' are now merged into 'modules' collection.
    if "module" in category or "elective" in category:
        context = query_collection("modules", question)
    elif "regulation" in category:
        context = query_collection("regulations", question)
    else:
        # Default or "other":
        c1 = query_collection("modules", question, n_results=2)
        c2 = query_collection("regulations", question, n_results=1)
        context = c1 + "\n" + c2

    print(f"\n--- 2. RETRIEVAL (Top 3 Chunks) ---")
    if not context:
        print("No documents found.")
        context = "No information found."
    else:
        print(f"Raw Context:\n{context}\n")
    
    # C. GENERATE
    print(f"--- 3. GENERATION (Model: {llm.model}) ---")
    response = generator_chain.invoke({"context": context, "question": question})
    print(f"\nAI: {response}\n")
    return response

# 7. INTERACTIVE LOOP
if __name__ == "__main__":
    print("Welcome to the AI RAG System! (Type 'exit' to quit)")
    while True:
        q = input("> ")
        if q.lower() in ["exit", "quit", "q"]: break
        if not q.strip(): continue
        
        run_rag(q)
