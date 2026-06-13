# Markdown-Based Table Chunking Strategy

Text is chunked with `RecursiveCharacterTextSplitter`.

Markdown tables are handled separately:

1. Detect a table header row containing pipes.
2. Confirm the next row is a Markdown separator row.
3. Capture all following pipe rows.
4. Store the full table as a single chunk.

This keeps table headers and rows together during vector search.

