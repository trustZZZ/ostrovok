"""
Утилиты LLM: тонкая обёртка над единым клиентом app.llm_client.

Единая точка импорта для graph.py, search.py и других модулей.
"""
from app.llm_client import get_llm, generate_questions, parse_answer_with_llm

__all__ = ["get_llm", "generate_questions", "parse_answer_with_llm"]