import '../../../../core/constants/api_constants.dart';
import '../../../../core/network/api_client.dart';

class SignupResult {
  const SignupResult({required this.message, this.verificationHint});

  final String message;
  final String? verificationHint;
}

class AuthApiService {
  AuthApiService({ApiClient? apiClient, this.baseUrl})
    : _apiClient = apiClient ?? ApiClient(debugMode: false);

  final ApiClient _apiClient;
  final String? baseUrl;

  Future<String> login({
    required String email,
    required String password,
  }) async {
    final json = await _apiClient.postJson(
      Uri.parse('${ApiConstants.apiBaseUrl(baseUrl)}/auth/login'),
      {'email': email.trim(), 'password': password},
    );
    final accessToken = json['access_token']?.toString().trim() ?? '';
    if (accessToken.isEmpty) {
      throw const FormatException('Login response did not include an access token.');
    }
    return accessToken;
  }

  Future<SignupResult> signup({
    required String email,
    required String password,
    String? fullName,
  }) async {
    final body = <String, dynamic>{
      'email': email.trim(),
      'password': password,
    };
    final trimmedFullName = fullName?.trim() ?? '';
    if (trimmedFullName.isNotEmpty) {
      body['full_name'] = trimmedFullName;
    }
    final json = await _apiClient.postJson(
      Uri.parse('${ApiConstants.apiBaseUrl(baseUrl)}/auth/signup'),
      body,
    );
    final message = json['message']?.toString().trim() ?? '';
    final verificationHint = json['verification_hint']?.toString().trim();
    return SignupResult(
      message: message.isEmpty
          ? 'Account created. Please check your email to verify your account.'
          : message,
      verificationHint: verificationHint == null || verificationHint.isEmpty
          ? null
          : verificationHint,
    );
  }

  Future<String> forgotPassword({required String email}) async {
    final json = await _apiClient.postJson(
      Uri.parse('${ApiConstants.apiBaseUrl(baseUrl)}/auth/forgot-password'),
      {'email': email.trim()},
    );
    return json['message']?.toString().trim() ??
        'If the account exists, reset instructions were sent.';
  }

  Future<String> verifyEmail({required String token}) async {
    final json = await _apiClient.postJson(
      Uri.parse('${ApiConstants.apiBaseUrl(baseUrl)}/auth/verify-email'),
      {'token': token.trim()},
    );
    return json['message']?.toString().trim() ??
        'Email verified successfully.';
  }

  Future<String> resetPassword({
    required String token,
    required String newPassword,
  }) async {
    final json = await _apiClient.postJson(
      Uri.parse('${ApiConstants.apiBaseUrl(baseUrl)}/auth/reset-password'),
      {'token': token.trim(), 'new_password': newPassword},
    );
    return json['message']?.toString().trim() ??
        'Password reset successfully.';
  }
}
