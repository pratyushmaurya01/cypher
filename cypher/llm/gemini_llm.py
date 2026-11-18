"""LangChain-native Gemini client — query understanding + grounded answer generation.

Two distinct LangChain LCEL calls per chat request:
  Call 1: Query Understanding (ChatGoogleGenerativeAI -> JsonOutputParser)
  Call 2: Answer Generation (ChatGoogleGenerativeAI -> StrOutputParser)
"""

from __future__ import annotations

import json
import logging
import textwrap
from typing import Any

from cypher.config import get_settings

logger = logging.getLogger(__name__)

# Supported graph relationship types — prevents LLM hallucinations
_VALID_RELATIONSHIP_TYPES = frozenset({
    "CALLS", "DEFINES", "DEFINES_METHOD", "IMPORTS", "INHERITS",
    "INSTANTIATES", "ROUTES_TO", "INCLUDES", "CONTAINS",
})

_VALID_ENTITY_TYPES = frozenset({
    "Function", "Class", "Module", "Route", "ExternalDependency", "Repository",
})

_VALID_DIRECTIONS = frozenset({"incoming", "outgoing", "both"})
_MAX_DEPTH = 3


class GeminiLLMError(Exception):
    """Raised when Gemini LangChain calls fail."""


class GeminiClient:
    """LangChain-native Gemini client for Cypher RAG pipeline."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()

        self._api_key = api_key or settings.gemini_api_key
        self._model = model or settings.gemini_model

        if not self._api_key:
            raise GeminiLLMError("GEMINI_API_KEY is not configured in .env.")

        try:
            from langchain_google_genai import ChatGoogleGenerativeAI

            self._chat_llm = ChatGoogleGenerativeAI(
                model=self._model,
                google_api_key=self._api_key,
                temperature=0.1,
            )
            logger.info("GeminiClient (LangChain) ready: model=%s", self._model)
        except Exception as exc:
            raise GeminiLLMError(f"LangChain Gemini init failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Call 1: Query Understanding
    # ------------------------------------------------------------------

    def understand_query(self, question: str, repository_summary: str = "") -> "QueryUnderstanding":
        """Parse user question into structured retrieval intent."""
        from cypher.schemas.rag import QueryUnderstanding
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        prompt_text = _build_understanding_prompt(question, repository_summary)
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an expert code intelligence analyzer for Python codebases."),
            ("human", "{prompt}"),
        ])
        chain = prompt | self._chat_llm | StrOutputParser()

        try:
            raw = chain.invoke({"prompt": prompt_text}).strip()
            # Clean markdown code block fences if returned
            if raw.startswith("```json"):
                raw = raw[7:]
            elif raw.startswith("```"):
                raw = raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

            data = json.loads(raw)
            understanding = QueryUnderstanding.model_validate(data)
            _sanitize_understanding(understanding)
            return understanding
        except Exception as exc:
            logger.error("LangChain understand_query failed: %s", exc)
            raise GeminiLLMError(f"Query understanding failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Call 2: Final Answer Generation
    # ------------------------------------------------------------------

    def generate_answer(
        self,
        question: str,
        understanding: "QueryUnderstanding",
        evidence_context: str,
    ) -> str:
        """Generate a grounded, richly-cited Markdown answer with inline code blocks."""
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        prompt_text = _build_generation_prompt(question, understanding, evidence_context)
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are Cypher, an expert code intelligence assistant for Python repositories."),
            ("human", "{prompt}"),
        ])
        chain = prompt | self._chat_llm | StrOutputParser()

        try:
            answer = chain.invoke({"prompt": prompt_text}).strip()
            if not answer:
                raise GeminiLLMError("Gemini returned an empty answer.")
            return answer
        except Exception as exc:
            logger.error("LangChain generate_answer failed: %s", exc)
            raise GeminiLLMError(f"Answer generation failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_understanding_prompt(question: str, repo_summary: str) -> str:
    return textwrap.dedent(f"""
    Analyze the user's question and return structured JSON for retrieval from a Code Knowledge Graph (Neo4j) and Vector search (ChromaDB).

    ## Repository summary:
    {repo_summary or "No summary available."}

    ## User question:
    "{question}"

    ## Output format (respond ONLY with valid JSON):
    {{
      "intent": "<one of: locate_symbol | trace_calls | explain_model | find_route | impact_analysis | architecture_overview | debug_error | generic_search | greeting>",
      "language": "<detected language: english | hindi | hinglish>",
      "entities": ["<symbol names, class names, function names, or file names like views.py, urls.py mentioned>"],
      "keywords": ["<relevant technical keywords for semantic search>"],
      "search_queries": [
        "<rephrased search query 1 optimized for embedding search>",
        "<rephrased search query 2>"
      ],
      "retrieval": {{
        "vector": true,
        "graph": true
      }},
      "graph_search": {{
        "entity_types": ["<from: Function, Class, Module, Route>"],
        "relationship_types": ["<from: CALLS, DEFINES, IMPORTS, INHERITS, INSTANTIATES, ROUTES_TO>"],
        "direction": "<incoming | outgoing | both>",
        "max_depth": 2
      }},
      "is_deterministic": false
    }}

    Rules:
    - If user says a greeting (like 'hi', 'hello', 'hey', 'namaste'), set intent to 'greeting'.
    - If user asks about a specific file (e.g. 'views.py', 'models.py', 'urls.py'), put that file name in 'entities' and 'keywords', and search for functions/classes defined inside it.
    - If user asks for all URLs or routes, set intent to 'find_route' and include 'urls.py' in entities.
    - For impact analysis questions (what breaks if X changes), use direction: 'both' and max_depth: 3.
    - Return ONLY the JSON object. No explanation text.
    """).strip()


def _build_generation_prompt(
    question: str,
    understanding: "QueryUnderstanding",
    evidence_context: str,
) -> str:
    if understanding.intent == "greeting":
        return textwrap.dedent(f"""
        The user has sent a greeting: "{question}".
        Respond warmly and concisely in {understanding.language}.
        Introduce yourself as Cypher, their codebase assistant.
        Tell them you are ready to answer questions about the repository's architecture, models, routes, and execution flow.
        Keep it brief (2-3 sentences).
        """).strip()

    return textwrap.dedent(f"""
    You are Cypher, an expert code intelligence assistant for Python repositories.

    ## Instructions
    - Directly answer the user's question using the retrieved code evidence below.
    - If the user asked for specific items (like "what functions are in views.py" or "list all routes"), LIST EXACTLY THOSE ITEMS FIRST with a clear explanation, then provide their code snippets.
    - Embed the relevant source code using markdown code blocks formatted as:
        ```python
        # <file_path> (Lines <start>-<end>)
        <exact source code here>
        ```
    - Clearly state which file and which lines contain each relevant piece of code.
    - Do NOT output unrelated files or unrelated symbols. Stay strictly focused on the user's specific question.
    - Respond in the user's language ({understanding.language}). If they asked in Hinglish or Hindi, respond naturally in Hinglish or Hindi with clear technical terms.

    ## User question:
    {question}

    ## Detected intent:
    {understanding.intent}

    ## Retrieved code evidence:
    {evidence_context}

    ## Your response:
    Give a clear, accurate, and direct answer. Include inline code snippets for the key functions/classes asked about.
    """).strip()


def _sanitize_understanding(u: "QueryUnderstanding") -> None:
    """Enforce safe bounds on what the LLM returned."""
    if u.graph_search:
        u.graph_search.max_depth = min(u.graph_search.max_depth, _MAX_DEPTH)
        u.graph_search.relationship_types = [
            r for r in u.graph_search.relationship_types if r in _VALID_RELATIONSHIP_TYPES
        ]
        u.graph_search.entity_types = [
            e for e in u.graph_search.entity_types if e in _VALID_ENTITY_TYPES
        ]
        if u.graph_search.direction not in _VALID_DIRECTIONS:
            u.graph_search.direction = "both"

    u.search_queries = u.search_queries[:5]
    u.entities = u.entities[:10]
    u.keywords = u.keywords[:10]
