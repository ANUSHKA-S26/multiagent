"""
Slide Knowledge Base

Stores PDF slide content using a local vector database
with local semantic embeddings.

Embedding model:
    sentence-transformers/all-MiniLM-L6-v2

No OpenAI API or external embedding API is required.
"""

import json
import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

import numpy as np


# ============================================================
# OPTIONAL CHROMADB
# ============================================================

try:
    import chromadb
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    print(
        "Warning: chromadb not available. "
        "Using simple local vector storage."
    )


# ============================================================
# LOCAL EMBEDDING MODEL
# ============================================================

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    print(
        "Warning: sentence-transformers not available. "
        "Keyword search will be used."
    )


class SlideKnowledgeBase:
    """
    Slide knowledge base for storing and retrieving PDF content.

    All embeddings are generated locally using SentenceTransformers.
    """

    def __init__(
        self,
        knowledge_base_name: str,
        kb_dir: str = "knowledge_base"
    ):
        self.kb_name = knowledge_base_name

        self.kb_dir = (
            Path(kb_dir) /
            knowledge_base_name
        )

        self.kb_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        # ----------------------------------------------------
        # Load local embedding model
        # ----------------------------------------------------

        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                print(
                    "Loading local embedding model "
                    "all-MiniLM-L6-v2..."
                )

                self.embedding_model = SentenceTransformer(
                    "sentence-transformers/all-MiniLM-L6-v2"
                )

                print(
                    "✓ Local embedding model loaded."
                )

            except Exception as e:
                print(
                    f"Warning: Could not load local "
                    f"embedding model: {e}"
                )

                self.embedding_model = None

        else:
            self.embedding_model = None

        # ----------------------------------------------------
        # Initialize storage
        # ----------------------------------------------------

        if CHROMADB_AVAILABLE:
            self._init_chromadb()
        else:
            self._init_simple_storage()


    # ========================================================
    # CHROMADB
    # ========================================================

    def _init_chromadb(self):
        """Initialize local ChromaDB vector database."""

        chroma_dir = (
            self.kb_dir /
            "chroma_db"
        )

        self.chroma_client = (
            chromadb.PersistentClient(
                path=str(chroma_dir)
            )
        )

        self.collection = (
            self.chroma_client
            .get_or_create_collection(
                name=self.kb_name,
                metadata={
                    "description":
                    "Slide deck knowledge base"
                }
            )
        )

        self.use_chromadb = True

        # Load chunks for keyword-search fallback.
        self.chunks = []

        chunks_file = (
            self.kb_dir /
            "chunks.json"
        )

        if chunks_file.exists():
            try:
                with open(
                    chunks_file,
                    "r",
                    encoding="utf-8"
                ) as f:
                    self.chunks = json.load(f)

            except Exception as e:
                print(
                    f"Warning: Could not load "
                    f"chunks.json: {e}"
                )


    # ========================================================
    # SIMPLE LOCAL STORAGE
    # ========================================================

    def _init_simple_storage(self):
        """Use simple file-based vector storage."""

        self.embeddings_file = (
            self.kb_dir /
            "embeddings.pkl"
        )

        self.data_file = (
            self.kb_dir /
            "chunks.json"
        )

        self.embeddings = {}
        self.chunks = []

        self.use_chromadb = False

        # Load existing chunks
        if self.data_file.exists():
            try:
                with open(
                    self.data_file,
                    "r",
                    encoding="utf-8"
                ) as f:
                    self.chunks = json.load(f)

            except Exception as e:
                print(
                    f"Warning: Could not load "
                    f"existing chunks: {e}"
                )

        # Load existing embeddings
        if self.embeddings_file.exists():
            try:
                with open(
                    self.embeddings_file,
                    "rb"
                ) as f:
                    self.embeddings = (
                        pickle.load(f)
                    )

            except Exception as e:
                print(
                    f"Warning: Could not load "
                    f"existing embeddings: {e}"
                )


    # ========================================================
    # CREATE KNOWLEDGE BASE
    # ========================================================

    def create_from_extracted_data(
        self,
        extracted_data: Dict[str, Any],
        chapter_filter: Optional[str] = None
    ):
        """
        Create knowledge base from extracted PDF data.
        """

        total_files = extracted_data.get(
            "total_extracted_files",
            len(extracted_data.get("slides", []))
        )

        print(
            f"Creating knowledge base from "
            f"{total_files} extracted files..."
        )

        chunks = []

        for slide_deck in extracted_data.get(
            "slides",
            []
        ):

            if (
                "error" in slide_deck
                or not slide_deck.get(
                    "slide_structure"
                )
            ):
                continue

            for slide in slide_deck[
                "slide_structure"
            ]:

                chunk = {
                    "id": (
                        f"{slide_deck['pdf_name']}"
                        f"_slide_"
                        f"{slide['slide_number']}"
                    ),

                    "pdf_name":
                    slide_deck["pdf_name"],

                    "filename":
                    slide_deck["filename"],

                    "slide_number":
                    slide["slide_number"],

                    "title":
                    slide["title"],

                    "content":
                    slide["content"],

                    "bullet_points":
                    slide.get(
                        "bullet_points",
                        []
                    ),

                    "chapter_filter":
                    chapter_filter,

                    "user_requirements":
                    extracted_data.get(
                        "user_requirements",
                        ""
                    ),

                    "metadata": {
                        "file_path":
                        slide_deck.get(
                            "file_path"
                        ),

                        "processed_at":
                        slide_deck.get(
                            "processed_at"
                        ),

                        "extracted_at":
                        extracted_data.get(
                            "extracted_at"
                        )
                    }
                }

                chunks.append(chunk)

        if not chunks:
            print(
                "Warning: No chunks to process"
            )

            return {
                "knowledge_base_name":
                self.kb_name,

                "created_at":
                datetime.now().isoformat(),

                "total_chunks": 0,

                "message":
                "No content extracted"
            }

        # Save chunks in memory too.
        self.chunks = chunks

        print(
            f"Generating LOCAL embeddings "
            f"for {len(chunks)} chunks..."
        )

        stored_count = 0

        for i, chunk in enumerate(chunks):

            if (i + 1) % 10 == 0:
                print(
                    f"  Progress: "
                    f"{i + 1}/{len(chunks)}"
                )

            text_to_embed = (
                f"{chunk['title']}\n"
                f"{chunk['content']}"
            )

            embedding = (
                self._generate_embedding(
                    text_to_embed
                )
            )

            if embedding is None:
                continue

            # ----------------------------------------------
            # ChromaDB
            # ----------------------------------------------

            if self.use_chromadb:
                try:
                    # upsert is safer than add when a KB
                    # is regenerated with the same IDs.
                    self.collection.upsert(
                        ids=[chunk["id"]],
                        embeddings=[embedding],
                        documents=[
                            text_to_embed
                        ],
                        metadatas=[
                            chunk["metadata"]
                        ]
                    )

                    stored_count += 1

                except Exception as e:
                    print(
                        "Warning: Failed to add "
                        f"to ChromaDB: {e}"
                    )

            # ----------------------------------------------
            # Simple storage
            # ----------------------------------------------

            else:
                self.embeddings[
                    chunk["id"]
                ] = embedding

                stored_count += 1

        # Save simple embeddings if ChromaDB
        # isn't available.
        if not self.use_chromadb:

            with open(
                self.embeddings_file,
                "wb"
            ) as f:
                pickle.dump(
                    self.embeddings,
                    f
                )

        # Always save chunks.json.
        chunks_json_file = (
            self.kb_dir /
            "chunks.json"
        )

        with open(
            chunks_json_file,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                chunks,
                f,
                indent=2,
                ensure_ascii=False
            )

        # Save metadata.
        metadata = {
            "knowledge_base_name":
            self.kb_name,

            "created_at":
            datetime.now().isoformat(),

            "total_chunks":
            len(chunks),

            "stored_embeddings":
            stored_count,

            "embedding_model":
            (
                "sentence-transformers/"
                "all-MiniLM-L6-v2"
            ),

            "embedding_type":
            "local",

            "source_storage_id":
            extracted_data.get(
                "storage_id"
            ),

            "user_requirements":
            extracted_data.get(
                "user_requirements"
            ),

            "target_chapters":
            extracted_data.get(
                "target_chapters"
            ),

            "chapter_filter":
            chapter_filter
        }

        metadata_file = (
            self.kb_dir /
            "metadata.json"
        )

        with open(
            metadata_file,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                metadata,
                f,
                indent=2,
                ensure_ascii=False
            )

        print(
            f"✓ Knowledge base created with "
            f"{len(chunks)} chunks"
        )

        print(
            f"✓ Stored {stored_count} "
            f"local embeddings"
        )

        return metadata


    # ========================================================
    # LOCAL EMBEDDING GENERATION
    # ========================================================

    def _generate_embedding(
        self,
        text: str
    ) -> Optional[List[float]]:
        """
        Generate embedding locally.

        No API call is made.
        """

        if self.embedding_model is None:
            return None

        try:
            # Limit extremely large text chunks.
            text = text[:12000]

            embedding = (
                self.embedding_model.encode(
                    text,
                    normalize_embeddings=True,
                    convert_to_numpy=True
                )
            )

            return embedding.tolist()

        except Exception as e:
            print(
                f"Error generating local "
                f"embedding: {e}"
            )

            return None


    # ========================================================
    # SEMANTIC SEARCH
    # ========================================================

    def search(
        self,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Semantic search for relevant slide content.
        """

        if not query or not query.strip():
            return []

        # If local embedding model could not load,
        # fall back to keyword search.
        if self.embedding_model is None:
            return self._keyword_search(
                query,
                top_k
            )

        query_embedding = (
            self._generate_embedding(
                query
            )
        )

        if query_embedding is None:
            return self._keyword_search(
                query,
                top_k
            )

        # ----------------------------------------------------
        # ChromaDB search
        # ----------------------------------------------------

        if self.use_chromadb:
            try:
                collection_count = (
                    self.collection.count()
                )

                if collection_count == 0:
                    return self._keyword_search(
                        query,
                        top_k
                    )

                actual_top_k = min(
                    top_k,
                    collection_count
                )

                results = (
                    self.collection.query(
                        query_embeddings=[
                            query_embedding
                        ],
                        n_results=actual_top_k
                    )
                )

                formatted_results = []

                if (
                    results.get("ids")
                    and len(results["ids"]) > 0
                ):
                    result_ids = (
                        results["ids"][0]
                    )

                    documents = (
                        results.get(
                            "documents"
                        ) or [[]]
                    )[0]

                    metadatas = (
                        results.get(
                            "metadatas"
                        ) or [[]]
                    )[0]

                    distances = (
                        results.get(
                            "distances"
                        ) or [[]]
                    )[0]

                    for i in range(
                        len(result_ids)
                    ):

                        formatted_results.append({
                            "id":
                            result_ids[i],

                            "content":
                            (
                                documents[i]
                                if i < len(documents)
                                else ""
                            ),

                            "metadata":
                            (
                                metadatas[i]
                                if i < len(metadatas)
                                else {}
                            ),

                            "distance":
                            (
                                distances[i]
                                if i < len(distances)
                                else None
                            )
                        })

                return formatted_results

            except Exception as e:
                print(
                    f"Error searching "
                    f"ChromaDB: {e}"
                )

                return self._keyword_search(
                    query,
                    top_k
                )

        # ----------------------------------------------------
        # Simple cosine-similarity search
        # ----------------------------------------------------

        similarities = []

        for (
            chunk_id,
            embedding
        ) in self.embeddings.items():

            similarity = (
                self._cosine_similarity(
                    query_embedding,
                    embedding
                )
            )

            similarities.append(
                (
                    similarity,
                    chunk_id
                )
            )

        similarities.sort(
            reverse=True,
            key=lambda x: x[0]
        )

        results = []

        chunk_dict = {
            chunk["id"]: chunk
            for chunk in self.chunks
        }

        for (
            similarity,
            chunk_id
        ) in similarities[:top_k]:

            chunk = chunk_dict.get(
                chunk_id,
                {}
            )

            results.append({
                "id":
                chunk_id,

                "content":
                (
                    f"{chunk.get('title', '')}\n"
                    f"{chunk.get('content', '')}"
                ),

                "metadata":
                chunk.get(
                    "metadata",
                    {}
                ),

                "similarity":
                float(similarity)
            })

        return results


    # ========================================================
    # KEYWORD FALLBACK
    # ========================================================

    def _keyword_search(
        self,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Keyword search fallback.

        Used only if local semantic embeddings
        cannot be generated.
        """

        query_lower = query.lower()

        keywords = [
            word
            for word in query_lower.split()
            if len(word) > 2
        ]

        if not keywords:
            return []

        results = []

        for chunk in self.chunks[:100]:

            text = (
                f"{chunk.get('title', '')} "
                f"{chunk.get('content', '')}"
            ).lower()

            score = sum(
                1
                for keyword in keywords
                if keyword in text
            )

            if score > 0:
                results.append({
                    "id":
                    chunk.get(
                        "id",
                        ""
                    ),

                    "content":
                    (
                        f"{chunk.get('title', '')}\n"
                        f"{chunk.get('content', '')}"
                    ),

                    "metadata":
                    chunk.get(
                        "metadata",
                        {}
                    ),

                    "similarity":
                    score / len(keywords)
                })

        results.sort(
            reverse=True,
            key=lambda x: x["similarity"]
        )

        return results[:top_k]


    # ========================================================
    # COSINE SIMILARITY
    # ========================================================

    def _cosine_similarity(
        self,
        vec1: List[float],
        vec2: List[float]
    ) -> float:
        """Calculate cosine similarity."""

        try:
            vec1 = np.array(
                vec1,
                dtype=np.float32
            )

            vec2 = np.array(
                vec2,
                dtype=np.float32
            )

            dot_product = np.dot(
                vec1,
                vec2
            )

            norm1 = np.linalg.norm(
                vec1
            )

            norm2 = np.linalg.norm(
                vec2
            )

            if (
                norm1 == 0
                or norm2 == 0
            ):
                return 0.0

            return float(
                dot_product /
                (norm1 * norm2)
            )

        except Exception as e:
            print(
                f"Error calculating "
                f"cosine similarity: {e}"
            )

            return 0.0


    # ========================================================
    # SUMMARY
    # ========================================================

    def get_all_content_summary(
        self
    ) -> Dict[str, Any]:
        """
        Get summary of knowledge-base contents.
        """

        if self.use_chromadb:
            try:
                count = (
                    self.collection.count()
                )

                return {
                    "total_chunks":
                    count,

                    "type":
                    "chromadb",

                    "embedding_model":
                    "all-MiniLM-L6-v2",

                    "embedding_type":
                    "local"
                }

            except Exception as e:
                return {
                    "total_chunks":
                    0,

                    "type":
                    "chromadb",

                    "error":
                    str(e)
                }

        return {
            "total_chunks":
            len(self.chunks),

            "type":
            "simple_storage",

            "embedding_model":
            "all-MiniLM-L6-v2",

            "embedding_type":
            "local",

            "chunks":
            self.chunks[:10]
        }