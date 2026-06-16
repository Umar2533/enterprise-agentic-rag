// import 'dart:async';
// import 'dart:convert';
// import 'dart:developer' as developer;

// import 'package:http/http.dart' as http;

// import '../errors/api_exception.dart';

// class ApiClient {
//   ApiClient({http.Client? client, this.debugMode = true})
//     : _client = client ?? http.Client();

//   final http.Client _client;
//   final bool debugMode;
//   static const Duration _timeout = Duration(seconds: 180);

//   Future<Map<String, dynamic>> getJson(Uri uri, {Map<String, String>? headers}) async {
//     _logRequest('GET', uri);
//     try {
//       final response = await _client.get(uri, headers: headers).timeout(_timeout);
//       return _handleResponse(response);
//     } on http.ClientException catch (error) {
//       throw ApiException(message: 'Backend is not reachable: ${error.message}');
//     }
//   }

//   Future<Map<String, dynamic>> postJson(
//     Uri uri,
//     Map<String, dynamic> body, {
//     Map<String, String>? headers,
//   }) async {
//     final encodedBody = jsonEncode(body);
//     _logRequest('POST', uri, body: encodedBody);
//     try {
//       final mergedHeaders = {
//         'Content-Type': 'application/json',
//         ...?headers,
//       };
//       final response = await _client
//           .post(
//             uri,
//             headers: mergedHeaders,
//             body: encodedBody,
//           )
//           .timeout(_timeout);
//       return _handleResponse(response);
//     } on http.ClientException catch (error) {
//       throw ApiException(message: 'Backend is not reachable: ${error.message}');
//     } on TimeoutException {
//       throw const ApiException(message: 'Backend request timed out.');
//     }
//   }

//   Future<Map<String, dynamic>> deleteJson(
//     Uri uri, {
//     Map<String, String>? headers,
//   }) async {
//     _logRequest('DELETE', uri);
//     try {
//       final response = await _client
//           .delete(uri, headers: headers)
//           .timeout(_timeout);
//       return _handleResponse(response);
//     } on http.ClientException catch (error) {
//       throw ApiException(message: 'Backend is not reachable: ${error.message}');
//     } on TimeoutException {
//       throw const ApiException(message: 'Backend request timed out.');
//     }
//   }

//   Future<Map<String, dynamic>> multipartPost(
//     Uri uri, {
//     required List<int> bytes,
//     String? filename,
//     required String fileField,
//     required Map<String, String> fields,
//     Map<String, String>? headers,
//   }) async {
//     _logRequest('POST multipart', uri, body: fields.toString());
//     try {
//       final request = http.MultipartRequest('POST', uri);
//       if (headers != null) {
//         request.headers.addAll(headers);
//       }
//       request.fields.addAll(fields);
//       request.files.add(
//         http.MultipartFile.fromBytes(
//           fileField,
//           bytes,
//           filename: filename ?? 'document',
//         ),
//       );
//       final streamedResponse = await request.send().timeout(_timeout);
//       final response = await http.Response.fromStream(streamedResponse);
//       return _handleResponse(response);
//     } on http.ClientException catch (error) {
//       throw ApiException(message: 'Backend is not reachable: ${error.message}');
//     } on TimeoutException {
//       throw const ApiException(message: 'Upload timed out.');
//     }
//   }

//   Map<String, dynamic> _handleResponse(http.Response response) {
//     if (debugMode) {
//       developer.log(
//         'Response ${response.statusCode}: ${response.body}',
//         name: 'EnterpriseRagApi',
//       );
//     }

//     final decoded = _decodeBody(response.body);
//     if (response.statusCode >= 200 && response.statusCode < 300) {
//       if (decoded is Map<String, dynamic>) {
//         return decoded;
//       }
//       throw const ApiException(
//         message: 'Backend returned an invalid response.',
//       );
//     }

//     throw ApiException(
//       statusCode: response.statusCode,
//       message: _extractErrorMessage(decoded, response.body),
//       details: decoded,
//     );
//   }

//   Object? _decodeBody(String body) {
//     if (body.trim().isEmpty) {
//       return null;
//     }

//     try {
//       return jsonDecode(body);
//     } on FormatException {
//       return body;
//     }
//   }

//   String _extractErrorMessage(Object? decoded, String rawBody) {
//     if (decoded is Map<String, dynamic>) {
//       final error = decoded['error'];
//       if (error is String && error.trim().isNotEmpty) {
//         return error;
//       }
//       if (error != null) {
//         return error.toString();
//       }
//       final detail = decoded['detail'];
//       if (detail is String && detail.trim().isNotEmpty) {
//         return detail;
//       }
//       if (detail is List) {
//         return detail.map((error) => _formatValidationError(error)).join('\n');
//       }
//       if (detail != null) {
//         return detail.toString();
//       }
//     }

//     return rawBody.trim().isEmpty ? 'Backend request failed.' : rawBody;
//   }

//   String _formatValidationError(Object error) {
//     if (error is Map<String, dynamic>) {
//       final loc = error['loc'];
//       final field = loc is List && loc.isNotEmpty ? loc.join('.') : 'body';
//       final message = error['msg']?.toString() ?? 'Invalid value';
//       return '$field: $message';
//     }
//     return error.toString();
//   }

//   void _logRequest(String method, Uri uri, {String? body}) {
//     if (!debugMode) {
//       return;
//     }
//     developer.log('$method $uri', name: 'EnterpriseRagApi');
//     if (body != null) {
//       developer.log('Request body: $body', name: 'EnterpriseRagApi');
//     }
//   }
// }
import 'dart:async';
import 'dart:convert';
import 'dart:developer' as developer;

import 'package:http/http.dart' as http;

import '../errors/api_exception.dart';

class ApiClient {
  ApiClient({http.Client? client, this.debugMode = true})
    : _client = client ?? http.Client();

  final http.Client _client;
  final bool debugMode;

  static const Duration _timeout = Duration(seconds: 180);

  Future<Map<String, dynamic>> getJson(
    Uri uri, {
    Map<String, String>? headers,
  }) async {
    _logRequest('GET', uri);

    try {
      final response = await _client
          .get(uri, headers: headers)
          .timeout(_timeout);

      return _handleResponse(response);
    } on TimeoutException {
      throw const ApiException(message: 'Backend request timed out.');
    } on http.ClientException catch (error) {
      throw ApiException(message: 'Backend is not reachable: ${error.message}');
    } catch (error) {
      throw ApiException(message: 'Backend request failed: $error');
    }
  }

  Future<Map<String, dynamic>> postJson(
    Uri uri,
    Map<String, dynamic> body, {
    Map<String, String>? headers,
  }) async {
    final encodedBody = jsonEncode(body);
    _logRequest('POST', uri, body: encodedBody);

    try {
      final mergedHeaders = {'Content-Type': 'application/json', ...?headers};

      final response = await _client
          .post(uri, headers: mergedHeaders, body: encodedBody)
          .timeout(_timeout);

      return _handleResponse(response);
    } on TimeoutException {
      throw const ApiException(message: 'Backend request timed out.');
    } on http.ClientException catch (error) {
      throw ApiException(message: 'Backend is not reachable: ${error.message}');
    } catch (error) {
      throw ApiException(message: 'Backend request failed: $error');
    }
  }

  Future<Map<String, dynamic>> deleteJson(
    Uri uri, {
    Map<String, String>? headers,
  }) async {
    _logRequest('DELETE', uri);

    try {
      final response = await _client
          .delete(uri, headers: headers)
          .timeout(_timeout);

      return _handleResponse(response);
    } on TimeoutException {
      throw const ApiException(message: 'Backend request timed out.');
    } on http.ClientException catch (error) {
      throw ApiException(message: 'Backend is not reachable: ${error.message}');
    } catch (error) {
      throw ApiException(message: 'Backend request failed: $error');
    }
  }

  Future<Map<String, dynamic>> multipartPost(
    Uri uri, {
    required List<int> bytes,
    String? filename,
    required String fileField,
    required Map<String, String> fields,
    Map<String, String>? headers,
  }) async {
    _logRequest('POST multipart', uri, body: fields.toString());

    try {
      final request = http.MultipartRequest('POST', uri);

      if (headers != null) {
        request.headers.addAll(headers);
      }

      request.fields.addAll(fields);

      request.files.add(
        http.MultipartFile.fromBytes(
          fileField,
          bytes,
          filename: filename ?? 'document',
        ),
      );

      final streamedResponse = await request.send().timeout(_timeout);
      final response = await http.Response.fromStream(streamedResponse);

      return _handleResponse(response);
    } on TimeoutException {
      throw const ApiException(message: 'Upload timed out.');
    } on http.ClientException catch (error) {
      throw ApiException(message: 'Backend is not reachable: ${error.message}');
    } catch (error) {
      throw ApiException(message: 'Upload failed: $error');
    }
  }

  Map<String, dynamic> _handleResponse(http.Response response) {
    if (debugMode) {
      _logResponse(response);
    }

    final decoded = _decodeBody(response.body);

    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (decoded is Map<String, dynamic>) {
        return decoded;
      }

      throw const ApiException(
        message: 'Backend returned an invalid response.',
      );
    }

    throw ApiException(
      statusCode: response.statusCode,
      message: _extractErrorMessage(
        decoded,
        response.body,
        response.statusCode,
      ),
      details: decoded,
    );
  }

  Object? _decodeBody(String body) {
    if (body.trim().isEmpty) {
      return null;
    }

    try {
      return jsonDecode(body);
    } on FormatException {
      return body;
    }
  }

  String _extractErrorMessage(Object? decoded, String rawBody, int statusCode) {
    final serialized = decoded == null ? rawBody : jsonEncode(decoded);
    final lowered = serialized.toLowerCase();
    if (lowered.contains('insufficient_quota') ||
        (statusCode == 429 && lowered.contains('quota'))) {
      return 'Your OpenAI API key has no available quota. Please add billing/credits in OpenAI Platform or use another key.';
    }
    if (lowered.contains('<!doctype html') || lowered.contains('<html')) {
      return 'Backend is temporarily unavailable. Please try again.';
    }
    if (decoded is Map<String, dynamic>) {
      final error = decoded['error'];

      if (error is String && error.trim().isNotEmpty) {
        return error;
      }

      if (error != null) {
        return error.toString();
      }

      final detail = decoded['detail'];

      if (detail is String && detail.trim().isNotEmpty) {
        return detail;
      }

      if (detail is List) {
        return detail.map((error) => _formatValidationError(error)).join('\n');
      }

      if (detail != null) {
        return detail.toString();
      }

      final message = decoded['message'];

      if (message is String && message.trim().isNotEmpty) {
        return message;
      }
    }

    return rawBody.trim().isEmpty ? 'Backend request failed.' : rawBody;
  }

  String _formatValidationError(Object error) {
    if (error is Map<String, dynamic>) {
      final loc = error['loc'];
      final field = loc is List && loc.isNotEmpty ? loc.join('.') : 'body';
      final message = error['msg']?.toString() ?? 'Invalid value';

      return '$field: $message';
    }

    return error.toString();
  }

  void _logRequest(String method, Uri uri, {String? body}) {
    if (!debugMode) {
      return;
    }

    final message = '$method $uri';

    // print is intentional for Flutter run / adb logcat visibility.
    print(message);
    developer.log(message, name: 'EnterpriseRagApi');

    if (body != null) {
      print('Request body: $body');
      developer.log('Request body: $body', name: 'EnterpriseRagApi');
    }
  }

  void _logResponse(http.Response response) {
    final body = response.body.length > 1200
        ? '${response.body.substring(0, 1200)}...'
        : response.body;

    final message = 'Response ${response.statusCode}: $body';

    // print is intentional for Flutter run / adb logcat visibility.
    print(message);
    developer.log(message, name: 'EnterpriseRagApi');
  }
}
