
"""
Test Gemini Chat Models and Embeddings using LangChain.

Run:
    .\.venv\Scripts\python.exe testmodel.py
"""

import os
from dotenv import load_dotenv

# 1. Load API key
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY", "")

if not api_key:
    print("ERROR: GEMINI_API_KEY is not set in .env")
    raise SystemExit(1)

print("GEMINI_API_KEY loaded successfully!")
print("=" * 65)

# 2. LangChain imports
from langchain_google_genai import (
    ChatGoogleGenerativeAI,
    GoogleGenerativeAIEmbeddings
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


# ---------------------------------------------------------
# 3. Test both Chat Models
# ---------------------------------------------------------

candidate_models = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]

working_chat_models = []

print("\nCHAT MODEL TESTING")
print("=" * 65)

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful coding assistant."),
    ("human", "{input_text}"),
])

output_parser = StrOutputParser()

for model_name in candidate_models:

    print(f"\nTrying model: {model_name}")

    try:
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
        )

        chain = prompt | llm | output_parser

        response = chain.invoke({
            "input_text": "Hi! Explain Python in one sentence."
        })

        print(f"SUCCESS: {model_name}")
        print(f"Response: {response.strip()}")

        working_chat_models.append(model_name)

    except Exception as e:
        print(f"FAILED: {model_name}")
        print(f"Error: {e}")


# ---------------------------------------------------------
# 4. Test Embedding Model
# ---------------------------------------------------------

embedding_model = "gemini-embedding-001"
working_embed_model = None

print("\n" + "=" * 65)
print("EMBEDDING MODEL TESTING")
print("=" * 65)

try:
    embeddings = GoogleGenerativeAIEmbeddings(
        model=embedding_model,
        google_api_key=api_key,
    )

    sample_text = """
    def login_user(request):
        return authenticate(request)
    """

    vector = embeddings.embed_query(sample_text)

    print(f"SUCCESS: {embedding_model}")
    print(f"Vector dimensions: {len(vector)}")
    print(
        f"Vector preview: "
        f"[{vector[0]:.4f}, {vector[1]:.4f}, {vector[2]:.4f}, ...]"
    )

    working_embed_model = embedding_model

except Exception as e:
    print(f"FAILED: {embedding_model}")
    print(f"Error: {e}")


# ---------------------------------------------------------
# 5. Final Summary
# ---------------------------------------------------------

print("\n" + "=" * 65)
print("FINAL TEST SUMMARY")
print("=" * 65)

print("\nWorking Chat Models:")

if working_chat_models:
    for model in working_chat_models:
        print(f"  SUCCESS: {model}")
else:
    print("  No chat models working.")

print("\nWorking Embedding Model:")
print(f"  {working_embed_model or 'None'}")

print("\n" + "=" * 65)
