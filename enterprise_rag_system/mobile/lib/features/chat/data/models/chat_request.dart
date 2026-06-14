import '../../../../../core/constants/api_constants.dart';

class ChatRequest {
  const ChatRequest({
    required this.sessionId,
    required this.collectionName,
    required this.question,
    this.answerLength = ApiConstants.defaultAnswerLength,
    this.allowWebSearch = false,
  });

  final String sessionId;
  final String collectionName;
  final String question;
  final String answerLength;
  final bool allowWebSearch;

  Map<String, dynamic> toJson() {
    return {
      'session_id': sessionId,
      'collection_name': collectionName,
      'question': question,
      'answer_length': answerLength,
      'allow_web_search': allowWebSearch,
    };
  }
}
