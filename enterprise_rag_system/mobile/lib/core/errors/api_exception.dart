class ApiException implements Exception {
  const ApiException({required this.message, this.statusCode, this.details});

  final String message;
  final int? statusCode;
  final Object? details;

  @override
  String toString() {
    if (message == 'Add your OpenAI API key in Settings to use this feature.' ||
        message ==
            'Your OpenAI API key has no available quota. Please add billing/credits in OpenAI Platform or use another key.') {
      return message;
    }
    if (statusCode == null) {
      return message;
    }
    return 'Request failed with status $statusCode: $message';
  }
}
