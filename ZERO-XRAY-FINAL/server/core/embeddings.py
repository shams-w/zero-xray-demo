from sentence_transformers import SentenceTransformer
import faiss
import numpy as np


class StandardsKnowledgeBase:

    def __init__(self):
        self.model = SentenceTransformer(
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )

        self.standards = []
        self.index = None

    def build(self, text):

        chunks = [
            chunk.strip()
            for chunk in text.split("\n\n")
            if chunk.strip()
        ]

        self.standards = chunks

        embeddings = self.model.encode(
            chunks,
            normalize_embeddings=True
        )

        embeddings = np.array(
            embeddings,
            dtype="float32"
        )

        dimension = embeddings.shape[1]

        self.index = faiss.IndexFlatIP(dimension)

        self.index.add(embeddings)

    def search(self, query, k=5):

        if self.index is None:
            raise RuntimeError(
                "Knowledge base has not been initialized."
            )

        query_embedding = self.model.encode(
            [query],
            normalize_embeddings=True
        )

        query_embedding = np.array(
            query_embedding,
            dtype="float32"
        )

        scores, indices = self.index.search(
            query_embedding,
            k
        )

        results = []

        for score, index in zip(
            scores[0],
            indices[0]
        ):
            if index < len(self.standards):
                results.append({
                    "standard": self.standards[index],
                    "score": float(score)
                })

        return results