import 'dart:io' show Platform;
import 'package:flutter/foundation.dart';

class ApiConstants {
  const ApiConstants._();

  // Backend URLs
  static const String webBaseUrl =
      'https://enterprise-rag-backend-2u4p.onrender.com';
  static const String androidEmulatorBaseUrl =
      'https://enterprise-rag-backend-2u4p.onrender.com';
  static const String physicalDeviceBaseUrl =
      'https://enterprise-rag-backend-2u4p.onrender.com';

  /// Heuristic to detect if running on an Android emulator in pure Dart.
  static bool get _isAndroidEmulator {
    if (kIsWeb) return false;
    if (!Platform.isAndroid) return false;
    final version = Platform.operatingSystemVersion.toLowerCase();
    return version.contains('sdk') ||
        version.contains('emulator') ||
        version.contains('google') ||
        version.contains('goldfish') ||
        version.contains('vbox') ||
        version.contains('generic');
  }

  static String get defaultBaseUrl {
    if (kIsWeb) {
      return webBaseUrl;
    }

    if (Platform.isAndroid) {
      if (_isAndroidEmulator) {
        return androidEmulatorBaseUrl;
      }
      return physicalDeviceBaseUrl;
    }

    if (Platform.isIOS) {
      return physicalDeviceBaseUrl;
    }

    // Default fallback for desktop/other platforms
    return webBaseUrl;
  }

  static String _cleanBaseUrl(String? baseUrl) {
    final trimmed = baseUrl?.trim();
    if (trimmed != null && trimmed.isNotEmpty) {
      return trimmed.replaceAll(RegExp(r'/+$'), '');
    }
    return defaultBaseUrl.replaceAll(RegExp(r'/+$'), '');
  }

  static String apiBaseUrl([String? baseUrl]) {
    return '${_cleanBaseUrl(baseUrl)}/api/v1';
  }

  static String healthEndpoint([String? baseUrl]) {
    return '${apiBaseUrl(baseUrl)}/health';
  }

  static String chatEndpoint([String? baseUrl]) {
    return '${apiBaseUrl(baseUrl)}/chat';
  }

  static String uploadDocumentEndpoint([String? baseUrl]) {
    return '${apiBaseUrl(baseUrl)}/upload/document';
  }

  static String collectionsEndpoint([String? baseUrl]) {
    return '${apiBaseUrl(baseUrl)}/collections/list';
  }

  static String selectCollectionEndpoint([String? baseUrl]) {
    return '${apiBaseUrl(baseUrl)}/collections/select';
  }

  static String deleteCollectionByNameEndpoint(
    String collectionName, [
    String? baseUrl,
  ]) {
    final encodedCollectionName = Uri.encodeComponent(collectionName);
    return '${apiBaseUrl(baseUrl)}/collections/delete/by-name/$encodedCollectionName';
  }

  static String rebuildBm25Endpoint(String collectionName, [String? baseUrl]) {
    final encodedCollectionName = Uri.encodeComponent(collectionName);
    return '${apiBaseUrl(baseUrl)}/collections/bm25/rebuild/$encodedCollectionName';
  }

  static const String defaultAnswerLength = 'Medium: 180-250 words';
  static const bool renderFreeMvp = bool.fromEnvironment('RENDER_FREE_MVP');
  static const String environment = String.fromEnvironment(
    'ENVIRONMENT',
    defaultValue: 'development',
  );

  static String get defaultEmbeddingProvider {
    final productionBackend = defaultBaseUrl.contains('.onrender.com');
    return renderFreeMvp ||
            environment.toLowerCase() == 'production' ||
            productionBackend
        ? 'cloudflare'
        : 'huggingface';
  }

  static const List<String> supportedEmbeddingProviders = [
    'huggingface',
    'cloudflare',
    'openai',
    'sentence-transformers',
    'sentence_transformers',
  ];
}
