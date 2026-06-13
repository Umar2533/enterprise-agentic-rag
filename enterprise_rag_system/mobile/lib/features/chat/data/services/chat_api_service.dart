import 'dart:developer' as developer;

import '../../../../../core/constants/api_constants.dart';
import '../../../../../core/network/api_client.dart';
import '../models/chat_request.dart';
import '../models/chat_response.dart';
import '../models/collection_summary.dart';
import '../models/health_status.dart';

class ChatApiService {
  ChatApiService({ApiClient? apiClient, this.baseUrl})
    : _apiClient = apiClient ?? ApiClient();

  final ApiClient _apiClient;
  final String? baseUrl;

  Future<HealthStatus> checkHealth() async {
    final json = await _apiClient.getJson(
      Uri.parse(ApiConstants.healthEndpoint(baseUrl)),
    );
    return HealthStatus.fromJson(json);
  }

  Future<List<CollectionSummary>> listCollections({
    Map<String, String>? headers,
  }) async {
    final json = await _apiClient.getJson(
      Uri.parse(ApiConstants.collectionsEndpoint(baseUrl)),
      headers: headers,
    );
    final collections = json['collections'];
    if (collections is! List) {
      return const [];
    }
    return collections
        .whereType<Map>()
        .map(
          (item) => CollectionSummary.fromJson(Map<String, dynamic>.from(item)),
        )
        .where((item) => item.collectionName.trim().isNotEmpty)
        .toList();
  }

  Future<CollectionSummary> selectCollection(
    CollectionSummary collection, {
    Map<String, String>? headers,
  }) async {
    developer.log(
      'Selecting collection=${collection.collectionName} '
      'session_id=${collection.sessionId} '
      'embedding_provider=${collection.embeddingProvider}',
      name: 'EnterpriseRagApi',
    );
    final json = await _apiClient
        .postJson(
          Uri.parse(ApiConstants.selectCollectionEndpoint(baseUrl)),
          {
            'collection_name': collection.collectionName,
            'embedding_provider': collection.embeddingProvider,
          },
          headers: headers,
        );
    return CollectionSummary.fromJson(json);
  }

  Future<void> deleteCollectionByName(
    String collectionName, {
    Map<String, String>? headers,
  }) async {
    await _apiClient.deleteJson(
      Uri.parse(
        ApiConstants.deleteCollectionByNameEndpoint(collectionName, baseUrl),
      ),
      headers: headers,
    );
  }

  Future<CollectionBuildSummary?> getCollectionSummary(
    String collectionName, {
    Map<String, String>? headers,
  }) async {
    final encodedCollectionName = Uri.encodeComponent(collectionName);
    final json = await _apiClient.getJson(
      Uri.parse(
        '${ApiConstants.apiBaseUrl(baseUrl)}/collections/$encodedCollectionName/summary',
      ),
      headers: headers,
    );
    final summary = json['summary'];
    if (summary is! Map) {
      return null;
    }
    return CollectionBuildSummary.fromJson(
      Map<String, dynamic>.from(summary),
    );
  }

  Future<ChatResponse> sendMessage(
    ChatRequest request, {
    Map<String, String>? headers,
  }) async {
    final json = await _apiClient.postJson(
      Uri.parse(ApiConstants.chatEndpoint(baseUrl)),
      request.toJson(),
      headers: headers,
    );
    return ChatResponse.fromJson(json);
  }
}
