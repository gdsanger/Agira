"""
RAG (Retrieval-Augmented Generation) Pipeline Service for Agira.

This module provides a centralized RAG service that performs hybrid search
(BM25 + Vector) over Weaviate data and returns structured, agent-ready context.
"""

from .service import RAGPipelineService, build_context
from .models import RAGContext, RAGContextObject
from .extended_service import (
    ExtendedRAGPipelineService,
    build_extended_context,
    ExtendedRAGContext,
    OptimizedQuery,
)

__all__ = [
    "RAGPipelineService",
    "build_context",
    "RAGContext",
    "RAGContextObject",
    "ExtendedRAGPipelineService",
    "build_extended_context",
    "ExtendedRAGContext",
    "OptimizedQuery",
]
