import '../../../../../core/constants/api_constants.dart';

class ChatRequest {
  const ChatRequest({
    required this.sessionId,
    required this.question,
    this.answerLength = ApiConstants.defaultAnswerLength,
    this.allowWebSearch = false,
  });

  final String sessionId;
  final String question;
  final String answerLength;
  final bool allowWebSearch;

  Map<String, dynamic> toJson() {
    return {
      'session_id': sessionId,
      'question': question,
      'answer_length': answerLength,
      'allow_web_search': allowWebSearch,
    };
  }
}
