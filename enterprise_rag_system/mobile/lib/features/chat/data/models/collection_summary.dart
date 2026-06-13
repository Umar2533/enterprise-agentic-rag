import '../../../../../core/constants/api_constants.dart';

class CollectionSummary {
  const CollectionSummary({
    required this.collectionName,
    required this.embeddingProvider,
    this.sessionId = '',
    this.filename = '',
    this.source = '',
    this.chunkCount,
    this.bm25Ready,
    this.retrievalMode = '',
    this.retrievalWarning = '',
  });

  final String collectionName;
  final String embeddingProvider;
  final String sessionId;
  final String filename;
  final String source;
  final int? chunkCount;
  final bool? bm25Ready;
  final String retrievalMode;
  final String retrievalWarning;

  factory CollectionSummary.fromJson(Map<String, dynamic> json) {
    final provider = _normalizeEmbeddingProvider(json['embedding_provider']);
    return CollectionSummary(
      collectionName: (json['collection_name'] ?? '').toString(),
      embeddingProvider: provider,
      sessionId: (json['session_id'] ?? '').toString(),
      filename: (json['filename'] ?? '').toString(),
      source: (json['source'] ?? '').toString(),
      chunkCount: _intValue(json['chunk_count']),
      bm25Ready: json.containsKey('bm25_ready')
          ? json['bm25_ready'] == true
          : null,
      retrievalMode: (json['retrieval_mode'] ?? '').toString(),
      retrievalWarning: (json['retrieval_warning'] ?? '').toString(),
    );
  }

  static int? _intValue(Object? value) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    return int.tryParse(value?.toString() ?? '');
  }

  static String _normalizeEmbeddingProvider(Object? value) {
    final provider = (value ?? '').toString().trim().toLowerCase();
    if (provider.isEmpty ||
        provider == 'unknown' ||
        provider == 'none' ||
        provider == 'null') {
      return ApiConstants.defaultEmbeddingProvider;
    }
    if (provider == 'sentence-transformers' ||
        provider == 'sentence_transformers') {
      return ApiConstants.defaultEmbeddingProvider;
    }
    return provider;
  }
}

class CollectionBuildSummary {
  const CollectionBuildSummary({
    required this.documentName,
    required this.documentType,
    required this.documentUnitsLabel,
    required this.documentUnitsValue,
    required this.chunksCreated,
    required this.vectorsStored,
    required this.chunkSize,
    required this.chunkOverlap,
    required this.embeddingModel,
    this.lastBuiltAt,
  });

  final String documentName;
  final String documentType;
  final String documentUnitsLabel;
  final int? documentUnitsValue;
  final int? chunksCreated;
  final int? vectorsStored;
  final int? chunkSize;
  final int? chunkOverlap;
  final String embeddingModel;
  final DateTime? lastBuiltAt;

  String get documentUnits {
    if (documentUnitsValue == null) {
      return documentUnitsLabel.isEmpty ? 'N/A' : documentUnitsLabel;
    }
    return documentUnitsLabel.isEmpty
        ? documentUnitsValue.toString()
        : '$documentUnitsValue $documentUnitsLabel';
  }

  factory CollectionBuildSummary.fromJson(Map<String, dynamic> json) {
    final rawUnits = json['document_units'];
    return CollectionBuildSummary(
      documentName: (json['document_name'] ?? '').toString(),
      documentType: (json['file_type'] ?? json['document_type'] ?? '')
          .toString(),
      documentUnitsLabel:
          (json['document_units_label'] ?? (rawUnits is String ? rawUnits : ''))
              .toString(),
      documentUnitsValue: CollectionSummary._intValue(
        json['document_units_value'] ?? (rawUnits is num ? rawUnits : null),
      ),
      chunksCreated: CollectionSummary._intValue(json['chunks_created']),
      vectorsStored: CollectionSummary._intValue(json['vectors_stored']),
      chunkSize: CollectionSummary._intValue(json['chunk_size']),
      chunkOverlap: CollectionSummary._intValue(json['chunk_overlap']),
      embeddingModel: (json['embedding_model'] ?? '').toString(),
      lastBuiltAt: DateTime.tryParse(
        (json['last_built_at'] ?? json['build_timestamp'] ?? '').toString(),
      ),
    );
  }
}
