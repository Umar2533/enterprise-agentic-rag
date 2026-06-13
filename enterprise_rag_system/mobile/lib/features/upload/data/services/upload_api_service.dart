import '../../../../core/constants/api_constants.dart';
import '../../../../core/network/api_client.dart';
import '../models/upload_result.dart';

class UploadApiService {
  UploadApiService({ApiClient? apiClient, this.baseUrl})
    : _apiClient = apiClient ?? ApiClient();

  final ApiClient _apiClient;
  final String? baseUrl;

  Future<UploadResult> uploadDocument({
    required List<int> bytes,
    String? filename,
    required String collectionName,
    required String embeddingProvider,
    int chunkSize = 700,
    int chunkOverlap = 80,
    int topK = 5,
    int maxIterations = 3,
    bool useExistingCollection = false,
    Map<String, String>? headers,
  }) async {
    final json = await _apiClient.multipartPost(
      Uri.parse(ApiConstants.uploadDocumentEndpoint(baseUrl)),
      bytes: bytes,
      filename: filename,
      fileField: 'file',
      fields: {
        'collection_name': collectionName,
        'chunk_size': chunkSize.toString(),
        'chunk_overlap': chunkOverlap.toString(),
        'k': topK.toString(),
        'max_iterations': maxIterations.toString(),
        'embedding_provider': _normalizeProvider(embeddingProvider),
        'use_existing_collection': useExistingCollection.toString(),
      },
      headers: headers,
    );
    return UploadResult.fromJson(json);
  }

  String _normalizeProvider(String value) {
    final provider = value.trim().toLowerCase();
    if (provider.isEmpty || provider == 'unknown') {
      return ApiConstants.defaultEmbeddingProvider;
    }
    if (provider == 'sentence-transformers' ||
        provider == 'sentence_transformers') {
      return ApiConstants.defaultEmbeddingProvider;
    }
    return provider;
  }
}
