class ChatResponse {
  const ChatResponse({
    required this.success,
    required this.answer,
    required this.metadata,
    required this.sources,
  });

  final bool success;
  final String answer;
  final Map<String, dynamic> metadata;
  final List<Map<String, dynamic>> sources;

  factory ChatResponse.fromJson(Map<String, dynamic> json) {
    final sources = json['sources'];
    return ChatResponse(
      success: json['success'] == true,
      answer: (json['answer'] ?? '').toString(),
      metadata: _extractMetadata(json),
      sources: sources is List
          ? sources
                .whereType<Map>()
                .map(
                  (item) => _normalizeSource(Map<String, dynamic>.from(item)),
                )
                .toList()
          : const [],
    );
  }

  static Map<String, dynamic> _extractMetadata(Map<String, dynamic> json) {
    const keys = [
      'search_type',
      'evaluation',
      'iteration_count',
      'retrieved_docs_count',
      'web_results_count',
      'confidence_level',
      'retrieval_mode',
      'retrieval_warning',
      'web_search_used',
      'web_search_available',
      'web_search_requires_approval',
      'llm_provider',
      'llm_model',
      'runtime_openai_active',
      'llm_fallback_warning',
      'llm_fallback_status',
      'error_reason',
      'trace_steps',
      'trace',
      'iterations',
      'documents_used',
      'relevant_chunks',
      'quality',
      'confidence',
      'evaluation_status',
      'dense',
      'bm25',
      'hybrid',
    ];

    final metadata = <String, dynamic>{};
    for (final key in keys) {
      final value = json[key];
      if (_hasDisplayValue(value)) {
        metadata[key] = value;
      }
    }
    return metadata;
  }

  static Map<String, dynamic> _normalizeSource(Map<String, dynamic> source) {
    final metadata = source['metadata'] is Map
        ? Map<String, dynamic>.from(source['metadata'] as Map)
        : <String, dynamic>{};
    final url = _firstValue(source, metadata, const ['url', 'link']);
    final title = _firstValue(source, metadata, const [
      'title',
      'document_title',
    ]);
    final sourceType = _firstValue(source, metadata, const [
      'source_type',
      'retrieval_type',
      'type',
    ]);
    final sourceMarker = _firstValue(source, metadata, const ['source']);
    final marker = '${sourceType ?? ''} ${sourceMarker ?? ''}'.toLowerCase();
    final retrievalScore = _firstValue(source, metadata, const [
      'retrieval_score',
      'score',
    ]);
    final denseScore = _firstValue(source, metadata, const ['dense_score']);
    final bm25Score = _firstValue(source, metadata, const ['bm25_score']);
    final metadataScore = _firstValue(source, metadata, const [
      'metadata_score',
    ]);
    final keywordScore = _firstValue(source, metadata, const [
      'keyword_score',
    ]);
    final fileName = _firstValue(source, metadata, const [
      'file_name',
      'filename',
    ]);
    final pageNumber = _firstValue(source, metadata, const [
      'page_number',
      'page',
    ]);
    final chunkId = _firstValue(source, metadata, const [
      'chunk_id',
      'chunk_index',
    ]);
    final sectionTitle = _firstValue(source, metadata, const [
      'section_title',
    ]);
    final collectionName = _firstValue(source, metadata, const [
      'collection_name',
    ]);
    final isWebSource =
        marker.contains('web') ||
        url != null ||
        (title != null && fileName == null);

    final normalized = <String, dynamic>{
      ...source,
      'metadata': metadata,
      'source_kind': isWebSource ? 'web' : 'document',
    };
    final optionalFields = <String, Object?>{
      'retrieval_score': retrievalScore,
      'dense_score': denseScore,
      'bm25_score': bm25Score,
      'metadata_score': metadataScore,
      'keyword_score': keywordScore,
      'file_name': fileName,
      'page_number': pageNumber,
      'chunk_id': chunkId,
      'section_title': sectionTitle,
      'collection_name': collectionName,
      'title': title,
      'url': url,
    }..removeWhere((key, value) => value == null);
    normalized.addAll(optionalFields);
    return normalized;
  }

  static Object? _firstValue(
    Map<String, dynamic> source,
    Map<String, dynamic> metadata,
    List<String> keys,
  ) {
    for (final key in keys) {
      final direct = source[key];
      if (_hasDisplayValue(direct)) {
        return direct;
      }
      final nested = metadata[key];
      if (_hasDisplayValue(nested)) {
        return nested;
      }
    }
    return null;
  }

  static bool _hasDisplayValue(Object? value) {
    if (value == null) {
      return false;
    }
    if (value is String) {
      return value.trim().isNotEmpty;
    }
    if (value is Iterable) {
      return value.isNotEmpty;
    }
    return true;
  }
}
