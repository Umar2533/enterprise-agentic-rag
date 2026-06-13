import 'package:flutter/services.dart';

import '../models/picked_document.dart';

class NativeFilePicker {
  static const MethodChannel _channel = MethodChannel('enterprise_rag/files');

  Future<PickedDocument?> pickDocument() async {
    final result = await _channel.invokeMapMethod<String, Object?>(
      'pickDocument',
    );
    if (result == null) {
      return null;
    }
    final bytes = result['bytes'];
    if (bytes is! Uint8List) {
      return null;
    }
    return PickedDocument(
      name: result['name']?.toString() ?? 'document',
      bytes: bytes,
    );
  }
}
