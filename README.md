# University RAG System (Master AI for Industrial Applications)

This project is a **Retrieval-Augmented Generation (RAG)** system designed to assist students of the **Master Artificial Intelligence for Industrial Applications** program. It allows users to query information regarding course modules, electives, and examination regulations using natural language.

The system indexes extracted data from university PDF documents (Course Catalogue, Study Plans, Regulations) and uses a local Large Language Model (LLM) to provide accurate, context-aware answers.

## 🚀 Features

*   **Intelligent Query Routing**: automatically classifies questions into "Modules" or "Regulations" to query the most relevant data source.
*   **Module Information**: Retrieve details like Learning Outcomes, Content, Credits (ECTS), Professors, and Prerequisites.
*   **Regulation Insights**: Ask about exam rules, grading policies, and preliminary notes.
*   **Source Attribution**: Answers include citations (e.g., "[CHUNK 1] (Source: ...)") to verify information.
*   **Local Privacy**: Runs entirely locally using **Ollama** and **ChromaDB**, ensuring data privacy.

## 🛠️ Tech Stack

*   **Language**: Python 3.8+
*   **LLM Orchestration**: [LangChain](https://www.langchain.com/)
*   **Vector Database**: [ChromaDB](https://www.trychroma.com/) (Persistent local storage)
*   **LLM Server**: [Ollama](https://ollama.com/) (running Llama 3)
*   **Embeddings**: `sentence-transformers` (`all-MiniLM-L6-v2`)
*   **Containerization**: Docker & Docker Compose

## 📋 Prerequisites

Before running the system, ensure you have the following:

1.  **Ollama**: Installed and running on your local machine.
    *   One-click install from [ollama.com](https://ollama.com/).
    *   Pull the Llama 3 model:
        ```bash
        ollama pull llama3
        ```
2.  **Files**: The `data/` folder must contain the necessary JSON files (`master_modules.json`, `regulations.json`, etc.). *These are typically generated from the raw PDFs using the `Extraction.ipynb` notebook.*

## ⚡ Installation & Usage (Local Python)

1.  **Clone the Repository**
    ```bash
    git clone <repository_url>
    cd RAG_System
    ```

2.  **Install Dependencies**
    It is recommended to use a virtual environment.
    ```bash
    pip install -r requirements.txt
    ```

3.  **Build the Vector Index**
    This step reads the JSON data from `data/` and creates the ChromaDB index.
    ```bash
    python build_index.py
    ```
    *Output: You should see "Index built successfully in 'data/chroma_db'!"*

4.  **Run the Query System**
    Start the interactive CLI:
    ```bash
    python query_rag.py
    ```
    You can now ask questions like:
    > "What are the prerequisites for Deep Learning?"
    > "Tell me about the exam regulations for failing a module."

## 🐳 Running with Docker

You can run the entire application in a Docker container.

1.  **Ensure Ollama is running** on your host machine.
    *   *Note: The `docker-compose.yml` is configured to connect to `host.docker.internal:11434` to access your local Ollama instance.*

2.  **Build and Run**
    ```bash
    docker-compose up --build
    ```

3.  **Interact with the Container**
    Since the application waits for user input (`stdin`), you need to attach to the running container if not started in interactive mode, or typically run it directly via:
    ```bash
    docker run -it --network="host" -v ${PWD}/data:/app/data rag-system python query_rag.py
    ```
    *(Or simply use the local Python method if interactive Docker usage is tricky on your setup).*

## 📂 Project Structure

```graphql
RAG_System/
├── data/                    # Data storage
│   ├── chroma_db/           # Generated Vector Database (Persistent)
│   ├── master_modules.json  # Extracted Module Data
│   ├── regulations.json     # Extracted Regulation Data
│   └── ...
├── build_index.py           # Script to ingest JSONs into ChromaDB
├── query_rag.py             # Main CLI script for RAG queries
├── requirements.txt         # Python dependencies
├── docker-compose.yml       # Docker services configuration
├── Dockerfile               # Docker image definition
└── Extraction.ipynb         # Notebook used for PDF -> JSON extraction
```

## 🧠 System Architecture

1.  **Ingestion**: `build_index.py` loads JSON data, creates embeddings using `all-MiniLM-L6-v2`, and stores them in `ChromaDB`.
2.  **Routing**: Incoming queries are analyzed by an LLM Router to choose the best collection ("modules" vs "regulations").
3.  **Retrieval**: The top 3 most relevant chunks are fetched from ChromaDB.
4.  **Generation**: The context is passed to Llama 3 (via Ollama) to generate a precise, grounded answer.


