class HealthStatus {
  const HealthStatus({
    required this.isHealthy,
    required this.app,
    required this.vectorDbProvider,
    required this.embeddingProvider,
    required this.supportedEmbeddingProviders,
    required this.openAiConfigured,
    required this.qdrantConfigured,
    required this.tavilyConfigured,
  });

  final bool isHealthy;
  final String app;
  final String vectorDbProvider;
  final String embeddingProvider;
  final List<String> supportedEmbeddingProviders;
  final bool openAiConfigured;
  final bool qdrantConfigured;
  final bool tavilyConfigured;

  factory HealthStatus.fromJson(Map<String, dynamic> json) {
    return HealthStatus(
      isHealthy: json['success'] == true,
      app: (json['app'] ?? 'Enterprise RAG').toString(),
      vectorDbProvider: (json['vector_db_provider'] ?? 'unknown').toString(),
      embeddingProvider: (json['embedding_provider'] ?? 'huggingface')
          .toString(),
      supportedEmbeddingProviders: json['supported_embedding_providers'] is List
          ? (json['supported_embedding_providers'] as List)
                .map((item) => item.toString())
                .where((item) => item.trim().isNotEmpty)
                .toList()
          : const ['huggingface', 'openai'],
      openAiConfigured: json['openai_configured'] == true,
      qdrantConfigured: json['qdrant_configured'] == true,
      tavilyConfigured: json['tavily_configured'] == true,
    );
  }
}
