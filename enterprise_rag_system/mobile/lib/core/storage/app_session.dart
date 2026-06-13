import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../constants/api_constants.dart';

class AppSession extends ChangeNotifier {
  static const MethodChannel _channel = MethodChannel(
    'enterprise_rag/settings',
  );

  static const _backendUrlKey = 'backend_url';
  static const _sessionIdKey = 'session_id';
  static const _collectionNameKey = 'collection_name';
  static const _embeddingProviderKey = 'embedding_provider';
  static const _debugModeKey = 'debug_mode';
  static const _themeModeKey = 'theme_mode';
  static const _jwtTokenKey = 'jwt_token';
  static const _apiKeyKey = 'api_key';

  String backendUrl = ApiConstants.defaultBaseUrl;
  String sessionId = '';
  String collectionName = '';
  String embeddingProvider = ApiConstants.defaultEmbeddingProvider;
  bool debugMode = true;
  ThemeMode themeMode = ThemeMode.system;
  String? jwtToken;
  String? apiKey;

  bool get hasSession => sessionId.trim().isNotEmpty;
  bool get hasCollection => collectionName.trim().isNotEmpty;

  Map<String, String> get headers {
    final headersMap = <String, String>{};
    final token = jwtToken?.trim() ?? '';
    if (token.isNotEmpty) {
      headersMap['Authorization'] = 'Bearer $token';
    }
    final key = apiKey?.trim() ?? '';
    if (key.isNotEmpty) {
      headersMap['X-API-Key'] = key;
    }
    return headersMap;
  }

  Map<String, String> get requestHeaders => headers;
  Map<String, String> get authHeaders => headers;

  Future<void> load() async {
    final data = await _readStore();
    backendUrl =
        data[_backendUrlKey]?.toString() ?? ApiConstants.defaultBaseUrl;
    sessionId = data[_sessionIdKey]?.toString() ?? '';
    collectionName = data[_collectionNameKey]?.toString() ?? '';
    embeddingProvider = _normalizeProvider(
      data[_embeddingProviderKey]?.toString(),
    );
    debugMode = data[_debugModeKey] is bool
        ? data[_debugModeKey] as bool
        : true;
    themeMode = _themeModeFromString(data[_themeModeKey]?.toString());
    jwtToken = data[_jwtTokenKey]?.toString();
    apiKey = data[_apiKeyKey]?.toString();
    notifyListeners();
  }

  Future<void> setBackendUrl(String value) async {
    backendUrl = value.trim().isEmpty
        ? ApiConstants.defaultBaseUrl
        : value.trim();
    await _saveValue(_backendUrlKey, backendUrl);
    notifyListeners();
  }

  Future<void> setEmbeddingProvider(String value) async {
    embeddingProvider = _normalizeProvider(value);
    await _saveValue(_embeddingProviderKey, embeddingProvider);
    notifyListeners();
  }

  Future<void> setDebugMode(bool value) async {
    debugMode = value;
    await _saveValue(_debugModeKey, value);
    notifyListeners();
  }

  Future<void> setThemeMode(ThemeMode value) async {
    themeMode = value;
    await _saveValue(_themeModeKey, value.name);
    notifyListeners();
  }

  Future<void> setJwtToken(String? value) async {
    jwtToken = value?.trim();
    if (jwtToken == null || jwtToken!.isEmpty) {
      jwtToken = null;
      await _removeValues([_jwtTokenKey]);
    } else {
      await _saveValue(_jwtTokenKey, jwtToken!);
    }
    notifyListeners();
  }

  Future<void> setApiKey(String? value) async {
    apiKey = value?.trim();
    if (apiKey == null || apiKey!.isEmpty) {
      apiKey = null;
      await _removeValues([_apiKeyKey]);
    } else {
      await _saveValue(_apiKeyKey, apiKey!);
    }
    notifyListeners();
  }

  Future<void> activateSession({
    required String sessionId,
    required String collectionName,
    required String embeddingProvider,
  }) async {
    this.sessionId = sessionId.trim();
    this.collectionName = collectionName.trim();
    this.embeddingProvider = _normalizeProvider(embeddingProvider);
    await _saveValue(_sessionIdKey, this.sessionId);
    await _saveValue(_collectionNameKey, this.collectionName);
    await _saveValue(_embeddingProviderKey, this.embeddingProvider);
    notifyListeners();
  }

  Future<void> resetSession() async {
    sessionId = '';
    collectionName = '';
    await _removeValues([_sessionIdKey, _collectionNameKey]);
    notifyListeners();
  }

  Future<void> clearAll() async {
    await _clearStore();
    backendUrl = ApiConstants.defaultBaseUrl;
    sessionId = '';
    collectionName = '';
    embeddingProvider = ApiConstants.defaultEmbeddingProvider;
    debugMode = true;
    themeMode = ThemeMode.system;
    jwtToken = null;
    apiKey = null;
    notifyListeners();
  }

  String _normalizeProvider(String? value) {
    final provider = (value ?? '').trim().toLowerCase();
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

  ThemeMode _themeModeFromString(String? value) {
    return ThemeMode.values.firstWhere(
      (mode) => mode.name == value,
      orElse: () => ThemeMode.system,
    );
  }

  Future<Map<String, Object?>> _readStore() async {
    try {
      final data = await _channel.invokeMapMethod<String, Object?>('read');
      return data ?? {};
    } catch (_) {
      return {};
    }
  }

  Future<void> _saveValue(String key, Object value) async {
    try {
      await _channel.invokeMethod<void>('write', {'key': key, 'value': value});
    } catch (_) {}
  }

  Future<void> _removeValues(List<String> keys) async {
    try {
      await _channel.invokeMethod<void>('remove', {'keys': keys});
    } catch (_) {}
  }

  Future<void> _clearStore() async {
    try {
      await _channel.invokeMethod<void>('clear');
    } catch (_) {}
  }
}
