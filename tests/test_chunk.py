from app.retrieval.chunk import chunk_text, _split_long


def test_short_text_single_chunk():
    assert chunk_text("hello world") == ["hello world"]


def test_empty_text_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_long_text_splits_into_multiple():
    para = ("This is a sentence about peptide testing. " * 40).strip()
    chunks = chunk_text(para, max_chars=300, overlap=40)
    assert len(chunks) > 1
    assert all(c.strip() for c in chunks)
    # content preserved (first words appear)
    assert "peptide testing" in chunks[0]


def test_oversized_paragraph_without_sentences_is_hard_split():
    blob = "word " * 800  # ~4000 chars, no sentence boundaries
    pieces = _split_long(blob, 500)
    assert all(len(p) <= 500 for p in pieces)
    assert len("".join(pieces).replace(" ", "")) > 0


def test_paragraph_boundaries_respected():
    text = "First para about labs.\n\nSecond para about vendors.\n\nThird para about codes."
    chunks = chunk_text(text, max_chars=40, overlap=10)
    joined = " ".join(chunks)
    assert "labs" in joined and "vendors" in joined and "codes" in joined
