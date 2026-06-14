import '../../../../core/constants/api_constants.dart';

class UploadResult {
  const UploadResult({
    required this.success,
    required this.sessionId,
    required this.collectionName,
    required this.filename,
    required this.embeddingProvider,
    required this.retrievalMode,
    required this.retrievalWarning,
    required this.message,
    required this.skipped,
    this.summary,
  });

  final bool success;
  final String sessionId;
  final String collectionName;
  final String filename;
  final String embeddingProvider;
  final String retrievalMode;
  final String retrievalWarning;
  final String message;
  final bool skipped;
  final UploadBuildSummary? summary;

  factory UploadResult.fromJson(Map<String, dynamic> json) {
    return UploadResult(
      success: json['success'] == true,
      sessionId: (json['session_id'] ?? '').toString(),
      collectionName: (json['collection_name'] ?? '').toString(),
      filename: (json['filename'] ?? '').toString(),
      embeddingProvider:
          (json['embedding_provider'] ?? ApiConstants.defaultEmbeddingProvider)
              .toString(),
      retrievalMode: (json['retrieval_mode'] ?? '').toString(),
      retrievalWarning: (json['retrieval_warning'] ?? '').toString(),
      message: (json['message'] ?? '').toString(),
      skipped: json['skipped'] == true,
      summary: json['summary'] is Map
          ? UploadBuildSummary.fromJson(
              Map<String, dynamic>.from(json['summary'] as Map),
            )
          : null,
    );
  }
}

class UploadBuildSummary {
  const UploadBuildSummary({
    required this.collectionName,
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

  final String collectionName;
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

  factory UploadBuildSummary.fromJson(Map<String, dynamic> json) {
    final rawUnits = json['document_units'];
    return UploadBuildSummary(
      collectionName: (json['collection_name'] ?? '').toString(),
      documentName: (json['document_name'] ?? '').toString(),
      documentType: (json['file_type'] ?? json['document_type'] ?? '')
          .toString(),
      documentUnitsLabel:
          (json['document_units_label'] ?? (rawUnits is String ? rawUnits : ''))
              .toString(),
      documentUnitsValue: _intValue(
        json['document_units_value'] ?? (rawUnits is num ? rawUnits : null),
      ),
      chunksCreated: _intValue(json['chunks_created']),
      vectorsStored: _intValue(json['vectors_stored']),
      chunkSize: _intValue(json['chunk_size']),
      chunkOverlap: _intValue(json['chunk_overlap']),
      embeddingModel: (json['embedding_model'] ?? '').toString(),
      lastBuiltAt: DateTime.tryParse(
        (json['last_built_at'] ?? json['build_timestamp'] ?? '').toString(),
      ),
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
}
