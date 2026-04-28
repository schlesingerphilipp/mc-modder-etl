import pytest
import numpy as np
from unittest.mock import patch
from app.vectordb.categorize_commits import batch_summaries_kmeans, deduplicate_categories, CategoryList
import app.vectordb.categorize_commits as categorize_commits

class TestBatchSummariesKMeans:
    def test_batches_correct_number(self):
        rng = np.random.RandomState(42)
        embeddings = rng.randn(100, 8)
        labels = batch_summaries_kmeans(embeddings, summaries_per_batch=20)
        # Should create 5 clusters
        assert len(set(labels)) == 5
        assert labels.shape == (100,)

class TestDeduplicateCategories:
    def test_deduplicate_simple(self):
        # Patch get_llm to return a dummy object with .invoke returning a CategoryList
        class DummyLLM:
            def invoke(self, input=None, **kwargs):
                return CategoryList(categories=["A", "B", "C"])
        with patch.object(categorize_commits, "get_llm", return_value=DummyLLM()):
            categories = ["A", "A", "B", "C", "B"]
            result = categorize_commits.deduplicate_categories(categories)
            assert set(result) == {"A", "B", "C"}
