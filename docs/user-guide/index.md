# User Guide

This guide covers the main concepts and usage patterns of Kreuzberg for text extraction.

## Contents

- [Basic Usage](basic-usage.md) - Essential usage patterns and concepts
- [OCR Configuration](ocr-configuration.md) - Configure OCR for optimal text extraction
- [OCR Backends](ocr-backends.md) - Choose and configure different OCR engines
- [Supported Formats](supported-formats.md) - Details on all supported document formats

## Best Practices

- Use the async API for better performance in web applications and concurrent extraction
- Configure OCR language settings to match your document languages for better accuracy
- For large documents, consider file streaming methods to reduce memory usage
- When processing many similar documents, reuse configuration objects for consistency

## Common Use Cases

**Document Analysis:**

```python
from kreuzberg import extract_file, ExtractionConfig

async def analyze_document(file_path):
    result = await extract_file(file_path, config=ExtractionConfig())

    # Get basic document content
    text = result.content

    # Access metadata
    title = result.metadata.get("title", "Untitled")
    author = result.metadata.get("authors", ["Unknown"])[0]

    return {"title": title, "author": author, "content": text, "word_count": len(text.split()), "char_count": len(text)}
```
