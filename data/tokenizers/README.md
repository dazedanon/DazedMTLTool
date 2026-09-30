# Offline token counting

The existing translators and Len API estimates use the `cl100k_base` encoding
for GPT-4-compatible token counting. The cached table is shipped so a clean
installation can count tokens without downloading a file. It is tokenizer data,
not a model or any game content.

- Source: https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken
- Cache filename (SHA-1 of the source URL): `9b5ad71b2ce5302211f9c61530b329a4922fc6a4`
- SHA-256: `223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7`
- Loader and checksum: `tiktoken_ext.openai_public.cl100k_base`
- tiktoken license: [MIT](LICENSE.txt)

Keep the table, attribution, ignore exception, and shipped-data inventory together
when updating this encoding. Tiktoken verifies the table against its own checksum.
